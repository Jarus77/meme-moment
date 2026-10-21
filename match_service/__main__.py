"""Run the service:  MATCH_SERVICE_KEY=... python -m match_service"""
from __future__ import annotations

import logging
import os
import sys
from pathlib import Path

from .app import MatchApp
from .data import load_caption_vectors, load_index
from .encoder import MODEL_ID, SigLIP2TextEncoder
from .hybrid import HybridSearcher
from .server import make_server


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    key = os.environ.get("MATCH_SERVICE_KEY", "")
    if not key:
        print("MATCH_SERVICE_KEY is required (a shared secret the web app sends in X-Match-Key).", file=sys.stderr)
        return 2
    data_dir = Path(os.environ.get("MATCH_DATA_DIR", Path(__file__).parent / "data"))
    host = os.environ.get("MATCH_HOST", "127.0.0.1")
    port = int(os.environ.get("MATCH_PORT", "8808"))

    index = load_index(data_dir)
    encoder = SigLIP2TextEncoder()
    encoder.load_in_background()
    hybrid = HybridSearcher(index, text_embed=encoder.encode, caption_vectors=load_caption_vectors(data_dir),
                            picture_embed=encoder.encode)
    server = make_server(MatchApp(index, encoder, key, MODEL_ID.split("/")[-1], hybrid=hybrid), host, port)
    logging.info("match service on http://%s:%d (%d templates); model loading in background", host, port, len(index))
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
