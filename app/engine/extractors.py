"""Concrete extractors. Each produces an ExtractionResult for one field.

Extractors operate on captured PageCapture objects (already-fetched HTML/text)
so the engine can run fallback chains without extra network round-trips, and so
they are trivially unit-testable without a browser.
"""
from __future__ import annotations

import re
from typing import Any, Optional

from app.engine.parsing import (
    lines,
    parse_about,
    parse_certifications,
    parse_education,
    parse_experience,
    parse_languages,
    parse_pills,
    skills_from_pills,
)
from app.engine.types import (
    ExtractionContext,
    ExtractionError,
    ExtractionResult,
    FieldSource,
    PageCapture,
)

TOPCARD_URN_RE = re.compile(r"card\.ref(ACoA[A-Za-z0-9_\-]{8,})Topcard")
URN_RE = re.compile(r"urn:li:fsd_profile:([A-Za-z0-9_]+)|\b(ACoA[A-Za-z0-9_\-]{8,})\b")
LOCATION_RE = re.compile(r"[A-Za-z]{2,},\s*[A-Za-z]{2,}(,\s*[A-Za-z]{2,})?$")


class BaseExtractor:
    """Interface every extractor implements."""

    source: FieldSource
    field: str

    def extract(self, ctx: ExtractionContext) -> ExtractionResult:  # pragma: no cover
        raise NotImplementedError

    @staticmethod
    def _result(field: str, value: Any, source: FieldSource, confidence: float, valid: bool = True, warning: str | None = None) -> ExtractionResult:
        return ExtractionResult(
            field=field, value=value, source=source,
            confidence=confidence, valid=valid, warning=warning,
        )

    def _missing(self, field: str, reason: str) -> ExtractionResult:
        return ExtractionResult(
            field=field, value=None, source=FieldSource.MISSING,
            confidence=0.0, valid=False, warning=reason,
        )

    def _images(self, cap: PageCapture) -> list[str]:
        imgs: list[str] = []
        for m in re.finditer(r'https://media\.licdn\.com/dms/image/[^"\s\\]+', cap.html):
            src = m.group(0)
            if "profile-displayphoto" in src or "profile-displaybackgroundimage" in src:
                if src not in imgs:
                    imgs.append(src)
        return imgs

    def _urn(self, cap: PageCapture) -> Optional[str]:
        m = TOPCARD_URN_RE.search(cap.html)
        if not m:
            m = URN_RE.search(cap.html)
        if m:
            raw = m.group(1) or m.group(2)
            if raw:
                return "urn:li:fsd_profile:" + raw
        # NOTE: the mobile page only exposes the *viewer's* member id, which is
        # not the profile's URN — return None rather than a wrong value.
        return None


