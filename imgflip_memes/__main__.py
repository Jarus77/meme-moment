"""CLI: python -m imgflip_memes --limit 1500"""
from __future__ import annotations

import argparse
import logging
from pathlib import Path

from .crawl import backfill_images, crawl
from .db import MemeDatabase
from .examples import crawl_examples
from .fetch import PoliteFetcher
from .images import ImageDownloader


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Build a SQLite database of imgflip meme templates.")
    parser.add_argument("--db", default="data/memes.db", help="SQLite file (default: %(default)s)")
    parser.add_argument("--cache", default="data/cache", help="raw HTML cache dir (default: %(default)s)")
    parser.add_argument("--images", default="data/images", help="image output dir (default: %(default)s)")
    parser.add_argument("--no-images", action="store_true", help="skip downloading images")
    parser.add_argument("--repair-examples", action="store_true", help="fix stored example captions and exit")
    parser.add_argument("--no-examples", action="store_true", help="skip example captions")
    parser.add_argument("--examples-only", action="store_true", help="only run the example-caption pass")
    parser.add_argument("--example-pages", type=int, default=1, help="pages of examples per template (~14 each)")
    parser.add_argument("--limit", type=int, default=1500, help="target number of memes in the DB")
    parser.add_argument("--delay", type=float, default=1.5, help="seconds between live requests")
    parser.add_argument("--start-page", type=int, default=1)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    Path(args.db).parent.mkdir(parents=True, exist_ok=True)

    fetcher = PoliteFetcher(cache_dir=Path(args.cache), delay=args.delay)
    images = None if args.no_images else ImageDownloader(Path(args.images), fetcher.get_binary)
    with MemeDatabase(args.db) as db:
        if args.repair_examples:
            logging.info("repaired %d example captions", db.repair_example_titles())
            return 0
        if not args.examples_only:
            stats = crawl(fetcher.get, db, limit=args.limit, start_page=args.start_page, images=images)
            if images:
                backfill_images(db, images)  # catches rows stored before images were enabled
            logging.info("templates done: %s; db now holds %d memes", stats, db.count())
        if not args.no_examples:
            logging.info("examples done: %s", crawl_examples(fetcher.get, db, pages=args.example_pages))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
