"""Download template images to disk."""
from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from .fetch import FetchError

log = logging.getLogger(__name__)

_BASE36 = "0123456789abcdefghijklmnopqrstuvwxyz"
MAX_IMAGE_BYTES = 15 * 1024 * 1024


@dataclass(frozen=True)
class ImageResult:
    path: str
    kind: str  # "full" or "thumbnail"


def _base36(number: int) -> str:
    digits = ""
    while number:
        number, rem = divmod(number, 36)
        digits = _BASE36[rem] + digits
    return digits or "0"


def full_image_url(asset_id: int, file_type: str) -> str:
    """imgflip names each template file after the base-36 form of its id."""
    return f"https://i.imgflip.com/{_base36(asset_id)}.{file_type}"


class ImageDownloader:
    """Prefers the full-size image and falls back to the listing thumbnail (~250px)."""

    def __init__(
        self,
        directory: Path,
        fetch_binary: Callable[[str], tuple[bytes, str]],
        max_bytes: int = MAX_IMAGE_BYTES,
    ) -> None:
        self._dir = Path(directory)
        self._dir.mkdir(parents=True, exist_ok=True)
        self._fetch = fetch_binary
        self._max_bytes = max_bytes

    def __call__(self, asset_id: int, file_type: str, thumbnail_url: str) -> ImageResult | None:
        return self.download(asset_id, file_type, thumbnail_url)

    def download(self, asset_id: int, file_type: str, thumbnail_url: str) -> ImageResult | None:
        full_path = self._dir / f"{asset_id}.{file_type}"
        if full_path.exists():
            return ImageResult(str(full_path), "full")

        if self._try(full_image_url(asset_id, file_type), full_path):
            return ImageResult(str(full_path), "full")

        thumb_path = self._dir / f"{asset_id}.thumb.{thumbnail_url.rsplit('.', 1)[-1] or 'jpg'}"
        if thumbnail_url and (thumb_path.exists() or self._try(thumbnail_url, thumb_path)):
            return ImageResult(str(thumb_path), "thumbnail")
        log.warning("no image obtained for asset %d", asset_id)
        return None

    def _try(self, url: str, destination: Path) -> bool:
        try:
            data, content_type = self._fetch(url)
        except FetchError as exc:
            log.info("image unavailable at %s: %s", url, exc)
            return False
        if not content_type.startswith("image/") or not data or len(data) > self._max_bytes:
            log.info("rejecting %s (type %r, %d bytes)", url, content_type, len(data))
            return False
        tmp = destination.with_suffix(destination.suffix + ".part")
        tmp.write_bytes(data)
        tmp.replace(destination)
        return True
