import assert from "node:assert/strict";
import { Readable } from "node:stream";
import test from "node:test";
import { createFetchHandler, createRequestHandler } from "../server.mjs";


const automemeData = { template_id: 61579, url: "https://i.imgflip.com/auto.jpg", page_url: "https://imgflip.com/i/auto" };
const aiMemeData = {
  template_id: 61579,
  url: "https://i.imgflip.com/generated.jpg",
  page_url: "https://imgflip.com/i/generated",
  texts: ["When the task is done", "Another task appears"],
};

function jsonResponse(body, status = 200) {
  return new Response(JSON.stringify(body), { status, headers: { "content-type": "application/json" } });
}

async function call(handler, pathname, body, method = "POST", extraHeaders = {}) {
  const chunks = body === undefined ? [] : [Buffer.from(typeof body === "string" ? body : JSON.stringify(body))];
  const request = Readable.from(chunks);
  request.url = pathname;
  request.method = method;
  request.headers = { host: "localhost:3000", "content-type": "application/json", ...extraHeaders };
  const response = {
    statusCode: 0,
    headers: {},
    headersSent: false,
    body: "",
    rawBody: Buffer.alloc(0),
    writeHead(statusCode, headers) {
      this.statusCode = statusCode;
      this.headers = headers;
      this.headersSent = true;
    },
    end(value = "") {
      this.rawBody = Buffer.isBuffer(value) ? value : Buffer.from(String(value));
      this.body = this.rawBody.toString("utf8");
    },
    destroy() {},
  };
  await handler(request, response);
  return {
    status: response.statusCode,
    headers: response.headers,
    text: response.body,
    bytes: response.rawBody,
    json: () => JSON.parse(response.body),
  };
}

async function withApp(options, run) {
  const handler = createRequestHandler(options);
  await run((pathname, body, method = "POST") => call(handler, pathname, body, method));
}

function providerFetch(calls, { fail = false } = {}) {
  return async (url, init) => {
    const pathname = new URL(url).pathname;
    calls.push({ pathname, init });
    if (fail) return jsonResponse({ success: false, error_message: "secret upstream detail" });
    if (pathname === "/automeme") return jsonResponse({ success: true, data: automemeData });
    if (pathname === "/ai_meme") return jsonResponse({ success: true, data: aiMemeData });
    if (pathname === "/caption_image") {
      return jsonResponse({ success: true, data: { url: "https://i.imgflip.com/edited.jpg", page_url: "https://imgflip.com/i/edited" } });
    }
    throw new Error(`Unexpected path: ${pathname}`);
  };
}

test("matched prompt returns editable captions through the server route", async () => {
  const calls = [];
  await withApp({ apiKey: "test-token", fetchImpl: providerFetch(calls) }, async (request) => {
    const response = await request("/api/generate", { prompt: "When one meeting becomes another" });
    const result = response.json();

    assert.equal(response.status, 200);
    assert.equal(result.templateId, "61579");
    assert.deepEqual(result.texts, aiMemeData.texts);
    assert.equal(result.matchedTemplate, true);
    assert.equal(calls.length, 2);
    assert.ok(calls.every(({ init }) => init.headers.Authorization === "Bearer test-token"));
  });
});

test("long prompts are rewritten before Imgflip matching and returned for user transparency", async () => {
  const calls = [];
  const handler = createRequestHandler({
    apiKey: "test-token",
    fetchImpl: providerFetch(calls),
    rewritePrompt: async () => "We shipped it, now rebuild it",
  });
  const response = await call(handler, "/api/generate", {
    prompt: "Our team shipped a customer dashboard after months of delays and leadership now wants it rebuilt before anyone uses it.",
  });
  const result = response.json();

  assert.equal(response.status, 200);
  assert.equal(result.promptRewrite, "We shipped it, now rebuild it");
  assert.equal(new URLSearchParams(calls[0].init.body).get("text"), "We shipped it, now rebuild it");
  assert.equal(new URLSearchParams(calls[1].init.body).get("prefix_text"), "We shipped it, now rebuild it");
});

