"""Copy what the Vercel function needs into this folder (run before `vercel deploy`).

    python tools/make_bundle.py            # code + data only (no model)
    python tools/make_bundle.py --model /tmp/enc_float16   # also include the compact text tower
"""
from __future__ import annotations

import argparse
import shutil
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]
SRC = HERE.parent / "match_service"
RUNTIME_MODULES = ("__init__.py", "app.py", "asgi.py", "compact.py", "data.py", "encoder.py", "hybrid.py", "index.py", "lexical.py")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", type=Path, help="folder with the compact text tower to ship")
    args = parser.parse_args()

    target = HERE / "match_service"
    shutil.rmtree(target, ignore_errors=True)
    target.mkdir()
    for name in RUNTIME_MODULES:
        shutil.copy2(SRC / name, target / name)
    shutil.copytree(SRC / "data", target / "data")

    model_dir = HERE / "model"
    shutil.rmtree(model_dir, ignore_errors=True)
    if args.model:
        shutil.copytree(args.model, model_dir)
    leaked = [p for p in HERE.rglob(".env*") if ".venv" not in p.parts]
    assert not leaked, f"refusing to bundle secrets: {leaked}"
    size = sum(f.stat().st_size for f in HERE.rglob("*") if f.is_file() and "tools" not in f.parts)
    print(f"bundle ready: {size / 1e6:.1f} MB (model {'included' if args.model else 'NOT included'})")


if __name__ == "__main__":
    main()
