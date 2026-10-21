import zlib
from pathlib import Path

import pytest

from imgflip_memes.crawl import backfill_images, crawl
from imgflip_memes.db import MemeDatabase
from imgflip_memes.fetch import FetchError
from imgflip_memes.images import ImageResult

FIXTURES = Path(__file__).parent / "fixtures"
LISTING = (FIXTURES / "listing_page2.html").read_text()
GENERATOR = (FIXTURES / "generator_drake.html").read_text()
EMPTY = "<html><body></body></html>"


def listing_html(entries: list[tuple[int | None, str]]) -> str:
    cards = "".join(
        f'<div class="mt-box"><h3 class="mt-title"><a href="/meme/{(str(i) + "/") if i else ""}{slug}">{slug}</a></h3>'
        f'<div class="mt-img-wrap"><a href="/meme/{slug}"><img src="//i.imgflip.com/4/{slug}.jpg"/></a></div></div>'
        for i, slug in entries
    )
    return f"<html><body>{cards}</body></html>"


class FakeImages:
    def __init__(self, succeed: bool = True):
        self.succeed = succeed
        self.calls: list[tuple[int, str, str]] = []

    def __call__(self, asset_id: int, file_type: str, thumbnail_url: str):
        self.calls.append((asset_id, file_type, thumbnail_url))
        return ImageResult(f"imgs/{asset_id}.{file_type}", "full") if self.succeed else None


class FakeSite:
    """Serves the listing fixture on page 1 and a generator page for any slug."""

    def __init__(
        self,
        fail_slugs: frozenset[str] = frozenset(),
        unparseable: frozenset[str] = frozenset(),
        generic_page: frozenset[str] = frozenset(),
        listing: str = LISTING,
    ):
        self.listing = listing
        self.requests: list[str] = []
        self.fail_slugs = fail_slugs
        self.unparseable = unparseable
        self.generic_page = generic_page

    def __call__(self, url: str) -> str:
        self.requests.append(url)
        if "memetemplates" in url:
            return self.listing if "page=1" in url else EMPTY
        slug = url.rsplit("/", 1)[-1]
        if slug in self.fail_slugs:
            raise FetchError(f"boom {slug}")
        if slug in self.unparseable:
            return "<html>no data</html>"
        if slug in self.generic_page:
            return GENERATOR  # what imgflip serves after redirecting an unknown slug
        # Serve the Drake page, re-labelled with a unique id and the requested slug.
        page = GENERATOR.replace('"id":181913649,', f'"id":{zlib.crc32(slug.encode())},', 1)
        return page.replace('"url_name":"Drake-Hotline-Bling"', f'"url_name":"{slug}"', 1)


@pytest.fixture
def db():
    with MemeDatabase(":memory:") as database:
        yield database


def generator_requests(site: FakeSite) -> list[str]:
    return [u for u in site.requests if "memegenerator" in u]


def test_crawl_stores_every_template_on_page(db):
    stats = crawl(FakeSite(), db, limit=100)
    assert stats.stored == 40
    assert db.count() == 40


def test_limit_caps_stored_templates(db):
    stats = crawl(FakeSite(), db, limit=5)
    assert stats.stored == 5
    assert db.count() == 5


def test_crawl_stops_on_empty_listing_page(db):
    site = FakeSite()
    crawl(site, db, limit=1000)
    listing_calls = [u for u in site.requests if "memetemplates" in u]
    assert len(listing_calls) == 2  # page 1 full, page 2 empty -> stop


def test_resume_skips_templates_already_stored(db):
    crawl(FakeSite(), db, limit=10)
    site = FakeSite()
    stats = crawl(site, db, limit=100)
    assert stats.skipped == 10
    assert stats.stored == 30
    assert len(generator_requests(site)) == 30


def test_fetch_error_is_counted_and_crawl_continues(db):
    first_slug = "Whisper-and-Goosebumps"
    stats = crawl(FakeSite(fail_slugs=frozenset({first_slug})), db, limit=100)
    assert stats.failed == 1
    assert stats.stored == 39
    assert not db.has_slug(first_slug)


def test_parse_error_is_counted_and_crawl_continues(db):
    stats = crawl(FakeSite(unparseable=frozenset({"Whisper-and-Goosebumps"})), db, limit=100)
    assert stats.failed == 1
    assert stats.stored == 39


def test_generator_url_uses_numeric_id_when_listing_link_has_one(db):
    site = FakeSite()
    crawl(site, db, limit=100)
    urls = generator_requests(site)
    assert "https://imgflip.com/memegenerator/101956210/Whisper-and-Goosebumps" in urls
    assert "https://imgflip.com/memegenerator/Whisper-and-Goosebumps" not in urls


def test_redirected_generic_page_is_not_stored_under_wrong_slug(db):
    stats = crawl(FakeSite(generic_page=frozenset({"Whisper-and-Goosebumps"})), db, limit=100)
    assert stats.failed == 1
    assert not db.has_slug("Whisper-and-Goosebumps")


def test_templates_with_2026_ids_are_crawled_before_older_ones(db):
    listing = listing_html([(None, "Classic"), (100, "Old"), (700_000_000, "Fresh")])
    crawl(FakeSite(listing=listing), db, limit=1)
    assert db.has_slug("Fresh") and db.count() == 1


def test_older_templates_fill_the_remainder_after_2026_ones(db):
    listing = listing_html([(None, "Classic"), (100, "Old"), (700_000_000, "Fresh")])
    crawl(FakeSite(listing=listing), db, limit=10)
    assert db.count() == 3


def test_image_downloaded_for_each_stored_meme(db):
    images = FakeImages()
    crawl(FakeSite(), db, limit=3, images=images)
    assert len(images.calls) == 3
    assert db.missing_images() == []
    assert all(a[2].startswith("https://i.imgflip.com/") for a in images.calls)


def test_image_failure_does_not_fail_the_crawl(db):
    stats = crawl(FakeSite(), db, limit=3, images=FakeImages(succeed=False))
    assert stats.stored == 3 and stats.failed == 0
    assert len(db.missing_images()) == 3


def test_backfill_images_fills_rows_without_one(db):
    crawl(FakeSite(), db, limit=3)
    assert len(db.missing_images()) == 3
    assert backfill_images(db, FakeImages()) == 3
    assert db.missing_images() == []
