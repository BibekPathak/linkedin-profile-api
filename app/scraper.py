"""Facade over the adaptive extraction engine.

Keeps the public API stable (scrape_profile(...) -> ProfileData) while
delegating to the engine under the hood. Supports two capture backends:

- "http": plain httpx + li_at cookie (fast, low memory, no browser). Used by
  default and on constrained hosts where Chromium would OOM.
- "playwright": headless Chromium for pages that need JS hydration.

Additional metadata (provenance, diagnostics) is returned when
include_metadata=True.
"""
from __future__ import annotations

import logging
import os
import time
from typing import Optional

from app.engine.engine import ExtractionEngine
from app.engine.types import ExtractionContext, ExtractionOutcome, ScrapeError
from app.engine.http_capture import capture_profile_http

logger = logging.getLogger(__name__)

_http_engine = ExtractionEngine(None)
_playwright_engine = ExtractionEngine(None)


async def _capture_http(url: str):
    li_at = os.getenv("LINKEDIN_LI_AT")
    if not li_at:
        raise ScrapeError("AUTH_FAILED", "Missing LINKEDIN_LI_AT environment variable.")
    return await capture_profile_http(li_at, url)


async def scrape_profile(
    browser,
    url: str,
    include_metadata: bool = False,
    mode: Optional[str] = None,
) -> dict | ExtractionOutcome:
    """Scrape a LinkedIn profile.

    mode: "http" (default) or "playwright". Falls back to the env var
    SCRAPE_MODE, then "http".
    """
    mode = mode or os.getenv("SCRAPE_MODE", "http")
    start = time.time()

    if mode == "playwright":
        ctx = await _capture_playwright(browser, url)
        outcome = await _playwright_engine.extract(ctx)
    else:
        ctx = await _capture_http(url)
        outcome = await _http_engine.extract(ctx)

    outcome.diagnostics.timings_ms["total"] = int((time.time() - start) * 1000)
    if include_metadata:
        return outcome
    return outcome.profile.model_dump()


async def _capture_playwright(browser, url: str) -> ExtractionContext:
    from app.engine.capture import capture_profile

    return await capture_profile(browser, url)