test("batch results receive concise Gemini captions rendered onto each matching template", async () => {
  const calls = [];
  let template = 9300;
  const handler = createRequestHandler({
    apiKey: "test-token",
    rewritePrompt: async (_prompt, count) => Array.from({ length: count }, (_, index) => `Funny angle ${index + 1}`),
    writeCaptions: async (_prompt, options) => options.map((option, index) => option.texts.map(() => `Punchline ${index + 1}`)),
    fetchImpl: async (url, init) => {
      const pathname = new URL(url).pathname;
      const fields = new URLSearchParams(init.body);
      calls.push({ pathname, fields });
      if (pathname === "/ai_meme") {
        template += 1;
        return jsonResponse({ success: true, data: { ...aiMemeData, template_id: template } });
      }
      if (pathname === "/caption_image") {
        return jsonResponse({ success: true, data: { url: `https://i.imgflip.com/edited-${fields.get("template_id")}.jpg`, page_url: "https://imgflip.com/i/edited" } });
      }
      throw new Error(`Unexpected path: ${pathname}`);
    },
  });
  const response = await call(handler, "/api/generate", { prompt: "A surprisingly long task", count: 5, strategy: "general" });
  const result = response.json();
  assert.equal(response.status, 200);
  assert.equal(result.memes.length, 5);
  assert.equal(result.memes[0].texts[0], "Punchline 1");
  assert.equal(result.memes[4].promptIdea, "Funny angle 5");
  assert.equal(calls.filter(({ pathname }) => pathname === "/caption_image").length, 5);
  assert.ok(calls.filter(({ pathname }) => pathname === "/caption_image").every(({ fields }) => fields.get("boxes[0][text]").startsWith("Punchline")));
});

test("optional visual captioning sends only size-limited Imgflip images to Gemini", async () => {
  const calls = [];
  let receivedOptions;
  const handler = createRequestHandler({
    apiKey: "test-token",
    environment: { GEMINI_API_KEY: "gemini-test" },
    writeCaptions: async (_prompt, options) => {
      receivedOptions = options;
      return options.map((option) => option.texts.map(() => "A joke about what is visible"));
    },
    fetchImpl: async (url, init) => {
      if (url.startsWith("https://i.imgflip.com/")) {
        calls.push({ url, init });
        return new Response(Buffer.from("fake image bytes"), { headers: { "content-type": "image/png" } });
      }
      return providerFetch(calls)(url, init);
    },
  });
  const response = await call(handler, "/api/generate", { prompt: "A situation", analyzeImages: true });
  const result = response.json();
  assert.equal(response.status, 200);
  assert.equal(calls.filter((call) => call.url?.startsWith("https://i.imgflip.com/")).length, 1);
  assert.equal(receivedOptions[0].image.mimeType, "image/png");
  assert.equal(Buffer.from(receivedOptions[0].image.data, "base64").toString(), "fake image bytes");
  assert.equal(result.imageAnalysisCount, 1);
  assert.equal(result.memes[0].imageAnalysisSent, true);
  assert.equal(result.memes[0].visualCaptionsApplied, true);
  assert.equal(result.memes[0].texts[0], "A joke about what is visible");
});

test("falls back to text captioning when an image is unsupported and body cancellation fails", async () => {
  const providerCalls = [];
  const handler = createRequestHandler({
    apiKey: "test-token",
    environment: { GEMINI_API_KEY: "gemini-test" },
    writeCaptions: async (_prompt, options) => {
      assert.equal(options[0].image, null);
      return options.map((option) => option.texts.map(() => "Text-only punchline"));
    },
    fetchImpl: async (url, init) => {
      if (url.startsWith("https://i.imgflip.com/")) {
        return new Response(new ReadableStream({ cancel() { return Promise.reject(new Error("cancel failed")); } }), {
          headers: { "content-type": "text/html" },
        });
      }
      return providerFetch(providerCalls)(url, init);
    },
  });
  const response = await call(handler, "/api/generate", { prompt: "A situation", analyzeImages: true });
  const result = response.json();
  assert.equal(response.status, 200, response.text);
  assert.equal(result.imageAnalysisCount, 0);
  assert.equal(result.memes[0].captionPolished, true);
  assert.equal(result.memes[0].texts[0], "Text-only punchline");
});

