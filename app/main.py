import logging
import os
import time
from contextlib import asynccontextmanager

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Query
from playwright.async_api import async_playwright

from app.cache import TTLCache
from app.engine.capture import parse_vanity
from app.engine.diff import diff_profiles
from app.engine.snapshot import SnapshotStore
from app.engine.types import ExtractionOutcome, ScrapeError
from app.metrics import metrics
from app.models import (
    ChangesResponse,
    DiffRequest,
    DiffResponse,
    ProfileData,
    ProfileDebugResponse,
    ProfileMetadata,
    ProfileUrlInput,
    SnapshotResponse,
    SourceInfo,
)
from app.scraper import scrape_profile

load_dotenv()

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
logger = logging.getLogger(__name__)

SCRAPE_MODE = os.getenv("SCRAPE_MODE", "http")  # "http" (default) or "playwright"

cache = TTLCache(ttl_seconds=900, max_size=200)
snapshots = SnapshotStore()

FIELD_ORDER = [
    "name", "headline", "location", "connections", "about", "profile_urn",
    "profile_images", "experience", "education", "skills", "certifications", "languages",
]


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.scrape_mode = SCRAPE_MODE
    if SCRAPE_MODE == "playwright":
        pw = await async_playwright().start()
        app.state.playwright = pw
        app.state.browser = await pw.chromium.launch(
            headless=True,
            # Memory-lean flags for constrained hosts (Render free tier = 512MB).
            args=[
                "--no-sandbox",
                "--disable-setuid-sandbox",
                "--disable-dev-shm-usage",
                "--single-process",
                "--disable-gpu",
                "--disable-software-rasterizer",
                "--disable-extensions",
                "--disable-background-networking",
                "--disable-sync",
                "--disable-default-apps",
                "--no-first-run",
                "--no-default-browser-check",
                "--metrics-recording-only",
                "--js-flags=--max-old-space-size=256",
            ],
        )
        logger.info("Playwright browser launched (playwright mode)")
    else:
        logger.info("HTTP scrape mode (no browser) — SCRAPE_MODE=%s", SCRAPE_MODE)
    yield
    if SCRAPE_MODE == "playwright":
        await app.state.browser.close()
        await pw.stop()


app = FastAPI(
    title="LinkedIn Profile API",
    version="2.0.0",
    description=(
        "Reverse-engineered LinkedIn profile scraper with an adaptive extraction "
        "engine, field-level provenance, diff/snapshot, and service metrics. "
        "Built for an engineering hiring challenge; for evaluation use only."
    ),
    lifespan=lifespan,
)


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.get("/")
async def root():
    return {
        "service": "LinkedIn Profile API",
        "version": "2.0.0",
        "endpoints": {
            "scrape": "POST /api/v1/profile (add ?debug=true for metadata)",
            "diff": "POST /api/v1/profile/diff",
            "snapshot": "POST /api/v1/profile/snapshot",
            "changes": "GET /api/v1/profile/changes?url=...",
            "metrics": "GET /metrics",
            "health": "GET /health",
            "docs": "/docs",
        },
    }


def _build_metadata(outcome: ExtractionOutcome) -> ProfileMetadata:
    sources = {}
    for field in FIELD_ORDER:
        prov = outcome.provenance.get(field)
        if not prov:
            continue
        r = prov.result
        status = "success" if r.valid else "missing"
        sources[field] = SourceInfo(
            source=r.source.value,
            confidence=round(r.confidence, 3),
            status=status,
            duration_ms=r.duration_ms,
        )
    return ProfileMetadata(
        sources=sources,
        timings_ms=outcome.diagnostics.timings_ms,
        pages_visited=outcome.diagnostics.pages_visited,
        warnings=outcome.diagnostics.warnings,
        schema_health=outcome.diagnostics.schema_health,
    )


def _classify(field_status: dict[str, bool]) -> str:
    vals = list(field_status.values())
    if all(vals):
        return "success"
    if any(vals):
        return "partial"
    return "failed"


