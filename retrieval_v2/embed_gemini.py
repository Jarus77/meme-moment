"""Embed every template picture and every example caption with Gemini Embedding 2 (768-d, one shared text/image space).

    python embed_gemini.py            # resumable; writes pictures.npy and captions.npy next to this file
Set GEMINI_API_KEY in your environment first. The key is never printed.
"""
from __future__ import annotations

import base64
import concurrent.futures as cf
import io
import json
import os
import sqlite3
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
HERE = Path(__file__).parent
DIM = 768
MODEL = "gemini-embedding-2"
BASE = "https://generativelanguage.googleapis.com/v1beta/models/"
KEY = os.environ.get("GEMINI_API_KEY") or sys.exit("Set GEMINI_API_KEY before running this script.")


def call(path: str, body: dict, tries: int = 6) -> dict:
    data = json.dumps(body).encode()
    for attempt in range(tries):
        request = urllib.request.Request(BASE + path, data=data, headers={"x-goog-api-key": KEY, "Content-Type": "application/json"})
        try:
            return json.load(urllib.request.urlopen(request, timeout=120))
        except urllib.error.HTTPError as error:
            if error.code in (429, 500, 502, 503, 504) and attempt < tries - 1:
                time.sleep(2 ** attempt)
                continue
            raise RuntimeError(f"HTTP {error.code}: {error.read().decode()[:200]}") from None
        except (urllib.error.URLError, TimeoutError):
            if attempt == tries - 1:
                raise
            time.sleep(2 ** attempt)
    raise RuntimeError("unreachable")


def unit(rows: list[list[float]]) -> np.ndarray:
    array = np.array(rows, dtype=np.float32)
    return array / np.linalg.norm(array, axis=1, keepdims=True)


def embed_texts(texts: list[str]) -> np.ndarray:
    result = call(f"{MODEL}:batchEmbedContents", {"requests": [
        {"model": f"models/{MODEL}", "content": {"parts": [{"text": t}]}, "taskType": "RETRIEVAL_DOCUMENT", "outputDimensionality": DIM}
        for t in texts]})
    return unit([e["values"] for e in result["embeddings"]])


def embed_image(path: Path) -> np.ndarray:
    image = Image.open(path).convert("RGB")
    image.thumbnail((768, 768))
    buffer = io.BytesIO()
    image.save(buffer, "JPEG", quality=85)
    result = call(f"{MODEL}:embedContent", {"content": {"parts": [{"inline_data": {"mime_type": "image/jpeg", "data": base64.b64encode(buffer.getvalue()).decode()}}]},
                                           "taskType": "RETRIEVAL_DOCUMENT", "outputDimensionality": DIM})
    return unit([result["embedding"]["values"]])[0]


def main() -> None:
    templates = json.loads((ROOT / "match_service/data/templates.json").read_text())
    con = sqlite3.connect(ROOT / "data/memes.db")
    paths = [ROOT / con.execute("SELECT image_path FROM memes WHERE asset_id=?", (t["asset_id"],)).fetchone()[0] for t in templates]

    texts = [" / ".join(c["box_texts"]) for t in templates for c in t["captions"]]
    out = HERE / "captions.npy"
    if not out.exists():
        print(f"embedding {len(texts)} captions in batches of 100 ...", flush=True)
        batches = [texts[i:i + 100] for i in range(0, len(texts), 100)]
        with cf.ThreadPoolExecutor(8) as pool:
            done = 0
            results = []
            for vectors in pool.map(embed_texts, batches):
                results.append(vectors); done += 1
                if done % 20 == 0: print(f"  caption batches {done}/{len(batches)}", flush=True)
        np.save(out, np.concatenate(results).astype(np.float16))
    print("captions done", flush=True)

    out = HERE / "pictures.npy"
    if not out.exists():
        print(f"embedding {len(paths)} template pictures ...", flush=True)
        with cf.ThreadPoolExecutor(12) as pool:
            results = []
            for i, vector in enumerate(pool.map(embed_image, paths), start=1):
                results.append(vector)
                if i % 150 == 0: print(f"  pictures {i}/{len(paths)}", flush=True)
        np.save(out, np.stack(results).astype(np.float16))
    print("pictures done", flush=True)


if __name__ == "__main__":
    main()
