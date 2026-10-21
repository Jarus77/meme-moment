import { createServer } from "node:http";
import { readFile } from "node:fs/promises";
import { resolve } from "node:path";
import { Readable } from "node:stream";
import { pathToFileURL } from "node:url";
import { createImgflipClient, ImgflipError } from "./lib/imgflip.mjs";
import { validateFeedbackRequest } from "./lib/feedback.mjs";
import { createPhotoMemeService, PhotoMemeError, validatePhotoRequest } from "./lib/photo-meme.mjs";
import { createSituationMemeService, validateSituationRequest } from "./lib/situation-meme.mjs";
import { createCaptionWriter, createPromptRewriter } from "./lib/prompt-rewriter.mjs";
import { readJsonBody, RequestError, validateCaptionRequest, validateGenerateRequest } from "./lib/validation.mjs";

const ROOT = new URL("./public/", import.meta.url);
const STATIC_FILES = new Map([
  ["/", { file: "index.html", type: "text/html; charset=utf-8" }],
  ["/app.js", { file: "app.js", type: "text/javascript; charset=utf-8" }],
  ["/ui-model.mjs", { file: "ui-model.mjs", type: "text/javascript; charset=utf-8" }],
  ["/ui-actions.mjs", { file: "ui-actions.mjs", type: "text/javascript; charset=utf-8" }],
  ["/photo-meme.mjs", { file: "photo-meme.mjs", type: "text/javascript; charset=utf-8" }],
  ["/styles.css", { file: "styles.css", type: "text/css; charset=utf-8" }],
]);
const MIME_BY_EXTENSION = new Map([
  [".jpg", "image/jpeg"],
  [".jpeg", "image/jpeg"],
  [".png", "image/png"],
  [".webp", "image/webp"],
  [".gif", "image/gif"],
]);
const MIME_BY_EXTENSION_REVERSE = new Map([...MIME_BY_EXTENSION].map(([extension, mime]) => [mime, extension]));
const MAX_DOWNLOAD_BYTES = 20 * 1024 * 1024;
const MAX_GEMINI_IMAGE_BYTES = 1024 * 1024;
const LOOPBACK_HOSTS = new Set(["localhost", "127.0.0.1", "[::1]"]);

function trustedOrigin(request, environment) {
  const origin = request.headers?.origin;
  if (origin === undefined) return true;

  let originUrl;
  let hostUrl;
  try {
    originUrl = new URL(origin);
    hostUrl = new URL(`http://${request.headers.host || "localhost"}`);
  } catch {
    return false;
  }
  if (originUrl.origin !== origin || originUrl.host !== hostUrl.host) return false;

  if (originUrl.protocol === "http:" && LOOPBACK_HOSTS.has(originUrl.hostname)) return true;
  if (originUrl.protocol !== "https:") return false;

  const configuredOrigins = [environment.APP_ORIGIN]
    .filter(Boolean)
    .map((value) => {
      try { return new URL(value).origin; } catch { return ""; }
    });
  for (const hostname of [environment.VERCEL_URL, environment.VERCEL_BRANCH_URL, environment.VERCEL_PROJECT_PRODUCTION_URL]) {
    if (!hostname) continue;
    try { configuredOrigins.push(new URL(`https://${hostname}`).origin); } catch {}
  }
  return configuredOrigins.includes(originUrl.origin);
}

function sendJson(response, status, body) {
  response.writeHead(status, {
    "content-type": "application/json; charset=utf-8",
    "cache-control": "no-store",
    "x-content-type-options": "nosniff",
  });
  response.end(JSON.stringify(body));
}

function errorResponse(error) {
  if (error instanceof RequestError) {
    return { status: error.status, body: { error: error.message, code: error.code } };
  }
  if (error instanceof ImgflipError) {
    const status = error.code === "MISSING_API_KEY" ? 503 : error.code === "MATCH_FAILED" ? 409 : error.code === "INVALID_INPUT" ? 400 : 502;
    return { status, body: { error: error.message, code: error.code } };
  }
  if (error instanceof PhotoMemeError) return { status: error.status, body: { error: error.message, code: error.code } };
  return { status: 500, body: { error: "Something went wrong. Please try again.", code: "INTERNAL_ERROR" } };
}

