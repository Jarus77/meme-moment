"""THROWAWAY SPIKE: thin wrappers giving every model the same embed_images / embed_texts API."""
from __future__ import annotations

import os

import numpy as np
import torch
from PIL import Image

DEVICE = os.environ.get("SPIKE_DEVICE") or ("mps" if torch.backends.mps.is_available() else "cpu")
DTYPE = torch.float16 if DEVICE == "mps" else torch.float32


def _normalise(vectors: np.ndarray) -> np.ndarray:
    vectors = np.asarray(vectors, dtype=np.float32)
    return vectors / np.linalg.norm(vectors, axis=1, keepdims=True)


def _tensor(output) -> torch.Tensor:
    """transformers 5.x returns a ModelOutput (pooler_output = projected embedding); 4.x a tensor."""
    return output if isinstance(output, torch.Tensor) else output.pooler_output


def _progress(label: str, done: int, total: int) -> None:
    print(f"   {label} {min(done, total)}/{total}", flush=True)


def _batches(items, size):
    for start in range(0, len(items), size):
        yield items[start:start + size]


def _load(path) -> Image.Image:
    return Image.open(path).convert("RGB")


class SigLIP2:
    name = "siglip2"

    def __init__(self) -> None:
        from transformers import AutoModel, AutoProcessor

        model_id = "google/siglip2-so400m-patch14-384"
        self.model = AutoModel.from_pretrained(model_id, torch_dtype=DTYPE).to(DEVICE).eval()
        self.processor = AutoProcessor.from_pretrained(model_id)

    @torch.no_grad()
    def embed_images(self, paths, batch: int = 8) -> np.ndarray:
        out = []
        for chunk in _batches(list(paths), batch):
            inputs = self.processor(images=[_load(p) for p in chunk], return_tensors="pt")
            features = _tensor(self.model.get_image_features(pixel_values=inputs["pixel_values"].to(DEVICE, DTYPE)))
            out.append(features.float().cpu().numpy())
            _progress("images", len(out) * batch, len(paths))
        return _normalise(np.concatenate(out))

    @torch.no_grad()
    def embed_texts(self, texts, batch: int = 32) -> np.ndarray:
        out = []
        for chunk in _batches(list(texts), batch):
            # SigLIP was trained on lower-cased text padded to 64 tokens.
            inputs = self.processor(
                text=[t.lower() for t in chunk], padding="max_length", max_length=64,
                truncation=True, return_tensors="pt",
            )
            features = _tensor(self.model.get_text_features(input_ids=inputs["input_ids"].to(DEVICE)))
            out.append(features.float().cpu().numpy())
            if len(out) % 20 == 0:
                _progress("texts", len(out) * batch, len(texts))
        return _normalise(np.concatenate(out))


class JinaClipV2:
    name = "jina_clip_v2"

    def __init__(self) -> None:
        from transformers import AutoModel

        # NOTE: trust_remote_code runs Python shipped inside the Hugging Face repo.
        self.model = AutoModel.from_pretrained(
            "jinaai/jina-clip-v2", trust_remote_code=True, torch_dtype=DTYPE
        ).to(DEVICE).eval()

    @torch.no_grad()
    def embed_images(self, paths, batch: int = 8) -> np.ndarray:
        out = [np.asarray(self.model.encode_image([_load(p) for p in chunk]), dtype=np.float32)
               for chunk in _batches(list(paths), batch)]
        return _normalise(np.concatenate(out))

    @torch.no_grad()
    def embed_texts(self, texts, batch: int = 32) -> np.ndarray:
        out = [np.asarray(self.model.encode_text(list(chunk)), dtype=np.float32)
               for chunk in _batches(list(texts), batch)]
        return _normalise(np.concatenate(out))


MODELS = {"siglip2": SigLIP2, "jina": JinaClipV2}