class MainProfileExtractor(BaseExtractor):
    """Top card + About from the main profile page.

    Produces: name, headline, location, connections, about, profile_urn,
    profile_images. Also yields low-confidence experience/education guesses
    from the top-card "Company · School" line (fallback only).
    """

    source = FieldSource.MAIN_PROFILE

    def _top_card(self, cap: PageCapture) -> dict:
        """Parse the top-card block from main page text.

        Handles two layouts:
        - Playwright `main.innerText`: starts with name.
        - Raw-HTML text extraction (HTTP mode): may start with the page title
          ("<Name> | LinkedIn") and nav noise before the real top card.

        Layout (blank lines elided):
            name
            "· 1st" / "· 2nd"  (connection degree / self marker)
            headline
            location
            "·"  "Contact info" ...  "connections"
        """
        ls = lines(cap.main_text)
        name = headline = location = connections = None

        # Name: prefer the page <title> (strip " | LinkedIn").
        m = re.search(r"^(.*?)\s*\|\s*LinkedIn$", cap.title.strip()) if cap.title else None
        title_name = m.group(1).strip() if m else None

        # Find the first line that looks like a real name (not nav/title noise).
        idx = 0
        for i, l in enumerate(ls):
            if title_name and l == title_name:
                idx = i
                break
            if (l and len(l) <= 40 and not l.startswith("·")
                    and l.lower() not in {"0 notifications", "home", "my network", "jobs", "messaging", "notifications", "me", "learning", "for business", "more", "search", "skip to search"}
                    and "linkedin" not in l.lower()):
                idx = i
                break
        if ls and idx < len(ls):
            name = ls[idx]

        # location: line matching "<City>, <Region>[, <Country>]" but NOT the
        # top-card "Company · School" summary line.
        for i, l in enumerate(ls):
            if LOCATION_RE.search(l) and "connection" not in l.lower():
                if " · " in l:
                    continue  # skip "Sorin Investments · IIIT Roorkee" style line
                location = l
                prev = ls[i - 1] if i >= 1 else None
                if prev and not re.match(r"^·\s*\d", prev) and "contact info" not in prev.lower() and " · " not in prev:
                    headline = prev
                elif i >= 2:
                    headline = ls[i - 2]
                break
        for i, l in enumerate(ls):
            if l.lower() == "connections" and i >= 1:
                connections = ls[i - 1]
                break
        return {"name": name or title_name, "headline": headline, "location": location, "connections": connections}

    def extract(self, ctx: ExtractionContext) -> dict[str, ExtractionResult]:
        cap = ctx.main
        top = self._top_card(cap)
        results: dict[str, ExtractionResult] = {}

        results["name"] = self._result("name", top.get("name"), self.source, 0.99, valid=bool(top.get("name")))
        results["headline"] = self._result("headline", top.get("headline"), self.source, 0.95, valid=bool(top.get("headline")))
        results["location"] = self._result("location", top.get("location"), self.source, 0.92, valid=bool(top.get("location")))

        conn = top.get("connections")
        if not conn:
            m = re.search(r"([\d,+]+\+?)\s+connections", cap.main_text)
            if m:
                conn = m.group(1)
        results["connections"] = self._result("connections", conn, self.source, 0.9, valid=bool(conn))

        about = parse_about(cap.main_text)
        results["about"] = self._result("about", about, self.source, 0.9, valid=bool(about))

        urn = self._urn(cap)
        results["profile_urn"] = self._result("profile_urn", urn, self.source, 0.99, valid=bool(urn))

        imgs = self._images(cap)
        results["profile_images"] = self._result("profile_images", imgs, self.source, 0.9, valid=len(imgs) > 0)
        return results


class DetailsExtractor(BaseExtractor):
    """Base for the /details/* section pages."""

    section: str
    source = FieldSource.DETAILS_PAGE

    def _capture(self, ctx: ExtractionContext) -> PageCapture:
        cap = ctx.details.get(self.section) or ctx.captures.get(self.section)
        if cap is None:
            raise ExtractionError(f"details page for {self.section} not captured")
        return cap


class ExperienceDetailsExtractor(DetailsExtractor):
    section = "experience"
    field = "experience"

    def extract(self, ctx: ExtractionContext) -> ExtractionResult:
        cap = self._capture(ctx)
        items = parse_experience(cap.main_text)
        if not items and "experience" not in cap.main_text.lower():
            return self._missing("experience", "section_not_found")
        return self._result("experience", items, self.source, 0.96 if items else 0.5, valid=True)


class EducationDetailsExtractor(DetailsExtractor):
    section = "education"
    field = "education"

    def extract(self, ctx: ExtractionContext) -> ExtractionResult:
        cap = self._capture(ctx)
        items = parse_education(cap.main_text)
        if not items and "education" not in cap.main_text.lower():
            return self._missing("education", "section_not_found")
        return self._result("education", items, self.source, 0.96 if items else 0.5, valid=True)


