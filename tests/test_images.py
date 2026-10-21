from pathlib import Path

import pytest

from imgflip_memes.fetch import FetchError
from imgflip_memes.images import ImageDownloader, ImageResult, full_image_url

JPEG = b"\xff\xd8\xff\xe0fakejpegbytes"
THUMB = "https://i.imgflip.com/4/30b1gx.jpg"


class FakeBinary:
    """Maps url -> (bytes, content_type) | Exception."""

    def __init__(self, responses: dict):
        self.responses = responses
        self.calls: list[str] = []

    def __call__(self, url: str):
        self.calls.append(url)
        result = self.responses.get(url, FetchError("HTTP 404"))
        if isinstance(result, Exception):
            raise result
        return result


def downloader(tmp_path: Path, responses: dict, **kwargs):
    fake = FakeBinary(responses)
    return ImageDownloader(tmp_path, fake, **kwargs), fake


def test_full_image_url_is_base36_of_asset_id():
    assert full_image_url(181913649, "jpg") == "https://i.imgflip.com/30b1gx.jpg"
    assert full_image_url(322841258, "png") == "https://i.imgflip.com/5c7lwq.png"


def test_downloads_full_size_image(tmp_path):
    dl, fake = downloader(tmp_path, {"https://i.imgflip.com/30b1gx.jpg": (JPEG, "image/jpeg")})
    result = dl.download(181913649, "jpg", THUMB)
    assert result == ImageResult(path=str(tmp_path / "181913649.jpg"), kind="full")
    assert Path(result.path).read_bytes() == JPEG
    assert fake.calls == ["https://i.imgflip.com/30b1gx.jpg"]


def test_falls_back_to_thumbnail_when_full_size_missing(tmp_path):
    dl, _ = downloader(tmp_path, {THUMB: (JPEG, "image/jpeg")})
    result = dl.download(181913649, "jpg", THUMB)
    assert result.kind == "thumbnail"
    assert Path(result.path).exists()


def test_returns_none_when_everything_fails(tmp_path):
    dl, _ = downloader(tmp_path, {})
    assert dl.download(181913649, "jpg", THUMB) is None
    assert list(tmp_path.iterdir()) == []


def test_non_image_content_type_is_rejected(tmp_path):
    dl, _ = downloader(
        tmp_path,
        {"https://i.imgflip.com/30b1gx.jpg": (b"<html>", "text/html"), THUMB: (JPEG, "image/jpeg")},
    )
    assert dl.download(181913649, "jpg", THUMB).kind == "thumbnail"


def test_oversized_image_is_rejected(tmp_path):
    big = b"x" * 101
    dl, _ = downloader(
        tmp_path, {"https://i.imgflip.com/30b1gx.jpg": (big, "image/jpeg")}, max_bytes=100
    )
    assert dl.download(181913649, "jpg", "") is None


def test_existing_full_file_is_reused_without_a_request(tmp_path):
    (tmp_path / "181913649.jpg").write_bytes(JPEG)
    dl, fake = downloader(tmp_path, {})
    result = dl.download(181913649, "jpg", THUMB)
    assert result.kind == "full" and fake.calls == []