test("static app response prevents framing by other sites", async () => {
  const handler = createRequestHandler({ apiKey: "test-token", fetchImpl: async () => assert.fail("provider must not be called") });
  const response = await call(handler, "/", undefined, "GET");

  assert.equal(response.status, 200);
  assert.match(response.headers["content-security-policy"], /frame-ancestors 'none'/);
  assert.match(response.headers["content-security-policy"], /blob:/);
});

test("invalid and oversized prompt inputs are rejected before provider calls", async () => {
  const calls = [];
  await withApp({ apiKey: "test-token", fetchImpl: providerFetch(calls) }, async (request) => {
    for (const prompt of ["   ", "x".repeat(501)]) {
      const response = await request("/api/generate", { prompt });
      assert.equal(response.status, 400);
      assert.equal(response.json().code, "INVALID_INPUT");
    }
    assert.equal(calls.length, 0);
  });
});

test("unsupported batch sizes are rejected before provider calls", async () => {
  let calls = 0;
  await withApp({ apiKey: "test-token", fetchImpl: async () => { calls += 1; } }, async (request) => {
    for (const count of [0, 2, 8, "5"]) {
      const response = await request("/api/generate", { prompt: "A situation", count });
      assert.equal(response.status, 400);
      assert.equal(response.json().code, "INVALID_INPUT");
    }
    assert.equal(calls, 0);
  });
});

test("image analysis option must be a boolean", async () => {
  const handler = createRequestHandler({ apiKey: "test-token", fetchImpl: async () => assert.fail("provider must not be called") });
  for (const analyzeImages of ["true", 1, null]) {
    const response = await call(handler, "/api/generate", { prompt: "A situation", analyzeImages });
    assert.equal(response.status, 400);
    assert.equal(response.json().code, "INVALID_INPUT");
  }
});

test("cross-origin generation is rejected before premium provider calls", async () => {
  let calls = 0;
  const handler = createRequestHandler({ apiKey: "test-token", fetchImpl: async () => { calls += 1; } });
  const response = await call(handler, "/api/generate", { prompt: "A situation" }, "POST", { origin: "https://attacker.example" });

  assert.equal(response.status, 403);
  assert.equal(response.json().code, "CROSS_ORIGIN_REQUEST");
  assert.equal(calls, 0);
});

test("a matching attacker-controlled Host and Origin cannot authorize generation", async () => {
  let calls = 0;
  const handler = createRequestHandler({ apiKey: "test-token", fetchImpl: async () => { calls += 1; } });
  const response = await call(handler, "/api/generate", { prompt: "A situation" }, "POST", {
    host: "attacker.example:3000",
    origin: "http://attacker.example:3000",
  });

  assert.equal(response.status, 403);
  assert.equal(response.json().code, "CROSS_ORIGIN_REQUEST");
  assert.equal(calls, 0);
});

test("Vercel deployment origin is allowed for its API requests", async () => {
  const calls = [];
  await withApp({
    apiKey: "test-token",
    environment: { VERCEL_URL: "meme-project.vercel.app" },
    fetchImpl: providerFetch(calls),
  }, async (request) => {
    const response = await request("/api/generate", { prompt: "A situation" }, "POST", {
      host: "meme-project.vercel.app",
      origin: "https://meme-project.vercel.app",
    });
    assert.equal(response.status, 200);
    assert.equal(calls.length, 2);
  });
});

test("Vercel Fetch adapter translates web requests to the existing API handler", async () => {
  const calls = [];
  const handler = createFetchHandler({
    apiKey: "test-token",
    environment: { VERCEL_URL: "meme-project.vercel.app" },
    fetchImpl: providerFetch(calls),
  });
  const response = await handler(new Request("https://meme-project.vercel.app/api/generate", {
    method: "POST",
    headers: { origin: "https://meme-project.vercel.app", "content-type": "application/json" },
    body: JSON.stringify({ prompt: "A situation" }),
  }));

  assert.equal(response.status, 200);
  assert.deepEqual((await response.json()).texts, aiMemeData.texts);
  assert.equal(calls.length, 2);
});