async function serveStatic(pathname, response) {
  const entry = STATIC_FILES.get(pathname);
  if (!entry) return false;
  try {
    const content = await readFile(new URL(entry.file, ROOT));
    response.writeHead(200, {
      "content-type": entry.type,
      "cache-control": "no-cache",
      "x-content-type-options": "nosniff",
      "content-security-policy": "default-src 'self'; img-src 'self' https://i.imgflip.com data: blob:; style-src 'self'; script-src 'self'; connect-src 'self'; frame-ancestors 'none'",
    });
    response.end(content);
  } catch {
    sendJson(response, 500, { error: "The app files could not be read.", code: "STATIC_FILE_ERROR" });
  }
  return true;
}

function parseDownloadUrl(value) {
  let url;
  try {
    url = new URL(value);
  } catch {
    throw new RequestError("INVALID_DOWNLOAD_URL", "That image link is invalid.");
  }
  if (url.protocol !== "https:" || url.hostname !== "i.imgflip.com" || url.port || url.username || url.password) {
    throw new RequestError("INVALID_DOWNLOAD_URL", "Only images hosted by Imgflip can be downloaded here.");
  }
  return url;
}

async function readBoundedImage(response, maxBytes = MAX_DOWNLOAD_BYTES) {
  const reader = response.body?.getReader();
  if (!reader) throw new RequestError("DOWNLOAD_FAILED", "Imgflip did not return an image.", 502);
  const chunks = [];
  let size = 0;
  try {
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      size += value.byteLength;
      if (size > maxBytes) {
        try { await reader.cancel(); } catch {}
        throw new RequestError("DOWNLOAD_TOO_LARGE", "That image is too large to download.", 413);
      }
      chunks.push(Buffer.from(value));
    }
  } catch (error) {
    if (error instanceof RequestError) throw error;
    throw new RequestError("DOWNLOAD_FAILED", "Imgflip could not provide that image.", 502);
  }
  return Buffer.concat(chunks, size);
}

async function cancelResponseBody(response) {
  try { await response.body?.cancel(); } catch {}
}

async function fetchGeminiReferenceImage(imageUrl, fetchImpl) {
  let target;
  try {
    target = parseDownloadUrl(imageUrl);
  } catch {
    return null;
  }

  let response;
  try {
    response = await fetchImpl(target.href, { redirect: "manual", signal: AbortSignal.timeout(10_000) });
  } catch {
    return null;
  }
  if (!response.ok || (response.status >= 300 && response.status < 400)) {
    await cancelResponseBody(response);
    return null;
  }

  const mimeType = (response.headers.get("content-type") || "").split(";")[0].trim().toLowerCase();
  if (!["image/jpeg", "image/png", "image/webp", "image/gif"].includes(mimeType)) {
    await cancelResponseBody(response);
    return null;
  }
  const declaredLength = Number(response.headers.get("content-length"));
  if (Number.isFinite(declaredLength) && declaredLength > MAX_GEMINI_IMAGE_BYTES) {
    await cancelResponseBody(response);
    return null;
  }
  try {
    const bytes = await readBoundedImage(response, MAX_GEMINI_IMAGE_BYTES);
    return { mimeType, data: bytes.toString("base64") };
  } catch {
    return null;
  }
}

