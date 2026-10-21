from pathlib import Path

import pytest

from imgflip_memes.db import MemeDatabase
from imgflip_memes.examples import crawl_examples
from imgflip_memes.fetch import FetchError
from imgflip_memes.models import ExampleCaption
from tests.test_db import make_record

PAGE = (Path(__file__).parent / "fixtures" / "meme_page_whisper.html").read_text()
EMPTY = "<html><body></body></html>"


def make_example(example_id="e1", **overrides) -> ExampleCaption:
    fields = dict(
        example_id=example_id, url=f"https://imgflip.com/i/{example_id}", title="Title",
        caption_raw="Title | a; b | image tagged in x | made w/ Imgflip meme maker",
        box_texts=("a", "b"), tags=("x",), author="Bob", author_url="https://imgflip.com/user/Bob",
        views=10, upvotes=2, comments=0,
    )
    return ExampleCaption(**{**fields, **overrides})


class FakeSite:
    def __init__(self, fail_ids=frozenset(), pages=None):
        self.requests: list[str] = []
        self.fail_ids = fail_ids
        self.pages = pages or {}

    def __call__(self, url: str) -> str:
        self.requests.append(url)
        if any(f"/meme/{i}/" in url for i in self.fail_ids):
            raise FetchError("boom")
        if "page=" in url:
            return self.pages.get(int(url.rsplit("page=", 1)[1]), EMPTY)
        return PAGE


@pytest.fixture
def db():
    with MemeDatabase(":memory:") as database:
        for i in (1, 2, 3):
            database.upsert(make_record(asset_id=i, slug=f"M{i}"))
        yield database


def count(db, sql="SELECT COUNT(*) FROM example_captions"):
    return db.connection.execute(sql).fetchone()[0]


def test_db_replaces_examples_idempotently_and_keeps_authors(db):
    db.replace_examples(1, [make_example("a"), make_example("b")])
    db.replace_examples(1, [make_example("c", author="Zed")])
    rows = db.connection.execute("SELECT example_id, author, box_texts, tags FROM example_captions").fetchall()
    assert [(r["example_id"], r["author"]) for r in rows] == [("c", "Zed")]
    assert rows[0]["box_texts"] == '["a", "b"]'


def test_examples_cascade_when_meme_deleted(db):
    db.replace_examples(1, [make_example()])
    db.connection.execute("DELETE FROM memes WHERE asset_id = 1")
    assert count(db) == 0


def test_memes_without_examples_excludes_scraped_even_if_zero_found(db):
    db.replace_examples(1, [])
    assert {t.asset_id for t in db.memes_without_examples()} == {2, 3}


def test_crawl_stores_examples_for_every_meme(db):
    stats = crawl_examples(FakeSite(), db)
    assert stats.memes == 3 and stats.examples == 42
    assert count(db) == 42
    assert count(db, "SELECT COUNT(*) FROM example_captions WHERE author IS NULL") == 0


def test_uses_numeric_id_url(db):
    site = FakeSite()
    crawl_examples(site, db)
    assert "https://imgflip.com/meme/1/M1" in site.requests


def test_resume_does_not_refetch(db):
    crawl_examples(FakeSite(), db)
    site = FakeSite()
    assert crawl_examples(site, db).memes == 0 and site.requests == []


def test_fetch_error_is_counted_and_meme_stays_pending(db):
    stats = crawl_examples(FakeSite(fail_ids=frozenset({2})), db)
    assert stats.failed == 1 and stats.memes == 2
    assert [t.asset_id for t in db.memes_without_examples()] == [2]


def test_pages_option_fetches_following_pages_and_stops_on_empty(db):
    site = FakeSite(pages={2: PAGE})
    crawl_examples(site, db, pages=3, limit=1)
    page_urls = [u for u in site.requests if "M1" in u]
    assert len(page_urls) == 3  # page 1, page 2 (full), page 3 (empty -> stop)
    assert count(db) == 14  # page 2 repeats page 1's examples; duplicates collapse


def test_limit_caps_memes_processed(db):
    assert crawl_examples(FakeSite(), db, limit=2).memes == 2


def test_repair_example_titles_strips_leaked_title_from_stored_rows(db):
    leaked = make_example(
        "leak", title="Peter parker reading a book",
        caption_raw="Peter parker reading a book  | MEANWHILE; WAYS TO DIE",
        box_texts=("Peter parker reading a book  | MEANWHILE", "WAYS TO DIE"),
    )
    clean = make_example("ok", title="T", caption_raw="a; b", box_texts=("a", "b"))
    db.replace_examples(1, [leaked, clean])
    assert db.repair_example_titles() == 1
    rows = {r["example_id"]: r for r in db.connection.execute("SELECT * FROM example_captions")}
    assert rows["leak"]["caption_raw"] == "MEANWHILE; WAYS TO DIE"
    assert rows["leak"]["box_texts"] == '["MEANWHILE", "WAYS TO DIE"]'
    assert rows["ok"]["box_texts"] == '["a", "b"]'
    assert db.repair_example_titles() == 0  # idempotent
