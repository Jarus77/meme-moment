import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import { renderAnalogs, renderFitCards } from "../public/fit-view.mjs";

class FakeNode {
  constructor(tag) { this.tag = tag; this.children = []; this.attrs = {}; this.listeners = {}; this.className = ""; this._text = ""; }
  setAttribute(name, value) { this.attrs[name] = value; }
  appendChild(child) { this.children.push(child); return child; }
  replaceChildren(...nodes) { this.children = nodes; }
  addEventListener(type, handler) { this.listeners[type] = handler; }
  set textContent(value) { this._text = String(value); this.children = []; }
  get textContent() { return this._text + this.children.map((c) => c.textContent).join(""); }
  find(predicate, found = []) { if (predicate(this)) found.push(this); this.children.forEach((c) => c.find?.(predicate, found)); return found; }
}
const doc = { createElement: (tag) => new FakeNode(tag), createTextNode: (text) => { const n = new FakeNode("#text"); n._text = text; return n; } };

const CARD = {
  rank: 1, texts: ["<img src=x onerror=alert(1)>", "second"], imageUrl: "blob:1", rated: 0,
  template: { name: " Light Monsters ", source_url: "https://imgflip.com/meme/11/light-monsters" },
  adaptedFrom: { box_texts: ["Me: Turns on light"], author: "<b>alice</b>", url: "https://imgflip.com/i/aaa", upvotes: 141 },
};

test("each card shows the picture, template link, credited original, rating buttons and a download link", () => {
  const container = new FakeNode("div");
  renderFitCards(container, [CARD, { ...CARD, imageUrl: "blob:2" }], { doc });
  assert.equal(container.children.length, 2);
  const card = container.children[0];
  assert.equal(card.find((n) => n.tag === "img")[0].attrs.src, "blob:1");
  const links = card.find((n) => n.tag === "a");
  assert.ok(links.some((a) => a.attrs.href === "https://imgflip.com/meme/11/light-monsters" && a.textContent === "Light Monsters ↗"));
  assert.ok(links.some((a) => a.attrs.href === "https://imgflip.com/i/aaa" && a.textContent === "<b>alice</b>"));
  assert.ok(links.every((a) => a.attrs.target !== "_blank" || /noopener/.test(a.attrs.rel)));
  assert.equal(card.find((n) => n.className === "fit-rate-button").length, 5);
  assert.ok(card.textContent.includes("141 upvotes"));
  assert.equal(links.find((a) => a.className === "download-button").attrs.download, "meme-option-1.png");
});

test("user and caption text is only ever set as text, never as HTML", () => {
  const container = new FakeNode("div");
  renderFitCards(container, [CARD], { doc });
  const img = container.children[0].find((n) => n.tag === "img")[0];
  assert.ok(img.attrs.alt.includes("<img src=x onerror=alert(1)>"));
  for (const source of ["../public/fit-view.mjs", "../public/fit-meme.mjs"]) {
    assert.equal(/innerHTML|outerHTML|insertAdjacentHTML|document\.write/.test(readFileSync(new URL(source, import.meta.url), "utf8")), false, source);
  }
});

test("clicking a rating button reports the card index and the rating", () => {
  const container = new FakeNode("div");
  const calls = [];
  renderFitCards(container, [CARD, CARD], { doc, onRate: (...args) => calls.push(args) });
  const buttons = container.children[1].find((n) => n.className === "fit-rate-button");
  buttons[3].listeners.click();
  assert.deepEqual(calls, [[1, 4]]);
});

test("a rated card shows thanks and marks the chosen rating as pressed", () => {
  const container = new FakeNode("div");
  renderFitCards(container, [{ ...CARD, rated: 5 }], { doc });
  const card = container.children[0];
  assert.ok(card.textContent.includes("Thanks!"));
  assert.deepEqual(card.find((n) => n.className === "fit-rate-button").map((b) => b.attrs["aria-pressed"]), ["false", "false", "false", "false", "true"]);
});

test("the evidence list credits each real caption's template and author", () => {
  const list = new FakeNode("ul");
  renderAnalogs(list, [{ box_texts: ["Me: Turns on light", "Monsters:"], template: { name: "disappearing " }, author: "alice", url: "https://imgflip.com/i/aaa", upvotes: 141 }], { doc });
  assert.equal(list.children.length, 1);
  assert.ok(list.children[0].textContent.includes("Me: Turns on light / Monsters:"));
  assert.ok(list.children[0].textContent.includes("disappearing"));
  assert.equal(list.children[0].find((n) => n.tag === "a")[0].attrs.href, "https://imgflip.com/i/aaa");
});

test("a card explains which searches found its meme, in plain words", () => {
  const container = new FakeNode("div");
  renderFitCards(container, [{ ...CARD, foundBy: ["meaning", "photo_picture"] }, { ...CARD, foundBy: [] }], { doc });
  const found = container.children[0].find((n) => n.className === "fit-found")[0];
  assert.match(found.textContent, /your situation ↔ real captions/);
  assert.match(found.textContent, /your photo ↔ meme pictures/);
  assert.equal(container.children[1].find((n) => n.className === "fit-found").length, 0);
});
