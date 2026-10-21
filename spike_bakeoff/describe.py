"""THROWAWAY SPIKE: one-line scene description of a photo from Claude (cached on disk)."""
from __future__ import annotations

import base64
import io
import json
from pathlib import Path

import anthropic
from PIL import Image

CACHE = Path(__file__).parent / "index/descriptions.json"
MODEL = "claude-haiku-4-5-20251001"
PROMPT = (
    "Describe this photo in one sentence for a meme writer: the situation, the emotion, and any "
    "notable objects or layout (e.g. 'person staring at three closed doors, looking indecisive'). "
    "Describe what is visible; do not guess who anyone is."
)


def describe(photo: Path) -> str:
    cache = json.loads(CACHE.read_text()) if CACHE.exists() else {}
    if photo.name in cache:
        return cache[photo.name]
    image = Image.open(photo).convert("RGB")
    image.thumbnail((1280, 1280))
    buffer = io.BytesIO()
    image.save(buffer, "JPEG", quality=88)
    response = anthropic.Anthropic().messages.create(
        model=MODEL, max_tokens=120,
        messages=[{"role": "user", "content": [
            {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg",
                                         "data": base64.b64encode(buffer.getvalue()).decode()}},
            {"type": "text", "text": PROMPT},
        ]}],
    )
    text = response.content[0].text.strip()
    CACHE.parent.mkdir(exist_ok=True)
    CACHE.write_text(json.dumps({**cache, photo.name: text}, indent=1))
    return text