class SkillsDetailsExtractor(DetailsExtractor):
    section = "skills"
    field = "skills"

    def extract(self, ctx: ExtractionContext) -> ExtractionResult:
        cap = self._capture(ctx)
        text_low = cap.main_text.lower()
        names = parse_pills(cap.main_text, "skills")
        # Genuine empty-state marker (profile has no skills yet) -> valid empty.
        if "add skills" in text_low or "showcase your skills" in text_low or "when you add new skills" in text_low:
            return self._result("skills", [], self.source, 0.7, valid=True)
        # Real content must have endorsement markers; otherwise the page is
        # JS-hydrated-only (raw HTML via HTTP mode) -> missing.
        has_real_content = "endorsed by" in text_low or "endorsement" in text_low or any(len(n) >= 3 for n in names)
        if not has_real_content:
            return self._missing("skills", "requires_javascript_or_empty")
        if not names:
            return self._result("skills", [], self.source, 0.7, valid=True)
        return self._result("skills", skills_from_pills(cap.main_text), self.source, 0.9, valid=True)


class CertificationsDetailsExtractor(DetailsExtractor):
    section = "certifications"
    field = "certifications"

    def extract(self, ctx: ExtractionContext) -> ExtractionResult:
        cap = self._capture(ctx)
        text_low = cap.main_text.lower()
        items = parse_certifications(cap.main_text)
        if "nothing to see for now" in text_low or "add licenses or certifications" in text_low:
            return self._result("certifications", [], self.source, 0.7, valid=True)
        has_real_content = any(i.name for i in items) and ("issued " in text_low or "show credential" in text_low)
        if not has_real_content:
            return self._missing("certifications", "requires_javascript_or_empty")
        return self._result("certifications", items, self.source, 0.9, valid=True)


class LanguagesDetailsExtractor(DetailsExtractor):
    section = "languages"
    field = "languages"

    def extract(self, ctx: ExtractionContext) -> ExtractionResult:
        cap = self._capture(ctx)
        text_low = cap.main_text.lower()
        items = parse_languages(cap.main_text)
        if "nothing to see for now" in text_low or "add languages" in text_low:
            return self._result("languages", [], self.source, 0.7, valid=True)
        has_real_content = any(i.name for i in items) and any(
            i.proficiency for i in items if i.proficiency
        )
        if not has_real_content:
            return self._missing("languages", "requires_javascript_or_empty")
        return self._result("languages", items, self.source, 0.9, valid=True)


class MobileProfileExtractor(BaseExtractor):
    """Extracts every field from the mobile web (p_mwlite) server-rendered page.

    The mobile page includes about, experience, education, skills,
    certifications and languages in a single HTML response — no JavaScript
    needed. This is the primary strategy for HTTP mode on constrained hosts.
    """

    source = FieldSource.MAIN_PROFILE

    def extract(self, ctx: ExtractionContext) -> dict[str, ExtractionResult]:
        from app.engine.parsing import parse_mobile_profile

        cap = ctx.main
        parsed = parse_mobile_profile(cap.main_text)

        results: dict[str, ExtractionResult] = {}
        results["name"] = self._result("name", parsed.get("name"), self.source, 0.98, valid=bool(parsed.get("name")))
        results["headline"] = self._result("headline", parsed.get("headline"), self.source, 0.92, valid=bool(parsed.get("headline")))
        results["location"] = self._result("location", parsed.get("location"), self.source, 0.9, valid=bool(parsed.get("location")))
        results["connections"] = self._result("connections", parsed.get("connections"), self.source, 0.9, valid=bool(parsed.get("connections")))
        results["about"] = self._result("about", parsed.get("about"), self.source, 0.9, valid=bool(parsed.get("about")))
        results["experience"] = self._result("experience", parsed.get("experience") or [], self.source, 0.95, valid=True)
        results["education"] = self._result("education", parsed.get("education") or [], self.source, 0.95, valid=True)
        results["skills"] = self._result("skills", parsed.get("skills") or [], self.source, 0.9, valid=True)
        results["certifications"] = self._result("certifications", parsed.get("certifications") or [], self.source, 0.9, valid=True)
        results["languages"] = self._result("languages", parsed.get("languages") or [], self.source, 0.9, valid=True)

        urn = self._urn(cap)
        results["profile_urn"] = self._result("profile_urn", urn, self.source, 0.99, valid=bool(urn))

        imgs = self._images(cap)
        results["profile_images"] = self._result("profile_images", imgs, self.source, 0.9, valid=len(imgs) > 0)
        return results