async function handleDownload(requestUrl, response, fetchImpl) {
  let target;
  try {
    target = parseDownloadUrl(requestUrl.searchParams.get("url") || "");
  } catch (error) {
    const mapped = errorResponse(error);
    sendJson(response, mapped.status, mapped.body);
    return;
  }

  let image;
  try {
    image = await fetchImpl(target.href, { redirect: "manual", signal: AbortSignal.timeout(10_000) });
  } catch {
    sendJson(response, 502, { error: "Imgflip could not provide that image.", code: "DOWNLOAD_FAILED" });
    return;
  }

  if (image.status >= 300 && image.status < 400) {
    sendJson(response, 502, { error: "Imgflip redirected the image request; download was stopped.", code: "DOWNLOAD_FAILED" });
    return;
  }
  if (!image.ok) {
    sendJson(response, 502, { error: "Imgflip could not provide that image.", code: "DOWNLOAD_FAILED" });
    return;
  }

  const mime = (image.headers.get("content-type") || "").split(";")[0].trim().toLowerCase();
  const extension = MIME_BY_EXTENSION_REVERSE.get(mime);
  if (!extension) {
    sendJson(response, 502, { error: "Imgflip did not return a supported image type.", code: "DOWNLOAD_FAILED" });
    return;
  }
  const declaredLength = Number(image.headers.get("content-length"));
  if (Number.isFinite(declaredLength) && declaredLength > MAX_DOWNLOAD_BYTES) {
    sendJson(response, 413, { error: "That image is too large to download.", code: "DOWNLOAD_TOO_LARGE" });
    return;
  }

  let bytes;
  try {
    bytes = await readBoundedImage(image);
  } catch (error) {
    const mapped = errorResponse(error);
    sendJson(response, mapped.status, mapped.body);
    return;
  }
  response.writeHead(200, {
    "content-type": mime,
    "content-length": String(bytes.length),
    "content-disposition": `attachment; filename="meme-${Date.now()}${extension}"`,
    "cache-control": "no-store",
    "content-security-policy": "default-src 'none'",
    "x-content-type-options": "nosniff",
  });
  response.end(bytes);
}

