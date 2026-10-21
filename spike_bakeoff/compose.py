"""THROWAWAY SPIKE: lay classic meme text (Impact, white with black outline) over a photo."""
from __future__ import annotations

import argparse
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

FONT = "/System/Library/Fonts/Supplemental/Impact.ttf"


def wrap_to_fit(draw, text, max_width, start_size, max_lines=3):
    """Largest font size (shrinking from start_size) at which text wraps into <= max_lines lines."""
    for size in range(start_size, 14, -2):
        font = ImageFont.truetype(FONT, size)
        lines, line = [], ""
        for word in text.upper().split():
            trial = f"{line} {word}".strip()
            if draw.textlength(trial, font=font) <= max_width:
                line = trial
            else:
                lines.append(line)
                line = word
        lines.append(line)
        if len(lines) <= max_lines and all(draw.textlength(l, font=font) <= max_width for l in lines):
            return font, lines
    raise ValueError(f"cannot fit: {text!r}")


def draw_block(draw, img_w, img_h, text, position):
    font, lines = wrap_to_fit(draw, text, img_w * 0.92, int(img_h * 0.058), max_lines=2)
    line_h = font.size * 1.08
    total = line_h * len(lines)
    y = img_h * 0.03 if position == "top" else img_h - total - img_h * 0.035
    for line in lines:
        x = (img_w - draw.textlength(line, font=font)) / 2
        draw.text((x, y), line, font=font, fill="white", stroke_width=max(2, font.size // 14), stroke_fill="black")
        y += line_h


def compose(photo: Path, top: str, bottom: str, out: Path) -> Path:
    image = Image.open(photo).convert("RGB")
    draw = ImageDraw.Draw(image)
    draw_block(draw, image.width, image.height, top, "top")
    draw_block(draw, image.width, image.height, bottom, "bottom")
    out.parent.mkdir(parents=True, exist_ok=True)
    image.save(out)
    return out


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("photo")
    parser.add_argument("--top", required=True)
    parser.add_argument("--bottom", required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()
    print(compose(Path(args.photo), args.top, args.bottom, Path(args.out)))
