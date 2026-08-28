import logging
import re
from typing import Optional

from playwright.async_api import Browser, BrowserContext, Page

from app.auth import new_authenticated_context
from app.models import Certification, Education, Experience, Language, ProfileData, Skill

logger = logging.getLogger(__name__)

PROFILE_URL_RE = re.compile(r"linkedin\.com/in/([A-Za-z0-9\-_]+)/?")
URN_RE = re.compile(r"urn:li:fsd_profile:([A-Za-z0-9_]+)|\b(ACoA[A-Za-z0-9_\-]{8,})\b")
TOPCARD_URN_RE = re.compile(r"card\.ref(ACoA[A-Za-z0-9_\-]{8,})Topcard")

SECTION_PATHS = {
    "experience": "details/experience/",
    "education": "details/education/",
    "skills": "details/skills/",
    "certifications": "details/certifications/",
    "languages": "details/languages/",
}

NOISE = {
    "experience", "education", "skills", "licenses & certifications", "certifications",
    "languages", "all", "industry knowledge", "tools & technologies", "interpersonal skills",
    "show more", "show all", "see all", "add", "endorse", "add a new skill", "add new skill",
    "more", "highlights", "featured", "activity", "about", "people you may know",
    "more profiles for you", "you might like", "follow", "connect", "message", "back",
    "advertise on linkedin", "premium", "view my services", "open to", "add profile section",
    "enhance profile", "resources", "edit", "analytics", "profile viewers", "post impressions",
    "search appearances", "suggested", "people also viewed", "who your viewers also viewed",
    "contact info", "connection", "connections", "mutual connection", "learn more", "new",
    "promoted", "unfollow", "report", "block", "recent activity", "posts", "comments",
    "reposts", "recommendations", "show all activity", "create a post", "delete", "share",
    "invite", "accept", "message top connections", "get introduced", "introductions",
    "your premium features", "premium profile", "linkedin", "settings", "help", "sign out",
}


class ScrapeError(Exception):
    def __init__(self, code: str, detail: str):
        self.code = code
        self.detail = detail
        super().__init__(detail)


def parse_vanity(url: str) -> str:
    m = PROFILE_URL_RE.search(url)
    if not m:
        raise ScrapeError(
            "INVALID_URL",
            "URL must be a LinkedIn profile URL like https://www.linkedin.com/in/<vanity>/",
        )
    return m.group(1)


def _clean(s: Optional[str]) -> Optional[str]:
    if s is None:
        return None
    s = re.sub(r"\s+", " ", s).strip()
    return s or None


async def _is_auth_wall(page: Page) -> bool:
    title = (await page.title()).lower()
    return "sign in" in title or "login" in title or "/authwall" in page.url


async def _goto(page: Page, url: str) -> None:
    await page.goto(url, wait_until="domcontentloaded", timeout=45000)
    try:
        await page.wait_for_selector("main", timeout=15000)
    except Exception:
        pass
    await page.wait_for_timeout(1200)


async def _main_text(page: Page) -> str:
    try:
        return await page.inner_text("main")
    except Exception:
        return ""


def _lines(text: str) -> list[str]:
    return [l.strip() for l in text.splitlines() if l.strip()]


SIDEBAR_MARKERS = {
    "more profiles for you",
    "people you may know",
    "people also viewed",
    "who your viewers also viewed",
    "explore premium profiles",
    "pages for you",
    "from your company",
    "accessibility",
    "talent solutions",
    "community guidelines",
    "privacy & terms",
    "ad choices",
    "select language",
    "linkedin corporation",
    "advertise on linkedin",
    "you might like",
    "suggested",
    "private to you",
    "profile language",
}


def _truncate_at_sidebar(lines: list[str]) -> list[str]:
    """Cut a section's lines at the first sidebar/footer marker."""
    for idx, l in enumerate(lines):
        if l.lower() in SIDEBAR_MARKERS:
            return lines[:idx]
    return lines


