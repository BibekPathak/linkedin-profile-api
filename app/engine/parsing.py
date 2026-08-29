"""Shared text-parsing helpers used by extractors.

These operate on plain text captured from the DOM (`main.innerText`), which is
stable enough for line-wise parsing and avoids depending on LinkedIn's hashed
CSS class names.
"""
from __future__ import annotations

import re
from typing import Optional

from app.models import Certification, Education, Experience, Language, Skill

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

ABOUT_STOP = {
    "activity", "featured", "highlights", "post", "posts", "experience", "education",
    "skills", "recommendations", "interests", "more profiles for you",
}

_DATE_RANGE_RE = re.compile(
    r"^(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)|\d{4}\s*[-–]\s*(\d{4}|Present)"
)
_LOCATION_RE = re.compile(r"[A-Za-z]{2,},\s*[A-Za-z]{2,}(,\s*[A-Za-z]{2,})?$")


def clean(s: Optional[str]) -> Optional[str]:
    if s is None:
        return None
    s = re.sub(r"\s+", " ", s).strip()
    return s or None


def lines(text: str) -> list[str]:
    return [l.strip() for l in text.splitlines() if l.strip()]


def truncate_at_sidebar(lines_: list[str]) -> list[str]:
    for idx, l in enumerate(lines_):
        if l.lower() in SIDEBAR_MARKERS:
            return lines_[:idx]
    return lines_


def is_date_range(line: str) -> bool:
    return bool(_DATE_RANGE_RE.match(line))


def parse_company(line: Optional[str]) -> Optional[str]:
    if not line:
        return None
    if "·" in line:
        return line.split("·")[0].strip() or None
    return line or None


def looks_like_location(line: str) -> bool:
    return bool(_LOCATION_RE.search(line)) and len(line) < 60


def strip_degree(line: str) -> str:
    if re.match(r"^·\s*(\d[a-z+]*)$", line, re.I):
        return ""
    return line


def parse_about(main_text: str) -> Optional[str]:
    out: list[str] = []
    in_about = False
    for l in lines(main_text):
        low = l.lower()
        if low == "about":
            in_about = True
            continue
        if in_about:
            if low in ABOUT_STOP or low == "profile language" or low in SIDEBAR_MARKERS:
                break
            if low in NOISE or low.startswith("show more"):
                continue
            out.append(l)
    return clean(" ".join(out)) or None


def parse_experience(text: str) -> list[Experience]:
    """Parse /details/experience/ text into structured entries."""
    lines_ = truncate_at_sidebar(lines(text))
    items: list[Experience] = []
    i, n = 0, len(lines_)
    while i < n:
        line = lines_[i]
        if line.lower() == "experience":
            i += 1
            continue
        if line.lower() in NOISE or line.startswith("·") or re.match(r"^\d+$", line):
            i += 1
            continue
        if i + 2 < n:
            company_line = lines_[i + 1]
            date_line = lines_[i + 2]
            if is_date_range(date_line) and not is_date_range(line) and not is_date_range(company_line):
                title = strip_degree(line) or None
                company = parse_company(company_line)
                date_range = clean(date_line)
                location = None
                desc_parts: list[str] = []
                j = i + 3
                while j < n:
                    lj = lines_[j]
                    if lj.lower() in NOISE:
                        j += 1
                        continue
                    if looks_like_location(lj):
                        location = lj
                        j += 1
                        break
                    break
                while j < n:
                    lj = lines_[j]
                    low = lj.lower()
                    if j + 2 < n and is_date_range(lines_[j + 2]) and not is_date_range(lj) and lj.lower() not in NOISE:
                        break
                    if low in NOISE:
                        j += 1
                        continue
                    if looks_like_location(lj) and location is None:
                        location = lj
                        j += 1
                        continue
                    desc_parts.append(lj)
                    j += 1
                items.append(
                    Experience(
                        title=title,
                        company=company,
                        date_range=date_range,
                        location=location,
                        description=clean(" ".join(desc_parts)) if desc_parts else None,
                    )
                )
                i = j
                continue
        i += 1
    return items


