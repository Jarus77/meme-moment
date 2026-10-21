"""python -m match_service.export_templates --db data/memes.db --out match_service/data"""
from __future__ import annotations

import argparse
from pathlib import Path

from .data import export_templates


def main() -> int:
    parser = argparse.ArgumentParser(description="Export scraped templates and captions to templates.json.")
    parser.add_argument("--db", default="data/memes.db")
    parser.add_argument("--out", default=str(Path(__file__).parent / "data"))
    args = parser.parse_args()
    summary = export_templates(Path(args.db), Path(args.out))
    print(f"wrote {summary.templates} templates and {summary.captions} captions to {summary.out_dir / 'templates.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
