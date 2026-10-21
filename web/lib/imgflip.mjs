const API_BASE = "https://api.imgflip.com";
const MAX_CAPTIONS = 20;
const MAX_PREFIX_LENGTH = 64;

export class ImgflipError extends Error {
  constructor(code, message) {
    super(message);
    this.name = "ImgflipError";
    this.code = code;
  }
}

function safeError(code, message) {
  return new ImgflipError(code, message);
}

function providerFailure(response, body) {
  const details = typeof body?.error_message === "string" ? body.error_message.toLowerCase() : "";
  if (/premium|subscription/.test(details)) {
    return safeError("PROVIDER_PREMIUM_REQUIRED", "This feature requires an active Imgflip API Premium plan.");
  }
  if (response.status === 401 || response.status === 403 || /api key|invalid token|unauthorized|authentication/.test(details)) {
    return safeError("PROVIDER_AUTH_FAILED", "Imgflip rejected the API key. Check IMGFLIP_API in your server environment.");
  }
  if (response.status === 429 || /rate limit|quota|usage limit/.test(details)) {
    return safeError("PROVIDER_RATE_LIMITED", "Imgflip is limiting requests right now. Check your API usage and try again later.");
  }
  return safeError("PROVIDER_ERROR", "Imgflip could not create that meme. Try a shorter, simpler situation.");
}

function requireTemplateId(value) {
  const templateId = String(value ?? "");
  if (!/^\d{1,20}$/.test(templateId)) {
    throw safeError("INVALID_PROVIDER_RESPONSE", "Imgflip returned an invalid template.");
  }
  return templateId;
}

function requireHttpsUrl(value, hostname, message) {
  let url;
  try {
    url = new URL(value);
  } catch {
    throw safeError("INVALID_PROVIDER_RESPONSE", message);
  }
  if (url.protocol !== "https:" || url.hostname !== hostname || url.port || url.username || url.password) {
    throw safeError("INVALID_PROVIDER_RESPONSE", message);
  }
  return url.href;
}

function normalizePrompt(prompt) {
  if (typeof prompt !== "string" || !prompt.trim()) {
    throw safeError("INVALID_INPUT", "Describe a situation before generating a meme.");
  }
  return prompt.trim().replace(/\s+/g, " ");
}

function makePrefix(prompt) {
  const normalized = normalizePrompt(prompt);
  if (normalized.length <= MAX_PREFIX_LENGTH) {
    return { prefix: normalized, promptWasShortened: false };
  }

  const first64 = normalized.slice(0, MAX_PREFIX_LENGTH);
  const boundary = first64.lastIndexOf(" ");
  const prefix = (boundary > 0 ? first64.slice(0, boundary) : first64).trim();
  return { prefix, promptWasShortened: true };
}

function requireTexts(value) {
  if (!Array.isArray(value) || value.length < 1 || value.length > MAX_CAPTIONS) {
    throw safeError("INVALID_PROVIDER_RESPONSE", "Imgflip returned captions in an unsupported format.");
  }
  if (value.some((text) => typeof text !== "string" || text.length > 500)) {
    throw safeError("INVALID_PROVIDER_RESPONSE", "Imgflip returned captions in an unsupported format.");
  }
  return value;
}

function validateMemeCount(count) {
  if (!Number.isInteger(count) || count < 1 || count > 7) {
    throw safeError("INVALID_INPUT", "Choose between 1 and 7 meme options.");
  }
  return count;
}

function readMemeData(data) {
  if (!data || typeof data !== "object") {
    throw safeError("INVALID_PROVIDER_RESPONSE", "Imgflip returned an incomplete meme.");
  }
  return {
    templateId: requireTemplateId(data.template_id),
    imageUrl: requireHttpsUrl(data.url, "i.imgflip.com", "Imgflip returned an unsafe image URL."),
    pageUrl: requireHttpsUrl(data.page_url, "imgflip.com", "Imgflip returned an invalid meme page URL."),
    texts: requireTexts(data.texts),
  };
}

