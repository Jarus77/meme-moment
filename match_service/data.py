"""Export the template index to a compact, database-free bundle and load it back."""
from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from .index import TemplateIndex

BOX_COLUMNS = ("x", "y", "w", "h", "rotation", "font", "font_color", "outline_color")


@dataclass(frozen=True)
class ExportSummary:
    templates: int
    captions: int
    out_dir: Path


def _template(con: sqlite3.Connection, slug: str, max_captions: int) -> dict:
    from imgflip_memes.images import full_image_url  # export-only; the running service must not need it

    row = con.execute(
        "SELECT asset_id, slug, name, source_url, file_type, width, height, safe_for_work, "
        "box_count, boxes_explicit FROM memes WHERE slug = ?", (slug,),
    ).fetchone()
    if row is None:
        raise ValueError(f"template {slug!r} is in the index but not in the database")
    boxes = con.execute(
        f"SELECT {', '.join(BOX_COLUMNS)} FROM boxes WHERE meme_id = ? ORDER BY box_index", (row["asset_id"],)
    ).fetchall()
    captions = con.execute(
        "SELECT box_texts, author, url, upvotes FROM example_captions WHERE meme_id = ? "
        "ORDER BY upvotes DESC, rowid LIMIT ?", (row["asset_id"], max_captions),
    ).fetchall()
    return {
        "asset_id": row["asset_id"], "slug": row["slug"], "name": row["name"].strip(),
        "source_url": row["source_url"],
        "image_url": full_image_url(row["asset_id"], row["file_type"] or "jpg"),
        "width": row["width"], "height": row["height"],
        "safe_for_work": bool(row["safe_for_work"]),
        "box_count": row["box_count"], "boxes_explicit": bool(row["boxes_explicit"]),
        "boxes": [{c: b[c] for c in BOX_COLUMNS} for b in boxes],
        "captions": [
            {"box_texts": json.loads(c["box_texts"] or "[]"), "author": c["author"] or "unknown",
             "url": c["url"], "upvotes": c["upvotes"] or 0}
            for c in captions if json.loads(c["box_texts"] or "[]")
        ],
    }


def build_service_data(db_path: Path, index_dir: Path, out_dir: Path, max_captions: int = 20) -> ExportSummary:
    index_dir, out_dir = Path(index_dir), Path(out_dir)
    slugs = json.loads((index_dir / "meta.json").read_text())["slugs"]
    vectors = np.load(index_dir / "siglip2.npz")["img"]
    if len(vectors) != len(slugs):
        raise ValueError(f"index has {len(vectors)} vectors but meta lists {len(slugs)} slugs")

    con = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    try:
        templates = [_template(con, slug, max_captions) for slug in slugs]
    finally:
        con.close()

    out_dir.mkdir(parents=True, exist_ok=True)
    np.save(out_dir / "vectors.npy", vectors.astype(np.float16))
    (out_dir / "templates.json").write_text(json.dumps(templates, separators=(",", ":")))
    return ExportSummary(len(templates), sum(len(t["captions"]) for t in templates), out_dir)


def load_index(data_dir: Path) -> TemplateIndex:
    data_dir = Path(data_dir)
    vectors = np.load(data_dir / "vectors.npy").astype(np.float32)
    templates = json.loads((data_dir / "templates.json").read_text())
    return TemplateIndex(vectors, templates)


def load_caption_vectors(data_dir: Path) -> np.ndarray:
    return np.load(Path(data_dir) / "caption_vectors.npy").astype(np.float32)


def export_templates(db_path: Path, out_dir: Path, max_captions: int = 20) -> ExportSummary:
    """Write templates.json for every template that has a downloaded picture, in scrape order.

    This is the first step of the embedding pipeline: the vectors computed next must follow this order.
    """
    con = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    try:
        slugs = [r["slug"] for r in con.execute("SELECT slug FROM memes WHERE image_path IS NOT NULL ORDER BY index_no")]
        templates = [_template(con, slug, max_captions) for slug in slugs]
    finally:
        con.close()
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "templates.json").write_text(json.dumps(templates, separators=(",", ":")))
    return ExportSummary(len(templates), sum(len(t["captions"]) for t in templates), out_dir)
