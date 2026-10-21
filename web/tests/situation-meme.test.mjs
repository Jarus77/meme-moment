import assert from "node:assert/strict";
import test from "node:test";
import { PhotoMemeError } from "../lib/photo-meme.mjs";
import { createSituationMemeService, validateSituationRequest } from "../lib/situation-meme.mjs";

const SITUATION = "When you are working in the dark for hours and your roommate turns on the bright light";

function jpeg(width = 320, height = 240) {
  return Buffer.from([0xff, 0xd8, 0xff, 0xc0, 0x00, 0x0b, 0x08, (height >> 8) & 0xff, height & 0xff, (width >> 8) & 0xff, width & 0xff, 0x01, 0x01, 0x11, 0x00, 0xff, 0xd9]);
}
const photoDataUrl = (bytes = jpeg()) => `data:image/jpeg;base64,${bytes.toString("base64")}`;

function template(id, name, boxCount = 2) {
  return {
    asset_id: id, slug: name.toLowerCase().replace(/\s+/g, "-"), name,
    source_url: `https://imgflip.com/meme/${id}/${name.toLowerCase().replace(/\s+/g, "-")}`,
    image_url: `https://i.imgflip.com/${id}.jpg`, width: 400, height: 300, safe_for_work: true,
    box_count: boxCount, boxes_explicit: false, boxes: [],
  };
}
const MATCHES = {
  model: "m",
  matches: [
    { rank: 1, score: 0.1, found_by: ["meaning", "keywords"], template: template(11, "Light Monsters"), example_captions: [
      { box_texts: ["Me: Turns on light", "Monsters in the room:"], author: "alice", url: "https://imgflip.com/i/aaa", upvotes: 141 },
      { box_texts: ["The monsters when I turn on the lights"], author: "bob", url: "https://imgflip.com/i/bbb", upvotes: 9 }] },
    { rank: 2, score: 0.09, found_by: ["photo_picture", "not-a-real-search"], template: template(22, "Limmy Waking Up"), example_captions: [
      { box_texts: ["WHEN MY BRIGHTNESS IS HIGHER THAN 2%", "MY EYES"], author: "carol", url: "https://imgflip.com/i/ccc", upvotes: 16 }] },
    { rank: 3, score: 0.08, template: template(33, "Blinking Guy", 1), example_captions: [
      { box_texts: ["*LITERALLY BLINKS*"], author: "dave", url: "https://imgflip.com/i/ddd", upvotes: 3 }] },
  ],
  analogs: [{ box_texts: ["Me: Turns on light", "Monsters in the room:"], author: "alice", url: "https://imgflip.com/i/aaa", upvotes: 141, score: 0.9,
    template: { asset_id: 11, slug: "light-monsters", name: "Light Monsters", source_url: "https://imgflip.com/meme/11/light-monsters", image_url: "https://i.imgflip.com/11.jpg", box_count: 2 } }],
};

function options(list) {
  return { candidates: [{ content: { parts: [{ text: JSON.stringify({ options: list }) }] } }] };
}
const GOOD_OPTIONS = [
  { asset_id: 11, source_index: 0, texts: ["Me: Turns the light on", "My roommate in the room:"] },
  { asset_id: 22, source_index: 0, texts: ["WHEN THE ROOM BRIGHTNESS IS HIGHER THAN 2%", "MY EYES"] },
  { asset_id: 33, source_index: 0, texts: ["*BLINKS AT THE LIGHT FOR 5 MINUTES*"] },
];

function makeService(overrides = {}) {
  const calls = { embed: [], match: [], gemini: [] };
  const logs = [];
  const fetchImpl = async (url, init) => {
    const body = init?.body ? JSON.parse(init.body) : null;
    const respond = (status, payload) => ({ ok: status < 400, status, headers: new Headers(), json: async () => payload, text: async () => JSON.stringify(payload) });
    if (String(url).includes(":embedContent")) {
      calls.embed.push({ url: String(url), headers: init.headers, body });
      if (overrides.embedFails) return respond(500, { error: "boom" });
      return respond(200, { embedding: { values: new Array(overrides.dim ?? 768).fill(0.01) } });
    }
    if (String(url).startsWith("https://match.test")) {
      calls.match.push({ url: String(url), headers: init.headers, body });
      if (overrides.matchFails) return respond(503, {});
      return respond(200, overrides.matches ?? MATCHES);
    }
    if (String(url).includes(":generateContent")) {
      calls.gemini.push({ url: String(url), headers: init.headers, body });
      if (overrides.geminiStatus) return respond(overrides.geminiStatus, { error: { message: "bad field" } });
      return respond(200, options(overrides.options ?? GOOD_OPTIONS));
    }
    throw new Error(`unexpected url ${url}`);
  };
  const service = createSituationMemeService({
    geminiApiKey: "gem-key", matchServiceUrl: "https://match.test", matchServiceKey: "match-key", fetchImpl,
    log: (entry) => logs.push(entry),
  });
  return { service, calls, logs };
}

