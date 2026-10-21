"""Build and check a compact copy of the SigLIP 2 text tower for small serverless functions.

    python tools/compact_encoder.py build --dtype bfloat16 --out model
    python tools/compact_encoder.py check --path model --dtype bfloat16
"""
from __future__ import annotations

import argparse
import json
import resource
import sys
import time
from pathlib import Path

import numpy as np
import torch
from transformers import AutoTokenizer, Siglip2TextModel

ROOT = Path(__file__).resolve().parents[2]
MODEL_ID = "google/siglip2-so400m-patch14-384"
DTYPES = {"float32": torch.float32, "bfloat16": torch.bfloat16, "float16": torch.float16}


def build(dtype: str, out: Path) -> None:
    model = Siglip2TextModel.from_pretrained(MODEL_ID, dtype=torch.float32).eval().to(DTYPES[dtype])
    model.save_pretrained(out, safe_serialization=True)
    AutoTokenizer.from_pretrained(MODEL_ID).save_pretrained(out)
    size = sum(f.stat().st_size for f in out.iterdir())
    print(f"saved {dtype} text tower to {out}: {size / 1e9:.2f} GB")


def check(path: Path, dtype: str, n: int = 150) -> None:
    started = time.time()
    tokenizer = AutoTokenizer.from_pretrained(path)
    model = Siglip2TextModel.from_pretrained(path, dtype=DTYPES[dtype]).eval()
    print(f"load {time.time() - started:.1f}s, peak RSS after load {resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1e9:.2f} GB")

    meta = json.loads((ROOT / "spike_bakeoff/index/meta.json").read_text())
    reference = np.load(ROOT / "spike_bakeoff/index/siglip2.npz")["cap"]
    rng = np.random.default_rng(0)
    picks = rng.choice(len(meta["caption_text"]), size=n, replace=False)
    sims, took = [], []
    for i in picks:
        tokens = tokenizer([meta["caption_text"][i].lower()], padding="max_length", max_length=64,
                           truncation=True, return_tensors="pt")
        t = time.time()
        with torch.no_grad():
            vec = model(input_ids=tokens["input_ids"]).pooler_output[0].float().numpy()
        took.append(time.time() - t)
        sims.append(float(vec @ reference[i] / np.linalg.norm(vec)))
    sims = np.array(sims)
    print(f"{dtype}: cosine vs fp32 index vectors over {n} random captions: "
          f"min {sims.min():.5f}  p5 {np.percentile(sims, 5):.5f}  mean {sims.mean():.5f}")
    print(f"latency {np.mean(took) * 1000:.0f} ms/description, peak RSS {resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1e9:.2f} GB")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("build"); b.add_argument("--dtype", choices=DTYPES, default="bfloat16"); b.add_argument("--out", type=Path, required=True)
    c = sub.add_parser("check"); c.add_argument("--path", type=Path, required=True); c.add_argument("--dtype", choices=DTYPES, default="bfloat16")
    args = parser.parse_args()
    build(args.dtype, args.out) if args.cmd == "build" else check(args.path, args.dtype)