test("missing API key returns setup instructions without calling Imgflip", async () => {
  let calls = 0;
  await withApp({ apiKey: "", fetchImpl: async () => { calls += 1; } }, async (request) => {
    const response = await request("/api/generate", { prompt: "A situation" });
    const result = response.json();

    assert.equal(response.status, 503);
    assert.equal(result.code, "MISSING_API_KEY");
    assert.match(result.error, /IMGFLIP_API/);
    assert.equal(calls, 0);
  });
});

test("malformed request JSON returns a bounded client error", async () => {
  await withApp({ apiKey: "test-token", fetchImpl: async () => assert.fail("provider must not be called") }, async (request) => {
    const response = await request("/api/generate", "{not json");
    const result = response.json();

    assert.equal(response.status, 400);
    assert.equal(result.code, "INVALID_JSON");
  });
});

test("provider details do not leak through API errors", async () => {
  const calls = [];
  await withApp({ apiKey: "test-token", fetchImpl: providerFetch(calls, { fail: true }) }, async (request) => {
    const response = await request("/api/generate", { prompt: "A situation" });
    const result = response.json();

    assert.equal(response.status, 502);
    assert.equal(result.code, "PROVIDER_ERROR");
    assert.doesNotMatch(result.error, /secret upstream detail/);
  });
});

test("general generation strategy skips automatic template selection", async () => {
  const calls = [];
  await withApp({ apiKey: "test-token", fetchImpl: providerFetch(calls) }, async (request) => {
    const response = await request("/api/generate", { prompt: "A situation", strategy: "general" });
    const result = response.json();

    assert.equal(response.status, 200);
    assert.equal(result.matchedTemplate, false);
    assert.deepEqual(calls.map(({ pathname }) => pathname), ["/ai_meme"]);
  });
});

test("caption endpoint renders an arbitrary number of boxes", async () => {
  const calls = [];
  await withApp({ apiKey: "test-token", fetchImpl: providerFetch(calls) }, async (request) => {
    const response = await request("/api/caption", { templateId: "61579", texts: ["One", "Two", "Three"] });
    const result = response.json();
    const fields = new URLSearchParams(calls[0].init.body);

    assert.equal(response.status, 200);
    assert.equal(result.imageUrl, "https://i.imgflip.com/edited.jpg");
    assert.deepEqual([0, 1, 2].map((index) => fields.get(`boxes[${index}][text]`)), ["One", "Two", "Three"]);
  });
});

test("caption endpoint rejects invalid box arrays before provider calls", async () => {
  let calls = 0;
  await withApp({ apiKey: "test-token", fetchImpl: async () => { calls += 1; } }, async (request) => {
    const response = await request("/api/caption", { templateId: "abc", texts: [] });
    assert.equal(response.status, 400);
    assert.equal(response.json().code, "INVALID_INPUT");
    assert.equal(calls, 0);
  });
});

test("unsupported routes and methods fail without provider calls", async () => {
  await withApp({ apiKey: "test-token", fetchImpl: async () => assert.fail("provider must not be called") }, async (request) => {
    assert.equal((await request("/api/missing", undefined, "GET")).status, 404);
    assert.equal((await request("/api/generate", undefined, "GET")).status, 405);
  });
});

test("download route returns Imgflip images as safe attachments", async () => {
  const imageBytes = Buffer.from([137, 80, 78, 71, 1, 2, 3]);
  let fetchOptions;
  const requestHandler = createRequestHandler({
    apiKey: "test-token",
    fetchImpl: async (_url, options) => {
      fetchOptions = options;
      return new Response(imageBytes, { headers: { "content-type": "image/png", "content-length": String(imageBytes.length) } });
    },
  });
  const url = encodeURIComponent("https://i.imgflip.com/sample.png");
  const response = await call(requestHandler, `/api/download?url=${url}`, undefined, "GET");

  assert.equal(response.status, 200);
  assert.deepEqual(response.bytes, imageBytes);
  assert.equal(response.headers["content-type"], "image/png");
  assert.match(response.headers["content-disposition"], /^attachment; filename="meme-[\w-]+\.png"$/);
  assert.equal(response.headers["x-content-type-options"], "nosniff");
  assert.equal(fetchOptions.redirect, "manual");
  assert.ok(fetchOptions.signal instanceof AbortSignal);
});