async function handleRequest(request, response, client, photoMemeService, fetchImpl, environment, rewritePrompt, writeCaptions, captionWriterConfigured, extras = {}) {
  const requestUrl = new URL(request.url, "http://localhost");
  if (request.method === "GET" && await serveStatic(requestUrl.pathname, response)) return;

  if (request.method === "POST" && requestUrl.pathname.startsWith("/api/")) {
    if (!trustedOrigin(request, environment)) {
      sendJson(response, 403, { error: "This request did not come from this app.", code: "CROSS_ORIGIN_REQUEST" });
      return;
    }
  }

  if ((requestUrl.pathname === "/api/generate" || requestUrl.pathname === "/api/caption") && request.method !== "POST") {
    sendJson(response, 405, { error: "Use POST for this API route.", code: "METHOD_NOT_ALLOWED" });
    return;
  }

  if (requestUrl.pathname === "/api/photo-meme" && request.method !== "POST") {
    sendJson(response, 405, { error: "Use POST for this API route.", code: "METHOD_NOT_ALLOWED" });
    return;
  }

  for (const path of ["/api/situation-meme", "/api/feedback"]) {
    if (requestUrl.pathname === path && request.method !== "POST") {
      sendJson(response, 405, { error: "Use POST for this API route.", code: "METHOD_NOT_ALLOWED" });
      return;
    }
  }

  if (request.method === "POST" && requestUrl.pathname === "/api/situation-meme") {
    try {
      const input = validateSituationRequest(await readJsonBody(request, { maxBytes: 7 * 1024 * 1024 }));
      sendJson(response, 200, await extras.situationMemeService.generate(input));
    } catch (error) {
      const mapped = errorResponse(error);
      sendJson(response, mapped.status, mapped.body);
    }
    return;
  }

  if (request.method === "POST" && requestUrl.pathname === "/api/feedback") {
    try {
      extras.feedbackLog(validateFeedbackRequest(await readJsonBody(request, { maxBytes: 2 * 1024 })));
      sendJson(response, 200, { ok: true });
    } catch (error) {
      const mapped = errorResponse(error);
      sendJson(response, mapped.status, mapped.body);
    }
    return;
  }

  if (request.method === "POST" && requestUrl.pathname === "/api/photo-meme") {
    try {
      const input = validatePhotoRequest(await readJsonBody(request, { maxBytes: 7 * 1024 * 1024 }));
      const result = await photoMemeService.generate(input);
      sendJson(response, 200, result);
    } catch (error) {
      const mapped = errorResponse(error);
      sendJson(response, mapped.status, mapped.body);
    }
    return;
  }

  if (requestUrl.pathname === "/api/download" && request.method !== "GET") {
    sendJson(response, 405, { error: "Use GET for this API route.", code: "METHOD_NOT_ALLOWED" });
    return;
  }

  if (request.method === "GET" && requestUrl.pathname === "/api/download") {
    await handleDownload(requestUrl, response, fetchImpl);
    return;
  }

  if (request.method === "POST" && requestUrl.pathname === "/api/generate") {
    try {
      const input = validateGenerateRequest(await readJsonBody(request));
      const rewrites = await rewritePrompt(input.prompt, input.count);
      const promptIdeas = Array.isArray(rewrites) && rewrites.length === input.count
        ? rewrites
        : typeof rewrites === "string" && input.count === 1
          ? [rewrites]
          : Array(input.count).fill(input.prompt);
      const generatedMemes = input.count === 1
        ? [input.strategy === "general"
          ? await client.generateGeneralMeme(promptIdeas[0])
          : await client.generatePromptMeme(promptIdeas[0])]
        : input.strategy === "general"
          ? await client.generateGeneralMemes(promptIdeas, input.count)
          : await client.generatePromptMemes(promptIdeas, input.count);
      let annotated = generatedMemes.map((meme, index) => {
        const promptIdea = meme.promptIdea || promptIdeas[index] || promptIdeas[0];
        return { ...meme, promptIdea, jokeAngle: promptIdea === input.prompt ? null : promptIdea };
      });
      const captionOptions = await Promise.all(annotated.map(async (meme) => ({
        situation: meme.promptIdea,
        texts: meme.texts,
        ...(input.analyzeImages && captionWriterConfigured ? { image: await fetchGeminiReferenceImage(meme.imageUrl, fetchImpl) } : {}),
      })));
      const imageAnalysisCount = captionOptions.filter((option) => option.image).length;
      annotated = annotated.map((meme, index) => ({ ...meme, imageAnalysisSent: Boolean(captionOptions[index].image) }));
      const captions = await writeCaptions(input.prompt, captionOptions);
      if (captions) {
        annotated = await Promise.all(annotated.map(async (meme, index) => {
          try {
            const rendered = await client.renderCaptionMeme(meme.templateId, captions[index]);
            return { ...meme, ...rendered, texts: captions[index], captionPolished: true, visualCaptionsApplied: Boolean(captionOptions[index].image) };
          } catch {
            return meme;
          }
        }));
      }
      const result = annotated[0];
      sendJson(response, 200, {
        ...result,
        matchedTemplate: input.strategy === "matched" && Boolean(result.matchedTemplate),
        promptRewrite: promptIdeas[0] === input.prompt ? null : promptIdeas[0],
        promptIdeas,
        memes: annotated,
        requestedCount: input.count,
        partial: annotated.length < input.count,
        imageAnalysisRequested: input.analyzeImages,
        imageAnalysisCount,
        imageAnalysisAvailable: Boolean(captions && imageAnalysisCount),
      });
    } catch (error) {
      const mapped = errorResponse(error);
      sendJson(response, mapped.status, mapped.body);
    }
    return;
  }

  if (request.method === "POST" && requestUrl.pathname === "/api/caption") {
    try {
      const input = validateCaptionRequest(await readJsonBody(request));
      const result = await client.renderCaptionMeme(input.templateId, input.texts);
      sendJson(response, 200, result);
    } catch (error) {
      const mapped = errorResponse(error);
      sendJson(response, mapped.status, mapped.body);
    }
    return;
  }

  if (requestUrl.pathname.startsWith("/api/")) {
    sendJson(response, request.method === "GET" || request.method === "POST" ? 404 : 405, {
      error: "That API route is not available.",
      code: "NOT_FOUND",
    });
    return;
  }

  sendJson(response, 404, { error: "Page not found.", code: "NOT_FOUND" });
}

