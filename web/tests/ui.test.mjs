import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";
import { captionFieldsHtml, createDownloadHref } from "../public/ui-model.mjs";
import { createMemeActions } from "../public/ui-actions.mjs";

test("generator shell has a prompt input and generate action", async () => {
  const page = await readFile(new URL("../public/index.html", import.meta.url), "utf8");

  assert.match(page, /<title>[^<]*meme/i);
  assert.match(page, /<textarea[^>]*id="prompt"/);
  assert.match(page, /id="meme-count"/);
  assert.match(page, /id="analyze-images"/);
  assert.match(page, /id="image-analysis-note"/);
  assert.match(page, /value="5" selected/);
  assert.match(page, /id="candidate-list"/);
  assert.match(page, /<button[^>]*id="generate"/);
  assert.match(page, /id="caption-form"/);
  assert.match(page, /id="try-another"/);
  assert.match(page, /id="download-meme"/);
  assert.match(page, /id="general-generate"/);
});

test("photo-to-meme page is open and explains its flow with credited match evidence", async () => {
  const page = await readFile(new URL("../public/index.html", import.meta.url), "utf8");
  assert.match(page, /id="photo-form"/);
  assert.match(page, /id="photo-input"[^>]*accept="image\/\*"/);
  assert.match(page, /resized JPEG must be 5 MB or less/i);
  assert.match(page, /never to the matcher/i);
  assert.match(page, /does not identify anyone/i);
  assert.match(page, /id="photo-option-list"/);
  assert.match(page, /id="matched-template-list"/);
  assert.match(page, /id="download-photo-meme"[^>]*download="photo-meme.png"/);
  assert.equal((page.match(/<li>/g) || []).length >= 4, true);
  const app = await readFile(new URL("../public/app.js", import.meta.url), "utf8");
  assert.match(app, /waking up; this can take up to 30 s/i);
  const vercelConfig = JSON.parse(await readFile(new URL("../vercel.json", import.meta.url), "utf8"));
  assert.equal(vercelConfig.functions["api/*.mjs"].maxDuration, 60);
});

test("photo matcher environment variables are documented without real values", async () => {
  const example = await readFile(new URL("../.env.example", import.meta.url), "utf8");
  const deploy = await readFile(new URL("../DEPLOYING.md", import.meta.url), "utf8");
  for (const variable of ["MATCH_SERVICE_URL", "MATCH_SERVICE_KEY"]) {
    assert.match(example, new RegExp(`^${variable}=`, "m"));
    assert.match(deploy, new RegExp(variable));
  }
  assert.match(deploy, /does not save uploaded photos/i);
});

test("caption editor creates exactly one field per returned caption", () => {
  for (const texts of [["One"], ["Top", "Bottom"], ["A", "B", "C"]]) {
    const html = captionFieldsHtml(texts);
    assert.equal((html.match(/data-caption-index=/g) || []).length, texts.length);
    texts.forEach((text, index) => assert.match(html, new RegExp(`>${text}</textarea>`)));
    assert.match(html, /CAPTION 01/);
  }
});

