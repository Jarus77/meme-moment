// DOM builders for the "fitted memes" results. Text always goes through textContent, never parsed as markup,
// so a situation, caption or author name can never inject HTML.

const FOUND_BY_LABELS = {
  keywords: "your words ↔ caption words",
  meaning: "your situation ↔ real captions",
  situation_picture: "your situation ↔ meme pictures",
  photo_picture: "your photo ↔ meme pictures",
  photo_caption: "your photo ↔ real captions",
};

function el(doc, tag, { className, text, attrs = {} } = {}) {
  const node = doc.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  for (const [name, value] of Object.entries(attrs)) node.setAttribute(name, value);
  return node;
}

function link(doc, href, text, className) {
  return el(doc, "a", { className, text, attrs: { href, target: "_blank", rel: "noreferrer noopener" } });
}

export function renderFitCards(container, cards, { onRate = () => {}, doc = document } = {}) {
  const nodes = cards.map((card, index) => {
    const article = el(doc, "article", { className: "fit-card" });
    article.appendChild(el(doc, "img", { attrs: { src: card.imageUrl, alt: `Meme option ${index + 1}: ${card.texts.join(" / ")}`, loading: "lazy" } }));

    const meta = el(doc, "div", { className: "fit-card-meta" });
    meta.appendChild(link(doc, card.template.source_url, `${card.template.name.trim()} ↗`, "fit-template"));

    const from = card.adaptedFrom;
    const adapted = el(doc, "p", { className: "fit-adapted" });
    adapted.appendChild(doc.createTextNode(`Adapted from “${from.box_texts.join(" / ")}” by `));
    adapted.appendChild(link(doc, from.url, from.author));
    adapted.appendChild(doc.createTextNode(` · ${from.upvotes} upvotes`));
    meta.appendChild(adapted);

    const found = (card.foundBy ?? []).map((name) => FOUND_BY_LABELS[name]).filter(Boolean);
    if (found.length) meta.appendChild(el(doc, "p", { className: "fit-found", text: `Found by: ${found.join(" · ")}` }));

    const rate = el(doc, "div", { className: "fit-rate", attrs: { role: "group", "aria-label": "How funny is this for you?" } });
    rate.appendChild(el(doc, "span", { text: card.rated ? "Thanks!" : "Funny for you?" }));
    for (let value = 1; value <= 5; value += 1) {
      const button = el(doc, "button", { className: "fit-rate-button", text: String(value), attrs: { type: "button", "aria-pressed": String(card.rated === value), "aria-label": `${value} out of 5` } });
      button.addEventListener("click", () => onRate(index, value));
      rate.appendChild(button);
    }
    meta.appendChild(rate);
    meta.appendChild(el(doc, "a", { className: "download-button", text: "Download ↓", attrs: { href: card.imageUrl, download: `meme-option-${index + 1}.png` } }));
    article.appendChild(meta);
    return article;
  });
  container.replaceChildren(...nodes);
}

export function renderAnalogs(list, analogs, { doc = document } = {}) {
  const nodes = analogs.map((analog) => {
    const item = el(doc, "li");
    item.appendChild(doc.createTextNode(`“${analog.box_texts.join(" / ")}” — ${analog.template.name.trim()}, by `));
    item.appendChild(link(doc, analog.url, analog.author));
    item.appendChild(doc.createTextNode(` · ${analog.upvotes} upvotes`));
    return item;
  });
  list.replaceChildren(...nodes);
}
