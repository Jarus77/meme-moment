"""Transport-independent request handling for the match service (see CONTRACT.md)."""
from __future__ import annotations

import hmac
import json
import logging
import math
from typing import Mapping, Protocol

import numpy as np

from .index import TemplateIndex

log = logging.getLogger(__name__)

MAX_BODY_BYTES = 64 * 1024  # a 1,152-number photo vector alone is ~25 KB of JSON
DESCRIPTION_MIN, DESCRIPTION_MAX = 3, 600
K_MIN, K_MAX, K_DEFAULT = 1, 30, 12
CAPTIONS_MIN, CAPTIONS_MAX, CAPTIONS_DEFAULT = 0, 20, 8


class Encoder(Protocol):
    ready: bool

    def encode(self, text: str) -> np.ndarray: ...


class ValidationError(ValueError):
    """Client sent something outside the contract."""


def _int_field(payload: Mapping, name: str, default: int, low: int, high: int) -> int:
    value = payload.get(name, default)
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValidationError(f"{name} must be an integer")
    if not low <= value <= high:
        raise ValidationError(f"{name} must be between {low} and {high}")
    return value


MAX_VECTOR_LENGTH = 4096


VECTOR_FIELDS = ("situation_vector", "description_vector", "photo_vector")


def _vector_field(payload: Mapping, name: str, dim: int) -> list[float] | None:
    if payload.get(name) is None:
        return None
    value = payload[name]
    if not isinstance(value, list) or not 1 <= len(value) <= MAX_VECTOR_LENGTH:
        raise ValidationError(f"{name} must be a list of numbers")
    if any(isinstance(x, bool) or not isinstance(x, (int, float)) or not math.isfinite(x) for x in value):
        raise ValidationError(f"{name} must contain only finite numbers")
    if len(value) != dim:
        raise ValidationError(f"{name} must have {dim} numbers")
    return [float(x) for x in value]


def _text_field(payload: Mapping, name: str) -> str | None:
    """Optional free-text field: absent -> None; present -> trimmed 3..600 character string."""
    if name not in payload or payload[name] is None:
        return None
    value = payload[name]
    if not isinstance(value, str):
        raise ValidationError(f"{name} must be a string")
    text = value.strip()
    if not DESCRIPTION_MIN <= len(text) <= DESCRIPTION_MAX:
        raise ValidationError(f"{name} must be {DESCRIPTION_MIN}-{DESCRIPTION_MAX} characters")
    return text


class MatchApp:
    def __init__(self, index: TemplateIndex, encoder: Encoder, key: str, model_name: str, hybrid=None) -> None:
        if not key:
            raise ValueError("a non-empty service key is required")
        self.index = index
        self.encoder = encoder
        self.hybrid = hybrid  # optional HybridSearcher; enables the "situation" input
        self._key = key
        self._model_name = model_name

    def handle(self, method: str, path: str, headers: Mapping[str, str], body: bytes) -> tuple[int, dict]:
        lowered = {k.lower(): v for k, v in headers.items()}
        if path == "/health":
            return self._health() if method == "GET" else (405, {"error": "method not allowed"})
        if path != "/match":
            return 404, {"error": "not found"}
        if method != "POST":
            return 405, {"error": "method not allowed"}
        if not hmac.compare_digest(lowered.get("x-match-key", ""), self._key):
            return 401, {"error": "missing or invalid key"}
        if len(body) > MAX_BODY_BYTES:
            return 413, {"error": "request body too large"}
        return self._match(body)

    def _health(self) -> tuple[int, dict]:
        return 200, {"ok": True, "templates": len(self.index), "model": self._model_name}

    def _match(self, body: bytes) -> tuple[int, dict]:
        try:
            payload = json.loads(body)
            if not isinstance(payload, dict):
                raise ValidationError("body must be a JSON object")
            description = _text_field(payload, "description")
            situation = _text_field(payload, "situation")
            vectors = {n: _vector_field(payload, n, self.index.dim) for n in VECTOR_FIELDS}
            vectors = {n: v for n, v in vectors.items() if v is not None}
            if description is None and situation is None and not vectors:
                raise ValidationError("description, situation or a vector is required")
            if self.encoder is None and self.hybrid is None and not vectors:
                raise ValidationError("this service needs situation_vector, description_vector or photo_vector")
            k = _int_field(payload, "k", K_DEFAULT, K_MIN, K_MAX)
            captions = _int_field(payload, "captions_per_template", CAPTIONS_DEFAULT, CAPTIONS_MIN, CAPTIONS_MAX)
        except json.JSONDecodeError:
            return 400, {"error": "body is not valid JSON"}
        except ValidationError as exc:
            return 400, {"error": str(exc)}

        if self.encoder is not None and not self.encoder.ready:
            return 503, {"error": "model is still loading"}
        try:
            if self.hybrid is not None and (situation is not None or vectors):
                result = self.hybrid.search(situation, description, k, captions, **vectors)
                return 200, {"model": self._model_name, **result}
            if vectors:  # no hybrid configured: plain picture search with the first vector we were given
                first = vectors.get("photo_vector") or vectors.get("description_vector") or vectors["situation_vector"]
                return 200, {"model": self._model_name, "matches": self.index.search(np.array(first), k, captions)}
            text = description if description is not None else situation  # no hybrid: picture search on the text
            matches = self.index.search(self.encoder.encode(text), k, captions)
        except ValueError as exc:  # our own input checks (e.g. a missing vector); messages never echo user text
            return 400, {"error": str(exc)}
        except Exception:  # never leak internals or the user's text to the client or the log
            log.exception("match failed")
            return 500, {"error": "internal error"}
        return 200, {"model": self._model_name, "matches": matches}
