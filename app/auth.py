import logging
import os

from playwright.async_api import Browser, BrowserContext

logger = logging.getLogger(__name__)

LI_AT = "li_at"
JSESSIONID = "JSESSIONID"
COOKIE_DOMAIN = ".linkedin.com"

# Domain-canonical base cookies. li_at/jsessioSESSIONID are injected from env.
BASE_COOKIES = [
    {"name": "lang", "value": "v=2&lang=en-us"},
    {"name": "bcookie", "value": 'v=2&1a2b3c4d-1111-2222-3333-444455556666'},
    {"name": "timezone", "value": "Asia/Calcutta"},
    {"name": "li_theme", "value": "light"},
    {"name": "li_theme_set", "value": "app"},
]


def _env_cookie(name: str) -> str | None:
    return os.getenv(f"LINKEDIN_{name.upper()}") or None


def has_credentials() -> bool:
    return bool(_env_cookie("LI_AT"))


async def new_authenticated_context(browser: Browser) -> BrowserContext:
    """Create a browser context seeded with the LinkedIn session cookie.

    The `li_at` cookie is the authenticated session token. It is read from the
    environment (LINKEDIN_LI_AT) so that credentials never live in the repo.
    """
    li_at = _env_cookie("LI_AT")
    if not li_at:
        raise RuntimeError(
            "Missing LinkedIn session cookie. Set LINKEDIN_LI_AT in the environment."
        )

    cookies = [
        {"name": c["name"], "value": c["value"], "domain": COOKIE_DOMAIN, "path": "/"}
        for c in BASE_COOKIES
    ]
    cookies.append(
        {
            "name": LI_AT,
            "value": li_at,
            "domain": COOKIE_DOMAIN,
            "path": "/",
            "secure": True,
            "httpOnly": True,
        }
    )
    # NOTE: JSESSIONID is intentionally NOT injected. LinkedIn issues a fresh
    # one on the first navigation and uses it as the CSRF token for its own
    # RSC component calls; a stale value makes those calls fail.

    context = await browser.new_context(
        user_agent=(
            "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/152.0.0.0 Safari/537.36"
        ),
        locale="en_US",
        viewport={"width": 1440, "height": 900},
    )
    await context.add_cookies(cookies)
    return context