export function createImgflipClient({ apiKey = process.env.IMGFLIP_API, fetchImpl = fetch } = {}) {
  async function post(endpoint, fields) {
    const token = typeof apiKey === "string" ? apiKey.trim() : "";
    if (!token) {
      throw safeError("MISSING_API_KEY", "Imgflip API key is not configured. Add IMGFLIP_API to the server environment.");
    }

    let response;
    try {
      response = await fetchImpl(`${API_BASE}/${endpoint}`, {
        method: "POST",
        headers: {
          Authorization: `Bearer ${token}`,
          "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
        },
        body: new URLSearchParams(fields),
        signal: AbortSignal.timeout(20_000),
      });
    } catch {
      throw safeError("PROVIDER_UNAVAILABLE", "Imgflip could not be reached. Please try again.");
    }

    let body;
    try {
      body = await response.json();
    } catch {
      throw safeError("PROVIDER_ERROR", "Imgflip returned a response the app could not read.");
    }

    if (!response.ok || body?.success !== true || !body.data) {
      throw providerFailure(response, body);
    }
    return body.data;
  }

  async function makeMeme(prompt, templateId) {
    const normalizedPrompt = normalizePrompt(prompt);
    const { prefix, promptWasShortened } = makePrefix(normalizedPrompt);
    const fields = { model: "openai", prefix_text: prefix };
    if (templateId !== undefined) fields.template_id = requireTemplateId(templateId);

    const data = await post("ai_meme", fields);
    const meme = readMemeData(data);
    if (templateId !== undefined && meme.templateId !== String(templateId)) {
      throw safeError("MATCH_FAILED", "Imgflip could not keep the selected template. Try a general meme instead.");
    }
    return { ...meme, matchedTemplate: templateId !== undefined, promptWasShortened };
  }

  async function generateDistinctGeneralMemes(prompts, count, initialMemes = []) {
    const targetCount = validateMemeCount(count);
    const promptList = Array.isArray(prompts) ? prompts : Array(targetCount).fill(prompts);
    const memes = [...initialMemes];
    const seenTemplateIds = new Set(memes.map((meme) => meme.templateId));
    let firstError;
    let nextPromptIndex = initialMemes.length;

    for (let attempt = 0; attempt < 2 && memes.length < targetCount; attempt += 1) {
      const needed = targetCount - memes.length;
      const currentPrompts = Array.from({ length: needed }, () => promptList[nextPromptIndex++] || promptList[0]);
      const outcomes = await Promise.allSettled(
        currentPrompts.map((prompt) => this.generateGeneralMeme(prompt)),
      );
      let successful = 0;
      outcomes.forEach((outcome, index) => {
        if (outcome.status === "rejected") {
          firstError ||= outcome.reason;
          return;
        }
        successful += 1;
        if (!seenTemplateIds.has(outcome.value.templateId)) {
          seenTemplateIds.add(outcome.value.templateId);
          memes.push({ ...outcome.value, promptIdea: currentPrompts[index] });
        }
      });
      if (successful === 0) break;
    }

    if (memes.length === 0) throw firstError || safeError("PROVIDER_ERROR", "Imgflip could not create that meme. Try a shorter, simpler situation.");
    return memes.slice(0, targetCount);
  }

  return {
    async generatePromptMeme(prompt) {
      const normalizedPrompt = normalizePrompt(prompt);
      const data = await post("automeme", { text: normalizedPrompt });
      const templateId = requireTemplateId(data.template_id);
      return makeMeme(normalizedPrompt, templateId);
    },

    async generateGeneralMeme(prompt) {
      return makeMeme(prompt);
    },

    async generateGeneralMemes(prompt, count) {
      const prompts = Array.isArray(prompt) ? prompt : Array(count).fill(prompt);
      return generateDistinctGeneralMemes.call(this, prompts, count);
    },

    async generatePromptMemes(prompts, count) {
      const targetCount = validateMemeCount(count);
      const promptList = Array.isArray(prompts) ? prompts : Array(targetCount).fill(prompts);
      const matched = await this.generatePromptMeme(promptList[0]);
      return generateDistinctGeneralMemes.call(this, promptList, targetCount, [matched]);
    },

    async renderCaptionMeme(templateId, texts) {
      const safeTemplateId = requireTemplateId(templateId);
      const safeTexts = requireTexts(texts);
      if (safeTexts.some((text) => !text.trim())) {
        throw safeError("INVALID_INPUT", "Each caption needs some text.");
      }
      const fields = { template_id: safeTemplateId };
      safeTexts.forEach((text, index) => {
        fields[`boxes[${index}][text]`] = text;
      });

      const data = await post("caption_image", fields);
      return {
        imageUrl: requireHttpsUrl(data.url, "i.imgflip.com", "Imgflip returned an unsafe image URL."),
        pageUrl: requireHttpsUrl(data.page_url, "imgflip.com", "Imgflip returned an invalid meme page URL."),
      };
    },
  };
}
