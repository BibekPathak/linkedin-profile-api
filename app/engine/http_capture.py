"""HTTP-only page capture (no browser).

The /details/* section pages are fully server-rendered — the profile data is
present in the raw HTML response. Fetching them with a plain HTTP client
(`httpx`) + the `li_at` cookie produces the exact same text the engine parses,
but uses a few MB of RAM instead of a full Chromium instance.

This is the default on constrained hosts (Render free tier = 512MB) where
Playwright + Chromium reliably OOMs.
"""
from __future__ import annotations

import logging
import re
import time
from html.parser import HTMLParser
from typing import Optional

import httpx

from app.engine.types import ExtractionContext, PageCapture, ScrapeError

logger = logging.getLogger(__name__)

PROFILE_URL_RE = re.compile(r"linkedin\.com/in/([A-Za-z0-9\-_]+)/?")
SECTION_PATHS = {
    "experience": "details/experience/",
    "education": "details/education/",
    "skills": "details/skills/",
    "certifications": "details/certifications/",
    "languages": "details/languages/",
}

BASE_HEADERS = {
    "user-agent": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/152.0.0.0 Safari/537.36"
    ),
    "accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "accept-language": "en-US,en;q=0.9",
    "cache-control": "no-cache",
}

BASE_COOKIES = {
    "lang": "v=2&lang=en-us",
    "bcookie": "v=2&x",
    "timezone": "Asia/Calcutta",
    "li_theme": "light",
    "li_theme_set": "app",
}


def parse_vanity(url: str) -> str:
    m = PROFILE_URL_RE.search(url)
    if not m:
        raise ScrapeError(
            "INVALID_URL",
            "URL must be a LinkedIn profile URL like https://www.linkedin.com/in/<vanity>/",
        )
    return m.group(1)


class _TextExtractor(HTMLParser):
    """Extract visible text, dropping <script>/<style> blocks."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._chunks: list[str] = []
        self._skip = 0

    def handle_starttag(self, tag: str, attrs) -> None:
        if tag in ("script", "style", "noscript"):
            self._skip += 1

    def handle_endtag(self, tag: str) -> None:
        if tag in ("script", "style", "noscript") and self._skip:
            self._skip -= 1

    def handle_data(self, data: str) -> None:
        if not self._skip:
            text = data.strip()
            if text:
                self._chunks.append(text)

    def text(self) -> str:
        return "\n".join(self._chunks)


def _html_to_text(html: str) -> str:
    parser = _TextExtractor()
    parser.feed(html)
    return parser.text()


def _is_auth_wall(text: str) -> bool:
    head = text[:2000].lower()
    return "sign in to linkedin" in head or "authwall" in head


async def capture_profile_http(li_at: str, url: str) -> ExtractionContext:
    """Fetch main profile + all detail pages via plain HTTP."""
    vanity = parse_vanity(url)
    cookies = dict(BASE_COOKIES)
    cookies["li_at"] = li_at

    client = httpx.AsyncClient(
        headers=BASE_HEADERS,
        cookies=cookies,
        timeout=30.0,
        follow_redirects=True,
    )
    ctx = ExtractionContext(vanity=vanity, profile_url=url)
    try:
        async def fetch(target: str, section: Optional[str]) -> Optional[PageCapture]:
            start = time.time()
            try:
                resp = await client.get(target)
            except Exception as e:
                logger.warning("http fetch failed for %s: %s", target, e)
                return None
            if resp.status_code != 200:
                logger.warning("http %s for %s", resp.status_code, target)
                return None
            html = resp.text
            text = _html_to_text(html)
            if _is_auth_wall(text):
                raise ScrapeError("AUTH_FAILED", "LinkedIn session expired or was rejected. Refresh LINKEDIN_LI_AT.")
            title = ""
            m = re.search(r"<title[^>]*>(.*?)</title>", html, re.S | re.I)
            if m:
                title = m.group(1).strip()
            return PageCapture(
                url=str(resp.url),
                main_text=text,
                html=html,
                title=title,
                duration_ms=int((time.time() - start) * 1000),
            )

        main = await fetch(url, None)
        if main is None:
            raise ScrapeError("SCRAPE_FAILED", "Main profile page could not be fetched.")
        ctx.main = main

        base = f"https://www.linkedin.com/in/{vanity}/"
        for section, path in SECTION_PATHS.items():
            cap = await fetch(base + path, section)
            if cap is not None:
                ctx.details[section] = cap
        return ctx
    finally:
        await client.aclose()
