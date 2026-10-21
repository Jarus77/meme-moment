"""Leave-one-out benchmark: given one community caption's text as the 'situation', does search recover its template?

The held-out caption is removed from the index, so a hit means the situation matched how OTHER people
used that template. Compares lexical (BM25) and several embedding models.   Usage: python loo.py MODEL...
"""
from __future__ import annotations

import json
import math
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
META = json.loads((ROOT / "spike_bakeoff/index/meta.json").read_text())
TEXTS = META["caption_text"]
TEMPLATE_OF = np.array(META["caption_template_idx"])
N_TEMPLATES = len(META["slugs"])
STOP = set("a an the and or of to in on at for with is are was were be been it its this that i you he she they we my your his her their our me when "
           "just so as by from but not no do does did have has had if then than too very can will would should could about into out up down over".split())
PREFIX = re.compile(r"^\s*(when|me when|me:|pov:|pov|me|how|my|that moment when|that feeling when)\b[\s:,-]*", re.I)


def normalise(text: str) -> str:
    """Drop the 'WHEN YOU...' style opener and the ' / ' box separators so surface form does not decide the match."""
    text = text.replace(" / ", " . ")
    return PREFIX.sub("", text).strip().lower()


def tokens(text: str) -> list[str]:
    return [t for t in re.findall(r"[a-z0-9']+", text.lower()) if t not in STOP and len(t) > 1]


class BM25:
    def __init__(self, docs: list[list[str]], k1: float = 1.5, b: float = 0.75) -> None:
        self.k1, self.b = k1, b
        self.lens = np.array([len(d) for d in docs], dtype=np.float32)
        self.avg = float(self.lens.mean())
        self.post: dict[str, list[tuple[int, int]]] = defaultdict(list)
        for i, doc in enumerate(docs):
            for term, tf in Counter(doc).items():
                self.post[term].append((i, tf))
        n = len(docs)
        self.idf = {t: math.log(1 + (n - len(p) + 0.5) / (len(p) + 0.5)) for t, p in self.post.items()}
        self.n = n

    def scores(self, query: list[str]) -> np.ndarray:
        out = np.zeros(self.n, dtype=np.float32)
        for term in set(query):
            for i, tf in self.post.get(term, ()):
                out[i] += self.idf[term] * tf * (self.k1 + 1) / (tf + self.k1 * (1 - self.b + self.b * self.lens[i] / self.avg))
        return out


def template_scores(caption_scores: np.ndarray, exclude: int) -> np.ndarray:
    caption_scores = caption_scores.copy()
    caption_scores[exclude] = -1e9
    best = np.full(N_TEMPLATES, -1e9, dtype=np.float32)
    np.maximum.at(best, TEMPLATE_OF, caption_scores)
    return best


def evaluate(name: str, score_fn, queries: list[int]) -> dict:
    ranks = []
    for q in queries:
        scores = template_scores(score_fn(q), q)
        true = TEMPLATE_OF[q]
        ranks.append(int((scores > scores[true]).sum()) + 1)
    r = np.array(ranks)
    result = {"method": name, "n": len(r), "hit@1": float((r <= 1).mean()), "hit@5": float((r <= 5).mean()),
              "hit@20": float((r <= 20).mean()), "MRR": float((1 / r).mean())}
    print(f"{name:34} n={len(r)}  hit@1 {result['hit@1']:.3f}  hit@5 {result['hit@5']:.3f}  hit@20 {result['hit@20']:.3f}  MRR {result['MRR']:.3f}", flush=True)
    return result


def embed_texts(model_id: str, texts: list[str], pooling: str, prefix: str = "", batch: int = 64) -> np.ndarray:
    import torch
    from transformers import AutoModel, AutoTokenizer
    tok = AutoTokenizer.from_pretrained(model_id)
    model = AutoModel.from_pretrained(model_id).eval()
    out = []
    for i in range(0, len(texts), batch):
        enc = tok([prefix + t for t in texts[i:i + batch]], padding=True, truncation=True, max_length=64, return_tensors="pt")
        with torch.no_grad():
            hidden = model(**enc).last_hidden_state
        if pooling == "cls":
            vec = hidden[:, 0]
        else:
            mask = enc["attention_mask"].unsqueeze(-1).float()
            vec = (hidden * mask).sum(1) / mask.sum(1)
        out.append(torch.nn.functional.normalize(vec, dim=-1).numpy())
    return np.concatenate(out)


MODELS = {  # name -> (hf id, pooling, query/doc prefix)
    "minilm-l6": ("sentence-transformers/all-MiniLM-L6-v2", "mean", ""),
    "bge-small": ("BAAI/bge-small-en-v1.5", "cls", ""),
    "e5-small": ("intfloat/e5-small-v2", "mean", "query: "),
}

if __name__ == "__main__":
    rng = np.random.default_rng(0)
    counts = Counter(TEMPLATE_OF.tolist())
    eligible = [i for i in range(len(TEXTS)) if counts[TEMPLATE_OF[i]] >= 2 and len(tokens(normalise(TEXTS[i]))) >= 3]
    queries = sorted(rng.choice(eligible, size=min(2500, len(eligible)), replace=False).tolist())
    print(f"{len(TEXTS)} captions, {N_TEMPLATES} templates, {len(eligible)} eligible queries, sampling {len(queries)}; random baseline hit@20 = {20 / N_TEMPLATES:.3f}\n", flush=True)
    results = []
    norm = [normalise(t) for t in TEXTS]

    bm = BM25([tokens(t) for t in norm])
    results.append(evaluate("BM25 (normalised)", lambda q: bm.scores(tokens(norm[q])), queries))

    z = np.load(ROOT / "spike_bakeoff/index/siglip2.npz")["cap"]
    results.append(evaluate("SigLIP2 text tower (raw)", lambda q: z @ z[q], queries))

    vectors = {}
    for name in sys.argv[1:]:
        hf_id, pooling, prefix = MODELS[name]
        cache = Path(__file__).parent / f"cap_{name}.npy"
        if cache.exists():
            vectors[name] = np.load(cache)
        else:
            print(f"embedding {len(norm)} captions with {name} ...", flush=True)
            vectors[name] = embed_texts(hf_id, norm, pooling, prefix)
            np.save(cache, vectors[name].astype(np.float16))
        v = vectors[name].astype(np.float32)
        results.append(evaluate(f"{name} (normalised)", lambda q, v=v: v @ v[q], queries))

    Path(__file__).with_name("loo_results.json").write_text(json.dumps(results, indent=1))