test("validateSituationRequest requires a 3-500 character situation and accepts an optional photo", () => {
  assert.equal(validateSituationRequest({ situation: `  ${SITUATION} ` }).situation, SITUATION);
  assert.equal(validateSituationRequest({ situation: SITUATION }).photo, null);
  const withPhoto = validateSituationRequest({ situation: SITUATION, photo: photoDataUrl() });
  assert.equal(withPhoto.photo.mimeType, "image/jpeg");
  for (const body of [{}, { situation: "hi" }, { situation: "x".repeat(501) }, { situation: 5 }, { photo: photoDataUrl() }]) {
    assert.throws(() => validateSituationRequest(body), (error) => error instanceof PhotoMemeError && error.status === 400);
  }
  assert.throws(() => validateSituationRequest({ situation: SITUATION, photo: "data:image/png;base64,AAAA" }), PhotoMemeError);
});

test("situation only: embeds the text, searches, adapts real captions, and sends no photo anywhere", async () => {
  const { service, calls } = makeService();
  const result = await service.generate({ situation: SITUATION, photo: null });
  assert.equal(result.mode, "situation");
  assert.equal(calls.embed.length, 1);
  assert.equal(calls.embed[0].body.content.parts[0].text, SITUATION);
  assert.equal(calls.embed[0].body.taskType, "RETRIEVAL_QUERY");
  assert.equal(calls.embed[0].body.outputDimensionality, 768);
  const matchBody = calls.match[0].body;
  assert.equal(matchBody.situation, SITUATION);
  assert.equal(matchBody.situation_vector.length, 768);
  assert.equal("photo_vector" in matchBody, false);
  assert.equal(calls.match[0].headers["X-Match-Key"], "match-key");
  assert.equal(JSON.stringify(calls.gemini[0].body).includes("inlineData"), false);
  assert.equal(result.candidates.length, 3);
  assert.deepEqual(result.candidates[0].texts, ["Me: Turns the light on", "My roommate in the room:"]);
  assert.equal(result.candidates[0].template.name, "Light Monsters");
  assert.deepEqual(result.candidates[0].adaptedFrom, { box_texts: ["Me: Turns on light", "Monsters in the room:"], author: "alice", url: "https://imgflip.com/i/aaa", upvotes: 141 });
});

test("photo plus situation: embeds the photo too, passes its vector, and shows Gemini the photo itself", async () => {
  const { service, calls } = makeService();
  const photo = { bytes: jpeg(), mimeType: "image/jpeg", width: 320, height: 240 };
  const result = await service.generate({ situation: SITUATION, photo });
  assert.equal(result.mode, "photo+situation");
  assert.equal(calls.embed.length, 2);
  const imageEmbed = calls.embed.find((call) => call.body.content.parts[0].inline_data);
  assert.equal(imageEmbed.body.content.parts[0].inline_data.data, jpeg().toString("base64"));
  assert.equal(calls.match[0].body.photo_vector.length, 768);
  const parts = calls.gemini[0].body.contents[0].parts;
  assert.ok(parts.some((part) => part.inlineData?.data === jpeg().toString("base64")));
  const prompt = parts.map((part) => part.text ?? "").join("\n");
  assert.match(prompt, /because of/i, "the situation must be presented as the cause behind the photo");
  assert.match(prompt, /adapt/i);
});

test("Gemini requests use the supported field names, a roomy token budget, and the key in a header", async () => {
  const { service, calls } = makeService();
  await service.generate({ situation: SITUATION, photo: null });
  const request = calls.gemini[0];
  const config = request.body.generationConfig;
  assert.equal(config.responseMimeType, "application/json");
  assert.ok(config.responseSchema);
  assert.equal("responseFormat" in config, false, "responseFormat makes Gemini return HTTP 400");
  assert.ok(config.maxOutputTokens >= 4096, "Gemini's hidden thinking tokens count against this budget");
  assert.equal(request.headers["x-goog-api-key"], "gem-key");
  assert.equal(request.url.includes("gem-key"), false);
});

