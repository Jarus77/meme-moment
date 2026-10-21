"""Needs torch + transformers (run with spike_bakeoff/.venv); skipped elsewhere."""
import json

import numpy as np
import pytest

torch = pytest.importorskip("torch")
pytest.importorskip("transformers")
from transformers import Siglip2TextConfig, Siglip2TextModel  # noqa: E402

from match_service.compact import ChunkedEmbedding, export_compact, load_compact  # noqa: E402

SHARD_BYTES = 40_000


@pytest.fixture(scope="module")
def reference():
    torch.manual_seed(0)
    config = Siglip2TextConfig(vocab_size=300, hidden_size=32, intermediate_size=64, num_hidden_layers=2,
                               num_attention_heads=4, max_position_embeddings=16)
    return Siglip2TextModel(config).eval()


@pytest.fixture
def compact_dir(reference, tmp_path):
    export_compact(reference, tmp_path, dtype=torch.float32, shard_bytes=SHARD_BYTES, embed_rows=64)
    return tmp_path


def embed(model, ids):
    with torch.no_grad():
        return model(input_ids=torch.tensor([ids])).pooler_output[0]


def test_every_exported_file_is_under_the_upload_limit(compact_dir):
    sizes = [f.stat().st_size for f in compact_dir.rglob("*") if f.is_file() and f.suffix in {".safetensors", ".npy"}]
    assert sizes and max(sizes) <= SHARD_BYTES
    assert len([f for f in compact_dir.glob("*.safetensors")]) > 1  # really sharded


def test_embedding_table_is_not_in_the_sharded_weights_but_split_into_chunks(compact_dir):
    index = json.loads((compact_dir / "model.safetensors.index.json").read_text())
    assert not any("token_embedding" in key for key in index["weight_map"])
    assert len(list((compact_dir / "embed").glob("part-*.npy"))) == 5  # 300 rows / 64 per chunk


def test_loaded_model_reproduces_the_original_output_exactly(reference, compact_dir):
    loaded = load_compact(compact_dir, torch.float32)
    ids = [5, 63, 64, 65, 127, 128, 299, 0, 7, 7, 1, 2, 3, 4, 9, 10]  # crosses every chunk boundary
    assert torch.allclose(embed(reference, ids), embed(loaded, ids), atol=1e-6)


def test_loaded_model_uses_the_chunked_embedding(compact_dir):
    assert isinstance(load_compact(compact_dir, torch.float32).get_submodule("embeddings.token_embedding"), ChunkedEmbedding)


def test_float16_export_stays_close_to_full_precision(reference, tmp_path):
    export_compact(reference, tmp_path, dtype=torch.float16, shard_bytes=SHARD_BYTES, embed_rows=64)
    loaded = load_compact(tmp_path, torch.float16)
    ids = list(range(16))
    a, b = embed(reference, ids), embed(loaded, ids).float()
    assert torch.nn.functional.cosine_similarity(a, b, dim=0) > 0.999


def test_chunked_embedding_handles_batches_and_validates_ids(compact_dir):
    emb = ChunkedEmbedding(compact_dir / "embed", torch.float32)
    assert emb(torch.tensor([[1, 2, 3], [250, 251, 252]])).shape == (2, 3, 32)
    with pytest.raises(IndexError):
        emb(torch.tensor([[300]]))


def test_tensor_larger_than_shard_limit_is_an_error(reference, tmp_path):
    with pytest.raises(ValueError, match="larger than"):
        export_compact(reference, tmp_path, dtype=torch.float32, shard_bytes=500, embed_rows=64)
