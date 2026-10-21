"""Align the SigLIP caption vectors (spike_bakeoff index) with the exported templates.json caption order.

    python -m match_service.tools_build_caption_vectors
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
DATA = Path(__file__).parent / "data"


def build(index_dir: Path = ROOT / "spike_bakeoff/index", data_dir: Path = DATA) -> tuple[int, int]:
    meta = json.loads((index_dir / "meta.json").read_text())
    vectors = np.load(index_dir / "siglip2.npz")["cap"]
    pool: dict[tuple[int, str], list[int]] = {}
    for row, (template, text) in enumerate(zip(meta["caption_template_idx"], meta["caption_text"])):
        pool.setdefault((template, text), []).append(row)

    templates = json.loads((data_dir / "templates.json").read_text())
    aligned, missing = [], 0
    for ti, template in enumerate(templates):
        for caption in template["captions"]:
            rows = pool.get((ti, " / ".join(caption["box_texts"])))
            if rows:
                aligned.append(vectors[rows[0]])
            else:
                missing += 1
                aligned.append(np.zeros(vectors.shape[1], dtype=np.float32))
    np.save(data_dir / "caption_vectors.npy", np.stack(aligned).astype(np.float16))
    return len(aligned), missing


if __name__ == "__main__":
    total, missing = build()
    print(f"aligned {total} caption vectors, {missing} without a match")
