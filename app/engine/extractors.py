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


class MainProfileExtractor(BaseExtractor):
    """Top card + About from the main profile page.

    Produces: name, headline, location, connections, about, profile_urn,
    profile_images. Also yields low-confidence experience/education guesses
    from the top-card "Company · School" line (fallback only).
    """

    source = FieldSource.MAIN_PROFILE

    def _top_card(self, cap: PageCapture) -> dict:
        """Parse the top-card block from main page text.

        Layout (blank lines elided):
            0: name
            1: "· 2nd"  (connection degree / self marker)
            2: headline
            3: location
            4: "·"  "Contact info" ...  "connections"
        """
        ls = lines(cap.main_text)
        name = headline = location = connections = None
        if ls:
            name = ls[0]
            for i, l in enumerate(ls):
                if LOCATION_RE.search(l) and "connection" not in l.lower():
                    location = l
                    prev = ls[i - 1] if i >= 1 else None
                    if prev and not re.match(r"^·\s*\d", prev):
                        headline = prev
                    elif i >= 2:
                        headline = ls[i - 2]
                    break
            for i, l in enumerate(ls):
                if l.lower() == "connections" and i >= 1:
                    connections = ls[i - 1]
                    break
        return {"name": name, "headline": headline, "location": location, "connections": connections}

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
        return None

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
        names = parse_pills(cap.main_text, "skills")
        # Empty state is a legitimate, complete answer ("no skills yet").
        # Only mark invalid if the page failed to load at all.
        if not names:
            text = cap.main_text.lower()
            if "skills" not in text and "add skills" not in text:
                return self._missing("skills", "section_not_found")
            return self._result("skills", [], self.source, 0.7, valid=True)
        return self._result("skills", skills_from_pills(cap.main_text), self.source, 0.9, valid=True)


class CertificationsDetailsExtractor(DetailsExtractor):
    section = "certifications"
    field = "certifications"

    def extract(self, ctx: ExtractionContext) -> ExtractionResult:
        cap = self._capture(ctx)
        items = parse_certifications(cap.main_text)
        if not items:
            text = cap.main_text.lower()
            if "certification" not in text:
                return self._missing("certifications", "section_not_found")
            return self._result("certifications", [], self.source, 0.7, valid=True)
        return self._result("certifications", items, self.source, 0.9, valid=True)


class LanguagesDetailsExtractor(DetailsExtractor):
    section = "languages"
    field = "languages"

    def extract(self, ctx: ExtractionContext) -> ExtractionResult:
        cap = self._capture(ctx)
        items = parse_languages(cap.main_text)
        if not items:
            text = cap.main_text.lower()
            if "languages" not in text:
                return self._missing("languages", "section_not_found")
            return self._result("languages", [], self.source, 0.7, valid=True)
        return self._result("languages", items, self.source, 0.9, valid=True)
