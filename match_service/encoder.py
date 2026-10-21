"""SigLIP 2 text tower only (the picture tower is not needed at request time)."""
from __future__ import annotations

import logging
import threading
from pathlib import Path

import numpy as np

log = logging.getLogger(__name__)

MODEL_ID = "google/siglip2-so400m-patch14-384"
MAX_TOKENS = 64  # SigLIP's text tower was trained on lower-cased text padded to 64 tokens


class SigLIP2TextEncoder:
    """Loads lazily so the HTTP server can start (and answer /health) before the 1.4 GB tower is ready."""

    def __init__(self, model_id: str = MODEL_ID, dtype: str = "float32") -> None:
        """``model_id`` may be a Hugging Face id or a local folder (e.g. the compact float16 copy)."""
        self._model_id = model_id
        self._dtype = dtype
        self._model = None
        self._tokenizer = None
        self._torch = None
        self._lock = threading.Lock()
        self.ready = False

    def load(self) -> None:
        import torch
        from transformers import AutoTokenizer, Siglip2TextModel

        log.info("loading %s text tower", self._model_id)
        tokenizer = AutoTokenizer.from_pretrained(self._model_id)
        dtype = getattr(torch, self._dtype)
        if (Path(self._model_id) / "embed" / "meta.json").exists():  # compact, upload-friendly layout
            from .compact import load_compact

            model = load_compact(Path(self._model_id), dtype)
        else:
            model = Siglip2TextModel.from_pretrained(self._model_id, dtype=dtype).eval()
        self._torch, self._tokenizer, self._model = torch, tokenizer, model
        self.ready = True
        log.info("text tower ready")

    def load_in_background(self) -> threading.Thread:
        thread = threading.Thread(target=self.load, name="encoder-load", daemon=True)
        thread.start()
        return thread

    def encode(self, text: str) -> np.ndarray:
        if not self.ready:
            raise RuntimeError("encoder is not loaded yet")
        tokens = self._tokenizer(
            [text.lower()], padding="max_length", max_length=MAX_TOKENS, truncation=True, return_tensors="pt"
        )
        with self._lock, self._torch.no_grad():
            output = self._model(input_ids=tokens["input_ids"])
        vector = output.pooler_output[0].float().numpy()  # float16 weights, float32 result
        return vector / np.linalg.norm(vector)