def parse_education(text: str) -> list[Education]:
    lines_ = truncate_at_sidebar(lines(text))
    items: list[Education] = []
    i, n = 0, len(lines_)
    header_found = False
    while i < n:
        line = lines_[i]
        low = line.lower()
        if low == "education":
            header_found = True
            i += 1
            continue
        if low in NOISE or low.startswith("·") or is_date_range(line) or re.match(r"^\d+$", line):
            i += 1
            continue
        school = line
        degree_lines: list[str] = []
        date_range = None
        j = i + 1
        while j < n:
            lj = lines_[j]
            lowj = lj.lower()
            if lowj in NOISE or lowj.startswith("·"):
                break
            if is_date_range(lj):
                date_range = clean(lj)
                j += 1
                break
            if j + 2 < n and not is_date_range(lines_[j + 1]) and is_date_range(lines_[j + 2]):
                break
            degree_lines.append(lj)
            j += 1
        desc_parts: list[str] = []
        while j < n:
            lj = lines_[j]
            lowj = lj.lower()
            if lowj in NOISE or is_date_range(lj) or lowj.startswith("·"):
                break
            if j + 2 < n and not is_date_range(lines_[j + 1]) and is_date_range(lines_[j + 2]):
                break
            desc_parts.append(lj)
            j += 1
        items.append(
            Education(
                school=school,
                degree=clean(" | ".join(degree_lines)) if degree_lines else None,
                date_range=date_range,
                description=clean(" ".join(desc_parts)) if desc_parts else None,
            )
        )
        i = j
    return items if header_found else []


def parse_certifications(text: str) -> list[Certification]:
    lines_ = truncate_at_sidebar(lines(text))
    items: list[Certification] = []
    i, n = 0, len(lines_)
    header_found = False
    while i < n:
        low = lines_[i].lower()
        if low in ("licenses & certifications", "certifications"):
            header_found = True
            i += 1
            continue
        if low in NOISE or low.startswith("·") or low in EMPTY_STATE:
            i += 1
            continue
        name = lines_[i]
        issuer = None
        date_range = None
        j = i + 1
        while j < n:
            lj = lines_[j]
            lowj = lj.lower()
            if lowj == "show credential":
                j += 1
                break
            if lowj in NOISE or lowj.startswith("·"):
                break
            if lj.startswith("Issued "):
                date_range = clean(lj)
            elif issuer is None:
                issuer = lj
            j += 1
        items.append(Certification(name=name, issuer=issuer, date_range=date_range))
        i = j
    return items if header_found else []


def parse_languages(text: str) -> list[Language]:
    lines_ = truncate_at_sidebar(lines(text))
    items: list[Language] = []
    i, n = 0, len(lines_)
    header_found = False
    while i < n:
        low = lines_[i].lower()
        if low == "languages":
            header_found = True
            i += 1
            continue
        if low in NOISE or low.startswith("·") or low in EMPTY_STATE:
            i += 1
            continue
        name = lines_[i]
        proficiency = None
        j = i + 1
        if j < n and not lines_[j].lower().startswith("·") and lines_[j].lower() not in NOISE:
            proficiency = lines_[j]
            j += 1
        items.append(Language(name=name, proficiency=proficiency))
        i = j
    return items if header_found else []


def parse_pills(text: str, header: str) -> list[str]:
    lines_ = truncate_at_sidebar(lines(text))
    out: list[str] = []
    found = False
    for line in lines_:
        low = line.lower()
        if not found:
            if low == header.lower():
                found = True
            continue
        # Ad / modal content signals the real section never rendered (JS-only).
        if low.startswith("ad options") or low.startswith("why am i seeing") or "manage your ad" in low:
            break
        if low in NOISE or re.match(r"^\d+\s*(endorsement|endorsements)$", low) or low.startswith("endorsed by"):
            continue
        if re.match(r"^\d+$", line):
            continue
        if low in EMPTY_STATE:
            continue
        out.append(line)
    return out if found else []


