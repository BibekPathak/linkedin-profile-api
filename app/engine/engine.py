"""The adaptive extraction engine.

Owns the per-field extractor chains and the fallback logic. It captures each
page exactly once, then runs strategies in order and keeps the first *valid*
result, mirroring:

    for extractor in extractors:
        try:
            result = extractor.extract(ctx)
            if result.valid:
                return result
        except ExtractionError:
            continue
"""
from __future__ import annotations

import logging
import time
from typing import Callable

from app.engine.extractors import (
    BaseExtractor,
    CertificationsDetailsExtractor,
    EducationDetailsExtractor,
    ExperienceDetailsExtractor,
    LanguagesDetailsExtractor,
    MainProfileExtractor,
    SkillsDetailsExtractor,
)
from app.engine.flight import FlightDataExtractor
from app.engine.types import (
    Diagnostics,
    ExtractionContext,
    ExtractionError,
    ExtractionOutcome,
    ExtractionResult,
    FieldProvenance,
    FieldSource,
)
from app.engine.validation import expected_nonempty, is_healthy, score_confidence
from app.models import ProfileData

logger = logging.getLogger(__name__)

SCALAR_FIELDS = ["name", "headline", "location", "connections", "about", "profile_urn", "profile_images"]

# Per-field extractor chains. First *valid* result wins; later entries are
# fallbacks used when a page changes or fails.
FIELD_EXTRACTORS: dict[str, list[BaseExtractor]] = {
    "experience": [ExperienceDetailsExtractor(), FlightDataExtractor("experience")],
    "education": [EducationDetailsExtractor(), FlightDataExtractor("education")],
    "skills": [SkillsDetailsExtractor(), FlightDataExtractor("skills")],
    "certifications": [CertificationsDetailsExtractor(), FlightDataExtractor("certifications")],
    "languages": [LanguagesDetailsExtractor(), FlightDataExtractor("languages")],
}


class ExtractionEngine:
    def __init__(self, capture: Callable[[ExtractionContext], ExtractionContext]):
        self._capture = capture

    async def extract(self, ctx: ExtractionContext) -> ExtractionOutcome:
        # Capture only if the context is empty (e.g. tests pre-populate it).
        if self._capture and (ctx.main is None or not ctx.main.main_text):
            ctx = await self._capture(ctx)
        provenance: dict[str, FieldProvenance] = {}
        diagnostics = Diagnostics()
        diagnostics.pages_visited = 1 + len(ctx.details)

        # scalar fields from main profile
        main_extractor = MainProfileExtractor()
        scalars = main_extractor.extract(ctx)
        for field in SCALAR_FIELDS:
            res = scalars.get(field)
            if res is None:
                res = ExtractionResult(field=field, value=None, source=FieldSource.MISSING, valid=False, warning="not_found")
            else:
                res.confidence = score_confidence(field, res.value, res.source)
                res.valid = res.valid and res.value is not None
            provenance[field] = FieldProvenance(field=field, result=res)

        # section fields via chains
        for field, chain in FIELD_EXTRACTORS.items():
            result = self._run_chain(ctx, field, chain)
            provenance[field] = FieldProvenance(field=field, result=result)
            diagnostics.timings_ms.setdefault(field, result.duration_ms)
            if result.warning:
                diagnostics.warnings.append({"section": field, "reason": result.warning, "fallback_attempted": True})
            # schema drift
            expect = expected_nonempty(field, ctx.main.main_text)
            diagnostics.schema_health[field] = is_healthy(expect, result)

        profile = self._build_profile(ctx, provenance)
        return ExtractionOutcome(profile=profile, provenance=provenance, diagnostics=diagnostics)

    def _run_chain(self, ctx: ExtractionContext, field: str, chain: list[BaseExtractor]) -> ExtractionResult:
        for extractor in chain:
            start = time.time()
            try:
                result = extractor.extract(ctx)
                result.duration_ms = int((time.time() - start) * 1000)
                result.field = field
                result.confidence = score_confidence(field, result.value, result.source)
                if result.valid:
                    return result
                logger.info("extractor %s for %s invalid (source=%s)", type(extractor).__name__, field, result.source.value)
            except ExtractionError as e:
                logger.warning("extractor %s for %s failed: %s", type(extractor).__name__, field, e)
                continue
        # all strategies failed
        return ExtractionResult(
            field=field, value=None, source=FieldSource.MISSING,
            valid=False, warning="all_strategies_failed",
        )

    @staticmethod
    def _build_profile(ctx: ExtractionContext, provenance: dict[str, FieldProvenance]) -> ProfileData:
        def v(field: str):
            return provenance[field].result.value if field in provenance else None

        return ProfileData(
            name=v("name"),
            headline=v("headline"),
            location=v("location"),
            about=v("about"),
            connections=v("connections"),
            profile_urn=v("profile_urn"),
            vanity_name=ctx.vanity,
            profile_images=v("profile_images") or [],
            experience=v("experience") or [],
            education=v("education") or [],
            skills=v("skills") or [],
            certifications=v("certifications") or [],
            languages=v("languages") or [],
        )
