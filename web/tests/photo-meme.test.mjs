import assert from "node:assert/strict";
import test from "node:test";
import { createPhotoMemeService, PhotoMemeError, validatePhotoRequest } from "../lib/photo-meme.mjs";

function jpeg(width = 320, height = 240) {
  return Buffer.from([
    0xff, 0xd8,
    0xff, 0xc0, 0x00, 0x0b, 0x08,
    (height >> 8) & 0xff, height & 0xff,
    (width >> 8) & 0xff, width & 0xff,
    0x01, 0x01, 0x11, 0x00,
    0xff, 0xd9,
  ]);
}

function photoRequest(bytes = jpeg()) {
  return { photo: `data:image/jpeg;base64,${bytes.toString("base64")}` };
}

const matchingResponse = {
  model: "fake-model",
  matches: [
    {
      rank: 1,
      score: 0.8,
      template: {
        asset_id: 123,
        slug: "reading-book",
        name: "Reading a book",
        source_url: "https://imgflip.com/meme/123/reading-book",
        image_url: "https://i.imgflip.com/template.jpg",
        width: 320,
        height: 240,
        safe_for_work: true,
        box_count: 2,
        boxes_explicit: false,
        boxes: [],
      },
      example_captions: [
        { box_texts: ["An example setup", "An example punchline"], author: "meme-maker", url: "https://imgflip.com/i/example", upvotes: 4 },
      ],
    },
  ],
};

test("photo validation accepts bounded JPEG data URLs and extracts dimensions", () => {
  const result = validatePhotoRequest(photoRequest());
  assert.equal(result.mimeType, "image/jpeg");
  assert.equal(result.width, 320);
  assert.equal(result.height, 240);
  assert.deepEqual(result.bytes, jpeg());
});

test("photo validation rejects non-images, malformed JPEGs, oversized photos, and dimensions over 1280", () => {
  for (const body of [
    { photo: "data:image/png;base64,iVBORw0KGgo=" },
    { photo: "data:image/jpeg;base64,aGVsbG8=" },
    { photo: "not a data URL" },
    { photo: `data:image/jpeg;base64,${Buffer.alloc(5 * 1024 * 1024 + 1).toString("base64")}` },
    photoRequest(jpeg(1281, 720)),
  ]) {
    assert.throws(() => validatePhotoRequest(body), PhotoMemeError);
  }
});

test("photo pipeline describes the photo, sends only text to matching, and returns three caption sets", async () => {
  const requests = [];
  let described;
  let captionInput;
  const service = createPhotoMemeService({
    geminiApiKey: "fake-gemini-key",
    matchServiceUrl: "http://127.0.0.1:8808",
    matchServiceKey: "fake-match-key",
    fetchImpl: async (url, init) => {
      requests.push({ url: String(url), init });
      return new Response(JSON.stringify(matchingResponse), { headers: { "content-type": "application/json" } });
    },
    describePhoto: async (photo) => { described = photo; return "A person smiles while reading a book."; },
    draftCaptions: async (description, matches) => {
      captionInput = { description, matches };
      return { selected_asset_id: 123, options: [
        { texts: ["OPTION ONE TOP", "OPTION ONE BOTTOM"] },
        { texts: ["OPTION TWO TOP", "OPTION TWO BOTTOM"] },
        { texts: ["OPTION THREE TOP", "OPTION THREE BOTTOM"] },
      ] };
    },
  });

  const result = await service.generate(validatePhotoRequest(photoRequest()));

  assert.equal(described.mimeType, "image/jpeg");
  assert.equal(described.bytes.length, jpeg().length);
  assert.equal(requests.length, 1);
  assert.equal(new URL(requests[0].url).pathname, "/match");
  assert.equal(requests[0].init.headers["X-Match-Key"], "fake-match-key");
  assert.equal(requests[0].init.redirect, "manual");
  assert.deepEqual(JSON.parse(requests[0].init.body), {
    description: "A person smiles while reading a book.", k: 12, captions_per_template: 8,
  });
  assert.doesNotMatch(requests[0].init.body, /data:image|base64/);
  assert.equal(captionInput.description, "A person smiles while reading a book.");
  assert.deepEqual(result.options[2].texts, ["OPTION THREE TOP", "OPTION THREE BOTTOM"]);
  assert.equal(result.selectedMatch.template.asset_id, 123);
});