def skills_from_pills(text: str) -> list[Skill]:
    return [Skill(name=n) for n in parse_pills(text, "skills")]


# ---- mobile web (p_mwlite_profile_view) parsing ---------------------------
# The mobile page server-renders the whole profile as flat text. Layout
# (blank lines elided):
#   About this profile
#   <name>
#   ...
#   2nd / Premium member
#   <headline>
#   <school>  <company>
#   <location>
#   <N>+ connections
#   About
#   <about text...>
#   Experience
#   <title> <company> <Mon YYYY> - <Present> <dur> <loc> <desc...>
#   Education
#   <school> <degree> <field> <YYYY> - <YYYY> <desc...>
#   Skills
#   <skill>...
#   Accomplishments
#   <count> Certifications
#   <cert name> <issuer> ...
#   <count> Languages
#   <language>...

MOBILE_SECTION_HEADERS = {
    "about": "About",
    "experience": "Experience",
    "education": "Education",
    "skills": "Skills",
    "certifications": "Certifications",
    "languages": "Languages",
    "accomplishments": "Accomplishments",
    "volunteer": "Volunteer Experience",
    "featured": "Featured",
    "activity": "Activity",
    "highlights": "Highlights",
}

_MONTH = r"(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)"
_MOBILE_DATE = re.compile(rf"^{_MONTH}\s*\d{{4}}$|^\d{{4}}$")


def _is_mobile_date(line: str) -> bool:
    return bool(_MOBILE_DATE.match(line))


def _strip_mobile_noise(line: str) -> bool:
    low = line.lower()
    return low in {"see more", "see less", "…more", "…less", "more", "less", "-"} or line.startswith("…")