test("download route rejects untrusted schemes and hosts before fetching", async () => {
  let calls = 0;
  const requestHandler = createRequestHandler({ apiKey: "test-token", fetchImpl: async () => { calls += 1; } });
  const badUrls = [
    "http://i.imgflip.com/sample.png",
    "https://imgflip.com/sample.png",
    "https://i.imgflip.com.evil.test/sample.png",
    "javascript:alert(1)",
    "not a URL",
  ];

  for (const value of badUrls) {
    const response = await call(requestHandler, `/api/download?url=${encodeURIComponent(value)}`, undefined, "GET");
    assert.equal(response.status, 400);
    assert.equal(response.json().code, "INVALID_DOWNLOAD_URL");
  }
  assert.equal(calls, 0);
});

test("download route never follows Imgflip redirects", async () => {
  let options;
  const requestHandler = createRequestHandler({
    apiKey: "test-token",
    fetchImpl: async (_url, fetchOptions) => {
      options = fetchOptions;
      return new Response(null, { status: 302, headers: { location: "https://evil.test/image.png" } });
    },
  });
  const response = await call(requestHandler, `/api/download?url=${encodeURIComponent("https://i.imgflip.com/sample.png")}`, undefined, "GET");

  assert.equal(response.status, 502);
  assert.equal(response.json().code, "DOWNLOAD_FAILED");
  assert.equal(options.redirect, "manual");
});

test("download route rejects non-image and failed upstream responses", async () => {
  for (const fetchImpl of [
    async () => new Response("not an image", { headers: { "content-type": "text/plain" } }),
    async () => { throw new Error("private network detail"); },
  ]) {
    const requestHandler = createRequestHandler({ apiKey: "test-token", fetchImpl });
    const response = await call(requestHandler, `/api/download?url=${encodeURIComponent("https://i.imgflip.com/sample.png")}`, undefined, "GET");
    assert.equal(response.status, 502);
    assert.equal(response.json().code, "DOWNLOAD_FAILED");
    assert.doesNotMatch(response.text, /private network detail/);
  }
});

test("download route rejects a declared body larger than 20 MiB", async () => {
  const requestHandler = createRequestHandler({
    apiKey: "test-token",
    fetchImpl: async () => new Response(null, {
      headers: { "content-type": "image/png", "content-length": String(20 * 1024 * 1024 + 1) },
    }),
  });
  const response = await call(requestHandler, `/api/download?url=${encodeURIComponent("https://i.imgflip.com/large.png")}`, undefined, "GET");

  assert.equal(response.status, 413);
  assert.equal(response.json().code, "DOWNLOAD_TOO_LARGE");
});

function fakePhotoJpeg(width = 320, height = 240) {
  return Buffer.from([0xff, 0xd8, 0xff, 0xc0, 0x00, 0x0b, 0x08, height >> 8, height & 0xff, width >> 8, width & 0xff, 0x01, 0x01, 0x11, 0x00, 0xff, 0xd9]);
}

const fakeMatches = {
  matches: [{
    rank: 1, score: 0.7,
    template: {
      asset_id: 42, slug: "test", name: "Test template",
      source_url: "https://imgflip.com/meme/42/test", image_url: "https://i.imgflip.com/test.jpg",
      width: 300, height: 200, safe_for_work: true, box_count: 1, boxes_explicit: false, boxes: [],
    },
    example_captions: [{ box_texts: ["Example caption"], author: "example-user", url: "https://imgflip.com/i/example", upvotes: 1 }],
  }],
};

test("photo-meme API is available without authentication configuration", async () => {
  const calls = [];
  let geminiCall = 0;
  const handler = createRequestHandler({
    environment: { GEMINI_API_KEY: "fake-gemini", MATCH_SERVICE_URL: "https://match.test", MATCH_SERVICE_KEY: "fake-match" },
    fetchImpl: async (url, init) => {
      const target = new URL(url);
      calls.push({ target, init });
      if (target.hostname === "match.test") return jsonResponse(fakeMatches);
      geminiCall += 1;
      const text = geminiCall === 1
        ? JSON.stringify({ description: "A person smiles while reading a book." })
        : JSON.stringify({ selected_asset_id: 42, options: [
          { texts: ["Fresh first option"] }, { texts: ["Fresh second option"] }, { texts: ["Fresh third option"] },
        ] });
      return jsonResponse({ candidates: [{ content: { parts: [{ text }] } }] });
    },
  });
  const image = fakePhotoJpeg();
  const response = await call(handler, "/api/photo-meme", { photo: `data:image/jpeg;base64,${image.toString("base64")}` });
  assert.equal(response.status, 200, response.text);
  assert.equal(response.json().options.length, 3);
});