export function createRequestHandler({ apiKey, fetchImpl = fetch, environment: environmentOverride = process.env, rewritePrompt: rewritePromptOverride, writeCaptions: writeCaptionsOverride, photoMemeService: photoMemeServiceOverride, situationMemeService: situationMemeServiceOverride, feedbackLog: feedbackLogOverride } = {}) {
  const environment = { ...process.env, ...environmentOverride };
  const configuredApiKey = apiKey ?? environment.IMGFLIP_API;
  const client = createImgflipClient({ apiKey: configuredApiKey, fetchImpl });
  const rewritePrompt = rewritePromptOverride ?? createPromptRewriter({
    apiKey: environment.GEMINI_API_KEY ?? "",
    model: environment.GEMINI_MODEL,
    fetchImpl,
  });
  const writeCaptions = writeCaptionsOverride ?? createCaptionWriter({
    apiKey: environment.GEMINI_API_KEY ?? "",
    model: environment.GEMINI_MODEL,
    fetchImpl,
  });
  const captionWriterConfigured = Boolean(writeCaptionsOverride || environment.GEMINI_API_KEY?.trim());
  const photoMemeService = photoMemeServiceOverride ?? createPhotoMemeService({
    geminiApiKey: environment.GEMINI_API_KEY,
    model: environment.GEMINI_MODEL,
    matchServiceUrl: environment.MATCH_SERVICE_URL,
    matchServiceKey: environment.MATCH_SERVICE_KEY,
    fetchImpl,
  });
  const situationMemeService = situationMemeServiceOverride ?? createSituationMemeService({
    geminiApiKey: environment.GEMINI_API_KEY,
    model: environment.GEMINI_MODEL,
    matchServiceUrl: environment.SITUATION_MATCH_URL,
    matchServiceKey: environment.MATCH_SERVICE_KEY,
    fetchImpl,
  });
  const feedbackLog = feedbackLogOverride ?? ((entry) => console.log("[feedback]", JSON.stringify(entry)));
  const extras = { situationMemeService, feedbackLog };
  return (request, response) => {
    return handleRequest(request, response, client, photoMemeService, fetchImpl, environment, rewritePrompt, writeCaptions, captionWriterConfigured, extras).catch(() => {
      if (!response.headersSent) sendJson(response, 500, { error: "Something went wrong. Please try again.", code: "INTERNAL_ERROR" });
      else response.destroy();
    });
  };
}

export function createFetchHandler(options = {}) {
  const nodeHandler = createRequestHandler(options);
  return async (webRequest) => {
    const requestUrl = new URL(webRequest.url);
    const requestBody = webRequest.body ? Readable.fromWeb(webRequest.body) : Readable.from([]);
    requestBody.url = `${requestUrl.pathname}${requestUrl.search}`;
    requestBody.method = webRequest.method;
    requestBody.headers = Object.fromEntries(webRequest.headers.entries());
    requestBody.headers.host ||= requestUrl.host;

    let status = 500;
    let headers = {};
    const chunks = [];
    const response = {
      headersSent: false,
      writeHead(nextStatus, nextHeaders) {
        status = nextStatus;
        headers = nextHeaders;
        this.headersSent = true;
      },
      end(value = "") {
        chunks.push(Buffer.isBuffer(value) ? value : Buffer.from(String(value)));
      },
      destroy() { chunks.length = 0; },
    };

    await nodeHandler(requestBody, response);
    return new Response(Buffer.concat(chunks), { status, headers });
  };
}

export function createAppServer(options = {}) {
  return createServer(createRequestHandler(options));
}

export function startServer({ port = Number(process.env.PORT || 3000), host = "127.0.0.1" } = {}) {
  const server = createAppServer();
  server.listen(port, host, () => {
    console.log(`Meme Moment is ready at http://${host}:${port}`);
  });
  return server;
}

if (process.argv[1] && import.meta.url === pathToFileURL(resolve(process.argv[1])).href) {
  startServer();
}
