function safeMessage(payload, fallback) {
  return typeof payload?.error === "string" && payload.error.length < 300 ? payload.error : fallback;
}

async function readJson(response) {
  try {
    return await response.json();
  } catch {
    return {};
  }
}

export function createMemeActions({ fetchImpl = fetch, onState = () => {} } = {}) {
  let state = {
    phase: "idle",
    busy: false,
    result: null,
    candidates: [],
    selectedIndex: 0,
    error: "",
    fallbackPrompt: null,
    requestedCount: 1,
    partial: false,
    analyzeImages: false,
  };

  function copyState() {
    const candidates = state.candidates.map((candidate) => ({ ...candidate, texts: [...candidate.texts] }));
    return {
      ...state,
      candidates,
      result: candidates[state.selectedIndex] ? { ...candidates[state.selectedIndex], texts: [...candidates[state.selectedIndex].texts] } : null,
      fallbackAvailable: Boolean(state.fallbackPrompt),
    };
  }

  function publish() {
    onState(copyState());
  }

  function getState() {
    return copyState();
  }

  async function generate(prompt, strategy = "matched", count = 1, analyzeImages = false) {
    const cleanPrompt = typeof prompt === "string" ? prompt.trim() : "";
    if (!cleanPrompt) {
      state = { ...state, phase: "error", error: "Describe a situation first.", fallbackPrompt: null };
      publish();
      return { ok: false, code: "INVALID_INPUT", error: state.error };
    }
    if (state.busy) return { ok: false, code: "BUSY", error: "A meme is already being made." };

    state = { ...state, busy: true, phase: "generating", error: "", fallbackPrompt: null, requestedCount: count, analyzeImages };
    publish();
    try {
      const response = await fetchImpl("/api/generate", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ prompt: cleanPrompt, strategy, count, analyzeImages }),
      });
      const payload = await readJson(response);
      if (!response.ok) {
        const error = safeMessage(payload, "The meme could not be made. Please try again.");
        state = {
          ...state,
          busy: false,
          phase: "error",
          error,
          fallbackPrompt: strategy === "matched" && payload.code === "MATCH_FAILED" ? cleanPrompt : null,
        };
        publish();
        return { ok: false, code: payload.code || "GENERATION_FAILED", error };
      }
      const candidates = Array.isArray(payload.memes) && payload.memes.length
        ? payload.memes
        : [payload];
      if (candidates.some((candidate) => !candidate.templateId || !candidate.imageUrl || !Array.isArray(candidate.texts) || candidate.texts.length < 1 || candidate.texts.length > 20)) {
        throw new Error("Imgflip returned an incomplete meme.");
      }
      state = { ...state, busy: false, phase: "ready", candidates, selectedIndex: 0, error: "", fallbackPrompt: null, requestedCount: payload.requestedCount || count, partial: Boolean(payload.partial), analyzeImages: Boolean(payload.imageAnalysisRequested) };
      publish();
      return { ok: true, result: getState().result };
    } catch {
      state = { ...state, busy: false, phase: "error", error: "The meme service could not be reached. Please try again.", fallbackPrompt: null };
      publish();
      return { ok: false, code: "GENERATION_FAILED", error: state.error };
    }
  }

  async function updateCaptions(texts) {
    const current = state.candidates[state.selectedIndex];
    if (!current) return { ok: false, code: "NO_RESULT", error: "Make a meme before editing captions." };
    if (state.busy) return { ok: false, code: "BUSY", error: "Please wait for the current action to finish." };
    if (!Array.isArray(texts) || texts.length !== current.texts.length || texts.some((text) => typeof text !== "string" || !text.trim() || text.length > 500)) {
      state = { ...state, phase: "error", error: "Keep one short caption in each text box.", fallbackPrompt: null };
      publish();
      return { ok: false, code: "INVALID_INPUT", error: state.error };
    }

    state = { ...state, busy: true, phase: "rendering", error: "" };
    publish();
    try {
      const response = await fetchImpl("/api/caption", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ templateId: current.templateId, texts }),
      });
      const payload = await readJson(response);
      if (!response.ok || !payload.imageUrl) {
        const error = safeMessage(payload, "The captions could not be updated. Your current meme is still here.");
        state = { ...state, busy: false, phase: "error", error };
        publish();
        return { ok: false, code: payload.code || "CAPTION_FAILED", error };
      }
      const candidates = [...state.candidates];
      candidates[state.selectedIndex] = { ...current, ...payload, texts: [...texts] };
      state = {
        ...state,
        busy: false,
        phase: "ready",
        candidates,
        error: "",
      };
      publish();
      return { ok: true, result: getState().result };
    } catch {
      state = { ...state, busy: false, phase: "error", error: "The captions could not be updated. Your current meme is still here." };
      publish();
      return { ok: false, code: "CAPTION_FAILED", error: state.error };
    }
  }

  return {
    getState,
    generate,
    generateGeneral(prompt, count = 1, analyzeImages = false) {
      return generate(prompt, "general", count, analyzeImages);
    },
    selectCandidate(index) {
      if (state.busy || !Number.isInteger(index) || index < 0 || index >= state.candidates.length) return false;
      state = { ...state, selectedIndex: index, error: "" };
      publish();
      return true;
    },
    updateCaptions,
  };
}
