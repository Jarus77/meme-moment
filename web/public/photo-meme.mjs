const MAX_EDGE = 1280;
const MAX_OUTPUT_BYTES = 5 * 1024 * 1024;

export function blobDataUrl(blob) {
  return blob.arrayBuffer().then((buffer) => {
    const bytes = new Uint8Array(buffer);
    let binary = "";
    for (let index = 0; index < bytes.length; index += 0x8000) {
      binary += String.fromCharCode(...bytes.subarray(index, index + 0x8000));
    }
    return `data:${blob.type};base64,${btoa(binary)}`;
  });
}

export async function resizePhotoFile(file, {
  createImageBitmapImpl = globalThis.createImageBitmap?.bind(globalThis),
  canvasFactory = (width, height) => {
    const canvas = document.createElement("canvas");
    canvas.width = width;
    canvas.height = height;
    return canvas;
  },
} = {}) {
  if (!file || typeof file.type !== "string" || !file.type.startsWith("image/")) {
    throw new Error("Choose an image file to make a photo meme.");
  }
  if (typeof createImageBitmapImpl !== "function") throw new Error("This browser can’t read that image. Try a different photo.");
  let bitmap;
  try { bitmap = await createImageBitmapImpl(file); } catch { throw new Error("This browser couldn’t open that image. Try a different photo."); }
  try {
    const scale = Math.min(1, MAX_EDGE / Math.max(bitmap.width, bitmap.height));
    const width = Math.max(1, Math.round(bitmap.width * scale));
    const height = Math.max(1, Math.round(bitmap.height * scale));
    const canvas = canvasFactory(width, height);
    const context = canvas.getContext("2d", { alpha: false });
    if (!context) throw new Error("This browser couldn’t prepare that image. Try again.");
    context.drawImage(bitmap, 0, 0, width, height);
    const blob = await new Promise((resolve, reject) => canvas.toBlob((value) => value ? resolve(value) : reject(new Error("JPEG conversion failed")), "image/jpeg", 0.9));
    if (blob.type !== "image/jpeg" || blob.size > MAX_OUTPUT_BYTES) throw new Error("The resized photo is still too large. Choose a smaller image.");
    return { dataUrl: await blobDataUrl(blob), width, height };
  } finally {
    bitmap.close?.();
  }
}

export function wrapCaptionText(text, measureText, maxWidth) {
  const words = String(text || "").trim().split(/\s+/).filter(Boolean);
  if (!words.length) return [""];
  const lines = [];
  let current = "";
  for (const word of words) {
    const candidate = current ? `${current} ${word}` : word;
    if (current && measureText(candidate) > maxWidth) {
      lines.push(current);
      current = word;
      if (lines.length === 2) break;
    } else {
      current = candidate;
    }
  }
  if (lines.length < 2 && current) lines.push(current);
  if (lines.length === 2 && words.join(" ") !== lines.join(" ")) {
    let lastLine = lines[1];
    while (lastLine && measureText(`${lastLine}…`) > maxWidth) lastLine = lastLine.slice(0, -1).trimEnd();
    lines[1] = `${lastLine || "…"}…`;
  }
  return lines.slice(0, 2);
}

function loadDataImage(dataUrl, ImageImpl = globalThis.Image) {
  return new Promise((resolve, reject) => {
    const image = new ImageImpl();
    image.onload = () => resolve(image);
    image.onerror = () => reject(new Error("The photo preview could not be opened."));
    image.src = dataUrl;
  });
}

