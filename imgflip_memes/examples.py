"""Second pass: collect community example captions from each template's page."""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Callable

from .db import MemeDatabase
from .fetch import FetchError
from .models import SITE, ExampleCaption
from .parse import parse_examples

log = logging.getLogger(__name__)

MEME_PAGE_URL = SITE + "/meme/{asset_id}/{slug}"


@dataclass(frozen=True)
class ExampleStats:
    memes: int = 0
    examples: int = 0
    failed: int = 0


def _fetch_examples(
    fetch: Callable[[str], str], asset_id: int, slug: str, pages: int
) -> tuple[ExampleCaption, ...]:
    base = MEME_PAGE_URL.format(asset_id=asset_id, slug=slug)
    collected: list[ExampleCaption] = []
    for page in range(1, pages + 1):
        found = parse_examples(fetch(base if page == 1 else f"{base}?page={page}"))
        if not found:
            break
        collected.extend(found)
    return tuple(collected)


def crawl_examples(
    fetch: Callable[[str], str],
    db: MemeDatabase,
    pages: int = 1,
    limit: int | None = None,
) -> ExampleStats:
    """Fetch example captions for memes not yet processed. Safe to re-run."""
    memes = examples = failed = 0
    for target in db.memes_without_examples():
        if limit is not None and memes >= limit:
            break
        try:
            found = _fetch_examples(fetch, target.asset_id, target.slug, pages)
        except FetchError as exc:
            log.warning("examples for %s failed: %s", target.slug, exc)
            failed += 1
            continue
        db.replace_examples(target.asset_id, found)
        memes += 1
        examples += len(found)
        if memes % 25 == 0:
            log.info("examples: %d memes done, %d captions", memes, examples)
    return ExampleStats(memes=memes, examples=examples, failed=failed)