test("photo-meme route runs Gemini description, text-only match search and caption drafting with fake services", async () => {
  const calls = [];
  let geminiCall = 0;
  const handler = createRequestHandler({
    environment: {
      GEMINI_API_KEY: "fake-gemini", MATCH_SERVICE_URL: "https://match.test", MATCH_SERVICE_KEY: "fake-match",
    },
    fetchImpl: async (url, init) => {
      const target = new URL(url);
      calls.push({ target, init });
      if (target.hostname === "match.test") return jsonResponse(fakeMatches);
      geminiCall += 1;
      const text = geminiCall === 1
        ? JSON.stringify({ description: "A person smiles while reading a book." })
        : JSON.stringify({ selected_asset_id: 42, options: [
          { texts: ["Fresh first option"] }, { texts: ["Fresh second option"] }, { texts: ["Fresh third option"] },
        ] });
      return jsonResponse({ candidates: [{ content: { parts: [{ text }] } }] });
    },
  });
  const image = fakePhotoJpeg();
  const response = await call(handler, "/api/photo-meme", { photo: `data:image/jpeg;base64,${image.toString("base64")}` });
  const result = response.json();
  const matchCall = calls.find(({ target }) => target.hostname === "match.test");

  assert.equal(response.status, 200, response.text);
  assert.equal(geminiCall, 2);
  assert.equal(result.options.length, 3);
  assert.equal(result.selectedMatch.template.asset_id, 42);
  assert.deepEqual(JSON.parse(matchCall.init.body), { description: "A person smiles while reading a book.", k: 12, captions_per_template: 8 });
  assert.equal(matchCall.init.headers["X-Match-Key"], "fake-match");
  assert.equal(matchCall.init.redirect, "manual");
  assert.doesNotMatch(matchCall.init.body, /base64|data:image/);
  assert.match(calls.find(({ target }) => target.hostname === "generativelanguage.googleapis.com").init.body, /inlineData/);
});

test("photo-meme route rejects invalid photos before calling Gemini or the match service", async () => {
  let calls = 0;
  const handler = createRequestHandler({
    environment: { GEMINI_API_KEY: "fake-gemini", MATCH_SERVICE_KEY: "fake-match" },
    fetchImpl: async () => { calls += 1; },
  });
  const response = await call(handler, "/api/photo-meme", { photo: "data:image/png;base64,iVBORw0KGgo=" });
  assert.equal(response.status, 400);
  assert.equal(response.json().code, "INVALID_PHOTO");
  assert.equal(calls, 0);
});

test("photo-meme route returns a friendly matcher outage response without leaking upstream details", async () => {
  let geminiCall = 0;
  const handler = createRequestHandler({
    environment: { GEMINI_API_KEY: "fake-gemini", MATCH_SERVICE_URL: "https://match.test", MATCH_SERVICE_KEY: "fake-match" },
    fetchImpl: async (url) => {
      if (new URL(url).hostname === "match.test") throw new Error("private upstream diagnostic");
      geminiCall += 1;
      return jsonResponse({ candidates: [{ content: { parts: [{ text: JSON.stringify({ description: "A person smiles while reading." }) }] } }] });
    },
  });
  const image = fakePhotoJpeg();
  const response = await call(handler, "/api/photo-meme", { photo: `data:image/jpeg;base64,${image.toString("base64")}` });
  assert.equal(response.status, 503);
  assert.equal(response.json().code, "MATCH_SERVICE_UNAVAILABLE");
  assert.doesNotMatch(response.text, /private upstream diagnostic|fake-match/);
  assert.equal(geminiCall, 1);
});
