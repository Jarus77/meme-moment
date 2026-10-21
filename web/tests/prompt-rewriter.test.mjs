import assert from "node:assert/strict";
import test from "node:test";
import { createCaptionWriter, createPromptRewriter } from "../lib/prompt-rewriter.mjs";

const longPrompt = "Our team shipped the customer dashboard after months of delays, and now leadership has asked us to rebuild it in a different framework before anyone has even used it.";

function geminiResponse(...text) {
  const value = text.length === 1 && typeof text[0] === "object" ? text[0] : { situations: text };
  return new Response(JSON.stringify({
    candidates: [{ content: { parts: [{ text: JSON.stringify(value) }] } }],
  }), { status: 200, headers: { "content-type": "application/json" } });
}

test("rewrites a long prompt into a short situation using the server-side Gemini API", async () => {
  let request;
  const rewritePrompt = createPromptRewriter({
    apiKey: "gemini-test-key",
    fetchImpl: async (url, init) => {
      request = { url, init, body: JSON.parse(init.body) };
      return geminiResponse("We shipped it, now rebuild it");
    },
  });

  const result = await rewritePrompt(longPrompt);

  assert.deepEqual(result, ["We shipped it, now rebuild it"]);
  assert.equal(request.url, "https://generativelanguage.googleapis.com/v1beta/models/gemini-3.6-flash:generateContent");
  assert.equal(request.init.headers["x-goog-api-key"], "gemini-test-key");
  assert.equal(request.body.contents[0].parts[0].text, longPrompt);
  assert.equal(request.body.generationConfig.maxOutputTokens, 300);
  assert.equal(request.body.generationConfig.responseMimeType, "application/json");
  assert.deepEqual(request.body.generationConfig.responseSchema, {
    type: "OBJECT", properties: { situations: { type: "ARRAY", items: { type: "STRING" }, minItems: 1, maxItems: 1 } }, required: ["situations"],
  });
  assert.equal("responseFormat" in request.body.generationConfig, false);
});

test("Gemini HTTP failures are logged but never returned as user-facing errors", async () => {
  const logs = [];
  const rewritePrompt = createPromptRewriter({
    apiKey: "test",
    logger: { error: (...args) => logs.push(args) },
    fetchImpl: async () => new Response(JSON.stringify({ error: { message: "Private Gemini detail" } }), { status: 400 }),
  });
  assert.equal(await rewritePrompt(longPrompt), null);
  assert.deepEqual(logs, [["Gemini API request failed", { status: 400, message: "Private Gemini detail" }]]);
});

test("uses Gemini on short prompts to create joke-ready phrasing", async () => {
  let calls = 0;
  const rewritePrompt = createPromptRewriter({ apiKey: "test", fetchImpl: async () => { calls += 1; return geminiResponse("The cat filed a formal complaint about the dog"); } });

  assert.deepEqual(await rewritePrompt("When Monday arrives"), ["The cat filed a formal complaint about the dog"]);
  assert.equal(calls, 1);
});

test("asks Gemini for exactly the requested number of distinct angles", async () => {
  let request;
  const rewritePrompt = createPromptRewriter({ apiKey: "test", fetchImpl: async (_url, init) => {
    request = JSON.parse(init.body);
    return geminiResponse("angle one", "angle two", "angle three", "angle four", "angle five");
  } });
  const result = await rewritePrompt("Our launch failed in an amusing way", 5);
  assert.equal(result.length, 5);
  assert.equal(request.generationConfig.responseSchema.properties.situations.maxItems, 5);
});

test("rejects repeated joke angles instead of presenting duplicate options", async () => {
  const rewritePrompt = createPromptRewriter({ apiKey: "test", fetchImpl: async () => geminiResponse("Same angle", "same ANGLE") });
  assert.equal(await rewritePrompt("A situation", 2), null);
});

