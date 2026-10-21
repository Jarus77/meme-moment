"""THROWAWAY SPIKE: top-K templates per photo, per model and retrieval mode, plus hit@K if labelled."""
from __future__ import annotations

import argparse
import csv
import gc
import json
from pathlib import Path

import numpy as np
import torch

from describe import describe
from models import MODELS

HERE = Path(__file__).parent
MODES = {
    "A photo>pics": "image-to-template-picture",
    "B photo>caps": "image-to-example-captions",
    "C A+B fused": "A and B summed",
    "D desc>caps": "Claude description-to-example-captions",
    "E desc>pics": "Claude description-to-template-picture",
}


def best_caption_per_template(cap_scores: np.ndarray, cap_idx: np.ndarray, n_templates: int) -> np.ndarray:
    out = np.full(n_templates, -1.0, dtype=np.float32)  # no captions -> sinks to the bottom
    np.maximum.at(out, cap_idx, cap_scores)
    return out


def scores_for(modes_in: dict, img_q: np.ndarray, desc_q: np.ndarray | None, index, cap_idx, n) -> dict:
    a = index["img"] @ img_q
    out = {"A photo>pics": a}
    if len(cap_idx):
        b = best_caption_per_template(index["cap"] @ img_q, cap_idx, n)
        out["B photo>caps"] = b
        out["C A+B fused"] = a + b
        if desc_q is not None:
            out["D desc>caps"] = best_caption_per_template(index["cap"] @ desc_q, cap_idx, n)
    if desc_q is not None:
        out["E desc>pics"] = index["img"] @ desc_q
    return out


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--photos", default=str(HERE / "photos"))
    parser.add_argument("--models", default="siglip2,jina")
    parser.add_argument("--k", type=int, default=3)
    parser.add_argument("--watch", default="", help="slug whose rank to report in every mode")
    parser.add_argument("--no-describe", action="store_true", help="skip Claude (modes D/E)")
    args = parser.parse_args()

    meta = json.loads((HERE / "index/meta.json").read_text())
    slugs, names = meta["slugs"], meta["names"]
    cap_idx = np.array(meta["caption_template_idx"], dtype=int)
    photos = sorted(p for p in Path(args.photos).iterdir() if p.suffix.lower() in {".jpg", ".jpeg", ".png", ".webp"})
    labels_file = Path(args.photos) / "labels.csv"
    labels = {}
    if labels_file.exists():
        with open(labels_file, newline="") as handle:
            labels = {r["photo"]: set(r["acceptable_slugs"].split("|")) for r in csv.DictReader(handle)}
    descriptions = {} if args.no_describe else {p.name: describe(p) for p in photos}
    for p in photos:
        if p.name in descriptions:
            print(f"[{p.name}] Claude sees: {descriptions[p.name]}")

    hits: dict[tuple[str, str], list[int]] = {}
    for key in args.models.split(","):
        model = MODELS[key]()
        index = np.load(HERE / f"index/{model.name}.npz")
        img_qs = model.embed_images(photos)
        desc_qs = model.embed_texts([descriptions[p.name] for p in photos]) if descriptions else None
        print(f"\n===== {model.name} =====")
        for i, photo in enumerate(photos):
            all_scores = scores_for(MODES, img_qs[i], None if desc_qs is None else desc_qs[i], index, cap_idx, len(slugs))
            print(f"\n{photo.name}")
            for mode, scores in all_scores.items():
                order = np.argsort(-scores)[:args.k]
                shown = ", ".join(f"{names[j]} ({scores[j]:.2f})" for j in order)
                print(f"  {mode:13} {shown}")
                if args.watch and args.watch in slugs:
                    rank = int((scores > scores[slugs.index(args.watch)]).sum()) + 1
                    print(f"  {'':13} -> {args.watch} rank {rank}/{len(slugs)}; score range: "
                          f"median {np.median(scores):.2f}, 95th pct {np.percentile(scores, 95):.2f}, max {scores.max():.2f}")
                if photo.name in labels:
                    rank = next((r for r, j in enumerate(np.argsort(-scores)) if slugs[j] in labels[photo.name]), 10**6)
                    hits.setdefault((model.name, mode), []).append(rank)
        del model
        gc.collect()
        if torch.backends.mps.is_available():
            torch.mps.empty_cache()

    if hits:
        print("\n===== hit rate (labelled photos) =====")
        print(f"{'model':14}{'mode':14}{'hit@1':>7}{'hit@3':>7}{'hit@5':>7}   n")
        for (model_name, mode), ranks in sorted(hits.items()):
            rate = lambda k: sum(r < k for r in ranks) / len(ranks)
            print(f"{model_name:14}{mode:14}{rate(1):7.0%}{rate(3):7.0%}{rate(5):7.0%}   {len(ranks)}")


if __name__ == "__main__":
    main()
