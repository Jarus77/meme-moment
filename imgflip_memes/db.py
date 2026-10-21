"""SQLite storage for meme templates."""
from __future__ import annotations

import json
import sqlite3
from types import TracebackType

from dataclasses import dataclass

from .models import ID_2026_START, ExampleCaption, MemeRecord
from .parse import box_texts_from, strip_title

SCHEMA = """
CREATE TABLE IF NOT EXISTS memes (
    asset_id      INTEGER PRIMARY KEY,
    index_no      INTEGER NOT NULL UNIQUE,
    slug          TEXT    NOT NULL UNIQUE,
    name          TEXT    NOT NULL,
    image_url     TEXT    NOT NULL,
    width         INTEGER,
    height        INTEGER,
    file_type     TEXT,
    safe_for_work INTEGER NOT NULL DEFAULT 1,
    creator_uid   INTEGER,
    box_count     INTEGER NOT NULL DEFAULT 0,
    boxes_explicit INTEGER NOT NULL DEFAULT 1,
    listing_page  INTEGER,
    likely_2026   INTEGER NOT NULL DEFAULT 0,
    image_path    TEXT,
    image_kind    TEXT,
    examples_scraped_at TEXT,
    source_url    TEXT    NOT NULL,
    attribution   TEXT    NOT NULL,
    scraped_at    TEXT    NOT NULL DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS boxes (
    meme_id        INTEGER NOT NULL REFERENCES memes(asset_id) ON DELETE CASCADE,
    box_index      INTEGER NOT NULL,
    x REAL, y REAL, w REAL, h REAL, rotation REAL,
    font TEXT, font_color TEXT, outline_color TEXT,
    force_caps INTEGER, text_align TEXT, vertical_align TEXT, font_max_size INTEGER,
    PRIMARY KEY (meme_id, box_index)
);
CREATE TABLE IF NOT EXISTS tags (
    meme_id INTEGER NOT NULL REFERENCES memes(asset_id) ON DELETE CASCADE,
    tag     TEXT    NOT NULL,
    PRIMARY KEY (meme_id, tag)
);
CREATE TABLE IF NOT EXISTS caption_drafts (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    meme_id    INTEGER NOT NULL REFERENCES memes(asset_id) ON DELETE CASCADE,
    caption    TEXT    NOT NULL,
    source     TEXT    NOT NULL DEFAULT 'manual',
    created_at TEXT    NOT NULL DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS example_captions (
    meme_id     INTEGER NOT NULL REFERENCES memes(asset_id) ON DELETE CASCADE,
    example_id  TEXT    NOT NULL,
    url         TEXT    NOT NULL,
    title       TEXT,
    caption_raw TEXT,
    box_texts   TEXT,
    tags        TEXT,
    author      TEXT,
    author_url  TEXT,
    views       INTEGER,
    upvotes     INTEGER,
    comments    INTEGER,
    PRIMARY KEY (meme_id, example_id)
);
CREATE INDEX IF NOT EXISTS idx_tags_tag ON tags(tag);
"""

_UPSERT_MEME = """
INSERT INTO memes (asset_id, index_no, slug, name, image_url, width, height, file_type,
                   safe_for_work, creator_uid, box_count, boxes_explicit, listing_page, likely_2026,
                   source_url, attribution)
VALUES (:asset_id,
        (SELECT COALESCE(MAX(index_no), 0) + 1 FROM memes),
        :slug, :name, :image_url, :width, :height, :file_type,
        :safe_for_work, :creator_uid, :box_count, :boxes_explicit, :listing_page, :likely_2026, :source_url, :attribution)
ON CONFLICT(asset_id) DO UPDATE SET
    slug=excluded.slug, name=excluded.name, image_url=excluded.image_url,
    width=excluded.width, height=excluded.height, file_type=excluded.file_type,
    safe_for_work=excluded.safe_for_work, creator_uid=excluded.creator_uid,
    box_count=excluded.box_count, boxes_explicit=excluded.boxes_explicit,
    listing_page=excluded.listing_page, likely_2026=excluded.likely_2026,
    source_url=excluded.source_url, attribution=excluded.attribution,
    scraped_at=datetime('now')
"""


# Columns added after the first release; applied to databases created before them.
_MIGRATIONS = (
    ("likely_2026", "INTEGER NOT NULL DEFAULT 0"),
    ("image_path", "TEXT"),
    ("image_kind", "TEXT"),
    ("examples_scraped_at", "TEXT"),
)


@dataclass(frozen=True)
class ImageTarget:
    asset_id: int
    file_type: str
    image_url: str


@dataclass(frozen=True)
class ExampleTarget:
    asset_id: int
    slug: str


