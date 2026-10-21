import { RequestError } from "./validation.mjs";

const MODES = new Set(["situation", "photo+situation", "photo"]);

// A rating from the person the meme was made for: the measure of "funny for you".
export function validateFeedbackRequest(body) {
  if (!Number.isInteger(body?.rating) || body.rating < 1 || body.rating > 5) {
    throw new RequestError("INVALID_INPUT", "Rate the meme from 1 to 5.");
  }
  if (!MODES.has(body.mode)) throw new RequestError("INVALID_INPUT", "Unknown meme mode.");
  const entry = { rating: body.rating, mode: body.mode };
  if (body.assetId !== undefined) {
    if (!Number.isSafeInteger(body.assetId) || body.assetId < 0) throw new RequestError("INVALID_INPUT", "Unknown meme template.");
    entry.assetId = body.assetId;
  }
  if (body.helpful !== undefined) {
    if (typeof body.helpful !== "boolean") throw new RequestError("INVALID_INPUT", "Invalid feedback.");
    entry.helpful = body.helpful;
  }
  return entry;
}