def parse_mobile_profile(text: str) -> dict:
    """Parse the mobile profile page text into a structured dict.

    Returns keys: name, headline, location, connections, about, experience,
    education, skills, certifications, languages.
    """
    lines_ = [l.strip() for l in text.splitlines() if l.strip()]
    result: dict = {
        "name": None, "headline": None, "location": None, "connections": None,
        "about": None, "experience": [], "education": [], "skills": [],
        "certifications": [], "languages": [],
    }

    # top card: name after "About this profile" (other-view) or "Share Profile" (self-view)
    for i, l in enumerate(lines_):
        if l in ("About this profile", "Share Profile") and i + 1 < len(lines_):
            result["name"] = lines_[i + 1]
            break
    for i, l in enumerate(lines_):
        if re.match(r"^[\d,+]+\+? connections$", l):
            result["connections"] = l.split()[0]
            break
    for l in lines_:
        if looks_like_location(l) and " · " not in l:
            # Prefer "City, Region, Country" (3 parts) over "School, Campus" (2).
            parts = [p.strip() for p in l.split(",") if p.strip()]
            if len(parts) >= 3:
                result["location"] = l
                break
    if result["location"] is None:
        for l in lines_:
            if looks_like_location(l) and " · " not in l and "Institute" not in l and "University" not in l and "School" not in l:
                result["location"] = l
                break
    # headline: the line right after the LAST top-card name occurrence
    name_idx = [i for i, l in enumerate(lines_) if l == result["name"]]
    if name_idx:
        i = name_idx[-1]
        for j in range(i + 1, min(i + 12, len(lines_))):
            cand = lines_[j]
            if cand in ("1st", "2nd", "3rd", "Premium member", "Member") or cand.startswith("·"):
                continue
            if re.match(r"^Joined \d{4}$", cand) or "contact information" in cand.lower():
                continue
            if looks_like_location(cand) or "connections" in cand:
                break
            result["headline"] = cand
            break

    def _slice_until(header: str, stop_headers: set[str]) -> list[str]:
        """Lines after `header` until a stop header or the section's own end."""
        start = None
        for i, l in enumerate(lines_):
            if l == header:
                start = i + 1
                break
        if start is None:
            return []
        out: list[str] = []
        for l in lines_[start:]:
            if l in stop_headers:
                break
            out.append(l)
        return out

    SECTION_STOPS = set(MOBILE_SECTION_HEADERS.values())

    _ADD_PROMPTS = {
        "add experience", "add education", "add skills", "add volunteering",
        "add accomplishments", "add certifications", "add languages", "add featured",
        "add a link", "add media", "add a photo", "upload a document",
        "add past positions to find new career opportunities or to re",
        "add your degree and college, get 11x more profile views. con",
        "add skills to showcase your strengths, get your profile noti",
        "ask to be recommended", "recommendations", "publications", "patents",
        "courses", "projects", "honors & awards", "test scores",
        "have more experience?", "have more education?",
        "edit", "open to job opportunities", "product engineer", "roles",
        "see all details", "visible to", "only recruiters", "private to you",
        "organizations", "certification", "accomplishments",
        "content credentials", "source or history information is available for this media.",
        "learn more", "add accomplishments",
    }
    _SELF_STOPS = {"Contact", "Other similar profiles", "Recommendations", "Accomplishments"}

    # About
    about_lines = _slice_until("About", SECTION_STOPS)
    result["about"] = clean(" ".join(
        l for l in about_lines if not _strip_mobile_noise(l) and l.lower() not in _ADD_PROMPTS
    ))

    # Experience
    exp_lines = _slice_until("Experience", SECTION_STOPS)
    exp_lines = [l for l in exp_lines if l.lower() not in _ADD_PROMPTS]
    result["experience"] = _parse_mobile_experience(exp_lines)

    # Education (stop at Volunteer Experience / Skills)
    edu_lines = _slice_until("Education", {"Volunteer Experience", "Skills", "Accomplishments", "Recommendations"})
    edu_lines = [
        l for l in edu_lines
        if l.lower() not in _ADD_PROMPTS
        and l != "Add education"
        and not l.lower().startswith("add your degree")
        and not l.lower().startswith("add past positions")
        and not l.lower().startswith("have more")
    ]
    result["education"] = _parse_mobile_education(edu_lines)

    # Skills (skills are single lines; stop at Accomplishments / Recommendations / Contact)
    skills_lines = _slice_until("Skills", _SELF_STOPS | {"Certifications", "Accomplishments"})
    if "add skills" in {l.lower() for l in skills_lines}:
        skills_lines = []
    result["skills"] = [
        Skill(name=l) for l in skills_lines
        if not _strip_mobile_noise(l)
        and l not in ("See more", "See less")
        and l.lower() not in _ADD_PROMPTS
        and not l.lower().startswith("add ")
        and l.lower() != "skills"
    ]

    # Certifications
    cert_lines = _slice_until("Certifications", _SELF_STOPS | {"Languages", "Accomplishments"})
    result["certifications"] = _parse_mobile_certifications(cert_lines)

    # Languages (languages are single words; stop at a numeric count / Courses / Contact)
    lang_lines: list[str] = []
    for l in _slice_until("Languages", _SELF_STOPS | {"Courses", "Contact"}):
        if re.match(r"^\d+$", l) or l == "Courses" or l.lower() in _ADD_PROMPTS or l.lower().startswith("add "):
            break
        lang_lines.append(l)
    result["languages"] = [
        Language(name=l) for l in lang_lines
        if not _strip_mobile_noise(l) and re.match(r"^[A-Za-z][A-Za-z\s'\-]{1,30}$", l)
    ]

    return result