async def _top_card(page: Page) -> Optional[dict]:
    """Extract the profile top card via a stable DOM anchor.

    Layout (blank lines elided):
        0: name
        1: "· 2nd"  (connection degree / self marker)
        2: headline
        3: location
        4: "·"  "Contact info"
        ...  "connections"
    """
    try:
        title_prefix = (await page.title()).split("|")[0].strip()
        out = await page.evaluate(
            """([prefix]) => {
                const h2s = [...document.querySelectorAll('h2')];
                const nameEl = h2s.find(h => (h.innerText || '').trim() === prefix)
                            || h2s.find(h => prefix.includes((h.innerText || '').trim().slice(0, 20)));
                if (!nameEl) return null;
                let p = nameEl, section = null;
                for (let d = 0; d < 14 && p; d++) {
                    if (p.tagName === 'SECTION') { section = p; break; }
                    p = p.parentElement;
                }
                if (!section) return null;
                return {
                    text: section.innerText,
                    photo: [...section.querySelectorAll("img[src*='profile-displayphoto']")].map(i => i.src),
                    bg: [...section.querySelectorAll("img[src*='profile-displaybackgroundimage']")].map(i => i.src),
                };
            }""",
            [title_prefix],
        )
    except Exception as e:
        logger.warning("top card extraction failed: %s", e)
        return None
    return out


def _parse_top_card(card: dict) -> dict:
    lines = _lines(card["text"])
    name = headline = location = connections = None
    if lines:
        name = lines[0]
        # headline is the line before a location pattern
        for i, l in enumerate(lines):
            if re.search(r"[A-Za-z]{2,},\s*[A-Za-z]{2,}(,\s*[A-Za-z]{2,})?$", l) and "connection" not in l.lower():
                location = l
                if i >= 1:
                    headline = lines[i - 1] if not re.match(r"^·\s*\d", lines[i - 1]) else (lines[i - 2] if i >= 2 else None)
                break
        # connections count: "<num>" immediately before "connections"
        for i, l in enumerate(lines):
            if l.lower() == "connections" and i >= 1:
                connections = lines[i - 1]
                break
    images = []
    for src in (card.get("photo") or []):
        if src not in images:
            images.append(src)
    for src in (card.get("bg") or []):
        if src not in images:
            images.append(src)
    return {"name": name, "headline": headline, "location": location, "connections": connections, "images": images}


ABOUT_STOP = {"activity", "featured", "highlights", "post", "posts", "experience", "education",
              "skills", "recommendations", "interests", "more profiles for you"}


def _parse_about(main_text: str) -> Optional[str]:
    lines = _lines(main_text)
    out = []
    in_about = False
    for l in lines:
        low = l.lower()
        if low == "about":
            in_about = True
            continue
        if in_about:
            if low in ABOUT_STOP or low == "profile language":
                break
            if low in NOISE or low.startswith("show more"):
                continue
            out.append(l)
    return _clean(" ".join(out)) or None


def _strip_degree(line: str) -> str:
    m = re.match(r"^·\s*(\d[a-z+]*)$", line, re.I)
    if m:
        return ""
    return line


async def _parse_experience(page: Page) -> list[Experience]:
    """Parse the /details/experience/ page by locating each entry block.

    Each block (blank lines elided):
        title
        company · type      (or company alone)
        date  ·  duration   (e.g. "Aug 2024 - Present · 2 yrs 1 mo")
        location
        description...
    """
    text = await _main_text(page)
    lines = _truncate_at_sidebar(_lines(text))
    items: list[Experience] = []
    i = 0
    n = len(lines)
    while i < n:
        line = lines[i]
        if line.lower() == "experience":
            i += 1
            continue
        # heuristic: a date range line marks the end of one entry's header.
        # We detect an entry start when we find: title (no date, not noise),
        # next meaningful lines include a company and a date.
        if line.lower() in NOISE or line.startswith("·") or re.match(r"^\d+$", line):
            i += 1
            continue
        # Try to consume an entry: title line, company line, date line
        if i + 2 < n:
            company_line = lines[i + 1]
            date_line = lines[i + 2]
            if _is_date_range(date_line) and not _is_date_range(line) and not _is_date_range(company_line):
                title = _strip_degree(line) or None
                company = _parse_company(company_line)
                date_range = _clean(date_line)
                location = None
                desc_parts = []
                # location is the next non-date, non-noise line after the date
                j = i + 3
                while j < n:
                    lj = lines[j]
                    if lj.lower() in NOISE:
                        j += 1
                        continue
                    if _looks_like_location(lj):
                        location = lj
                        j += 1
                        break
                    break
                # description until next entry start
                while j < n:
                    lj = lines[j]
                    low = lj.lower()
                    # next entry start = title followed by date two lines later
                    if j + 2 < n and _is_date_range(lines[j + 2]) and not _is_date_range(lj) and lj.lower() not in NOISE:
                        break
                    if low in NOISE:
                        j += 1
                        continue
                    if _looks_like_location(lj) and location is None:
                        location = lj
                        j += 1
                        continue
                    desc_parts.append(lj)
                    j += 1
                desc = _clean(" ".join(desc_parts)) if desc_parts else None
                items.append(
                    Experience(
                        title=title,
                        company=company,
                        date_range=date_range,
                        location=location,
                        description=desc,
                    )
                )
                i = j
                continue
        i += 1
    return items


