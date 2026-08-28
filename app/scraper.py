"""Facade over the adaptive extraction engine.

Keeps the public API stable (scrape_profile(browser, url) -> ProfileData) while
delegating to the engine under the hood. Additional metadata (provenance,
diagnostics) is returned when include_metadata=True.
"""
from __future__ import annotations

import logging
import time

from app.engine.capture import capture_profile
from app.engine.engine import ExtractionEngine
from app.engine.types import ExtractionOutcome

logger = logging.getLogger(__name__)

_engine = ExtractionEngine(capture_profile)


async def scrape_profile(browser, url: str, include_metadata: bool = False) -> dict | ExtractionOutcome:
    """Scrape a LinkedIn profile.

    Returns a ProfileData dict by default; if include_metadata=True returns an
    ExtractionOutcome containing profile + provenance + diagnostics.
    """
    start = time.time()
    ctx = await capture_profile(browser, url)
    outcome = await _engine.extract(ctx)
    outcome.diagnostics.timings_ms["total"] = int((time.time() - start) * 1000)
    if include_metadata:
        return outcome
    return outcome.profile.model_dump()
