import assert from "node:assert/strict";
import test from "node:test";
import { createImgflipClient, ImgflipError } from "../lib/imgflip.mjs";

const promptResult = {
  success: true,
  data: {
    template_id: 61579,
    url: "https://i.imgflip.com/auto.jpg",
    page_url: "https://imgflip.com/i/auto",
  },
};

const aiResult = {
  success: true,
  data: {
    template_id: 61579,
    url: "https://i.imgflip.com/ai.jpg",
    page_url: "https://imgflip.com/i/ai",
    texts: ["When the work ends", "The work arriving in your inbox"],
  },
};

function response(body) {
  return { ok: true, status: 200, json: async () => body };
}

test("matched generation uses Bearer auth and keeps the selected template", async () => {
  const requests = [];
  const client = createImgflipClient({
    apiKey: "test-token",
    fetchImpl: async (url, init) => {
      requests.push({ url, init });
      return response(requests.length === 1 ? promptResult : aiResult);
    },
  });

  const result = await client.generatePromptMeme("When work ends and more work arrives");

  assert.deepEqual(requests.map(({ url }) => new URL(url).pathname), ["/automeme", "/ai_meme"]);
  assert.equal(requests[0].init.headers.Authorization, "Bearer test-token");
  assert.equal(requests[1].init.headers.Authorization, "Bearer test-token");
  assert.equal(new URLSearchParams(requests[0].init.body).get("text"), "When work ends and more work arrives");
  assert.equal(new URLSearchParams(requests[1].init.body).get("template_id"), "61579");
  assert.equal(result.templateId, "61579");
  assert.deepEqual(result.texts, aiResult.data.texts);
  assert.equal(result.imageUrl, aiResult.data.url);
});

test("caption seed is shortened at a word boundary to Imgflip's 64 character limit", async () => {
  const requests = [];
  const client = createImgflipClient({
    apiKey: "test-token",
    fetchImpl: async (_url, init) => {
      requests.push(init);
      return response(requests.length === 1 ? promptResult : aiResult);
    },
  });
  const prompt = `${"word ".repeat(20)}tail`;

  const result = await client.generatePromptMeme(prompt);
  const prefix = new URLSearchParams(requests[1].body).get("prefix_text");

  assert.equal(prefix, "word ".repeat(12).trim());
  assert.ok(prefix.length <= 64);
  assert.equal(result.promptWasShortened, true);
});

test("general generation makes one AI-meme request and reports unmatched template", async () => {
  const requests = [];
  const client = createImgflipClient({
    apiKey: "test-token",
    fetchImpl: async (url, init) => {
      requests.push({ url, init });
      return response({ ...aiResult, data: { ...aiResult.data, template_id: 9001 } });
    },
  });

  const result = await client.generateGeneralMeme("A short topic");

  assert.equal(requests.length, 1);
  assert.equal(new URL(requests[0].url).pathname, "/ai_meme");
  assert.equal(new URLSearchParams(requests[0].init.body).has("template_id"), false);
  assert.equal(result.templateId, "9001");
  assert.equal(result.matchedTemplate, false);
});

test("general batch generation returns several distinct AI memes", async () => {
  let calls = 0;
  const client = createImgflipClient({
    apiKey: "test-token",
    fetchImpl: async (_url, init) => {
      calls += 1;
      assert.equal(new URLSearchParams(init.body).has("template_id"), false);
      return response({ ...aiResult, data: { ...aiResult.data, template_id: 9000 + calls } });
    },
  });

  const memes = await client.generateGeneralMemes("A short situation", 3);

  assert.equal(calls, 3);
  assert.deepEqual(memes.map((meme) => meme.templateId), ["9001", "9002", "9003"]);
  assert.ok(memes.every((meme) => !meme.matchedTemplate));
});

test("general batch sends and preserves a different joke angle for each option", async () => {
  const prompts = [];
  let templateId = 9400;
  const client = createImgflipClient({
    apiKey: "test-token",
    fetchImpl: async (_url, init) => {
      prompts.push(new URLSearchParams(init.body).get("prefix_text"));
      templateId += 1;
      return response({ ...aiResult, data: { ...aiResult.data, template_id: templateId } });
    },
  });
  const memes = await client.generateGeneralMemes(["First angle", "Second angle", "Third angle"], 3);
  assert.deepEqual(prompts, ["First angle", "Second angle", "Third angle"]);
  assert.deepEqual(memes.map((meme) => meme.promptIdea), prompts);
});

