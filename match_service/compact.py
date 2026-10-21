"""Ship the SigLIP 2 text tower as many small files (Vercel rejects any single file over 100 MB).

The 256,000-word vocabulary table is one 590 MB tensor, so it cannot be sharded the usual way.
It is stored as row chunks and read through memory-mapping (only the rows a request needs are
touched); everything else is sharded into ordinary safetensors files that transformers loads natively.
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import torch
from safetensors.torch import save_file
from torch import nn
from transformers import Siglip2TextModel

EMBED_SUFFIX = "token_embedding.weight"  # full key differs between transformers versions
INDEX_NAME = "model.safetensors.index.json"


def _nbytes(t: torch.Tensor) -> int:
    return t.numel() * t.element_size()


def export_compact(model: Siglip2TextModel, out_dir: Path, dtype: torch.dtype = torch.float16,
                   shard_bytes: int = 90 * 1024 * 1024, embed_rows: int = 32768) -> None:
    if dtype not in (torch.float16, torch.float32):
        raise ValueError("dtype must be float16 or float32 (the embedding chunks are stored as numpy arrays)")
    out = Path(out_dir)
    (out / "embed").mkdir(parents=True, exist_ok=True)
    state = {k: v.detach().to(dtype).cpu().contiguous() for k, v in model.state_dict().items()}

    embed_key = next(k for k in state if k.endswith(EMBED_SUFFIX))
    embedding = state.pop(embed_key)
    for part, start in enumerate(range(0, embedding.shape[0], embed_rows)):
        np.save(out / "embed" / f"part-{part:03d}.npy", embedding[start:start + embed_rows].numpy())
    (out / "embed" / "meta.json").write_text(json.dumps(
        {"rows": embedding.shape[0], "dim": embedding.shape[1], "part_rows": embed_rows,
         "module_path": embed_key[: -len(".weight")]}))

    budget = shard_bytes - max(4096, shard_bytes // 10)  # headroom for the safetensors header
    shards: list[dict[str, torch.Tensor]] = [{}]
    used = 0
    for name, tensor in state.items():
        if _nbytes(tensor) > budget:
            raise ValueError(f"tensor {name} ({_nbytes(tensor)} bytes) is larger than the shard budget {budget}")
        if used + _nbytes(tensor) > budget and shards[-1]:
            shards.append({})
            used = 0
        shards[-1][name] = tensor
        used += _nbytes(tensor)

    weight_map: dict[str, str] = {}
    for i, shard in enumerate(shards, start=1):
        filename = f"model-{i:05d}-of-{len(shards):05d}.safetensors"
        save_file(shard, out / filename, metadata={"format": "pt"})
        weight_map.update({name: filename for name in shard})
    (out / INDEX_NAME).write_text(json.dumps(
        {"metadata": {"total_size": sum(_nbytes(t) for t in state.values())}, "weight_map": weight_map}))
    model.config.save_pretrained(out)


class ChunkedEmbedding(nn.Module):
    """Drop-in for nn.Embedding that gathers rows from memory-mapped chunk files."""

    def __init__(self, embed_dir: Path, dtype: torch.dtype) -> None:
        super().__init__()
        meta = json.loads((Path(embed_dir) / "meta.json").read_text())
        self.rows, self.dim, self.part_rows = meta["rows"], meta["dim"], meta["part_rows"]
        self._parts = [np.load(p, mmap_mode="r") for p in sorted(Path(embed_dir).glob("part-*.npy"))]
        self._dtype = dtype

    def forward(self, input_ids: torch.Tensor) -> torch.Tensor:
        ids = input_ids.detach().cpu().numpy()
        if ids.size and (ids.min() < 0 or ids.max() >= self.rows):
            raise IndexError(f"token id out of range 0..{self.rows - 1}")
        flat = ids.reshape(-1)
        out = np.empty((flat.size, self.dim), dtype=self._parts[0].dtype)
        for i, token in enumerate(flat):
            part, row = divmod(int(token), self.part_rows)
            out[i] = self._parts[part][row]
        return torch.from_numpy(out.reshape(*ids.shape, self.dim)).to(self._dtype)


def load_compact(path: Path, dtype: torch.dtype) -> Siglip2TextModel:
    path = Path(path)
    # The vocabulary table is absent from the shards, so transformers initialises a throw-away one;
    # it is replaced straight away (transient cost, freed immediately).
    model = Siglip2TextModel.from_pretrained(path, dtype=dtype).eval()
    module_path = json.loads((path / "embed" / "meta.json").read_text())["module_path"]
    parent_path, _, attribute = module_path.rpartition(".")
    parent = model.get_submodule(parent_path) if parent_path else model
    setattr(parent, attribute, ChunkedEmbedding(path / "embed", dtype))
    return model
