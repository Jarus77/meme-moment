import assert from "node:assert/strict";
import test from "node:test";
import { createFitMemeActions } from "../public/fit-meme.mjs";

const SITUATION = "When you are working in the dark and your roommate turns on the light";

function candidate(id, name, texts) {
  return {
    rank: id, texts,
    template: { asset_id: id, name, source_url: `https://imgflip.com/meme/${id}/x`, image_url: `https://i.imgflip.com/${id}.jpg`, box_count: texts.length },
    adaptedFrom: { box_texts: ["orig"], author: "alice", url: "https://imgflip.com/i/aaa", upvotes: 5 },
  };
}
const RESULT = (mode) => ({ mode, situation: SITUATION, analogs: [], candidates: [candidate(11, "Light Monsters", ["a", "b"]), candidate(22, "Blinking", ["c"])] });

function harness({ result = RESULT("situation"), apiStatus = 200, failImages = [], failFeedback = false } = {}) {
  const requests = [];
  const rendered = [];
  const revoked = [];
  const states = [];
  const fetchImpl = async (url, init = {}) => {
    requests.push({ url: String(url), body: init.body ? JSON.parse(init.body) : null });
    if (String(url) === "/api/situation-meme") return { ok: apiStatus < 400, status: apiStatus, json: async () => (apiStatus < 400 ? result : { error: "Friendly failure." }) };
    if (String(url) === "/api/feedback") return { ok: !failFeedback, status: failFeedback ? 500 : 200, json: async () => ({ ok: true }) };
    if (String(url).startsWith("/api/download?url=")) {
      const id = decodeURIComponent(String(url)).match(/i\.imgflip\.com\/(\d+)/)[1];
      if (failImages.includes(Number(id))) return { ok: false, status: 502, blob: async () => { throw new Error("no"); } };
      return { ok: true, status: 200, blob: async () => ({ type: "image/jpeg", id }) };
    }
    throw new Error(`unexpected ${url}`);
  };
  const actions = createFitMemeActions({
    fetchImpl,
    resizeImpl: async (file) => ({ dataUrl: `data:image/jpeg;base64,PHOTO-${file.name}`, width: 10, height: 10 }),
    blobToDataUrl: async (blob) => `data:image/jpeg;base64,TEMPLATE-${blob.id}`,
    renderImpl: async (dataUrl, texts) => { rendered.push({ dataUrl, texts }); return { type: "image/png", n: rendered.length }; },
    createUrl: (blob) => `blob:${blob.n}`,
    revokeUrl: (url) => revoked.push(url),
    onState: (state) => states.push(state),
  });
  return { actions, requests, rendered, revoked, states };
}

test("situation only: sends no photo, draws each adapted caption on its template picture", async () => {
  const { actions, requests, rendered } = harness();
  const outcome = await actions.generate({ situation: SITUATION, file: null });
  assert.equal(outcome.ok, true);
  const post = requests.find((r) => r.url === "/api/situation-meme");
  assert.deepEqual(post.body, { situation: SITUATION });
  assert.deepEqual(requests.filter((r) => r.url.startsWith("/api/download")).map((r) => decodeURIComponent(r.url)),
    ["/api/download?url=https://i.imgflip.com/11.jpg", "/api/download?url=https://i.imgflip.com/22.jpg"]);
  assert.deepEqual(rendered.map((r) => r.dataUrl), ["data:image/jpeg;base64,TEMPLATE-11", "data:image/jpeg;base64,TEMPLATE-22"]);
  const state = actions.getState();
  assert.equal(state.mode, "situation");
  assert.equal(state.cards.length, 2);
  assert.equal(state.cards[0].imageUrl, "blob:1");
  assert.equal(state.cards[0].adaptedFrom.author, "alice");
});

test("photo plus situation: resizes the photo, sends it with the situation, and draws on the user's photo", async () => {
  const { actions, requests, rendered } = harness({ result: RESULT("photo+situation") });
  await actions.generate({ situation: SITUATION, file: { name: "me.png" } });
  const post = requests.find((r) => r.url === "/api/situation-meme");
  assert.deepEqual(post.body, { situation: SITUATION, photo: "data:image/jpeg;base64,PHOTO-me.png" });
  assert.equal(requests.some((r) => r.url.startsWith("/api/download")), false);
  assert.deepEqual(rendered.map((r) => r.dataUrl), Array(2).fill("data:image/jpeg;base64,PHOTO-me.png"));
  assert.equal(actions.getState().mode, "photo+situation");
});

test("an empty situation is refused locally with a friendly message", async () => {
  const { actions, requests } = harness();
  const outcome = await actions.generate({ situation: "  ", file: null });
  assert.equal(outcome.ok, false);
  assert.match(actions.getState().error, /situation/i);
  assert.equal(requests.length, 0);
});

test("API errors show the server's friendly message and leave the page usable", async () => {
  const { actions } = harness({ apiStatus: 503 });
  const outcome = await actions.generate({ situation: SITUATION, file: null });
  assert.equal(outcome.ok, false);
  assert.equal(actions.getState().error, "Friendly failure.");
  assert.equal(actions.getState().busy, false);
});

test("an incomplete payload is treated as a failure", async () => {
  const { actions } = harness({ result: { mode: "situation", candidates: [] } });
  assert.equal((await actions.generate({ situation: SITUATION, file: null })).ok, false);
});

test("a template picture that cannot be loaded drops only that card", async () => {
  const { actions } = harness({ failImages: [22] });
  const outcome = await actions.generate({ situation: SITUATION, file: null });
  assert.equal(outcome.ok, true);
  assert.deepEqual(actions.getState().cards.map((c) => c.template.asset_id), [11]);
});

test("if every template picture fails the user gets an error, not an empty page", async () => {
  const { actions } = harness({ failImages: [11, 22] });
  assert.equal((await actions.generate({ situation: SITUATION, file: null })).ok, false);
  assert.ok(actions.getState().error);
});

test("a second request while busy is ignored", async () => {
  const { actions } = harness();
  const first = actions.generate({ situation: SITUATION, file: null });
  const second = await actions.generate({ situation: SITUATION, file: null });
  assert.equal(second.code, "BUSY");
  await first;
});

test("rating a card posts feedback and remembers it; bad ratings and failures are handled", async () => {
  const { actions, requests } = harness();
  await actions.generate({ situation: SITUATION, file: null });
  assert.equal((await actions.rate(0, 5)).ok, true);
  assert.deepEqual(requests.find((r) => r.url === "/api/feedback").body, { rating: 5, mode: "situation", assetId: 11 });
  assert.equal(actions.getState().cards[0].rated, 5);
  assert.equal((await actions.rate(0, 9)).ok, false);
  assert.equal((await actions.rate(7, 3)).ok, false);
  const failing = harness({ failFeedback: true });
  await failing.actions.generate({ situation: SITUATION, file: null });
  assert.equal((await failing.actions.rate(0, 4)).ok, false);
  assert.equal(failing.actions.getState().cards[0].rated, 0);
});

test("starting a new run and dispose both release old image URLs", async () => {
  const { actions, revoked } = harness();
  await actions.generate({ situation: SITUATION, file: null });
  await actions.generate({ situation: SITUATION, file: null });
  assert.deepEqual(revoked, ["blob:1", "blob:2"]);
  actions.dispose();
  assert.ok(revoked.includes("blob:3") && revoked.includes("blob:4"));
});
