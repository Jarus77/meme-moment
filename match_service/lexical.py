"""Keyword (BM25) search helpers for matching a situation against community captions."""
from __future__ import annotations

import math
import re
from collections import Counter, defaultdict

import numpy as np

STOP = frozenset(
    "a an the and or of to in on at for with is are was were be been it its this that i you he she they we my your his her their our me when "
    "just so as by from but not no do does did have has had if then than too very can will would should could about into out up down over".split()
)
# "WHEN YOU ...", "Me when ...", "POV: ..." are formats, not content; keep them from deciding a match.
_OPENER = re.compile(r"^\s*(?:that (?:moment|feeling) when|me when|when you|when|pov:?|me:|how)\b[\s:,-]*", re.I)


def normalise(text: str) -> str:
    return _OPENER.sub("", text.replace(" / ", " . ")).strip().lower()


def tokens(text: str) -> list[str]:
    return [t for t in re.findall(r"[a-z0-9']+", text.lower()) if t not in STOP and len(t) > 1]


class BM25:
    def __init__(self, docs: list[list[str]], k1: float = 1.5, b: float = 0.75) -> None:
        if not docs:
            raise ValueError("BM25 needs at least one document")
        self._k1, self._b, self._n = k1, b, len(docs)
        self._lens = np.array([len(d) for d in docs], dtype=np.float32)
        self._avg = float(self._lens.mean()) or 1.0
        self._postings: dict[str, list[tuple[int, int]]] = defaultdict(list)
        for i, doc in enumerate(docs):
            for term, tf in Counter(doc).items():
                self._postings[term].append((i, tf))
        self._idf = {t: math.log(1 + (self._n - len(p) + 0.5) / (len(p) + 0.5)) for t, p in self._postings.items()}

    def scores(self, query: list[str]) -> np.ndarray:
        out = np.zeros(self._n, dtype=np.float32)
        for term in set(query):
            for i, tf in self._postings.get(term, ()):
                norm = tf + self._k1 * (1 - self._b + self._b * self._lens[i] / self._avg)
                out[i] += self._idf[term] * tf * (self._k1 + 1) / norm
        return out