def _is_date_range(line: str) -> bool:
    return bool(re.match(r"^(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)", line)) or bool(
        re.match(r"^\d{4}\s*[-–]\s*(\d{4}|Present)", line)
    )


def _parse_company(line: Optional[str]) -> Optional[str]:
    if not line:
        return None
    if "·" in line:
        return line.split("·")[0].strip() or None
    return line or None


def _looks_like_location(line: str) -> bool:
    return bool(re.search(r"[A-Za-z]{2,},\s*[A-Za-z]{2,}(,\s*[A-Za-z]{2,})?$", line)) and len(line) < 60


async def _parse_education(page: Page) -> list[Education]:
    text = await _main_text(page)
    lines = _truncate_at_sidebar(_lines(text))
    items: list[Education] = []
    i = 0
    n = len(lines)
    while i < n:
        line = lines[i]
        low = line.lower()
        if low == "education":
            i += 1
            continue
        if low in NOISE or low.startswith("·") or _is_date_range(line) or re.match(r"^\d+$", line):
            i += 1
            continue
        school = line
        degree_lines = []
        date_range = None
        j = i + 1
        # collect up to the next school start (school followed by non-date then date)
        while j < n:
            lj = lines[j]
            lowj = lj.lower()
            if lowj in NOISE or lowj.startswith("·"):
                break
            if _is_date_range(lj):
                date_range = _clean(lj)
                j += 1
                break
            # A new school begins at lj if lj+1 exists, lj+1 is not a date and lj+2 is a date
            if j + 2 < n and not _is_date_range(lines[j + 1]) and _is_date_range(lines[j + 2]):
                break
            degree_lines.append(lj)
            j += 1
        desc_parts = []
        while j < n:
            lj = lines[j]
            lowj = lj.lower()
            if lowj in NOISE or _is_date_range(lj) or lowj.startswith("·"):
                break
            if j + 2 < n and not _is_date_range(lines[j + 1]) and _is_date_range(lines[j + 2]):
                break
            desc_parts.append(lj)
            j += 1
        items.append(
            Education(
                school=school,
                degree=_clean(" | ".join(degree_lines)) if degree_lines else None,
                date_range=date_range,
                description=_clean(" ".join(desc_parts)) if desc_parts else None,
            )
        )
        i = j
    return items


EMPTY_STATE = {
    "when you add new skills they’ll show up here",
    "when you add new skills they'll show up here",
    "showcase your skills and strengths.",
    "add skills",
    "nothing to see for now",
    "when you add new languages they’ll show up here.",
    "when you add new languages they'll show up here.",
    "add languages",
    "add certifications",
    "no certifications to show",
    "when you add new licenses & certifications they’ll show up here.",
    "when you add new licenses & certifications they'll show up here.",
    "add licenses or certifications",
}


async def _parse_certifications(page: Page) -> list[Certification]:
    text = await _main_text(page)
    lines = _truncate_at_sidebar(_lines(text))
    items: list[Certification] = []
    i = 0
    n = len(lines)
    while i < n:
        low = lines[i].lower()
        if low == "licenses & certifications" or low == "certifications":
            i += 1
            continue
        if low in NOISE or low.startswith("·") or low in EMPTY_STATE:
            i += 1
            continue
        name = lines[i]
        issuer = None
        date_range = None
        j = i + 1
        while j < n:
            lj = lines[j]
            lowj = lj.lower()
            if lowj == "show credential":
                j += 1
                break
            if lowj in NOISE or lowj.startswith("·"):
                break
            if lj.startswith("Issued "):
                date_range = _clean(lj)
            elif issuer is None:
                issuer = lj
            j += 1
        items.append(Certification(name=name, issuer=issuer, date_range=date_range))
        i = j
    return items


