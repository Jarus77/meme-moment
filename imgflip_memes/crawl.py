"""Walk the template listing and store each template's details."""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Callable

from .db import MemeDatabase
from .fetch import FetchError
from .images import ImageResult
from .models import ID_2026_START, SITE, ListingEntry, MemeRecord
from .parse import ParseError, parse_generator, parse_listing

log = logging.getLogger(__name__)

LISTING_URL = SITE + "/memetemplates?page={page}"
GENERATOR_URL = SITE + "/memegenerator/{slug}"
GENERATOR_ID_URL = SITE + "/memegenerator/{template_id}/{slug}"


@dataclass(frozen=True)
class CrawlStats:
    stored: int = 0
    skipped: int = 0
    failed: int = 0


ImageSink = Callable[[int, str, str], "ImageResult | None"]


def _collect_listing(
    fetch: Callable[[str], str], start_page: int, max_pages: int
) -> tuple[list[tuple[int, ListingEntry]], int]:
    """Read listing pages until one is empty. Returns (page, entry) pairs and failed page count."""
    collected: list[tuple[int, ListingEntry]] = []
    failed = 0
    for page in range(start_page, start_page + max_pages):
        try:
            entries = parse_listing(fetch(LISTING_URL.format(page=page)))
        except FetchError as exc:
            log.error("listing page %d failed: %s", page, exc)
            failed += 1
            continue
        if not entries:
            log.info("listing page %d is empty; stopping", page)
            break
        collected.extend((page, entry) for entry in entries)
    return collected, failed


def _is_2026(entry: ListingEntry) -> bool:
    return entry.template_id is not None and entry.template_id >= ID_2026_START


def _download_image(
    db: MemeDatabase, images: ImageSink | None, asset_id: int, file_type: str, thumbnail_url: str
) -> bool:
    """Download and record one image. Failures are logged by the sink, never fatal."""
    result = images(asset_id, file_type, thumbnail_url) if images else None
    if result is None:
        return False
    db.set_image(asset_id, result.path, result.kind)
    return True


def backfill_images(db: MemeDatabase, images: ImageSink) -> int:
    """Download images for stored memes that don't have one yet. Returns how many succeeded."""
    targets = db.missing_images()
    succeeded = sum(
        _download_image(db, images, t.asset_id, t.file_type, t.image_url) for t in targets
    )
    log.info("image backfill: %d of %d fetched", succeeded, len(targets))
    return succeeded


def crawl(
    fetch: Callable[[str], str],
    db: MemeDatabase,
    limit: int,
    start_page: int = 1,
    max_pages: int = 80,
    images: ImageSink | None = None,
) -> CrawlStats:
    """Fill ``db`` until it holds ``limit`` memes. Safe to re-run: stored slugs are skipped.

    The whole listing is read first so templates that look like 2026 uploads (by id) are fetched
    before older ones; older templates then fill the remainder up to ``limit``.
    """
    stored = skipped = failed = 0
    candidates, failed = _collect_listing(fetch, start_page, max_pages)
    candidates.sort(key=lambda pair: not _is_2026(pair[1]))  # stable: keeps popularity order

    for page, entry in candidates:
        if db.count() >= limit:
            break
        if db.has_slug(entry.slug):
            skipped += 1
            continue
        # Templates outside the popular set only resolve with their numeric id in the URL;
        # the slug-only form redirects to a generic page showing some other meme.
        url = (
            GENERATOR_ID_URL.format(template_id=entry.template_id, slug=entry.slug)
            if entry.template_id
            else GENERATOR_URL.format(slug=entry.slug)
        )
        try:
            detail = parse_generator(fetch(url), entry.slug, entry.template_id)
        except (FetchError, ParseError) as exc:
            log.warning("skipping %s: %s", entry.slug, exc)
            failed += 1
            continue
        db.upsert(MemeRecord.from_parts(entry, detail, listing_page=page))
        _download_image(db, images, detail.asset_id, detail.file_type, entry.image_url)
        stored += 1
        if stored % 25 == 0:
            log.info("stored %d (db total %d)", stored, db.count())

    return CrawlStats(stored=stored, skipped=skipped, failed=failed)