test("options with an unknown template, the wrong box count, or a repeated template are dropped", async () => {
  const mixed = [
    { asset_id: 999, source_index: 0, texts: ["not a candidate", "x"] },
    { asset_id: 11, source_index: 0, texts: ["only one box"] },
    { asset_id: 22, source_index: 0, texts: ["WHEN BRIGHT", "MY EYES"] },
    { asset_id: 22, source_index: 0, texts: ["second take on the same template", "again"] },
    { asset_id: 33, source_index: 0, texts: ["*BLINKS*"] },
    { asset_id: 11, source_index: 0, texts: ["Me: Turns on light", "Monsters in the room:"] },
  ];
  const { service } = makeService({ options: mixed });
  const result = await service.generate({ situation: SITUATION, photo: null });
  assert.deepEqual(result.candidates.map((c) => c.template.asset_id), [22, 33, 11]);
});

test("adapting a real caption almost unchanged is allowed because the original author is credited", async () => {
  const verbatim = [
    { asset_id: 11, source_index: 0, texts: ["Me: Turns on light", "Monsters in the room:"] },
    { asset_id: 22, source_index: 0, texts: ["WHEN MY BRIGHTNESS IS HIGHER THAN 2%", "MY EYES"] },
    { asset_id: 33, source_index: 0, texts: ["*LITERALLY BLINKS*"] },
  ];
  const { service } = makeService({ options: verbatim });
  const result = await service.generate({ situation: SITUATION, photo: null });
  assert.equal(result.candidates.length, 3);
  assert.equal(result.candidates[0].adaptedFrom.author, "alice");
});

test("fewer than three usable options is reported as a caption failure", async () => {
  const { service } = makeService({ options: [GOOD_OPTIONS[0], { asset_id: 999, source_index: 0, texts: ["x", "y"] }] });
  await assert.rejects(service.generate({ situation: SITUATION, photo: null }), (error) => error.code === "INVALID_CAPTIONS");
});

test("upstream failures give friendly errors while the real status is logged server-side only", async () => {
  const gem = makeService({ geminiStatus: 400 });
  await assert.rejects(gem.service.generate({ situation: SITUATION, photo: null }), (error) => {
    assert.equal(error.code, "GEMINI_UNAVAILABLE");
    assert.equal(error.message.includes("bad field"), false);
    return true;
  });
  assert.ok(gem.logs.some((entry) => entry.stage === "adapt" && entry.status === 400));

  await assert.rejects(makeService({ embedFails: true }).service.generate({ situation: SITUATION, photo: null }), (e) => e.code === "GEMINI_UNAVAILABLE");
  await assert.rejects(makeService({ matchFails: true }).service.generate({ situation: SITUATION, photo: null }), (e) => e.code === "MATCH_SERVICE_UNAVAILABLE");
  await assert.rejects(makeService({ dim: 5 }).service.generate({ situation: SITUATION, photo: null }), (e) => e.code === "GEMINI_UNAVAILABLE");
});

test("no usable template matches is a clear 422", async () => {
  const { service } = makeService({ matches: { model: "m", matches: [], analogs: [] } });
  await assert.rejects(service.generate({ situation: SITUATION, photo: null }), (error) => error.code === "NO_TEMPLATE_MATCHES" && error.status === 422);
});

test("missing Gemini key or match service key are reported as not configured", async () => {
  const noKey = createSituationMemeService({ geminiApiKey: "", matchServiceUrl: "https://match.test", matchServiceKey: "k", fetchImpl: async () => { throw new Error("no call"); } });
  await assert.rejects(noKey.generate({ situation: SITUATION, photo: null }), (e) => e.code === "GEMINI_NOT_CONFIGURED");
  const noMatch = createSituationMemeService({ geminiApiKey: "g", matchServiceUrl: "https://match.test", matchServiceKey: "", fetchImpl: async (u) => ({ ok: true, status: 200, headers: new Headers(), json: async () => ({ embedding: { values: new Array(768).fill(0.1) } }), text: async () => "{}" }) });
  await assert.rejects(noMatch.generate({ situation: SITUATION, photo: null }), (e) => e.code === "MATCH_SERVICE_NOT_CONFIGURED");
});

test("each result says which searches found its template, and unknown search names are dropped", async () => {
  const { service } = makeService();
  const result = await service.generate({ situation: SITUATION, photo: null });
  assert.deepEqual(result.candidates[0].foundBy, ["meaning", "keywords"]);
  assert.deepEqual(result.candidates[1].foundBy, ["photo_picture"]);
  assert.deepEqual(result.candidates[2].foundBy, []);
});
