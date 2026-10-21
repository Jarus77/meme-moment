"""Assemble the v2 function: runtime modules + templates + Gemini-embedding vectors (768-d)."""
import shutil
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]
ROOT = HERE.parent
MODULES = ("__init__.py", "app.py", "asgi.py", "data.py", "hybrid.py", "index.py", "lexical.py")

target = HERE / "match_service"
shutil.rmtree(target, ignore_errors=True)
(target / "data").mkdir(parents=True)
for name in MODULES:
    shutil.copy2(ROOT / "match_service" / name, target / name)
shutil.copy2(ROOT / "match_service/data/templates.json", target / "data/templates.json")
shutil.copy2(ROOT / "retrieval_v2/pictures.npy", target / "data/vectors.npy")
shutil.copy2(ROOT / "retrieval_v2/captions.npy", target / "data/caption_vectors.npy")
assert not [p for p in HERE.rglob(".env*") if ".vercel" not in p.parts], "refusing to bundle secrets"
size = sum(f.stat().st_size for f in target.rglob("*") if f.is_file())
print(f"v2 bundle ready: {size / 1e6:.1f} MB; largest file {max(f.stat().st_size for f in target.rglob('*') if f.is_file()) / 1e6:.1f} MB")
