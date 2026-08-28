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
    while i < n:
        line = lines_[i]
        low = line.lower()
        if low == "education":
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
    return items


def parse_certifications(text: str) -> list[Certification]:
    lines_ = truncate_at_sidebar(lines(text))
    items: list[Certification] = []
    i, n = 0, len(lines_)
    while i < n:
        low = lines_[i].lower()
        if low in ("licenses & certifications", "certifications"):
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
    return items


def parse_languages(text: str) -> list[Language]:
    lines_ = truncate_at_sidebar(lines(text))
    items: list[Language] = []
    i, n = 0, len(lines_)
    while i < n:
        low = lines_[i].lower()
        if low == "languages":
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
    return items


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
        if low in NOISE or re.match(r"^\d+\s*(endorsement|endorsements)$", low) or low.startswith("endorsed by"):
            continue
        if re.match(r"^\d+$", line):
            continue
        if low in EMPTY_STATE:
            continue
        out.append(line)
    return out


def skills_from_pills(text: str) -> list[Skill]:
    return [Skill(name=n) for n in parse_pills(text, "skills")]
