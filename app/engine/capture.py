"""Page capture for the extraction engine.

Uses Playwright to fetch the profile main page + each /details/* page, captures
the DOM text + raw HTML, and times each request. Auth walls are detected here.
"""
from __future__ import annotations

import logging
import re
import time
from typing import Optional

from playwright.async_api import Browser, BrowserContext, Page

from app.auth import new_authenticated_context
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


def parse_vanity(url: str) -> str:
    m = PROFILE_URL_RE.search(url)
    if not m:
        raise ScrapeError(
            "INVALID_URL",
            "URL must be a LinkedIn profile URL like https://www.linkedin.com/in/<vanity>/",
        )
    return m.group(1)


async def _is_auth_wall(page: Page) -> bool:
    title = (await page.title()).lower()
    return "sign in" in title or "login" in title or "/authwall" in page.url


async def _capture(page: Page, url: str) -> PageCapture:
    start = time.time()
    # wait_until="commit" returns as soon as the response starts; LinkedIn's SPA
    # detail pages can otherwise hang on domcontentloaded and a lingering
    # navigation can interrupt the next page's goto. The polling loop below
    # handles content readiness + URL matching.
    try:
        await page.goto(url, wait_until="commit", timeout=30000)
    except Exception:
        pass
    try:
        await page.wait_for_selector("main", timeout=20000)
    except Exception:
        pass
    await page.wait_for_timeout(1500)
    # Retry until main has real text, we are on the target URL, and the text has
    # stopped growing (SPA hydration renders sections progressively). Polling for
    # stability avoids capturing a half-hydrated page.
    main_text = ""
    prev_len = 0
    stable_streak = 0
    for _ in range(12):
        try:
            current_url = page.url
            main_text = await page.inner_text("main")
        except Exception:
            current_url, main_text = "", ""
        target_path = url.split("linkedin.com")[-1].rstrip("/") or "/"
        current_path = current_url.split("linkedin.com")[-1].rstrip("/") or "/"
        on_target = current_path.startswith(target_path)
        if on_target and len(main_text.strip()) > 50:
            if len(main_text) == prev_len:
                stable_streak += 1
            else:
                stable_streak = 0
            if stable_streak >= 2:
                break
        prev_len = len(main_text)
        await page.wait_for_timeout(1500)
    try:
        html = await page.content()
    except Exception:
        html = ""
    try:
        title = await page.title()
    except Exception:
        title = ""
    return PageCapture(
        url=page.url if page.url else url, main_text=main_text, html=html, title=title,
        duration_ms=int((time.time() - start) * 1000),
    )


async def capture_profile(browser: Browser, url: str) -> ExtractionContext:
    """Fetch the main profile + all detail pages into an ExtractionContext."""
    vanity = parse_vanity(url)
    context: Optional[BrowserContext] = None
    page: Optional[Page] = None
    try:
        context = await new_authenticated_context(browser)
        page = await context.new_page()

        main = await _capture(page, url)
        if await _is_auth_wall(page):
            raise ScrapeError("AUTH_FAILED", "LinkedIn session expired or was rejected. Refresh LINKEDIN_LI_AT.")

        ctx = ExtractionContext(vanity=vanity, profile_url=url, main=main)
        base = f"https://www.linkedin.com/in/{vanity}/"
        for section, path in SECTION_PATHS.items():
            try:
                cap = await _capture(page, base + path)
                if await _is_auth_wall(page):
                    raise ScrapeError("AUTH_FAILED", "Session expired while fetching detail sections.")
                ctx.details[section] = cap
            except ScrapeError:
                raise
            except Exception as e:
                logger.warning("capture failed for %s: %s", path, e)
        return ctx
    finally:
        if page:
            try:
                await page.close()
            except Exception:
                pass
        if context:
            try:
                await context.close()
            except Exception:
                pass
