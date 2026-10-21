"""Pure HTML parsers: no network, no database."""
from __future__ import annotations

import json
import re

from bs4 import BeautifulSoup

from .models import SITE, Box, ExampleCaption, ListingEntry, TemplateDetail

_MEME_HREF = re.compile(r"^/meme/(?:(\d+)/)?([^/?#]+)")
_MEMES_VAR = re.compile(r"\bmemes=(?=[\[{])")
_INIT_MEME = re.compile(r"initMeme='([^']*)'")
_NUM_TEXTS = re.compile(r"numTexts:\s*(\d+)")
_EXAMPLE_HREF = re.compile(r"^/i/([A-Za-z0-9]+)")
_STAT = re.compile(r"([\d,]+)\s+(views|upvotes|comments)")
_ALT_SUFFIX = " | made w/ Imgflip meme maker"
_TAGS_PREFIX = "image tagged in "


class ParseError(ValueError):
    """The page did not have the structure we expect."""


def _absolute_image(src: str) -> str:
    return f"https:{src}" if src.startswith("//") else src


def parse_listing(html: str) -> tuple[ListingEntry, ...]:
    soup = BeautifulSoup(html, "html.parser")
    seen: set[str] = set()
    entries: list[ListingEntry] = []
    for box in soup.select("div.mt-box"):
        link = box.select_one("h3.mt-title a")
        image = box.select_one("img")
        match = _MEME_HREF.match(link.get("href", "")) if link else None
        if not (link and image and match) or match.group(2) in seen:
            continue
        seen.add(match.group(2))
        entries.append(
            ListingEntry(
                slug=match.group(2),
                name=link.get_text(strip=True),
                image_url=_absolute_image(image.get("src", "")),
                template_id=int(match.group(1)) if match.group(1) else None,
            )
        )
    return tuple(entries)


def _num(value: object, default: float = 0.0) -> float:
    return float(value) if isinstance(value, (int, float)) else default


def _parse_boxes(raw_settings: str | None) -> tuple[Box, ...]:
    try:
        settings = json.loads(raw_settings or "[]")
    except json.JSONDecodeError:
        return ()
    # Entries without a "type" are plain text boxes; "image" entries are stickers.
    texts = [s for s in settings if isinstance(s, dict) and s.get("type", "text") == "text"]
    return tuple(
        Box(
            box_index=i,
            x=_num(s.get("x")),
            y=_num(s.get("y")),
            w=_num(s.get("w")),
            h=_num(s.get("h")),
            rotation=_num(s.get("rotation")),
            font=s.get("font") or "",
            font_color=s.get("font_color") or "",
            outline_color=s.get("outline_color") or "",
            force_caps=bool(s.get("force_caps", False)),
            text_align=s.get("text_align") or "",
            vertical_align=s.get("vertical_align") or "",
            font_max_size=s.get("font_max_size"),
        )
        for i, s in enumerate(texts)
    )


def _split_names(raw: object) -> tuple[str, ...]:
    if not isinstance(raw, str):  # imgflip sometimes stores a number here
        return ()
    return tuple(name.strip() for name in raw.split(",") if name.strip())


def _select_entry(memes: object, init_meme: str) -> dict:
    """``memes`` is a list for popular templates and a dict (keyed '0'..'59','U') otherwise."""
    try:
        entry = memes[int(init_meme)] if isinstance(memes, list) else memes[init_meme]
    except (KeyError, IndexError, ValueError, TypeError) as exc:
        raise ParseError(f"initMeme {init_meme!r} not found in embedded data") from exc
    if not isinstance(entry, dict):
        raise ParseError("selected embedded entry is not an object")
    return entry


def parse_generator(html: str, slug: str, template_id: int | None = None) -> TemplateDetail:
    """Extract the page's own template from its embedded JSON.

    The embedded ``memes`` holds ~60 popular templates on every page; ``initMeme`` says which
    one this page is about. The result is checked against ``slug``/``template_id`` so a
    redirected generic page can never be stored under the wrong meme.
    """
    start = _MEMES_VAR.search(html)
    if not start:
        raise ParseError("no embedded memes data found")
    init = _INIT_MEME.search(html)
    if not init:
        raise ParseError("no initMeme found")
    try:
        memes, _ = json.JSONDecoder().raw_decode(html[start.end():])
    except json.JSONDecodeError as exc:
        raise ParseError(f"embedded memes data is not valid JSON: {exc}") from exc

    meme = _select_entry(memes, init.group(1))
    if meme.get("url_name") != slug and not (template_id and int(meme.get("id", 0)) == template_id):
        raise ParseError(
            f"page shows {meme.get('url_name')!r} (id {meme.get('id')}), expected {slug!r}"
        )

    try:
        return _build_detail(meme, html)
    except (KeyError, TypeError, ValueError, AttributeError) as exc:
        raise ParseError(f"unusable embedded entry for {slug!r}: {exc!r}") from exc


