import json

import numpy as np
import pytest

from imgflip_memes.db import MemeDatabase
from imgflip_memes.models import Box
from match_service.data import build_service_data, load_index
from tests.test_db import make_record
from tests.test_examples_crawl import make_example


@pytest.fixture
def sources(tmp_path):
    db_path = tmp_path / "memes.db"
    with MemeDatabase(str(db_path)) as db:
        db.upsert(make_record(asset_id=181913649, slug="Alpha", name="Alpha"))
        db.upsert(make_record(asset_id=87743020, slug="Beta", name="Beta", boxes=(), boxes_explicit=False))
        db.replace_examples(181913649, [
            make_example("e1", author="Low", upvotes=1), make_example("e2", author="High", upvotes=50),
            make_example("e3", author="Mid", upvotes=10),
        ])
        db.connection.execute("UPDATE memes SET safe_for_work = 0 WHERE slug = 'Beta'")
        db.connection.commit()
    index_dir = tmp_path / "index"
    index_dir.mkdir()
    (index_dir / "meta.json").write_text(json.dumps({"slugs": ["Beta", "Alpha"], "names": ["Beta", "Alpha"]}))
    np.savez(index_dir / "siglip2.npz", img=np.array([[3.0, 0.0], [0.0, 2.0]], dtype=np.float32),
             cap=np.zeros((0, 2), dtype=np.float32))
    return db_path, index_dir


def test_export_follows_index_order_and_stores_half_precision_vectors(sources, tmp_path):
    out = tmp_path / "out"
    summary = build_service_data(*sources, out)
    assert summary.templates == 2
    vectors = np.load(out / "vectors.npy")
    assert vectors.dtype == np.float16 and vectors.shape == (2, 2)
    templates = json.loads((out / "templates.json").read_text())
    assert [t["slug"] for t in templates] == ["Beta", "Alpha"]


def test_template_fields_match_the_contract(sources, tmp_path):
    out = tmp_path / "out"
    build_service_data(*sources, out)
    alpha = next(t for t in json.loads((out / "templates.json").read_text()) if t["slug"] == "Alpha")
    assert alpha["asset_id"] == 181913649
    assert alpha["source_url"] == "https://imgflip.com/meme/181913649/Alpha"
    assert alpha["image_url"] == "https://i.imgflip.com/30b1gx.jpg"
    assert alpha["box_count"] == 2 and alpha["boxes_explicit"] is True
    assert set(alpha["boxes"][0]) == {"x", "y", "w", "h", "rotation", "font", "font_color", "outline_color"}
    assert alpha["safe_for_work"] is True


def test_default_layout_template_has_no_boxes_and_unsafe_flag_is_kept(sources, tmp_path):
    out = tmp_path / "out"
    build_service_data(*sources, out)
    beta = next(t for t in json.loads((out / "templates.json").read_text()) if t["slug"] == "Beta")
    assert beta["boxes"] == [] and beta["boxes_explicit"] is False and beta["safe_for_work"] is False


def test_captions_carry_author_url_and_votes_and_are_capped(sources, tmp_path):
    out = tmp_path / "out"
    build_service_data(*sources, out, max_captions=2)
    alpha = next(t for t in json.loads((out / "templates.json").read_text()) if t["slug"] == "Alpha")
    assert [c["author"] for c in alpha["captions"]] == ["High", "Mid"]
    assert alpha["captions"][0]["url"].startswith("https://imgflip.com/i/")
    assert alpha["captions"][0]["box_texts"] == ["a", "b"] and alpha["captions"][0]["upvotes"] == 50


def test_load_index_roundtrip_is_searchable(sources, tmp_path):
    out = tmp_path / "out"
    build_service_data(*sources, out)
    index = load_index(out)
    assert len(index) == 2 and index.dim == 2
    best = index.search(np.array([0.0, 1.0]), k=1, captions_per_template=1)[0]
    assert best["template"]["slug"] == "Alpha" and best["example_captions"][0]["author"] == "High"


def test_slug_missing_from_database_is_an_error_naming_the_slug(sources, tmp_path):
    db_path, index_dir = sources
    (index_dir / "meta.json").write_text(json.dumps({"slugs": ["Beta", "Ghost"], "names": []}))
    with pytest.raises(ValueError, match="Ghost"):
        build_service_data(db_path, index_dir, tmp_path / "out")


def test_vector_and_slug_count_mismatch_is_an_error(sources, tmp_path):
    db_path, index_dir = sources
    (index_dir / "meta.json").write_text(json.dumps({"slugs": ["Beta"], "names": []}))
    with pytest.raises(ValueError, match="2 vectors"):
        build_service_data(db_path, index_dir, tmp_path / "out")


def test_runtime_imports_do_not_pull_in_the_scraper_package():
    # The service runs in its own environment; only the export step may use imgflip_memes.
    import subprocess, sys
    code = (
        "import sys; import match_service.data, match_service.app, match_service.server; "
        "bad=[m for m in sys.modules if m.split('.')[0] in ('imgflip_memes','requests')]; "
        "sys.exit(1 if bad else 0)"
    )
    assert subprocess.run([sys.executable, "-c", code]).returncode == 0


# ---- clean template export straight from the scraped database ----

def test_export_templates_writes_every_stored_template_in_index_order(tmp_path):
    from match_service.data import export_templates
    db_path = tmp_path / "memes.db"
    with MemeDatabase(str(db_path)) as db:
        db.upsert(make_record(asset_id=2, slug="Second", name="Second"))
        db.upsert(make_record(asset_id=1, slug="First", name="First"))
        db.set_image(2, "x/2.jpg", "full")
        db.set_image(1, "x/1.jpg", "full")
        db.replace_examples(1, [make_example("e1", author="Bob", upvotes=7)])
    summary = export_templates(db_path, tmp_path / "out")
    templates = json.loads((tmp_path / "out" / "templates.json").read_text())
    assert [t["slug"] for t in templates] == ["Second", "First"]  # insertion (index_no) order
    assert summary.templates == 2 and summary.captions == 1
    assert templates[1]["captions"][0]["author"] == "Bob"
    assert not (tmp_path / "out" / "vectors.npy").exists()  # vectors come from the embedding step


def test_export_templates_skips_templates_without_a_downloaded_image(tmp_path):
    from match_service.data import export_templates
    db_path = tmp_path / "memes.db"
    with MemeDatabase(str(db_path)) as db:
        db.upsert(make_record(asset_id=1, slug="HasImage", name="HasImage"))
        db.upsert(make_record(asset_id=2, slug="NoImage", name="NoImage"))
        db.set_image(1, "x/1.jpg", "full")
    export_templates(db_path, tmp_path / "out")
    assert [t["slug"] for t in json.loads((tmp_path / "out" / "templates.json").read_text())] == ["HasImage"]
