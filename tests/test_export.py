import csv
import json

import pytest

from imgflip_memes.db import MemeDatabase
from imgflip_memes.export import export_csv
from tests.test_crawl import FakeSite  # noqa: F401  (ensures fixtures importable)
from tests.test_db import make_record
from tests.test_examples_crawl import make_example


@pytest.fixture
def db():
    with MemeDatabase(":memory:") as database:
        database.upsert(make_record(asset_id=1, slug="Alpha"))
        database.upsert(make_record(asset_id=700_000_000, slug="Beta", boxes=(), boxes_explicit=False))
        database.set_image(1, "data/images/1.jpg", "full")
        database.replace_examples(1, [make_example("e1", author="Bob"), make_example("e2", author="anonymous", author_url=None)])
        yield database


def read(path):
    with open(path, newline="", encoding="utf-8-sig") as handle:
        return list(csv.DictReader(handle))


def test_writes_one_row_per_meme_and_per_example(db, tmp_path):
    result = export_csv(db, tmp_path)
    assert (result.memes, result.examples) == (2, 2)
    assert len(read(tmp_path / "memes.csv")) == 2
    assert len(read(tmp_path / "example_captions.csv")) == 2


def test_meme_row_has_image_boxes_tags_and_attribution(db, tmp_path):
    export_csv(db, tmp_path)
    row = next(r for r in read(tmp_path / "memes.csv") if r["slug"] == "Alpha")
    assert row["image_path"] == "data/images/1.jpg" and row["image_kind"] == "full"
    assert row["box_count"] == "2" and row["boxes_explicit"] == "1"
    assert row["tags"] == "alt one | alt two"
    assert row["example_count"] == "2"
    assert "imgflip" in row["attribution"].lower()
    assert row["source_url"] == "https://imgflip.com/meme/1/Alpha"


def test_box_positions_both_as_json_and_flat_columns(db, tmp_path):
    export_csv(db, tmp_path)
    row = next(r for r in read(tmp_path / "memes.csv") if r["slug"] == "Alpha")
    boxes = json.loads(row["box_positions"])
    assert [b["y"] for b in boxes] == [5.0, 300.0]
    assert (row["box1_x"], row["box1_y"], row["box1_w"], row["box1_h"]) == ("10.0", "5.0", "200.0", "50.0")
    assert row["box2_y"] == "300.0"


def test_meme_without_explicit_boxes_has_empty_positions(db, tmp_path):
    export_csv(db, tmp_path)
    row = next(r for r in read(tmp_path / "memes.csv") if r["slug"] == "Beta")
    assert row["box_count"] == "2" and row["boxes_explicit"] == "0"
    assert json.loads(row["box_positions"]) == [] and row["box1_x"] == ""
    assert row["likely_2026"] == "1"


def test_example_rows_keep_author_and_meme_name(db, tmp_path):
    export_csv(db, tmp_path)
    rows = read(tmp_path / "example_captions.csv")
    by_id = {r["example_id"]: r for r in rows}
    assert by_id["e1"]["author"] == "Bob" and by_id["e1"]["meme_slug"] == "Alpha"
    assert by_id["e2"]["author"] == "anonymous" and by_id["e2"]["author_url"] == ""
    assert by_id["e1"]["box_texts"] == "a | b"
    assert by_id["e1"]["url"].startswith("https://imgflip.com/i/")


def test_output_directory_is_created(db, tmp_path):
    out = tmp_path / "nested" / "export"
    export_csv(db, out)
    assert (out / "memes.csv").exists()
