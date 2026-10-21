"""In-memory cosine-similarity search over precomputed template picture vectors."""
from __future__ import annotations

from typing import Sequence

import numpy as np


class TemplateIndex:
    def __init__(self, vectors: np.ndarray, templates: Sequence[dict]) -> None:
        vectors = np.asarray(vectors, dtype=np.float32)
        if vectors.ndim != 2 or len(vectors) != len(templates):
            raise ValueError(f"need one vector per template, got {vectors.shape} for {len(templates)} templates")
        norms = np.linalg.norm(vectors, axis=1, keepdims=True)
        norms[norms == 0] = 1.0
        self._vectors = vectors / norms
        self._templates = tuple(templates)
        self._searchable = np.array([bool(t.get("safe_for_work", True)) for t in templates])

    def __len__(self) -> int:
        return len(self._templates)

    @property
    def dim(self) -> int:
        return self._vectors.shape[1]

    @property
    def templates(self) -> tuple[dict, ...]:
        return self._templates

    @property
    def searchable(self) -> np.ndarray:
        return self._searchable

    def picture_scores(self, query: np.ndarray) -> np.ndarray:
        """Cosine similarity of ``query`` to every template picture; -inf for templates we never return."""
        query = np.asarray(query, dtype=np.float32)
        if query.shape != (self.dim,):
            raise ValueError(f"query must have {self.dim} dimensions, got shape {query.shape}")
        norm = float(np.linalg.norm(query))
        if norm == 0.0:
            raise ValueError("query vector is all zeros")
        return np.where(self._searchable, self._vectors @ (query / norm), -np.inf)

    def search(self, query: np.ndarray, k: int, captions_per_template: int) -> list[dict]:
        scores = self.picture_scores(query)
        limit = min(k, int(self._searchable.sum()))
        order = np.argsort(-scores)[:limit]
        return [self._result(rank, int(i), float(scores[i]), captions_per_template)
                for rank, i in enumerate(order, start=1)]

    def _result(self, rank: int, i: int, score: float, captions_per_template: int) -> dict:
        template = self._templates[i]
        captions = sorted(template.get("captions", []), key=lambda c: -c.get("upvotes", 0))
        return {
            "rank": rank,
            "score": round(score, 4),
            "template": {k: v for k, v in template.items() if k != "captions"},
            "example_captions": captions[:captions_per_template],
        }