def _parse_mobile_experience(lines_: list[str]) -> list[Experience]:
    # Each entry is delimited by "See less" (mobile collapses each card).
    blocks: list[list[str]] = []
    cur: list[str] = []
    for l in lines_:
        if l in ("See less", "…less"):
            if cur:
                blocks.append(cur)
                cur = []
            continue
        cur.append(l)
    if cur:
        blocks.append(cur)

    items: list[Experience] = []
    for block in blocks:
        b = [l for l in block if not _strip_mobile_noise(l) and l not in ("See more", "See less")]
        if not b:
            continue
        title = b[0]
        company = None
        date_range = None
        location = None
        desc: list[str] = []
        j = 1
        if j < len(b) and not _is_mobile_date(b[j]):
            company = b[j]
            j += 1
        # date span
        if j < len(b) and _is_mobile_date(b[j]):
            start_d = b[j]
            j += 1
            if j < len(b) and b[j] == "-":
                j += 1
            end_d = None
            if j < len(b) and (_is_mobile_date(b[j]) or b[j] == "Present"):
                end_d = b[j]
                j += 1
            duration = None
            if j < len(b) and re.match(r"^\d+ (yrs?|mos?)( \d+ (yrs?|mos?))?$", b[j]):
                duration = b[j]
                j += 1
            span = clean(" - ".join(x for x in (start_d, end_d) if x))
            date_range = f"{span} · {duration}" if duration and span else (span or duration)
        # location
        if j < len(b) and looks_like_location(b[j]):
            location = b[j]
            j += 1
        desc = b[j:]
        items.append(Experience(
            title=title, company=company, date_range=date_range,
            location=location, description=clean(" ".join(desc)) if desc else None,
        ))
    return items


_INSTITUTION_RE = re.compile(
    r"(School|University|Institute|Academy|College|\bIIT\b|\bIIIT\b|\bNIT\b|Stoa)",
    re.I,
)


def _parse_mobile_education(lines_: list[str]) -> list[Education]:
    # Each education entry begins at a line that looks like an institution
    # (or is the first line). Descriptions never contain such a line, so this
    # is a reliable split point even when "See less" delimiters are absent.
    blocks: list[list[str]] = []
    cur: list[str] = []
    for l in lines_:
        if _strip_mobile_noise(l) or l in ("See more", "See less"):
            continue
        if _INSTITUTION_RE.search(l) and cur and any(_is_mobile_date(x) for x in cur):
            blocks.append(cur)
            cur = []
        cur.append(l)
    if cur:
        blocks.append(cur)

    items: list[Education] = []
    for block in blocks:
        b = [l for l in block if not _strip_mobile_noise(l)]
        if not b:
            continue
        school = b[0]
        degree_lines: list[str] = []
        date_range = None
        j = 1
        while j < len(b):
            lj = b[j]
            if _is_mobile_date(lj):
                start_d = lj
                j += 1
                if j < len(b) and b[j] == "-":
                    j += 1
                end_d = None
                if j < len(b) and (_is_mobile_date(b[j]) or b[j] == "Present"):
                    end_d = b[j]
                    j += 1
                date_range = clean(" - ".join(x for x in (start_d, end_d) if x))
                break
            degree_lines.append(lj)
            j += 1
        desc = b[j:]
        items.append(Education(
            school=school,
            degree=clean(" | ".join(degree_lines)) if degree_lines else None,
            date_range=date_range,
            description=clean(" ".join(desc)) if desc else None,
        ))
    return items


def _parse_mobile_certifications(lines_: list[str]) -> list[Certification]:
    items: list[Certification] = []
    i, n = 0, len(lines_)
    while i < n:
        l = lines_[i]
        if _strip_mobile_noise(l) or l in ("See more", "See less") or re.match(r"^\d+$", l):
            i += 1
            continue
        name = l
        issuer = None
        j = i + 1
        if j < n and not _strip_mobile_noise(lines_[j]) and not re.match(r"^\d+$", lines_[j]):
            issuer = lines_[j]
            j += 1
        items.append(Certification(name=name, issuer=issuer))
        i = j
    return items
