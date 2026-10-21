"""Hosted deployment of the match service on Modal (serverless, scales to zero).

    modal deploy match_service/modal_app.py        # see DEPLOY.md for the one-time setup

Nothing here touches your laptop at request time: the model is baked into the image and the
template data ships with the deploy. Only .py files and match_service/data/ are uploaded;
.env and logs are never included.
"""
from __future__ import annotations

import os
from pathlib import Path

import modal

MODEL_ID = "google/siglip2-so400m-patch14-384"
DATA_DIR = Path(__file__).parent / "data"
# 0 = scale to zero (cheapest, first request after idle waits for a cold start);
# set MATCH_MIN_CONTAINERS=1 at deploy time to keep one warm during a demo (costs money while up).
MIN_CONTAINERS = int(os.environ.get("MATCH_MIN_CONTAINERS", "0"))


def download_model() -> None:
    from huggingface_hub import snapshot_download

    snapshot_download(MODEL_ID, allow_patterns=["*.json", "*.safetensors", "*.model", "*.txt", "tokenizer*"])


image = (
    modal.Image.debian_slim(python_version="3.12")
    .pip_install("torch", index_url="https://download.pytorch.org/whl/cpu")
    .pip_install("transformers==5.20.2", "numpy", "sentencepiece", "protobuf", "huggingface_hub")
    .env({"HF_HOME": "/models", "TOKENIZERS_PARALLELISM": "false"})
    .run_function(download_model)  # bake the 4.5 GB checkpoint into the image once
    .add_local_dir(DATA_DIR, remote_path="/app/data")
    .add_local_python_source("match_service")
)

app = modal.App("match-service")


@app.cls(
    image=image,
    secrets=[modal.Secret.from_name("match-service")],  # must provide MATCH_SERVICE_KEY
    cpu=2.0,
    memory=4096,
    min_containers=MIN_CONTAINERS,
    scaledown_window=300,
    timeout=120,
)
@modal.concurrent(max_inputs=4)
class Service:
    @modal.enter()
    def start(self) -> None:
        from match_service.app import MatchApp
        from match_service.asgi import make_asgi_app
        from match_service.data import load_index
        from match_service.encoder import SigLIP2TextEncoder

        encoder = SigLIP2TextEncoder(MODEL_ID)
        encoder.load()  # the container only starts taking requests once this finishes
        self._asgi = make_asgi_app(
            MatchApp(load_index(Path("/app/data")), encoder, os.environ["MATCH_SERVICE_KEY"], MODEL_ID.split("/")[-1])
        )

    @modal.asgi_app()
    def web(self):
        return self._asgi