async def _parse_languages(page: Page) -> list[Language]:
    text = await _main_text(page)
    lines = _truncate_at_sidebar(_lines(text))
    items: list[Language] = []
    i = 0
    n = len(lines)
    while i < n:
        low = lines[i].lower()
        if low == "languages":
            i += 1
            continue
        if low in NOISE or low.startswith("·") or low in EMPTY_STATE:
            i += 1
            continue
        name = lines[i]
        proficiency = None
        j = i + 1
        if j < n and not lines[j].lower().startswith("·") and lines[j].lower() not in NOISE:
            proficiency = lines[j]
            j += 1
        items.append(Language(name=name, proficiency=proficiency))
        i = j
    return items


async def _parse_pills(page: Page, header: str) -> list[str]:
    text = await _main_text(page)
    lines = _truncate_at_sidebar(_lines(text))
    out: list[str] = []
    found = False
    for line in lines:
        low = line.lower()
        if not found:
            if low == header.lower():
                found = True
            continue
        if low in NOISE or re.match(r"^\d+\s*(endorsement|endorsements)$", low) or low.startswith("endorsed by"):
            continue
        if re.match(r"^\d+$", line):
            continue
        if low in EMPTY_STATE:
            continue
        out.append(line)
    return out


async def scrape_profile(browser: Browser, url: str) -> ProfileData:
    vanity = parse_vanity(url)
    context: Optional[BrowserContext] = None
    page: Optional[Page] = None
    try:
        context = await new_authenticated_context(browser)
        page = await context.new_page()

        await _goto(page, url)
        if await _is_auth_wall(page):
            raise ScrapeError("AUTH_FAILED", "LinkedIn session expired or was rejected. Refresh LINKEDIN_LI_AT.")

        main_text = await _main_text(page)
        card = await _top_card(page)
        top = _parse_top_card(card) if card else {}

        profile_urn = None
        try:
            html = await page.content()
            m = TOPCARD_URN_RE.search(html)
            if not m:
                m = URN_RE.search(html)
            if m:
                raw = m.group(1) or m.group(2)
                if raw:
                    profile_urn = "urn:li:fsd_profile:" + raw
        except Exception:
            pass

        name = top.get("name")
        if not name:
            try:
                title_prefix = (await page.title()).split("|")[0].strip()
                if title_prefix:
                    name = title_prefix
            except Exception:
                pass

        connections = top.get("connections")
        if not connections:
            m = re.search(r"([\d,+]+\+?)\s+connections", main_text)
            if m:
                connections = m.group(1)

        experiences: list[Experience] = []
        educations: list[Education] = []
        skills: list[Skill] = []
        certifications: list[Certification] = []
        languages: list[Language] = []

        base = f"https://www.linkedin.com/in/{vanity}/"
        try:
            await _goto(page, base + SECTION_PATHS["experience"])
            experiences = await _parse_experience(page)
        except ScrapeError:
            raise
        except Exception as e:
            logger.warning("experience parse failed: %s", e)

        try:
            await _goto(page, base + SECTION_PATHS["education"])
            educations = await _parse_education(page)
        except ScrapeError:
            raise
        except Exception as e:
            logger.warning("education parse failed: %s", e)

        try:
            await _goto(page, base + SECTION_PATHS["skills"])
            skills = [Skill(name=n) for n in await _parse_pills(page, "skills")]
        except ScrapeError:
            raise
        except Exception as e:
            logger.warning("skills parse failed: %s", e)

        try:
            await _goto(page, base + SECTION_PATHS["certifications"])
            certifications = await _parse_certifications(page)
        except ScrapeError:
            raise
        except Exception as e:
            logger.warning("certifications parse failed: %s", e)

        try:
            await _goto(page, base + SECTION_PATHS["languages"])
            languages = await _parse_languages(page)
        except ScrapeError:
            raise
        except Exception as e:
            logger.warning("languages parse failed: %s", e)

        return ProfileData(
            name=name,
            headline=top.get("headline"),
            location=top.get("location"),
            about=_parse_about(main_text),
            connections=connections,
            profile_urn=profile_urn,
            vanity_name=vanity,
            profile_images=top.get("images") or [],
            experience=experiences,
            education=educations,
            skills=skills,
            certifications=certifications,
            languages=languages,
        )
    except ScrapeError:
        raise
    except Exception as e:
        logger.exception("scrape failed for %s", url)
        raise ScrapeError("SCRAPE_FAILED", f"Failed to scrape profile: {e}") from e
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