export async function renderPhotoCaption(dataUrl, texts, {
  ImageImpl = globalThis.Image,
  canvasFactory = () => document.createElement("canvas"),
} = {}) {
  const image = await loadDataImage(dataUrl, ImageImpl);
  const width = image.naturalWidth || image.width;
  const height = image.naturalHeight || image.height;
  const canvas = canvasFactory();
  canvas.width = width;
  canvas.height = height;
  const context = canvas.getContext("2d");
  if (!context) throw new Error("This browser couldn’t render the caption. Try again.");
  context.drawImage(image, 0, 0, width, height);
  context.textAlign = "center";
  context.textBaseline = "middle";
  context.lineJoin = "round";
  context.fillStyle = "#fff";
  context.strokeStyle = "#000";
  const count = texts.length;
  const locations = count === 1
    ? [0.86]
    : count === 2
      ? [0.12, 0.88]
      : texts.map((_text, index) => 0.1 + index * (0.8 / (count - 1)));
  const blockHeight = Math.max(36, Math.floor(height / Math.max(count, 2) * 0.8));
  const maxWidth = width * 0.94;
  for (let index = 0; index < count; index += 1) {
    let fontSize = Math.min(72, Math.max(20, Math.floor(width * 0.075)));
    let lines;
    do {
      context.font = `900 ${fontSize}px Impact, "Arial Narrow", sans-serif`;
      lines = wrapCaptionText(texts[index], (value) => context.measureText(value).width, maxWidth);
      if (lines.every((line) => context.measureText(line).width <= maxWidth) && fontSize > 18) break;
      fontSize -= 2;
    } while (fontSize > 18);
    context.font = `900 ${fontSize}px Impact, "Arial Narrow", sans-serif`;
    context.lineWidth = Math.max(3, fontSize * 0.12);
    const lineHeight = fontSize * 1.02;
    const centerY = height * locations[index];
    const startY = centerY - ((lines.length - 1) * lineHeight) / 2;
    lines.forEach((line, lineIndex) => {
      const y = startY + lineIndex * lineHeight;
      context.strokeText(line, width / 2, y, maxWidth);
      context.fillText(line, width / 2, y, maxWidth);
    });
  }
  return new Promise((resolve, reject) => canvas.toBlob((blob) => {
    if (!blob) reject(new Error("The PNG could not be created. Try again."));
    else resolve(blob);
  }, "image/png"));
}

function safeError(payload) {
  return typeof payload?.error === "string" && payload.error.length < 300
    ? payload.error
    : "We couldn’t make a photo meme just now. Please try again.";
}

export function createPhotoMemeActions({
  fetchImpl = fetch,
  resizeImpl = resizePhotoFile,
  renderImpl = renderPhotoCaption,
  createUrl = (blob) => URL.createObjectURL(blob),
  revokeUrl = (url) => URL.revokeObjectURL(url),
  onState = () => {},
} = {}) {
  let state = { busy: false, error: "", photoDataUrl: "", description: "", selectedMatch: null, matches: [], options: [], optionIndex: 0, imageUrl: "" };
  let imageUrls = [];

  function getState() { return { ...state, options: state.options.map((option) => ({ texts: [...option.texts] })), matches: [...state.matches] }; }
  function publish() { onState(getState()); }
  function clearUrls() {
    for (const url of imageUrls) revokeUrl(url);
    imageUrls = [];
  }

  async function generate(file) {
    if (state.busy) return { ok: false, code: "BUSY", error: "Please wait for the current photo to finish." };
    clearUrls();
    state = { ...state, busy: true, error: "", imageUrl: "" };
    publish();
    try {
      const photo = await resizeImpl(file);
      const response = await fetchImpl("/api/photo-meme", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ photo: photo.dataUrl }),
      });
      let payload;
      try { payload = await response.json(); } catch { payload = {}; }
      if (!response.ok) throw new Error(safeError(payload));
      if (!Array.isArray(payload.options) || payload.options.length !== 3
        || payload.options.some((option) => !Array.isArray(option.texts) || !option.texts.length || option.texts.length > 20)
        || !Array.isArray(payload.matches) || !payload.selectedMatch?.template) {
        throw new Error("The photo-meme service returned an incomplete result. Please try again.");
      }
      const imageBlobs = await Promise.all(payload.options.map((option) => renderImpl(photo.dataUrl, option.texts)));
      imageUrls = imageBlobs.map((blob, index) => createUrl(blob, index));
      state = {
        ...state, busy: false, error: "", photoDataUrl: photo.dataUrl, description: payload.description,
        selectedMatch: payload.selectedMatch, matches: payload.matches, options: payload.options,
        optionIndex: 0, imageUrl: imageUrls[0],
      };
      publish();
      return { ok: true, result: getState() };
    } catch (error) {
      state = { ...state, busy: false, error: error instanceof Error ? error.message : "We couldn’t make a photo meme just now. Please try again." };
      publish();
      return { ok: false, code: "PHOTO_MEME_FAILED", error: state.error };
    }
  }

  return {
    getState,
    generate,
    selectOption(index) {
      if (state.busy || !Number.isInteger(index) || index < 0 || index >= state.options.length) return false;
      state = { ...state, optionIndex: index, imageUrl: imageUrls[index] };
      publish();
      return true;
    },
    dispose: clearUrls,
  };
}
