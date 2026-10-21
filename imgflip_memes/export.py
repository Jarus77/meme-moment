"""Export the database to spreadsheet-friendly CSV files."""
from __future__ import annotations

import argparse
import csv
import json
from dataclasses import dataclass
from pathlib import Path

from .db import MemeDatabase

BOX_FIELDS = ("x", "y", "w", "h")
MEME_COLUMNS = (
    "index_no", "asset_id", "name", "slug", "likely_2026", "safe_for_work", "width", "height",
    "file_type", "image_path", "image_kind", "box_count", "boxes_explicit", "box_positions",
)
MEME_TAIL_COLUMNS = (
    "tags", "example_count", "creator_uid", "attribution", "source_url", "image_url", "scraped_at",
)
EXAMPLE_COLUMNS = (
    "asset_id", "meme_name", "meme_slug", "example_id", "url", "title", "box_texts", "caption_raw",
    "tags", "author", "author_url", "views", "upvotes", "comments",
)
SEPARATOR = " | "


@dataclass(frozen=True)
class ExportResult:
    memes: int
    examples: int
    memes_path: Path
    examples_path: Path


def _boxes_by_meme(db: MemeDatabase) -> dict[int, list[dict]]:
    boxes: dict[int, list[dict]] = {}
    for row in db.connection.execute("SELECT * FROM boxes ORDER BY meme_id, box_index"):
        boxes.setdefault(row["meme_id"], []).append(
            {
                "x": row["x"], "y": row["y"], "w": row["w"], "h": row["h"],
                "rotation": row["rotation"], "font": row["font"], "font_color": row["font_color"],
                "outline_color": row["outline_color"], "text_align": row["text_align"],
                "vertical_align": row["vertical_align"], "force_caps": bool(row["force_caps"]),
            }
        )
    return boxes


def _tags_by_meme(db: MemeDatabase) -> dict[int, list[str]]:
    tags: dict[int, list[str]] = {}
    for row in db.connection.execute("SELECT meme_id, tag FROM tags ORDER BY meme_id, tag"):
        tags.setdefault(row["meme_id"], []).append(row["tag"])
    return tags


def _meme_rows(db: MemeDatabase) -> tuple[list[str], list[dict]]:
    boxes, tags = _boxes_by_meme(db), _tags_by_meme(db)
    example_counts = dict(
        db.connection.execute("SELECT meme_id, COUNT(*) FROM example_captions GROUP BY meme_id").fetchall()
    )
    max_boxes = max((len(b) for b in boxes.values()), default=0)
    flat_columns = [f"box{i}_{f}" for i in range(1, max_boxes + 1) for f in BOX_FIELDS]
    rows = []
    for meme in db.connection.execute("SELECT * FROM memes ORDER BY index_no"):
        meme_boxes = boxes.get(meme["asset_id"], [])
        row = {c: meme[c] for c in MEME_COLUMNS if c != "box_positions"}
        row.update(
            box_positions=json.dumps(meme_boxes),
            tags=SEPARATOR.join(tags.get(meme["asset_id"], [])),
            example_count=example_counts.get(meme["asset_id"], 0),
            **{c: meme[c] for c in MEME_TAIL_COLUMNS if c not in ("tags", "example_count")},
        )
        for i, box in enumerate(meme_boxes, start=1):
            row.update({f"box{i}_{f}": box[f] for f in BOX_FIELDS})
        rows.append(row)
    return [*MEME_COLUMNS, *flat_columns, *MEME_TAIL_COLUMNS], rows


def _example_rows(db: MemeDatabase) -> list[dict]:
    query = (
        "SELECT e.*, m.name AS meme_name, m.slug AS meme_slug, m.asset_id AS asset_id "
        "FROM example_captions e JOIN memes m ON m.asset_id = e.meme_id ORDER BY m.index_no, e.rowid"
    )
    return [
        {
            **{c: row[c] for c in EXAMPLE_COLUMNS if c not in ("box_texts", "tags")},
            "box_texts": SEPARATOR.join(json.loads(row["box_texts"] or "[]")),
            "tags": SEPARATOR.join(json.loads(row["tags"] or "[]")),
        }
        for row in db.connection.execute(query)
    ]


def _write(path: Path, columns: list[str] | tuple[str, ...], rows: list[dict]) -> None:
    # utf-8-sig so Excel/Numbers open emoji and accents correctly.
    with open(path, "w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(columns), restval="", extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def export_csv(db: MemeDatabase, out_dir: Path) -> ExportResult:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    meme_columns, meme_rows = _meme_rows(db)
    example_rows = _example_rows(db)
    memes_path, examples_path = out / "memes.csv", out / "example_captions.csv"
    _write(memes_path, meme_columns, meme_rows)
    _write(examples_path, EXAMPLE_COLUMNS, example_rows)
    return ExportResult(len(meme_rows), len(example_rows), memes_path, examples_path)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Export the meme database to CSV.")
    parser.add_argument("--db", default="data/memes.db")
    parser.add_argument("--out", default="data/export")
    args = parser.parse_args(argv)
    with MemeDatabase(args.db) as db:
        result = export_csv(db, Path(args.out))
    print(f"wrote {result.memes} memes -> {result.memes_path}; {result.examples} examples -> {result.examples_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
