"""Situation search: keywords + sentence meaning + template pictures, merged by rank.

Why merge: embedding-only search over captions was dominated by the shared "WHEN YOU..." wording, while
keyword-only search misses paraphrases. Rank fusion (RRF) needs no score calibration between the two.
Upvotes act as a small tie-breaking "this landed with people" signal, never as the main evidence.
"""
from __future__ import annotations

import math
from typing import Callable, Optional

import numpy as np

from .index import TemplateIndex
from .lexical import BM25, normalise, tokens

RRF_K = 60
LEXICAL_BONUS = 0.2     # weight of normalised BM25 inside the caption-level score
VIRALITY_WEIGHT = 0.01  # score added per log(1 + upvotes)
ANALOG_COUNT = 8
WEIGHTS = {"keywords": 1.0, "meaning": 1.0, "picture": 0.5, "photo_picture": 0.75, "photo_caption": 0.4}

Embed = Callable[[str], np.ndarray]


def _unit(vector: np.ndarray) -> np.ndarray:
    vector = np.asarray(vector, dtype=np.float32)
    norm = float(np.linalg.norm(vector))
    if norm == 0.0:
        raise ValueError("embedding is all zeros")
    return vector / norm


class HybridSearcher:
    def __init__(self, index: TemplateIndex, text_embed: Optional[Embed], caption_vectors: np.ndarray,
                 picture_embed: Optional[Embed]) -> None:
        """Embedders are optional: callers may instead pass ready-made query vectors to ``search``."""
        self._index = index
        self._text_embed, self._picture_embed = text_embed, picture_embed
        self._captions: list[tuple[int, dict]] = [
            (ti, c) for ti, t in enumerate(index.templates) for c in t.get("captions", [])
        ]
        if len(caption_vectors) != len(self._captions):
            raise ValueError(f"expected {len(self._captions)} caption vectors, got {len(caption_vectors)}")
        self._cap_vectors = np.asarray(caption_vectors, dtype=np.float32)
        self._cap_template = np.array([ti for ti, _ in self._captions], dtype=int)
        self._upvotes = np.array([c.get("upvotes", 0) for _, c in self._captions], dtype=np.float32)

        docs = [tokens(normalise(" / ".join(c["box_texts"]))) for _, c in self._captions]
        names = [tokens(t["name"]) for t in index.templates]
        self._bm25 = BM25(docs + names)
        self._doc_template = np.concatenate([self._cap_template, np.arange(len(names))])

    def _best_per_template(self, values: np.ndarray, owners: np.ndarray) -> np.ndarray:
        best = np.full(len(self._index), -np.inf, dtype=np.float32)
        np.maximum.at(best, owners, values)
        return best

    def _rrf(self, rankings: list[tuple[float, np.ndarray]]) -> np.ndarray:
        fused = np.zeros(len(self._index), dtype=np.float64)
        for weight, scores in rankings:
            order = np.argsort(-scores, kind="stable")
            for rank, ti in enumerate(order, start=1):
                if np.isfinite(scores[ti]):
                    fused[ti] += weight / (RRF_K + rank)
        return np.where(self._index.searchable, fused, -np.inf)

    def _query_vector(self, text: Optional[str], vector: Optional[np.ndarray], embed: Optional[Embed], name: str) -> Optional[np.ndarray]:
        dim = self._cap_vectors.shape[1]
        if vector is not None:
            unit = _unit(vector)
            if unit.shape != (dim,):
                raise ValueError(f"{name}_vector must have {dim} dimensions")
            return unit
        if not text:
            return None
        if embed is None:
            raise ValueError(f"{name}_vector is required because this service has no embedding model")
        return _unit(embed(text))

    def search(self, situation: Optional[str], description: Optional[str], k: int, captions_per_template: int,
               photo_vector: Optional[np.ndarray] = None, situation_vector: Optional[np.ndarray] = None,
               description_vector: Optional[np.ndarray] = None) -> dict:
        """Pool candidates from every pairing: situation/photo x captions/pictures (plus the photo description)."""
        if not situation and not description and photo_vector is None and situation_vector is None and description_vector is None:
            raise ValueError("need a situation, a description or a vector")
        rankings: list[tuple[float, np.ndarray]] = []
        pool_lists: dict[str, np.ndarray] = {}  # name -> per-template scores, used to build the candidate pool
        caption_scores: Optional[np.ndarray] = None

        situation_unit = self._query_vector(situation, situation_vector, self._text_embed, "situation")
        if situation:
            doc_scores = self._bm25.scores(tokens(normalise(situation)))
            keywords = self._best_per_template(doc_scores, self._doc_template)
            rankings.append((WEIGHTS["keywords"], keywords))
            pool_lists["keywords"] = keywords
        if situation_unit is not None:
            meaning = self._cap_vectors @ situation_unit
            by_meaning = self._best_per_template(meaning, self._cap_template)
            situation_pictures = self._index.picture_scores(situation_unit)
            rankings += [(WEIGHTS["meaning"], by_meaning), (WEIGHTS["picture"], situation_pictures)]
            pool_lists.update(meaning=by_meaning, situation_picture=situation_pictures)
            lexical = np.zeros(len(self._captions), dtype=np.float32)
            if situation:
                lexical = doc_scores[: len(self._captions)]
                lexical = lexical / lexical.max() if lexical.max() > 0 else lexical
            caption_scores = meaning + LEXICAL_BONUS * lexical + VIRALITY_WEIGHT * np.log1p(self._upvotes)

        description_unit = self._query_vector(description, description_vector, self._picture_embed, "description")
        if description_unit is not None:
            description_pictures = self._index.picture_scores(description_unit)
            rankings.append((WEIGHTS["picture"], description_pictures))
            pool_lists["description_picture"] = description_pictures

        if photo_vector is not None:
            photo = _unit(photo_vector)
            if photo.shape != (self._cap_vectors.shape[1],):
                raise ValueError(f"photo_vector must have {self._cap_vectors.shape[1]} dimensions")
            photo_pictures = self._index.picture_scores(photo)
            photo_captions = self._best_per_template(self._cap_vectors @ photo, self._cap_template)
            rankings += [(WEIGHTS["photo_picture"], photo_pictures), (WEIGHTS["photo_caption"], photo_captions)]
            pool_lists.update(photo_picture=photo_pictures, photo_caption=photo_captions)

        fused = self._rrf(rankings)
        pool = self._pool(pool_lists, min(k, int(self._index.searchable.sum())))
        order = np.array(sorted(pool, key=lambda ti: -fused[ti]), dtype=int)
        ranked = self._ordered(pool_lists)
        cutoff = min(k, int(self._index.searchable.sum()))
        matches = []
        for rank, ti in enumerate(order, start=1):
            match = self._match(rank, int(ti), float(fused[ti]), captions_per_template, caption_scores)
            match["found_by"] = [name for name in self.POOL_ORDER if name in ranked and int(ti) in ranked[name][:cutoff]]
            matches.append(match)
        return {"matches": matches, "analogs": self._analogs(caption_scores), "trace": self._trace(pool_lists)}

    # Text-side and photo-side searches alternate so neither can crowd the other out of a small pool.
    POOL_ORDER = ("meaning", "photo_picture", "keywords", "photo_caption", "situation_picture", "description_picture")

    def _ordered(self, lists: dict[str, np.ndarray]) -> dict[str, list[int]]:
        """Per search: searchable templates, best first (templates with no positive evidence excluded)."""
        searchable = self._index.searchable
        return {name: [int(ti) for ti in np.argsort(-scores, kind="stable")
                       if searchable[ti] and np.isfinite(scores[ti]) and scores[ti] > 0]
                for name, scores in lists.items()}

    def _pool(self, lists: dict[str, np.ndarray], size: int) -> list[int]:
        """Union of the searches: round-robin, taking each list's best template not already chosen."""
        searchable = self._index.searchable
        ordered = {name: [int(ti) for ti in np.argsort(-scores, kind="stable") if searchable[ti] and np.isfinite(scores[ti])]
                   for name, scores in lists.items()}
        pool: list[int] = []
        cursors = {name: 0 for name in ordered}
        while len(pool) < size and any(cursors[n] < len(ordered[n]) for n in ordered):
            for name in self.POOL_ORDER:
                if name not in ordered or len(pool) >= size:
                    continue
                while cursors[name] < len(ordered[name]) and ordered[name][cursors[name]] in pool:
                    cursors[name] += 1
                if cursors[name] < len(ordered[name]):
                    pool.append(ordered[name][cursors[name]])
        return pool

    def _trace(self, lists: dict[str, np.ndarray]) -> dict[str, list[dict]]:
        """Top three templates of every search with their raw scores: shows what was matched to what."""
        return {name: [{"name": self._index.templates[ti]["name"].strip(), "score": round(float(lists[name][ti]), 4)} for ti in order[:3]]
                for name, order in self._ordered(lists).items()}

    def _match(self, rank: int, ti: int, score: float, count: int, caption_scores: Optional[np.ndarray]) -> dict:
        template = self._index.templates[ti]
        if caption_scores is None:
            captions = sorted(template.get("captions", []), key=lambda c: -c.get("upvotes", 0))
        else:
            own = [(caption_scores[ci], c) for ci, (owner, c) in enumerate(self._captions) if owner == ti]
            captions = [c for _, c in sorted(own, key=lambda pair: -pair[0])]
        return {"rank": rank, "score": round(score, 4),
                "template": {k: v for k, v in template.items() if k != "captions"},
                "example_captions": captions[:count]}

    def _analogs(self, caption_scores: Optional[np.ndarray]) -> list[dict]:
        if caption_scores is None:
            return []
        ok = self._index.searchable[self._cap_template]
        ranked = np.argsort(-np.where(ok, caption_scores, -np.inf), kind="stable")[:ANALOG_COUNT]
        analogs = []
        for ci in ranked:
            if not ok[ci]:
                continue
            ti, caption = self._captions[int(ci)]
            t = self._index.templates[ti]
            analogs.append({
                "box_texts": caption["box_texts"], "author": caption["author"], "url": caption["url"],
                "upvotes": caption.get("upvotes", 0), "score": round(float(caption_scores[ci]), 4),
                "template": {k: t[k] for k in ("asset_id", "slug", "name", "source_url", "image_url", "box_count")},
            })
        return analogs
