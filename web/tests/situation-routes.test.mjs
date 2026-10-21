import assert from "node:assert/strict";
import { Readable } from "node:stream";
import test from "node:test";
import { PhotoMemeError } from "../lib/photo-meme.mjs";
import { createRequestHandler } from "../server.mjs";

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
    text: response.body,
    json: () => JSON.parse(response.body),
  };
}

const SITUATION = "When you are working in the dark for hours and your roommate turns on the bright light";
function jpeg() {
  return Buffer.from([0xff, 0xd8, 0xff, 0xc0, 0x00, 0x0b, 0x08, 0x00, 0xf0, 0x01, 0x40, 0x01, 0x01, 0x11, 0x00, 0xff, 0xd9]);
}
const RESULT = { mode: "situation", situation: SITUATION, candidates: [{ rank: 1, texts: ["a", "b"] }], analogs: [] };

function build({ service, feedback = [] } = {}) {
  const calls = [];
  const situationMemeService = service ?? { generate: async (input) => { calls.push(input); return RESULT; } };
  const handler = createRequestHandler({
    environment: { GEMINI_API_KEY: "g", MATCH_SERVICE_KEY: "m", IMGFLIP_API: "i" },
    situationMemeService,
    feedbackLog: (entry) => feedback.push(entry),
    fetchImpl: async () => { throw new Error("no network in route tests"); },
  });
  return { handler, calls, feedback };
}

test("situation route passes a trimmed situation to the service and returns its result", async () => {
  const { handler, calls } = build();
  const response = await call(handler, "/api/situation-meme", { situation: `  ${SITUATION} ` });
  assert.equal(response.status, 200);
  assert.deepEqual(response.json(), RESULT);
  assert.equal(calls[0].situation, SITUATION);
  assert.equal(calls[0].photo, null);
});

test("situation route forwards a validated photo", async () => {
  const { handler, calls } = build();
  const response = await call(handler, "/api/situation-meme", { situation: SITUATION, photo: `data:image/jpeg;base64,${jpeg().toString("base64")}` });
  assert.equal(response.status, 200);
  assert.deepEqual(calls[0].photo.bytes, jpeg());
});

test("situation route rejects bad input before calling the service", async () => {
  const { handler, calls } = build();
  for (const body of [{}, { situation: "hi" }, { situation: SITUATION, photo: "data:image/png;base64,AAAA" }]) {
    const response = await call(handler, "/api/situation-meme", body);
    assert.equal(response.status, 400);
    assert.ok(response.json().error);
  }
  assert.equal(calls.length, 0);
});

test("situation route has the same cross-origin protection and method rules as the other API routes", async () => {
  const { handler, calls } = build();
  const crossOrigin = await call(handler, "/api/situation-meme", { situation: SITUATION }, "POST", { origin: "https://evil.example" });
  assert.equal(crossOrigin.status, 403);
  assert.equal((await call(handler, "/api/situation-meme", undefined, "GET")).status, 405);
  assert.equal(calls.length, 0);
});

test("service errors become friendly responses with their own status and code, nothing else", async () => {
  const { handler } = build({ service: { generate: async () => { throw new PhotoMemeError("MATCH_SERVICE_UNAVAILABLE", "The meme finder is taking a break.", 503); } } });
  const response = await call(handler, "/api/situation-meme", { situation: SITUATION });
  assert.equal(response.status, 503);
  assert.deepEqual(response.json(), { error: "The meme finder is taking a break.", code: "MATCH_SERVICE_UNAVAILABLE" });
});

test("without keys the default service reports itself as not configured", async () => {
  const handler = createRequestHandler({ environment: { GEMINI_API_KEY: "", MATCH_SERVICE_KEY: "", SITUATION_MATCH_URL: "", IMGFLIP_API: "i" } });
  const response = await call(handler, "/api/situation-meme", { situation: SITUATION });
  assert.equal(response.status, 503);
  assert.equal(response.json().code, "GEMINI_NOT_CONFIGURED");
});

test("feedback route logs a valid rating server-side and rejects anything else", async () => {
  const { handler, feedback } = build();
  const ok = await call(handler, "/api/feedback", { rating: 4, mode: "photo+situation", assetId: 11, helpful: true });
  assert.equal(ok.status, 200);
  assert.deepEqual(feedback, [{ rating: 4, mode: "photo+situation", assetId: 11, helpful: true }]);
  for (const body of [{ rating: 0, mode: "situation" }, { rating: 6, mode: "situation" }, { rating: 3, mode: "nope" }, { rating: "5", mode: "situation" }, { rating: 3, mode: "situation", assetId: "x" }, {}]) {
    assert.equal((await call(handler, "/api/feedback", body)).status, 400);
  }
  assert.equal(feedback.length, 1);
  assert.equal((await call(handler, "/api/feedback", undefined, "GET")).status, 405);
  assert.equal((await call(handler, "/api/feedback", { rating: 5, mode: "situation" }, "POST", { origin: "https://evil.example" })).status, 403);
});