@app.post(
    "/api/v1/profile",
    responses={
        200: {
            "model": ProfileDebugResponse,
            "content": {
                "application/json": {
                    "example": {"profile": {}, "metadata": {}},
                }
            },
        },
        400: {"description": "Invalid URL"},
        404: {"description": "Profile not found / private / not found"},
        502: {"description": "Scraping failed"},
        503: {"description": "LinkedIn blocked the request or auth expired"},
    },
)
async def get_profile(
    payload: ProfileUrlInput,
    debug: bool = Query(False, description="Return profile + provenance/diagnostics metadata"),
):
    url = payload.url.strip()
    try:
        vanity = parse_vanity(url)
    except ScrapeError as e:
        raise HTTPException(status_code=400, detail=e.detail)

    cache_key = f"profile:{vanity}"
    cached = cache.get(cache_key)
    if cached is not None:
        metrics.record_cache(hit=True)
        cached["scraped_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        cached["cached"] = True
        if debug:
            meta = ProfileMetadata(**(cached.get("_metadata") or {}))
            profile_data = ProfileData(**{k: v for k, v in cached.items() if k != "_metadata"})
            return ProfileDebugResponse(profile=profile_data, metadata=meta)
        return {k: v for k, v in cached.items() if k != "_metadata"}

    metrics.record_cache(hit=False)
    try:
        browser = app.state.browser
        outcome = await scrape_profile(browser, url, include_metadata=True)
    except ScrapeError as e:
        metrics.record_scrape("failed", 0)
        mapping = {"INVALID_URL": 400, "NOT_FOUND": 404, "AUTH_FAILED": 503, "SCRAPE_FAILED": 502}
        status = mapping.get(e.code, 502)
        if e.code == "AUTH_FAILED":
            logger.error("Auth failed: %s", e.detail)
        raise HTTPException(status_code=status, detail=e.detail)

    profile = outcome.profile.model_dump()
    profile["scraped_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    profile["cached"] = False

    # metrics
    field_status = {
        f: (outcome.provenance[f].result.valid if f in outcome.provenance else False)
        for f in FIELD_ORDER
    }
    metrics.record_scrape(_classify(field_status), outcome.diagnostics.timings_ms.get("total", 0), field_status)

    metadata = _build_metadata(outcome)
    profile["_metadata"] = metadata.model_dump()

    cache.set(cache_key, profile)

    if debug:
        return ProfileDebugResponse(profile=ProfileData(**profile), metadata=metadata)

    clean_profile = {k: v for k, v in profile.items() if k != "_metadata"}
    return clean_profile


@app.post("/api/v1/profile/diff", response_model=DiffResponse)
async def profile_diff(req: DiffRequest):
    url = req.url.strip()
    try:
        parse_vanity(url)
    except ScrapeError as e:
        raise HTTPException(status_code=400, detail=e.detail)

    browser = app.state.browser
    try:
        outcome = await scrape_profile(browser, url, include_metadata=True)
    except ScrapeError as e:
        mapping = {"AUTH_FAILED": 503, "NOT_FOUND": 404}
        raise HTTPException(status_code=mapping.get(e.code, 502), detail=e.detail)

    current = outcome.profile.model_dump()
    changes = diff_profiles(req.previous or {}, current)
    return DiffResponse(url=url, changed=bool(changes), changes=changes)


@app.post("/api/v1/profile/snapshot", response_model=SnapshotResponse)
async def save_snapshot(payload: ProfileUrlInput):
    url = payload.url.strip()
    try:
        vanity = parse_vanity(url)
    except ScrapeError as e:
        raise HTTPException(status_code=400, detail=e.detail)

    browser = app.state.browser
    try:
        outcome = await scrape_profile(browser, url, include_metadata=True)
    except ScrapeError as e:
        raise HTTPException(status_code=503 if e.code == "AUTH_FAILED" else 502, detail=e.detail)

    current = outcome.profile.model_dump()
    snapshots.save(vanity, current)
    return SnapshotResponse(url=url, vanity_name=vanity, saved=True)


@app.get("/api/v1/profile/changes", response_model=ChangesResponse)
async def get_changes(url: str = Query(..., description="LinkedIn profile URL")):
    try:
        vanity = parse_vanity(url)
    except ScrapeError as e:
        raise HTTPException(status_code=400, detail=e.detail)

    previous = snapshots.get(vanity)
    if previous is None:
        return ChangesResponse(url=url, vanity_name=vanity, has_previous=False, changes={})

    browser = app.state.browser
    try:
        outcome = await scrape_profile(browser, url, include_metadata=True)
    except ScrapeError as e:
        raise HTTPException(status_code=503 if e.code == "AUTH_FAILED" else 502, detail=e.detail)

    current = outcome.profile.model_dump()
    changes = diff_profiles(previous, current)
    return ChangesResponse(url=url, vanity_name=vanity, has_previous=True, changes=changes)


@app.get("/metrics", response_model=dict)
async def get_metrics():
    return metrics.summary()