def _build_detail(meme: dict, html: str) -> TemplateDetail:
    boxes = _parse_boxes(meme.get("default_settings"))
    num_texts = _NUM_TEXTS.search(html)
    return TemplateDetail(
        asset_id=int(meme["id"]),
        creator_uid=meme.get("uid") or None,
        name=str(meme.get("name") or ""),
        width=int(meme.get("w") or 0),
        height=int(meme.get("h") or 0),
        file_type=str(meme.get("file_type") or ""),
        alt_names=_split_names(meme.get("altNames")),
        safe_for_work=meme.get("safe_for_work") == "yes",
        boxes=boxes,
        box_count=len(boxes) if boxes else int(num_texts.group(1)) if num_texts else 2,
        boxes_explicit=bool(boxes),
    )


def _stats(text: str) -> dict[str, int]:
    return {label: int(number.replace(",", "")) for number, label in _STAT.findall(text)}


def strip_title(body: str, title: str) -> str:
    """Remove a leading 'title |' (or a body that is only the title), ignoring whitespace/case.

    imgflip's alt text can differ from the visible title in spacing, so a plain startswith()
    missed it and the title leaked into the first text box.
    """
    words = title.split()
    if not words:
        return body
    pattern = r"\s+".join(re.escape(w) for w in words)
    stripped = re.sub(rf"^\s*{pattern}\s*(?:\|\s*|$)", "", body, count=1, flags=re.IGNORECASE)
    return stripped


def box_texts_from(caption_raw: str) -> tuple[str, ...]:
    return tuple(t.strip() for t in caption_raw.split(";") if t.strip())


def _split_alt(alt: str, title: str) -> tuple[str, tuple[str, ...]]:
    """alt is 'title | box1; box2 | image tagged in a,b | made w/ Imgflip meme maker'."""
    body = alt[: -len(_ALT_SUFFIX)] if alt.endswith(_ALT_SUFFIX) else alt
    body = strip_title(body, title)
    tags: tuple[str, ...] = ()
    head, sep, tail = body.rpartition(" | ")
    if tail.startswith(_TAGS_PREFIX):
        tags = tuple(t.strip() for t in tail[len(_TAGS_PREFIX):].split(",") if t.strip())
        body = head
    elif body.startswith(_TAGS_PREFIX):  # no caption text, only tags
        tags = tuple(t.strip() for t in body[len(_TAGS_PREFIX):].split(",") if t.strip())
        body = ""
    return body, tags


def parse_examples(html: str) -> tuple[ExampleCaption, ...]:
    soup = BeautifulSoup(html, "html.parser")
    examples: list[ExampleCaption] = []
    for unit in soup.select("div.base-unit"):
        link = unit.select_one("h2.base-unit-title a")
        match = _EXAMPLE_HREF.match(link.get("href", "")) if link else None
        if not match:
            continue
        title = link.get_text(strip=True)
        image = unit.select_one("img.base-img")
        caption_raw, tags = _split_alt(image.get("alt", "") if image else "", title)
        author_box = unit.select_one(".base-author")
        author_link = author_box.select_one("a") if author_box else None
        author_text = author_box.get_text(" ", strip=True).removeprefix("by").strip() if author_box else ""
        stats = _stats(unit.select_one(".base-view-count").get_text(" ") if unit.select_one(".base-view-count") else "")
        examples.append(
            ExampleCaption(
                example_id=match.group(1),
                url=f"{SITE}/i/{match.group(1)}",
                title=title,
                caption_raw=caption_raw,
                box_texts=box_texts_from(caption_raw),
                tags=tags,
                author=author_text or None,  # "anonymous" has no profile link but is still kept
                author_url=SITE + author_link["href"] if author_link and author_link.get("href") else None,
                views=stats.get("views", 0),
                upvotes=stats.get("upvotes", 0),
                comments=stats.get("comments", 0),
            )
        )
    return tuple(examples)
