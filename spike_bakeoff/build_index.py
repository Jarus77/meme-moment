"""THROWAWAY SPIKE: embed N templates (pictures + example captions) with each model."""
from __future__ import annotations

import argparse
import gc
import json
import sqlite3
from pathlib import Path

import numpy as np
import torch

from models import MODELS

HERE = Path(__file__).parent
ROOT = HERE.parent


def select_templates(db_path: Path, n: int):
    """Templates that have an image; those with example captions come first."""
    con = sqlite3.connect(db_path)
    con.row_factory = sqlite3.Row
    rows = con.execute(
        "SELECT m.asset_id, m.slug, m.name, m.image_path, COUNT(e.example_id) AS n_examples "
        "FROM memes m LEFT JOIN example_captions e ON e.meme_id = m.asset_id "
        "WHERE m.image_path IS NOT NULL GROUP BY m.asset_id "
        "ORDER BY (n_examples > 0) DESC, m.index_no LIMIT ?", (n,),
    ).fetchall()
    captions = []
    for idx, row in enumerate(rows):
        for ex in con.execute(
            "SELECT box_texts FROM example_captions WHERE meme_id = ? ORDER BY upvotes DESC LIMIT 20",
            (row["asset_id"],),
        ):
            text = " / ".join(json.loads(ex["box_texts"] or "[]"))
            if text:
                captions.append((idx, text))
    con.close()
    return rows, captions


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", default=str(ROOT / "data/memes.db"))
    parser.add_argument("--n", type=int, default=100)
    parser.add_argument("--models", default="siglip2,jina")
    args = parser.parse_args()

    rows, captions = select_templates(Path(args.db), args.n)
    print(f"{len(rows)} templates, {len(captions)} example captions "
          f"({sum(r['n_examples'] > 0 for r in rows)} templates have captions)")
    meta = {
        "slugs": [r["slug"] for r in rows], "names": [r["name"] for r in rows],
        "caption_template_idx": [c[0] for c in captions], "caption_text": [c[1] for c in captions],
    }
    (HERE / "index").mkdir(exist_ok=True)
    (HERE / "index/meta.json").write_text(json.dumps(meta))

    paths = [ROOT / r["image_path"] for r in rows]
    for key in args.models.split(","):
        print(f"== {key}")
        model = MODELS[key]()
        img = model.embed_images(paths)
        cap = model.embed_texts([c[1] for c in captions]) if captions else np.zeros((0, img.shape[1]), np.float32)
        np.savez(HERE / f"index/{model.name}.npz", img=img, cap=cap)
        print(f"   saved image{img.shape} caption{cap.shape}")
        del model
        gc.collect()
        if torch.backends.mps.is_available():
            torch.mps.empty_cache()


if __name__ == "__main__":
    main()