test("caption field values are HTML-escaped", () => {
  const html = captionFieldsHtml(["<script>alert('&')</script>"]);

  assert.doesNotMatch(html, /<script>/);
  assert.match(html, /&lt;script&gt;alert\(&#39;&amp;&#39;\)&lt;\/script&gt;/);
});

test("download URL accepts only Imgflip-hosted HTTPS images", () => {
  assert.equal(
    createDownloadHref("https://i.imgflip.com/a.jpg"),
    "/api/download?url=https%3A%2F%2Fi.imgflip.com%2Fa.jpg",
  );
  for (const url of ["http://i.imgflip.com/a.jpg", "https://i.imgflip.com.evil.test/a.jpg", "https://evil.test/a.jpg"]) {
    assert.throws(() => createDownloadHref(url), /Imgflip image URL/);
  }
});

test("empty prompt is rejected before generation request", async () => {
  let calls = 0;
  const actions = createMemeActions({ fetchImpl: async () => { calls += 1; } });

  const result = await actions.generate("   ");

  assert.equal(result.ok, false);
  assert.equal(actions.getState().error, "Describe a situation first.");
  assert.equal(calls, 0);
});

test("template match failure offers an explicit general-generation fallback", async () => {
  const requests = [];
  let lastPublishedState;
  const actions = createMemeActions({
    onState: (state) => { lastPublishedState = state; },
    fetchImpl: async (url, init) => {
      requests.push({ url, body: JSON.parse(init.body) });
      return new Response(JSON.stringify({ error: "Template not available", code: "MATCH_FAILED" }), { status: 409 });
    },
  });

  const result = await actions.generate("The meeting that keeps going");

  assert.equal(result.ok, false);
  assert.equal(actions.getState().fallbackPrompt, "The meeting that keeps going");
  assert.equal(actions.getState().fallbackAvailable, true);
  assert.equal(lastPublishedState.fallbackAvailable, true);
  assert.equal(requests.length, 1);
  assert.equal(requests[0].body.strategy, "matched");
});

test("general generation is only requested after its explicit action", async () => {
  const requests = [];
  const actions = createMemeActions({
    fetchImpl: async (_url, init) => {
      requests.push(JSON.parse(init.body));
      return new Response(JSON.stringify({ templateId: "61579", imageUrl: "https://i.imgflip.com/a.jpg", pageUrl: "https://imgflip.com/i/a", texts: ["Caption"], matchedTemplate: false }));
    },
  });

  await actions.generateGeneral("A situation");

  assert.equal(requests.length, 1);
  assert.equal(requests[0].strategy, "general");
  assert.equal(actions.getState().result.matchedTemplate, false);
});

test("failed caption update preserves the current result", async () => {
  const currentResult = { templateId: "61579", imageUrl: "https://i.imgflip.com/a.jpg", pageUrl: "https://imgflip.com/i/a", texts: ["Original"], matchedTemplate: true };
  let calls = 0;
  const actions = createMemeActions({
    fetchImpl: async () => {
      calls += 1;
      if (calls === 1) return new Response(JSON.stringify(currentResult));
      return new Response(JSON.stringify({ error: "Unable to render", code: "PROVIDER_ERROR" }), { status: 502 });
    },
  });
  await actions.generate("A situation");

  const result = await actions.updateCaptions(["Changed"]);

  assert.equal(result.ok, false);
  assert.deepEqual(actions.getState().result, currentResult);
});

test("batch generation keeps selectable candidates and edits the selected template", async () => {
  const candidates = [1, 2, 3, 4, 5].map((id) => ({
    templateId: String(61570 + id),
    imageUrl: `https://i.imgflip.com/${id}.jpg`,
    pageUrl: `https://imgflip.com/i/${id}`,
    texts: [`Draft ${id}`],
    promptIdea: `Joke angle ${id}`,
  }));
  const requests = [];
  const actions = createMemeActions({
    fetchImpl: async (url, init) => {
      const body = JSON.parse(init.body);
      requests.push({ url, body });
      if (url === "/api/generate") return new Response(JSON.stringify({ memes: candidates, requestedCount: 5 }));
      return new Response(JSON.stringify({ imageUrl: "https://i.imgflip.com/edited.jpg", pageUrl: "https://imgflip.com/i/edited" }));
    },
  });
  await actions.generate("The task came back", "matched", 5, true);
  assert.equal(requests[0].body.count, 5);
  assert.equal(requests[0].body.analyzeImages, true);
  assert.equal(actions.getState().candidates.length, 5);
  assert.equal(actions.selectCandidate(3), true);
  assert.equal(actions.getState().result.templateId, candidates[3].templateId);
  await actions.updateCaptions(["A sharper punchline"]);
  assert.equal(requests[1].body.templateId, candidates[3].templateId);
  assert.deepEqual(actions.getState().result.texts, ["A sharper punchline"]);
});
