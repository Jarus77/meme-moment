export class RequestError extends Error {
  constructor(code, message, status = 400) {
    super(message);
    this.name = "RequestError";
    this.code = code;
    this.status = status;
  }
}

const MAX_BODY_BYTES = 16 * 1024;

export async function readJsonBody(request, { maxBytes = MAX_BODY_BYTES } = {}) {
  const chunks = [];
  let size = 0;
  for await (const chunk of request) {
    size += chunk.length;
    if (size > maxBytes) {
      throw new RequestError("BODY_TOO_LARGE", "That request is too large.", 413);
    }
    chunks.push(chunk);
  }

  let body;
  try {
    body = JSON.parse(Buffer.concat(chunks).toString("utf8"));
  } catch {
    throw new RequestError("INVALID_JSON", "Send the request as valid JSON.");
  }
  if (!body || typeof body !== "object" || Array.isArray(body)) {
    throw new RequestError("INVALID_INPUT", "Send a JSON object with the required fields.");
  }
  return body;
}

export function validateGenerateRequest(body) {
  const prompt = typeof body.prompt === "string" ? body.prompt.trim() : "";
  if (!prompt || prompt.length > 500) {
    throw new RequestError("INVALID_INPUT", "Enter a situation between 1 and 500 characters.");
  }
  const strategy = body.strategy ?? "matched";
  if (strategy !== "matched" && strategy !== "general") {
    throw new RequestError("INVALID_INPUT", "Choose a supported generation option.");
  }
  const count = body.count ?? 1;
  if (![1, 5, 7].includes(count)) {
    throw new RequestError("INVALID_INPUT", "Choose 1, 5, or 7 meme options.");
  }
  const analyzeImages = body.analyzeImages === undefined ? false : body.analyzeImages;
  if (typeof analyzeImages !== "boolean") {
    throw new RequestError("INVALID_INPUT", "Choose whether Gemini should inspect the meme images.");
  }
  return { prompt, strategy, count, analyzeImages };
}

export function validateCaptionRequest(body) {
  const templateId = String(body.templateId ?? "");
  if (!/^\d{1,20}$/.test(templateId) || !Array.isArray(body.texts) || body.texts.length < 1 || body.texts.length > 20) {
    throw new RequestError("INVALID_INPUT", "The selected meme or caption boxes are invalid.");
  }
  if (body.texts.some((text) => typeof text !== "string" || text.length > 500 || !text.trim())) {
    throw new RequestError("INVALID_INPUT", "Each caption must contain 1 to 500 characters.");
  }
  return { templateId, texts: body.texts };
}
