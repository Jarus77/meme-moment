"""Polite HTTP fetching: robots rules, disk cache, fixed delay, bounded retries."""
from __future__ import annotations

import hashlib
import logging
import time
from pathlib import Path
from typing import Callable
from urllib.parse import urlparse

import requests

log = logging.getLogger(__name__)

USER_AGENT = "meme-template-research/0.1 (educational dataset; polite crawler, ~1 req/1.5s)"
# Mirrors https://imgflip.com/robots.txt (user-agent: *) as read on 2026-10-20.
DISALLOWED_PREFIXES = ("/orig/", "/browse/")
RETRYABLE = frozenset({429, 500, 502, 503, 504})


class FetchError(RuntimeError):
    """A page could not be retrieved."""


def is_allowed(url: str) -> bool:
    return not urlparse(url).path.startswith(DISALLOWED_PREFIXES)


class PoliteFetcher:
    def __init__(
        self,
        cache_dir: Path,
        delay: float = 1.5,
        max_retries: int = 4,
        timeout: float = 20.0,
        session: requests.Session | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self._cache_dir = Path(cache_dir)
        self._cache_dir.mkdir(parents=True, exist_ok=True)
        self._delay = delay
        self._max_retries = max_retries
        self._timeout = timeout
        self._sleep = sleep
        self._session = session or requests.Session()
        self._session.headers.update({"User-Agent": USER_AGENT})

    def _cache_path(self, url: str) -> Path:
        return self._cache_dir / f"{hashlib.sha256(url.encode()).hexdigest()[:32]}.html"

    def get(self, url: str) -> str:
        cached = self._cache_path(url)
        if is_allowed(url) and cached.exists():
            return cached.read_text()
        return self._store(cached, self._request(url).text)

    def get_binary(self, url: str) -> tuple[bytes, str]:
        """Fetch raw bytes (images). Callers persist the result themselves."""
        response = self._request(url)
        return response.content, response.headers.get("Content-Type", "")

    def _request(self, url: str):
        if not is_allowed(url):
            raise FetchError(f"disallowed by robots.txt: {url}")
        for attempt in range(1, self._max_retries + 1):
            self._sleep(self._delay)
            try:
                response = self._session.get(url, timeout=self._timeout)
            except requests.RequestException as exc:
                log.warning("request error on %s (attempt %d): %s", url, attempt, exc)
            else:
                if response.status_code == 200:
                    return response
                if response.status_code not in RETRYABLE:
                    raise FetchError(f"HTTP {response.status_code} for {url}")
                log.warning("HTTP %d on %s (attempt %d)", response.status_code, url, attempt)
            if attempt < self._max_retries:
                self._sleep(self._delay * 2**attempt)
        raise FetchError(f"gave up after {self._max_retries} attempts: {url}")

    @staticmethod
    def _store(path: Path, text: str) -> str:
        tmp = path.with_suffix(".tmp")
        tmp.write_text(text)
        tmp.replace(path)
        return text
