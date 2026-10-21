"""Vercel entrypoint for match service v2: pure vector + keyword search, no model, no network calls.

The web app turns the user's situation / photo into Gemini Embedding 2 vectors and sends them here.
"""
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from match_service.app import MatchApp  # noqa: E402
from match_service.asgi import make_asgi_app  # noqa: E402
from match_service.data import load_caption_vectors, load_index  # noqa: E402
from match_service.hybrid import HybridSearcher  # noqa: E402

_data = ROOT / "match_service" / "data"
_index = load_index(_data)
_hybrid = HybridSearcher(_index, text_embed=None, caption_vectors=load_caption_vectors(_data), picture_embed=None)
app = make_asgi_app(MatchApp(_index, None, os.environ["MATCH_SERVICE_KEY"], "gemini-embedding-2-768", hybrid=_hybrid))
