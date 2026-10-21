function escapeHtml(value) {
  return value.replace(/[&<>"']/g, (character) => ({
    "&": "&amp;",
    "<": "&lt;",
    ">": "&gt;",
    '"': "&quot;",
    "'": "&#39;",
  })[character]);
}

export function captionFieldsHtml(texts) {
  if (!Array.isArray(texts) || texts.length < 1 || texts.length > 20 || texts.some((text) => typeof text !== "string" || text.length > 500)) {
    throw new TypeError("Caption list must contain 1 to 20 strings of up to 500 characters.");
  }
  return texts.map((text, index) => `
    <div class="caption-field">
      <label for="caption-${index}">CAPTION ${String(index + 1).padStart(2, "0")}</label>
      <textarea id="caption-${index}" name="caption" data-caption-index="${index}" maxlength="500" rows="2" required>${escapeHtml(text)}</textarea>
      <span class="caption-field-count" aria-hidden="true">${text.length} / 500</span>
    </div>`).join("");
}

export function createDownloadHref(imageUrl) {
  let url;
  try {
    url = new URL(imageUrl);
  } catch {
    throw new TypeError("Use a valid Imgflip image URL.");
  }
  if (url.protocol !== "https:" || url.hostname !== "i.imgflip.com" || url.port || url.username || url.password) {
    throw new TypeError("Use a valid Imgflip image URL.");
  }
  return `/api/download?url=${encodeURIComponent(url.href)}`;
}