test("Gemini calls use the supported structured-output body and matcher gets 45 seconds", async () => {
  const requests = [];
  const timeoutDurations = [];
  let geminiCalls = 0;
  const service = createPhotoMemeService({
    geminiApiKey: "fake-gemini-key",
    matchServiceUrl: "https://matcher.example",
    matchServiceKey: "fake-match-key",
    timeoutSignal: (duration) => { timeoutDurations.push(duration); return AbortSignal.timeout(duration); },
    fetchImpl: async (url, init) => {
      const body = JSON.parse(init.body);
      requests.push({ url: String(url), init, body });
      if (String(url).includes("generativelanguage.googleapis.com")) {
        geminiCalls += 1;
        const output = geminiCalls === 1
          ? { description: "A person smiles while reading a book." }
          : { selected_asset_id: 123, options: [
            { texts: ["Fresh top one", "Fresh bottom one"] },
            { texts: ["Fresh top two", "Fresh bottom two"] },
            { texts: ["Fresh top three", "Fresh bottom three"] },
          ] };
        return new Response(JSON.stringify({ candidates: [{ content: { parts: [{ text: JSON.stringify(output) }] } }] }), { status: 200 });
      }
      return new Response(JSON.stringify(matchingResponse), { status: 200 });
    },
  });

  await service.generate(validatePhotoRequest(photoRequest()));

  const geminiRequests = requests.filter(({ url }) => url.includes("generativelanguage.googleapis.com"));
  assert.equal(geminiRequests.length, 2);
  assert.equal(geminiRequests[0].body.generationConfig.maxOutputTokens, 2048);
  assert.equal(geminiRequests[0].body.generationConfig.responseMimeType, "application/json");
  assert.deepEqual(geminiRequests[0].body.generationConfig.responseSchema, {
    type: "OBJECT", properties: { description: { type: "STRING" } }, required: ["description"],
  });
  assert.equal("responseFormat" in geminiRequests[0].body.generationConfig, false);
  assert.equal(geminiRequests[1].body.generationConfig.maxOutputTokens, 4096);
  assert.equal(geminiRequests[1].body.generationConfig.responseMimeType, "application/json");
  assert.deepEqual(geminiRequests[1].body.generationConfig.responseSchema, {
    type: "OBJECT",
    properties: {
      selected_asset_id: { type: "INTEGER" },
      options: {
        type: "ARRAY", minItems: 3, maxItems: 3,
        items: {
          type: "OBJECT",
          properties: { texts: { type: "ARRAY", items: { type: "STRING" }, minItems: 1, maxItems: 20 } },
          required: ["texts"],
        },
      },
    },
    required: ["selected_asset_id", "options"],
    propertyOrdering: ["selected_asset_id", "options"],
  });
  assert.equal("responseFormat" in geminiRequests[1].body.generationConfig, false);
  assert.deepEqual(timeoutDurations, [20_000, 45_000, 20_000]);
});

test("Gemini HTTP errors are logged server-side while clients receive only a generic message", async () => {
  const logs = [];
  const service = createPhotoMemeService({
    geminiApiKey: "fake-gemini-key",
    logger: { error: (...args) => logs.push(args) },
    fetchImpl: async () => new Response(JSON.stringify({ error: { message: "Gemini private diagnostic" } }), { status: 400 }),
  });
  await assert.rejects(service.generate(validatePhotoRequest(photoRequest())), (error) => {
    assert.equal(error.code, "GEMINI_UNAVAILABLE");
    assert.doesNotMatch(error.message, /Gemini private diagnostic/);
    return true;
  });
  assert.deepEqual(logs, [["Gemini API request failed", { status: 400, message: "Gemini private diagnostic" }]]);
});

test("photo pipeline refuses to reuse a community caption verbatim", async () => {
  const service = createPhotoMemeService({
    geminiApiKey: "fake-gemini-key",
    matchServiceKey: "fake-match-key",
    fetchImpl: async () => new Response(JSON.stringify(matchingResponse)),
    describePhoto: async () => "A person reads a book.",
    draftCaptions: async () => ({ selected_asset_id: 123, options: [
      { texts: ["An example setup", "Fresh line"] },
      { texts: ["Different setup", "Different punchline"] },
      { texts: ["Another setup", "Another punchline"] },
    ] }),
  });

  await assert.rejects(service.generate(validatePhotoRequest(photoRequest())), (error) => {
    assert.equal(error.code, "INVALID_CAPTIONS");
    return true;
  });
});

test("photo pipeline requires three distinct caption options", async () => {
  const service = createPhotoMemeService({
    geminiApiKey: "fake-gemini-key",
    matchServiceKey: "fake-match-key",
    fetchImpl: async () => new Response(JSON.stringify(matchingResponse)),
    describePhoto: async () => "A person reads a book.",
    draftCaptions: async () => ({ selected_asset_id: 123, options: [
      { texts: ["Fresh top", "Fresh bottom"] },
      { texts: ["Fresh top", "Fresh bottom"] },
      { texts: ["Another top", "Another bottom"] },
    ] }),
  });

  await assert.rejects(service.generate(validatePhotoRequest(photoRequest())), (error) => {
    assert.equal(error.code, "INVALID_CAPTIONS");
    return true;
  });
});

test("photo pipeline maps match-service outages to a friendly timeout error", async () => {
  const service = createPhotoMemeService({
    geminiApiKey: "fake-gemini-key",
    matchServiceKey: "fake-match-key",
    fetchImpl: async () => { throw new Error("private upstream diagnostic"); },
    describePhoto: async () => "A person reads a book.",
    draftCaptions: async () => assert.fail("captioning must not run"),
  });

  await assert.rejects(service.generate(validatePhotoRequest(photoRequest())), (error) => {
    assert.equal(error.code, "MATCH_SERVICE_UNAVAILABLE");
    assert.doesNotMatch(error.message, /private upstream diagnostic|fake-match-key/);
    return true;
  });
});

test("photo pipeline rejects non-HTTPS remote matcher URLs before sending its key", async () => {
  let calls = 0;
  const service = createPhotoMemeService({
    geminiApiKey: "fake-gemini-key",
    matchServiceUrl: "http://matcher.example",
    matchServiceKey: "fake-match-key",
    fetchImpl: async () => { calls += 1; },
    describePhoto: async () => "A person reads a book.",
    draftCaptions: async () => assert.fail("captioning must not run"),
  });

  await assert.rejects(service.generate(validatePhotoRequest(photoRequest())), (error) => {
    assert.equal(error.code, "MATCH_SERVICE_NOT_CONFIGURED");
    return true;
  });
  assert.equal(calls, 0);
});