class MemeDatabase:
    def __init__(self, path: str) -> None:
        self.connection = sqlite3.connect(path)
        self.connection.row_factory = sqlite3.Row
        self.connection.execute("PRAGMA foreign_keys = ON")
        self.connection.executescript(SCHEMA)
        self._migrate()

    def _migrate(self) -> None:
        existing = {r["name"] for r in self.connection.execute("PRAGMA table_info(memes)")}
        with self.connection:
            for column, ddl in _MIGRATIONS:
                if column not in existing:
                    self.connection.execute(f"ALTER TABLE memes ADD COLUMN {column} {ddl}")
            self.connection.execute(
                "UPDATE memes SET likely_2026 = (asset_id >= ?)", (ID_2026_START,)
            )
            # The slug-only /meme/<slug> form redirects to a generic page for non-popular templates.
            # attribution embeds that URL too; each fix keys off its own column so reruns are idempotent.
            self.connection.execute(
                "UPDATE memes SET attribution = replace(attribution, "
                "'/meme/' || slug || ')', '/meme/' || asset_id || '/' || slug || ')') "
                "WHERE attribution LIKE '%/meme/' || slug || ')%'"
            )
            self.connection.execute(
                "UPDATE memes SET source_url = 'https://imgflip.com/meme/' || asset_id || '/' || slug "
                "WHERE source_url NOT LIKE '%/' || asset_id || '/' || slug"
            )

    def __enter__(self) -> MemeDatabase:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.connection.close()

    def upsert(self, record: MemeRecord) -> None:
        with self.connection:
            self.connection.execute(
                _UPSERT_MEME,
                {
                    "asset_id": record.asset_id,
                    "slug": record.slug,
                    "name": record.name,
                    "image_url": record.image_url,
                    "width": record.width,
                    "height": record.height,
                    "file_type": record.file_type,
                    "safe_for_work": int(record.safe_for_work),
                    "creator_uid": record.creator_uid,
                    "box_count": record.box_count,
                    "boxes_explicit": int(record.boxes_explicit),
                    "listing_page": record.listing_page,
                    "likely_2026": int(record.asset_id >= ID_2026_START),
                    "source_url": record.source_url,
                    "attribution": record.attribution,
                },
            )
            self.connection.execute("DELETE FROM boxes WHERE meme_id = ?", (record.asset_id,))
            self.connection.execute("DELETE FROM tags WHERE meme_id = ?", (record.asset_id,))
            self.connection.executemany(
                "INSERT INTO boxes (meme_id, box_index, x, y, w, h, rotation, font, font_color, "
                "outline_color, force_caps, text_align, vertical_align, font_max_size) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                [
                    (record.asset_id, b.box_index, b.x, b.y, b.w, b.h, b.rotation, b.font,
                     b.font_color, b.outline_color, int(b.force_caps), b.text_align,
                     b.vertical_align, b.font_max_size)
                    for b in record.boxes
                ],
            )
            self.connection.executemany(
                "INSERT OR IGNORE INTO tags (meme_id, tag) VALUES (?, ?)",
                [(record.asset_id, tag) for tag in record.alt_names],
            )

    def has_slug(self, slug: str) -> bool:
        row = self.connection.execute("SELECT 1 FROM memes WHERE slug = ?", (slug,)).fetchone()
        return row is not None

    def count(self) -> int:
        return self.connection.execute("SELECT COUNT(*) FROM memes").fetchone()[0]

    def set_image(self, asset_id: int, path: str, kind: str) -> None:
        with self.connection:
            self.connection.execute(
                "UPDATE memes SET image_path = ?, image_kind = ? WHERE asset_id = ?",
                (path, kind, asset_id),
            )

    def missing_images(self) -> list[ImageTarget]:
        rows = self.connection.execute(
            "SELECT asset_id, file_type, image_url FROM memes WHERE image_path IS NULL ORDER BY index_no"
        ).fetchall()
        return [ImageTarget(r["asset_id"], r["file_type"] or "jpg", r["image_url"]) for r in rows]

    def replace_examples(self, meme_id: int, examples: list[ExampleCaption] | tuple[ExampleCaption, ...]) -> None:
        """Store a meme's example captions (replacing earlier ones) and mark it as scraped."""
        with self.connection:
            self.connection.execute("DELETE FROM example_captions WHERE meme_id = ?", (meme_id,))
            self.connection.executemany(
                "INSERT OR IGNORE INTO example_captions (meme_id, example_id, url, title, caption_raw, "
                "box_texts, tags, author, author_url, views, upvotes, comments) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                [
                    (meme_id, e.example_id, e.url, e.title, e.caption_raw,
                     json.dumps(e.box_texts), json.dumps(e.tags), e.author, e.author_url,
                     e.views, e.upvotes, e.comments)
                    for e in examples
                ],
            )
            self.connection.execute(
                "UPDATE memes SET examples_scraped_at = datetime('now') WHERE asset_id = ?", (meme_id,)
            )

    def repair_example_titles(self) -> int:
        """Strip a leaked '<title> |' prefix from stored example captions. Returns rows changed."""
        changed = 0
        with self.connection:
            for row in self.connection.execute(
                "SELECT meme_id, example_id, title, caption_raw FROM example_captions"
            ).fetchall():
                cleaned = strip_title(row["caption_raw"] or "", row["title"] or "")
                if cleaned == row["caption_raw"]:
                    continue
                self.connection.execute(
                    "UPDATE example_captions SET caption_raw = ?, box_texts = ? "
                    "WHERE meme_id = ? AND example_id = ?",
                    (cleaned, json.dumps(box_texts_from(cleaned)), row["meme_id"], row["example_id"]),
                )
                changed += 1
        return changed

    def memes_without_examples(self) -> list[ExampleTarget]:
        rows = self.connection.execute(
            "SELECT asset_id, slug FROM memes WHERE examples_scraped_at IS NULL ORDER BY index_no"
        ).fetchall()
        return [ExampleTarget(r["asset_id"], r["slug"]) for r in rows]
