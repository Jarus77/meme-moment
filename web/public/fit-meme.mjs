// Browser side of the "situation" and "photo + situation" modes.
// The server returns adapted real captions; this module draws them on the user's photo or on the template picture.
import { blobDataUrl, renderPhotoCaption, resizePhotoFile } from "./photo-meme.mjs";

function safeError(payload, fallback) {
  return typeof payload?.error === "string" && payload.error.length < 300 ? payload.error : fallback;
}

export function createFitMemeActions({
  fetchImpl = fetch,
  resizeImpl = resizePhotoFile,
  renderImpl = renderPhotoCaption,
  blobToDataUrl = blobDataUrl,
  createUrl = (blob) => URL.createObjectURL(blob),
  revokeUrl = (url) => URL.revokeObjectURL(url),
  onState = () => {},
} = {}) {
  let state = { busy: false, error: "", mode: "", situation: "", cards: [], analogs: [] };
  let imageUrls = [];

  const getState = () => ({ ...state, cards: state.cards.map((card) => ({ ...card })) });
  const publish = () => onState(getState());
  function clearUrls() {
    for (const url of imageUrls) revokeUrl(url);
    imageUrls = [];
  }
  function fail(message, code = "FIT_MEME_FAILED") {
    state = { ...state, busy: false, error: message };
    publish();
    return { ok: false, code, error: message };
  }

  async function templateDataUrl(imageUrl) {
    const response = await fetchImpl(`/api/download?url=${encodeURIComponent(imageUrl)}`);
    if (!response.ok) throw new Error("template picture unavailable");
    return blobToDataUrl(await response.blob());
  }

  async function generate({ situation, file }) {
    if (state.busy) return { ok: false, code: "BUSY", error: "Please wait for the current request to finish." };
    const text = typeof situation === "string" ? situation.trim() : "";
    if (text.length < 3) return fail("Describe the situation first (at least a few words).", "INVALID_SITUATION");
    clearUrls();
    state = { ...state, busy: true, error: "", cards: [], analogs: [] };
    publish();
    try {
      const photo = file ? await resizeImpl(file) : null;
      const response = await fetchImpl("/api/situation-meme", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify(photo ? { situation: text, photo: photo.dataUrl } : { situation: text }),
      });
      let payload;
      try { payload = await response.json(); } catch { payload = {}; }
      if (!response.ok) throw new Error(safeError(payload, "We couldn’t make memes just now. Please try again."));
      if (!Array.isArray(payload.candidates) || !payload.candidates.length
        || payload.candidates.some((c) => !Array.isArray(c?.texts) || !c.texts.length || !c.template?.image_url)) {
        throw new Error("The meme service returned an incomplete result. Please try again.");
      }

      const cache = new Map();
      const baseFor = (candidate) => {
        if (photo) return Promise.resolve(photo.dataUrl);
        const url = candidate.template.image_url;
        if (!cache.has(url)) cache.set(url, templateDataUrl(url));
        return cache.get(url);
      };
      const drawn = await Promise.all(payload.candidates.map(async (candidate) => {
        try { return { candidate, blob: await renderImpl(await baseFor(candidate), candidate.texts) }; } catch { return null; }
      }));
      const usable = drawn.filter(Boolean);
      if (!usable.length) throw new Error("We found captions but couldn’t draw them. Please try again.");
      imageUrls = usable.map(({ blob }, index) => createUrl(blob, index));
      state = {
        ...state, busy: false, error: "", mode: payload.mode, situation: text, analogs: payload.analogs ?? [],
        cards: usable.map(({ candidate }, index) => ({ ...candidate, imageUrl: imageUrls[index], rated: 0 })),
      };
      publish();
      return { ok: true, result: getState() };
    } catch (error) {
      return fail(error instanceof Error ? error.message : "We couldn’t make memes just now. Please try again.");
    }
  }

  async function rate(index, rating) {
    const card = state.cards[index];
    if (!card || !Number.isInteger(rating) || rating < 1 || rating > 5) return { ok: false, code: "INVALID_RATING" };
    try {
      const response = await fetchImpl("/api/feedback", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ rating, mode: state.mode, assetId: card.template.asset_id }),
      });
      if (!response.ok) return { ok: false, code: "FEEDBACK_FAILED" };
    } catch { return { ok: false, code: "FEEDBACK_FAILED" }; }
    state = { ...state, cards: state.cards.map((c, i) => (i === index ? { ...c, rated: rating } : c)) };
    publish();
    return { ok: true };
  }

  return { getState, generate, rate, dispose: clearUrls };
}