test("matched batch keeps its best match first and creates general alternatives", async () => {
  const paths = [];
  let generalId = 9100;
  const client = createImgflipClient({
    apiKey: "test-token",
    fetchImpl: async (url, init) => {
      const path = new URL(url).pathname;
      const fields = new URLSearchParams(init.body);
      paths.push({ path, fields });
      if (path === "/automeme") return response(promptResult);
      const templateId = fields.get("template_id") || String(++generalId);
      return response({ ...aiResult, data: { ...aiResult.data, template_id: Number(templateId) } });
    },
  });

  const memes = await client.generatePromptMemes(["Best match angle", "Alt two", "Alt three"], 3);

  assert.equal(memes.length, 3);
  assert.equal(memes[0].matchedTemplate, true);
  assert.deepEqual(memes.slice(1).map((meme) => meme.matchedTemplate), [false, false]);
  assert.equal(paths.filter(({ path }) => path === "/automeme").length, 1);
  assert.equal(paths.filter(({ path }) => path === "/ai_meme").length, 3);
  assert.equal(paths[0].fields.get("text"), "Best match angle");
  assert.equal(paths[2].fields.get("prefix_text"), "Alt two");
  assert.equal(paths[3].fields.get("prefix_text"), "Alt three");
  assert.equal(new Set(memes.map(({ templateId }) => templateId)).size, 3);
});

test("caption rendering submits one text box per caption without coordinates", async () => {
  const payloads = [];
  const client = createImgflipClient({
    apiKey: "test-token",
    fetchImpl: async (_url, init) => {
      payloads.push(new URLSearchParams(init.body));
      return response({ success: true, data: { url: "https://i.imgflip.com/edit.jpg", page_url: "https://imgflip.com/i/edit" } });
    },
  });

  await client.renderCaptionMeme("61579", ["First", "Second", "Third"]);

  assert.equal(payloads.length, 1);
  assert.equal(payloads[0].get("template_id"), "61579");
  assert.deepEqual([0, 1, 2].map((index) => payloads[0].get(`boxes[${index}][text]`)), ["First", "Second", "Third"]);
  assert.deepEqual([...payloads[0].keys()].filter((key) => /\[(x|y|width|height)\]$/.test(key)), []);
});

test("caption rendering supports a single text box", async () => {
  let payload;
  const client = createImgflipClient({
    apiKey: "test-token",
    fetchImpl: async (_url, init) => {
      payload = new URLSearchParams(init.body);
      return response({ success: true, data: { url: "https://i.imgflip.com/edit.jpg", page_url: "https://imgflip.com/i/edit" } });
    },
  });

  await client.renderCaptionMeme("61579", ["Only caption"]);

  assert.equal(payload.get("boxes[0][text]"), "Only caption");
  assert.equal(payload.has("boxes[1][text]"), false);
});

test("missing API key fails safely without making a provider request", async () => {
  let calls = 0;
  const client = createImgflipClient({ apiKey: "", fetchImpl: async () => { calls += 1; } });

  await assert.rejects(client.generatePromptMeme("A situation"), (error) => {
    assert.ok(error instanceof ImgflipError);
    assert.equal(error.code, "MISSING_API_KEY");
    assert.doesNotMatch(error.message, /test-token|Bearer\s/i);
    return true;
  });
  assert.equal(calls, 0);
});

test("selected-template mismatch fails with a safe retry category", async () => {
  const client = createImgflipClient({
    apiKey: "test-token",
    fetchImpl: async (_url, init) => response(new URLSearchParams(init.body).get("template_id")
      ? { ...aiResult, data: { ...aiResult.data, template_id: 999 } }
      : promptResult),
  });

  await assert.rejects(client.generatePromptMeme("A situation"), (error) => {
    assert.equal(error.code, "MATCH_FAILED");
    return true;
  });
});

test("provider failures do not expose upstream error text", async () => {
  const client = createImgflipClient({
    apiKey: "test-token",
    fetchImpl: async () => response({ success: false, error_message: "private upstream diagnostic" }),
  });

  await assert.rejects(client.generatePromptMeme("A situation"), (error) => {
    assert.ok(error instanceof ImgflipError);
    assert.equal(error.code, "PROVIDER_ERROR");
    assert.doesNotMatch(error.message, /private upstream diagnostic/);
    return true;
  });
});

test("Imgflip premium errors are explained without exposing arbitrary provider text", async () => {
  const client = createImgflipClient({
    apiKey: "test-token",
    fetchImpl: async () => response({ success: false, error_message: "This endpoint requires API Premium for this account" }),
  });

  await assert.rejects(client.generatePromptMeme("A short situation"), (error) => {
    assert.equal(error.code, "PROVIDER_PREMIUM_REQUIRED");
    assert.match(error.message, /active Imgflip API Premium/);
    assert.doesNotMatch(error.message, /for this account/);
    return true;
  });
});

test("provider image and page URLs must use expected HTTPS hosts", async () => {
  const client = createImgflipClient({
    apiKey: "test-token",
    fetchImpl: async (_url, init) => response(new URLSearchParams(init.body).get("template_id")
      ? { ...aiResult, data: { ...aiResult.data, url: "https://i.imgflip.com.evil.test/a.jpg" } }
      : promptResult),
  });

  await assert.rejects(client.generatePromptMeme("A situation"), (error) => {
    assert.equal(error.code, "INVALID_PROVIDER_RESPONSE");
    return true;
  });
});
