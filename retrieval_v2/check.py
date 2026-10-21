import json, sys
from pathlib import Path
import numpy as np
ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "retrieval_v2")]
from collections import Counter
from match_service.lexical import BM25, normalise, tokens
import embed_gemini as g
T = json.loads(open(ROOT / "match_service/data/templates.json").read())
cap = np.load(ROOT / "retrieval_v2/captions.npy").astype(np.float32); pic = np.load(ROOT / "retrieval_v2/pictures.npy").astype(np.float32)
owner = np.array([ti for ti, t in enumerate(T) for _ in t["captions"]]); texts = [" / ".join(c["box_texts"]) for t in T for c in t["captions"]]
n = len(T); counts = Counter(owner.tolist())
bm = BM25([tokens(normalise(x)) for x in texts])
rng = np.random.default_rng(0)
elig = [i for i in range(len(texts)) if counts[owner[i]] >= 2 and len(tokens(normalise(texts[i]))) >= 3]
Q = sorted(rng.choice(elig, 2500, replace=False).tolist())
def per_t(scores, q):
    s = scores.copy(); s[q] = -1e9; b = np.full(n, -1e9, np.float32); np.maximum.at(b, owner, s); return b
def rank_of(b, q): return int((b > b[owner[q]]).sum()) + 1
def rrf(*bs):
    f = np.zeros(n)
    for b in bs:
        for r, t in enumerate(np.argsort(-b, kind="stable"), 1): f[t] += 1 / (60 + r)
    return f
def report(name, rank_fn):
    r = np.array([rank_fn(q) for q in Q]); print(f"{name:34} hit@1 {np.mean(r<=1):.3f}  hit@5 {np.mean(r<=5):.3f}  hit@20 {np.mean(r<=20):.3f}  MRR {np.mean(1/r):.3f}")
report("BM25 keywords", lambda q: rank_of(per_t(bm.scores(tokens(normalise(texts[q]))), q), q))
report("Gemini Embedding 2 (captions)", lambda q: rank_of(per_t(cap @ cap[q], q), q))
report("BM25 + Gemini (rank fusion)", lambda q: rank_of(rrf(per_t(bm.scores(tokens(normalise(texts[q]))), q), per_t(cap @ cap[q], q)), q))

SIT = "When you are working in the dark for hours and your roommate turns on the bright light in the room"
v = np.array(g.call("gemini-embedding-2:embedContent", {"content": {"parts": [{"text": SIT}]}, "taskType": "RETRIEVAL_QUERY", "outputDimensionality": 768})["embedding"]["values"], np.float32); v /= np.linalg.norm(v)
print("\nPROFESSOR'S SITUATION ->")
print(" nearest real captions (Gemini embeddings, text-vs-text):")
s = cap @ v
for j in np.argsort(-s)[:7]: print(f"   {s[j]:.3f} [{T[owner[j]]['name'].strip()[:26]}] up={[c for c in T[owner[j]]['captions'] if ' / '.join(c['box_texts'])==texts[j]][0]['upvotes']:>4}  {texts[j][:80]}")
print(" nearest template pictures (text-vs-image):")
p = pic @ v
for i in np.argsort(-p)[:6]: print(f"   {p[i]:.3f} {T[i]['name'].strip()}")
