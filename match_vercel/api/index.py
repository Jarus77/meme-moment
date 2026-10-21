"""Vercel entrypoint: the match service as an ASGI app (see ../match_service/CONTRACT.md)."""
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from match_service.app import MatchApp  # noqa: E402
from match_service.asgi import make_asgi_app  # noqa: E402
from match_service.data import load_caption_vectors, load_index  # noqa: E402
from match_service.hybrid import HybridSearcher  # noqa: E402
from match_service.encoder import SigLIP2TextEncoder  # noqa: E402

encoder = SigLIP2TextEncoder(str(ROOT / "model"), dtype="float16")
if (ROOT / "model").is_dir():
    encoder.load()  # at cold start, so the first request does not pay for it twice

_data = ROOT / "match_service" / "data"
_index = load_index(_data)
_hybrid = HybridSearcher(_index, text_embed=encoder.encode, caption_vectors=load_caption_vectors(_data),
                         picture_embed=encoder.encode)
app = make_asgi_app(MatchApp(_index, encoder, os.environ["MATCH_SERVICE_KEY"], "siglip2-so400m-patch14-384", hybrid=_hybrid))
