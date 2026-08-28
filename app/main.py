import logging
import time
from contextlib import asynccontextmanager

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse
from playwright.async_api import async_playwright

from app.cache import TTLCache
from app.models import ProfileData, ProfileUrlInput
from app.scraper import ScrapeError, parse_vanity, scrape_profile

load_dotenv()

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
logger = logging.getLogger(__name__)

cache = TTLCache(ttl_seconds=900, max_size=200)


@asynccontextmanager
async def lifespan(app: FastAPI):
    pw = await async_playwright().start()
    app.state.playwright = pw
    app.state.browser = await pw.chromium.launch(
        headless=True,
        args=[
            "--no-sandbox",
            "--disable-setuid-sandbox",
            "--disable-dev-shm-usage",
        ],
    )
    logger.info("Playwright browser launched")
    yield
    await app.state.browser.close()
    await pw.stop()


app = FastAPI(
    title="LinkedIn Profile API",
    version="1.0.0",
    description=(
        "Reverse-engineered LinkedIn profile scraper. Accepts a public LinkedIn "
        "profile URL and returns structured profile data as JSON. Built for an "
        "engineering hiring challenge; for evaluation use only."
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
        "endpoint": "POST /api/v1/profile",
        "docs": "/docs",
    }


@app.post(
    "/api/v1/profile",
    response_model=ProfileData,
    responses={
        400: {"description": "Invalid URL"},
        404: {"description": "Profile not found / private / not found"},
        503: {"description": "LinkedIn blocked the request or auth expired"},
    },
)
async def get_profile(payload: ProfileUrlInput):
    url = payload.url.strip()
    try:
        vanity = parse_vanity(url)
    except ScrapeError as e:
        raise HTTPException(status_code=400, detail=e.detail)

    cache_key = f"profile:{vanity}"
    cached = cache.get(cache_key)
    if cached is not None:
        cached["scraped_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        cached["cached"] = True
        return cached

    try:
        browser = app.state.browser
        data = await scrape_profile(browser, url)
    except ScrapeError as e:
        mapping = {
            "INVALID_URL": 400,
            "NOT_FOUND": 404,
            "AUTH_FAILED": 503,
            "SCRAPE_FAILED": 502,
        }
        status = mapping.get(e.code, 502)
        if e.code == "AUTH_FAILED":
            logger.error("Auth failed: %s", e.detail)
        raise HTTPException(status_code=status, detail=e.detail)

    result = data.model_dump()
    result["scraped_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    result["cached"] = False
    cache.set(cache_key, result)
    return result
