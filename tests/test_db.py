import sqlite3

import pytest

from imgflip_memes.db import MemeDatabase
from imgflip_memes.models import Box, MemeRecord


def make_record(asset_id: int = 111, slug: str = "Some-Meme", **overrides) -> MemeRecord:
    fields = dict(
        asset_id=asset_id,
        slug=slug,
        name="Some Meme",
        image_url="https://i.imgflip.com/4/abc.jpg",
        width=600,
        height=400,
        file_type="jpg",
        safe_for_work=True,
        creator_uid=27,
        alt_names=("alt one", "alt two"),
        listing_page=3,
        boxes=(
            Box(0, 10.0, 5.0, 200.0, 50.0, 0, "arial", "#000000", "#ffffff", False, "center", "top"),
            Box(1, 10.0, 300.0, 200.0, 50.0, 0, "arial", "#000000", "#ffffff", False, "center", "bottom"),
        ),
    )
    return MemeRecord(**{**fields, **overrides})


@pytest.fixture
def db():
    with MemeDatabase(":memory:") as database:
        yield database


def rows(db, sql, *args):
    return db.connection.execute(sql, args).fetchall()


def test_upsert_stores_meme_boxes_and_tags(db):
    db.upsert(make_record())
    (meme,) = rows(db, "SELECT * FROM memes")
    assert meme["asset_id"] == 111
    assert meme["box_count"] == 2
    assert meme["source_url"] == "https://imgflip.com/meme/111/Some-Meme"
    assert "imgflip" in meme["attribution"].lower()
    assert len(rows(db, "SELECT * FROM boxes WHERE meme_id = 111 ORDER BY box_index")) == 2
    tags = {r["tag"] for r in rows(db, "SELECT tag FROM tags WHERE meme_id = 111")}
    assert {"alt one", "alt two"} <= tags


def test_upsert_is_idempotent_and_replaces_children(db):
    db.upsert(make_record())
    db.upsert(make_record(alt_names=("only",), boxes=make_record().boxes[:1]))
    assert len(rows(db, "SELECT * FROM memes")) == 1
    assert len(rows(db, "SELECT * FROM boxes")) == 1
    assert [r["tag"] for r in rows(db, "SELECT tag FROM tags")] == ["only"]


def test_index_number_assigned_in_insert_order(db):
    db.upsert(make_record(asset_id=5, slug="A"))
    db.upsert(make_record(asset_id=3, slug="B"))
    idx = {r["slug"]: r["index_no"] for r in rows(db, "SELECT slug, index_no FROM memes")}
    assert idx["A"] < idx["B"]


def test_reupsert_keeps_original_index_number(db):
    db.upsert(make_record(asset_id=5, slug="A"))
    first = rows(db, "SELECT index_no FROM memes")[0]["index_no"]
    db.upsert(make_record(asset_id=5, slug="A", name="Renamed"))
    assert rows(db, "SELECT index_no, name FROM memes")[0]["index_no"] == first


def test_has_slug_and_count(db):
    assert not db.has_slug("Some-Meme")
    db.upsert(make_record())
    assert db.has_slug("Some-Meme")
    assert db.count() == 1


def test_caption_drafts_table_exists_and_cascades(db):
    db.upsert(make_record())
    db.connection.execute(
        "INSERT INTO caption_drafts (meme_id, caption, source) VALUES (111, 'when you...', 'manual')"
    )
    db.connection.execute("DELETE FROM memes WHERE asset_id = 111")
    assert rows(db, "SELECT * FROM caption_drafts") == []


def test_foreign_keys_enforced(db):
    with pytest.raises(sqlite3.IntegrityError):
        db.connection.execute(
            "INSERT INTO boxes (meme_id, box_index) VALUES (999, 0)"
        )


def test_default_boxes_recorded_when_template_has_no_explicit_settings(db):
    db.upsert(make_record(boxes=(), boxes_explicit=False, default_box_count=2))
    (meme,) = rows(db, "SELECT box_count, boxes_explicit FROM memes")
    assert (meme["box_count"], meme["boxes_explicit"]) == (2, 0)
    assert rows(db, "SELECT * FROM boxes") == []


def test_image_path_roundtrip_and_missing_images(db):
    db.upsert(make_record(asset_id=1, slug="A"))
    db.upsert(make_record(asset_id=2, slug="B"))
    assert {m.asset_id for m in db.missing_images()} == {1, 2}
    db.set_image(1, "data/images/1.jpg", "full")
    assert [m.asset_id for m in db.missing_images()] == [2]
    (row,) = rows(db, "SELECT image_path, image_kind FROM memes WHERE asset_id = 1")
    assert (row["image_path"], row["image_kind"]) == ("data/images/1.jpg", "full")


def test_reupsert_keeps_downloaded_image(db):
    db.upsert(make_record(asset_id=1, slug="A"))
    db.set_image(1, "data/images/1.jpg", "full")
    db.upsert(make_record(asset_id=1, slug="A", name="Renamed"))
    assert rows(db, "SELECT image_path FROM memes")[0]["image_path"] == "data/images/1.jpg"


def test_likely_2026_flag_follows_id_cutoff(db):
    db.upsert(make_record(asset_id=100, slug="Old"))
    db.upsert(make_record(asset_id=700_000_000, slug="New"))
    flags = {r["slug"]: r["likely_2026"] for r in rows(db, "SELECT slug, likely_2026 FROM memes")}
    assert flags == {"Old": 0, "New": 1}


def test_opening_a_pre_image_schema_database_migrates_it(tmp_path):
    path = str(tmp_path / "old.db")
    old = sqlite3.connect(path)
    old.executescript(
        "CREATE TABLE memes (asset_id INTEGER PRIMARY KEY, index_no INTEGER NOT NULL UNIQUE,"
        " slug TEXT NOT NULL UNIQUE, name TEXT NOT NULL, image_url TEXT NOT NULL, width INTEGER,"
        " height INTEGER, file_type TEXT, safe_for_work INTEGER NOT NULL DEFAULT 1, creator_uid INTEGER,"
        " box_count INTEGER NOT NULL DEFAULT 0, boxes_explicit INTEGER NOT NULL DEFAULT 1,"
        " listing_page INTEGER, source_url TEXT NOT NULL, attribution TEXT NOT NULL,"
        " scraped_at TEXT NOT NULL DEFAULT (datetime('now')));"
        " INSERT INTO memes (asset_id,index_no,slug,name,image_url,source_url,attribution)"
        " VALUES (700000000,1,'S','N','u','s','Template via imgflip.com (https://imgflip.com/meme/S); uploaded by x.');"
    )
    old.commit()
    old.close()
    with MemeDatabase(path) as migrated:
        row = migrated.connection.execute("SELECT image_path, likely_2026 FROM memes").fetchone()
        assert row["image_path"] is None
        assert row["likely_2026"] == 1  # backfilled from asset_id
        url = migrated.connection.execute("SELECT source_url FROM memes").fetchone()[0]
        assert url == "https://imgflip.com/meme/700000000/S"  # slug-only form redirects wrongly
        attribution = migrated.connection.execute("SELECT attribution FROM memes").fetchone()[0]
        assert "(https://imgflip.com/meme/700000000/S)" in attribution
