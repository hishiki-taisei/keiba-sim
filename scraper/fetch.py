from __future__ import annotations

import gzip
import random
import time
from pathlib import Path

import requests

UA = "Mozilla/5.0 (keiba-sim research scraper; low rate)"


class Fetcher:
    """HTTP GET with a minimum interval between requests, retries and an on-disk cache.

    Every page is stored gzipped under ``cache_dir`` so the site is hit at most once per page
    and parsing can be redone offline.
    """

    def __init__(self, cache_dir: Path, interval: float = 1.2, timeout: float = 20.0):
        self.cache_dir = Path(cache_dir)
        self.interval = interval
        self.timeout = timeout
        self.session = requests.Session()
        self.session.headers["User-Agent"] = UA
        self._last = 0.0
        self.hits = 0

    def _wait(self):
        dt = time.monotonic() - self._last
        pause = self.interval + random.uniform(0, self.interval * 0.3)
        if dt < pause:
            time.sleep(pause - dt)
        self._last = time.monotonic()

    def get(self, url: str, key: str, encoding: str = "euc-jp", refresh: bool = False) -> str | None:
        """Return the page text, or None on 404. ``key`` is the cache path relative to cache_dir."""
        path = self.cache_dir / f"{key}.html.gz"
        if path.exists() and not refresh:
            return gzip.decompress(path.read_bytes()).decode(encoding, "replace")
        for attempt in range(5):
            self._wait()
            try:
                r = self.session.get(url, timeout=self.timeout)
            except requests.RequestException:
                time.sleep(5 * 2 ** attempt)
                continue
            self.hits += 1
            if r.status_code == 404:
                return None
            if r.status_code in (403, 429) or r.status_code >= 500:
                # Back off hard: the site is asking us to slow down.
                time.sleep(60 * (attempt + 1))
                continue
            r.raise_for_status()
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(gzip.compress(r.content))
            return r.content.decode(encoding, "replace")
        raise RuntimeError(f"giving up on {url}")
