"""Validation + confidence scoring for extracted fields.

Confidence is a function of (source, completeness). Sources are ranked:
details_page > main_profile > flight_data. Empty/absent data lowers confidence;
a fully complete details-page list scores highest.
"""
from __future__ import annotations

from app.engine.types import ExtractionResult, FieldSource

# Base confidence per source.
SOURCE_BASE = {
    FieldSource.DETAILS_PAGE: 0.96,
    FieldSource.MAIN_PROFILE: 0.90,
    FieldSource.FLIGHT_DATA: 0.45,
    FieldSource.MISSING: 0.0,
}


def score_confidence(field: str, value, source: FieldSource) -> float:
    if source == FieldSource.MISSING or value is None:
        return 0.0
    base = SOURCE_BASE.get(source, 0.5)

    if isinstance(value, list):
        if len(value) == 0:
            return 0.4  # valid-but-empty (profile genuinely has none)
        # completeness: fraction of items with their primary key present
        key = {
            "experience": "title",
            "education": "school",
            "certifications": "name",
            "languages": "name",
            "skills": "name",
        }.get(field)
        if key:
            complete = sum(1 for it in value if getattr(it, key, None) or (isinstance(it, dict) and it.get(key)))
            ratio = complete / len(value)
            return round(base * (0.75 + 0.25 * ratio), 3)
        return round(base * 0.95, 3)

    if isinstance(value, str) and len(value.strip()) >= 2:
        return base
    return round(base * 0.6, 3)


def is_healthy(expect_nonempty: bool, result: ExtractionResult) -> str:
    """Return 'healthy' or 'degraded' for a field given expected minimums.

    expect_nonempty=True means the top card hinted the profile has this section
    (e.g. a company listed → experience expected). If we got zero items where
    data was expected, the section is degraded.
    """
    if not result.valid:
        return "degraded"
    value = result.value
    if isinstance(value, list):
        if expect_nonempty and len(value) == 0:
            return "degraded"
        return "healthy"
    if expect_nonempty and value is None:
        return "degraded"
    return "healthy"


def expected_nonempty(field: str, main_text: str) -> bool:
    """Heuristic: does the top card / early main text suggest this section has data?

    Only inspects the region before the first 'About'/'Activity' marker to avoid
    matching sidebar/footer noise (e.g. "Skills" in a right-rail suggestion).
    """
    low = main_text.lower()
    cutoff = len(low)
    for marker in ("\nactivity", "\nabout", "\nmore profiles", "\npeople you may know"):
        idx = low.find(marker)
        if 0 <= idx < cutoff:
            cutoff = idx
    top = low[:cutoff]

    if field == "experience":
        return "· full-time" in top or "· part-time" in top or "· intern" in top
    if field == "education":
        return "bachelor" in top or "master" in top or "university" in top or "institute" in top or "school" in top
    # Skills / certifications / languages never appear in the top card as real
    # data (only as "add skills" prompts), so never mark them expected.
    return False