test("fails open when the LLM is not configured or returns invalid output", async () => {
  const unconfigured = createPromptRewriter({ apiKey: "" });
  assert.equal(await unconfigured(longPrompt), null);

  const malformed = createPromptRewriter({ apiKey: "test", fetchImpl: async () => geminiResponse("x".repeat(121)) });
  assert.equal(await malformed(longPrompt), null);
});

test("fails open instead of parsing an oversized Gemini response", async () => {
  let cancelled = false;
  const body = JSON.stringify({ candidates: [{ content: { parts: [{ text: `{"situation":"${"x".repeat(17_000)}"}` }] } }] });
  const oversized = createPromptRewriter({
    apiKey: "test",
    fetchImpl: async () => new Response(new ReadableStream({
      start(controller) { controller.enqueue(new TextEncoder().encode(body)); },
      cancel() { cancelled = true; },
    })),
  });

  assert.equal(await oversized(longPrompt), null);
  assert.equal(cancelled, true);
});

test("cancels a Gemini response when its declared length exceeds the cap", async () => {
  let cancelled = false;
  const oversized = createPromptRewriter({
    apiKey: "test",
    fetchImpl: async () => new Response(new ReadableStream({ cancel() { cancelled = true; } }), {
      headers: { "content-length": "20000" },
    }),
  });

  assert.equal(await oversized(longPrompt), null);
  assert.equal(cancelled, true);
});

test("writes funny captions while preserving each selected template's exact box count", async () => {
  let request;
  const writer = createCaptionWriter({ apiKey: "test", fetchImpl: async (_url, init) => {
    request = JSON.parse(init.body);
    return geminiResponse({ options: [{ texts: ["When the agent finds the answer", "The dashboard asks for a status update"] }, { texts: ["My data has a signal", "The signal is another meeting"] }] });
  } });
  const captions = await writer("Agents find a signal, then report it", [
    { situation: "Agent spots the signal", texts: ["A", "B"] },
    { situation: "Signal becomes a meeting", texts: ["A", "B"] },
  ]);
  assert.deepEqual(captions, [["When the agent finds the answer", "The dashboard asks for a status update"], ["My data has a signal", "The signal is another meeting"]]);
  assert.equal(request.generationConfig.maxOutputTokens, 4096);
  assert.equal(request.generationConfig.responseMimeType, "application/json");
  assert.equal(request.generationConfig.responseSchema.properties.options.maxItems, 2);
  assert.equal("responseFormat" in request.generationConfig, false);
  assert.match(request.systemInstruction.parts[0].text, /punchline/i);
});

test("includes optional Imgflip image bytes in Gemini's caption request", async () => {
  let request;
  const writer = createCaptionWriter({ apiKey: "test", fetchImpl: async (_url, init) => {
    request = JSON.parse(init.body);
    return geminiResponse({ options: [{ texts: ["A visually grounded punchline"] }] });
  } });
  const captions = await writer("The situation", [{ situation: "The punchline angle", texts: ["Draft"], image: { mimeType: "image/png", data: "aW1hZ2U=" } }]);
  assert.deepEqual(captions, [["A visually grounded punchline"]]);
  const parts = request.contents[0].parts;
  assert.equal(parts[2].inlineData.mimeType, "image/png");
  assert.equal(parts[2].inlineData.data, "aW1hZ2U=");
  assert.match(parts[0].text, /Draft/);
});

test("rejects caption output that changes a template's number of boxes", async () => {
  const writer = createCaptionWriter({ apiKey: "test", fetchImpl: async () => geminiResponse({ options: [{ texts: ["Only one"] }] }) });
  assert.equal(await writer("A situation", [{ situation: "A joke angle", texts: ["Top", "Bottom"] }]), null);
});

test("rejects identical caption sets across a batch", async () => {
  const writer = createCaptionWriter({ apiKey: "test", fetchImpl: async () => geminiResponse({ options: [{ texts: ["Same joke"] }, { texts: ["same joke"] }] }) });
  const captions = await writer("A situation", [
    { situation: "Angle one", texts: ["Draft"] },
    { situation: "Angle two", texts: ["Draft"] },
  ]);
  assert.equal(captions, null);
});
