"""Polite page fetching: robots.txt (RFC 9309), per-host rate limit, size cap, SQLite cache,
and an optional Crawl4AI browser fallback for JavaScript-only pages."""
from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from urllib.parse import urlparse
from urllib.robotparser import RobotFileParser

import httpx

from . import USER_AGENT
from .extract import needs_js, visible_text
from .store import Store
from .util import normalize_url

MAX_BYTES = 2_000_000
ROBOTS_TOKEN = "gruffet"


@dataclass
class Page:
    url: str
    final_url: str | None = None
    status: int | None = None
    html: str = ""
    error: str | None = None
    rendered: bool = False
    blocked: bool = False
    insecure_tls: bool = False

    @property
    def ok(self) -> bool:
        return self.status is not None and 200 <= self.status < 300 and bool(self.html)


class Fetcher:
    def __init__(self, store: Store, concurrency: int = 8, timeout: float = 15.0, respect_robots: bool = True,
                 render: str = "auto", max_age_s: float | None = 7 * 86400, host_delay_s: float = 1.0):
        assert render in ("never", "auto", "always")
        self.store, self.timeout, self.respect_robots = store, timeout, respect_robots
        self.render_mode, self.max_age_s, self.host_delay_s = render, max_age_s, host_delay_s
        self._sem = asyncio.Semaphore(concurrency)
        self._robots: dict[str, RobotFileParser | str] = {}
        self._robots_lock: dict[str, asyncio.Lock] = {}
        self._host_lock: dict[str, asyncio.Lock] = {}
        self._host_last: dict[str, float] = {}
        self._render_lock = asyncio.Lock()
        self._crawler = None
        self.render_available: bool | None = None

    async def __aenter__(self) -> "Fetcher":
        h = {"User-Agent": USER_AGENT, "Accept": "text/html,application/xhtml+xml;q=0.9,*/*;q=0.5",
             "Accept-Language": "en"}
        self._client = httpx.AsyncClient(headers=h, timeout=self.timeout, follow_redirects=True, max_redirects=5)
        self._client_insecure = httpx.AsyncClient(headers=h, timeout=self.timeout, follow_redirects=True,
                                                  max_redirects=5, verify=False)
        return self

    async def __aexit__(self, *exc) -> None:
        await self._client.aclose()
        await self._client_insecure.aclose()
        if self._crawler is not None:
            try:
                await self._crawler.close()
            except Exception:
                pass

    # -- robots ---------------------------------------------------------
    async def allowed(self, url: str) -> bool:
        if not self.respect_robots:
            return True
        p = urlparse(url)
        origin = f"{p.scheme}://{p.netloc}"
        lock = self._robots_lock.setdefault(origin, asyncio.Lock())
        async with lock:
            if origin not in self._robots:
                self._robots[origin] = await self._load_robots(origin)
        rp = self._robots[origin]
        if rp == "allow":
            return True
        if rp == "disallow":
            return False
        return rp.can_fetch(ROBOTS_TOKEN, url)  # type: ignore[union-attr]

    async def _load_robots(self, origin: str) -> RobotFileParser | str:
        try:
            r = await self._client.get(origin + "/robots.txt")
        except httpx.HTTPError:
            return "allow"  # unreachable host: the page fetch itself will report the real error
        if 200 <= r.status_code < 300:
            rp = RobotFileParser()
            rp.parse(r.text.splitlines())
            return rp
        if 500 <= r.status_code < 600:
            return "disallow"  # RFC 9309: server errors mean assume disallow
        return "allow"  # 4xx: no robots file

    # -- fetching -------------------------------------------------------
    async def _throttle(self, host: str) -> None:
        lock = self._host_lock.setdefault(host, asyncio.Lock())
        async with lock:
            wait = self.host_delay_s - (time.monotonic() - self._host_last.get(host, 0.0))
            if wait > 0:
                await asyncio.sleep(wait)
            self._host_last[host] = time.monotonic()

    async def _http_get(self, client: httpx.AsyncClient, url: str) -> Page:
        async with client.stream("GET", url) as r:
            ctype = r.headers.get("content-type", "").lower()
            page = Page(url=url, final_url=str(r.url), status=r.status_code)
            if r.status_code >= 400 or ("html" not in ctype and "xml" not in ctype and ctype):
                return page
            size, chunks = 0, []
            async for c in r.aiter_bytes():
                chunks.append(c)
                size += len(c)
                if size > MAX_BYTES:
                    break
            page.html = b"".join(chunks).decode(r.encoding or "utf-8", "replace")
            return page

    async def get(self, url: str, force_render: bool = False, allow_render: bool = True) -> Page:
        url = normalize_url(url) or url
        row = self.store.get_page(url, self.max_age_s)
        if row is not None:
            return Page(url, row["final_url"], row["status"], Store.page_html(row), row["error"],
                        bool(row["rendered"]), blocked=(row["error"] or "").startswith("blocked"))
        async with self._sem:
            page = await self._fetch_uncached(url, force_render, allow_render)
        self.store.put_page(url, page.final_url, page.status, page.error, page.html, page.rendered)
        self.store.commit()
        return page

    async def _fetch_uncached(self, url: str, force_render: bool, allow_render: bool = True) -> Page:
        host = urlparse(url).netloc
        if not await self.allowed(url):
            return Page(url, error="blocked by robots.txt", blocked=True)
        await self._throttle(host)
        try:
            try:
                page = await self._http_get(self._client, url)
            except httpx.HTTPError as e:
                if "CERTIFICATE_VERIFY_FAILED" in str(e) or "certificate" in str(e).lower():
                    page = await self._http_get(self._client_insecure, url)
                    page.insecure_tls = True
                else:
                    raise
        except httpx.HTTPError as e:
            return Page(url, error=f"{type(e).__name__}: {e}"[:200])
        want_render = allow_render and (self.render_mode == "always" or force_render or
                       (self.render_mode == "auto" and page.ok and needs_js(page.html, visible_text(page.html))))
        if want_render and (page.ok or page.status is None or self.render_mode == "always"):
            html = await self._render(page.final_url or url)
            if html:
                page.html, page.rendered, page.status = html, True, page.status or 200
        return page

    async def get_bytes(self, url: str, max_bytes: int = 8_000_000) -> tuple[bytes | None, str | None]:
        """Download a binary (image) politely. Returns (data, error)."""
        if not await self.allowed(url):
            return None, "blocked by robots.txt"
        async with self._sem:
            await self._throttle(urlparse(url).netloc)
            try:
                async with self._client.stream("GET", url) as r:
                    ctype = r.headers.get("content-type", "").lower()
                    if r.status_code >= 400:
                        return None, f"HTTP {r.status_code}"
                    if not ctype.startswith("image/"):
                        return None, f"not an image ({ctype or 'no content-type'})"
                    chunks, size = [], 0
                    async for c in r.aiter_bytes():
                        chunks.append(c)
                        size += len(c)
                        if size > max_bytes:
                            return None, "too large"
                    return b"".join(chunks), None
            except httpx.HTTPError as e:
                return None, f"{type(e).__name__}"

    async def _render(self, url: str) -> str | None:
        """Render with Crawl4AI's browser if the `browser` extra is installed, else skip quietly."""
        if self.render_available is False:
            return None
        try:
            from crawl4ai import AsyncWebCrawler, BrowserConfig, CacheMode, CrawlerRunConfig
        except ImportError:
            self.render_available = False
            return None
        self.render_available = True
        async with self._render_lock:
            try:
                if self._crawler is None:
                    self._crawler = AsyncWebCrawler(config=BrowserConfig(headless=True, verbose=False))
                    await self._crawler.start()
                res = await self._crawler.arun(url, config=CrawlerRunConfig(cache_mode=CacheMode.BYPASS, verbose=False))
                return res.html if res.success else None
            except Exception:
                return None
