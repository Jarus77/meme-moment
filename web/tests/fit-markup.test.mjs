import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const html = readFileSync(new URL("../public/index.html", import.meta.url), "utf8");
const app = readFileSync(new URL("../public/app.js", import.meta.url), "utf8");
const css = readFileSync(new URL("../public/styles.css", import.meta.url), "utf8");

test("the page offers exactly three ways in: situation, photo only, photo plus situation", () => {
  const tabs = [...html.matchAll(/<button[^>]*role="tab"[^>]*data-fit-tab="([a-z]+)"/g)].map((m) => m[1]);
  assert.deepEqual(tabs, ["situation", "photo", "both"]);
  for (const id of ["fit-form-situation", "fit-situation-text", "fit-form-both", "fit-photo-input", "fit-both-text", "fit-status", "fit-error", "fit-results", "fit-card-list", "fit-analogs"]) {
    assert.ok(html.includes(`id="${id}"`), `missing #${id}`);
  }
  assert.match(html, /<input id="fit-photo-input"[^>]*type="file"[^>]*accept="image\/\*"/);
  assert.equal([...html.matchAll(/<textarea id="fit-(?:situation|both)-text"[^>]*maxlength="500"/g)].length, 2);
});

test("the original situation tool and the photo-only tool are still on the page", () => {
  for (const id of ["meme-form", "prompt", "generate", "photo-form", "photo-input", "make-photo-meme", "photo-result"]) {
    assert.ok(html.includes(`id="${id}"`), `original #${id} was removed`);
  }
});

test("the page explains the pipeline briefly and is honest about where the photo goes", () => {
  assert.match(html, /real[^<]{0,60}captions/i);
  assert.match(html, /Gemini[^<]{0,80}(adjust|adapt)/i);
  const bothForm = html.slice(html.indexOf('id="fit-form-both"'), html.indexOf("</form>", html.indexOf('id="fit-form-both"')));
  assert.match(bothForm, /Gemini/);
  assert.match(bothForm, /never[^<]*(matcher|meme finder)/i);
  assert.match(bothForm, /does not save/i);
});

test("the script wires the new modes and releases image URLs when the page is left", () => {
  assert.match(app, /from '\.\/fit-meme\.mjs'/);
  assert.match(app, /from '\.\/fit-view\.mjs'/);
  assert.match(app, /fitActions\.dispose\(\)/);
  assert.match(app, /\/api\/situation-meme|fitActions\.generate/);
});

test("the new section is styled", () => {
  for (const selector of [".fit-workspace", ".fit-tabs", ".fit-tab", ".fit-card-list", ".fit-card", ".fit-rate-button"]) {
    assert.ok(css.includes(selector), `missing styles for ${selector}`);
  }
});

test("an Under the hood section explains exactly what is matched to what", () => {
  const start = html.indexOf('id="under-the-hood"');
  assert.ok(start > 0, "missing #under-the-hood");
  const section = html.slice(start, html.indexOf("</section>", start));
  const rows = [...section.matchAll(/<tr data-search="([a-z_]+)"/g)].map((m) => m[1]);
  assert.deepEqual(rows, ["keywords", "meaning", "situation_picture", "photo_picture", "photo_caption"]);
  for (const phrase of [/cosine/i, /same space/i, /round-robin|one slot at a time/i, /worked example/i, /not (yet )?(measured|tested|proven)/i, /upvotes/i]) {
    assert.match(section, phrase);
  }
});
