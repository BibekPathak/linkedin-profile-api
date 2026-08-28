"""Core types for the adaptive extraction engine."""
from __future__ import annotations

import enum
from dataclasses import dataclass, field
from typing import Any, Optional

from app.models import ProfileData


class FieldSource(enum.Enum):
    MAIN_PROFILE = "main_profile"
    DETAILS_PAGE = "details_page"
    FLIGHT_DATA = "flight_data"
    MISSING = "missing"


@dataclass
class ExtractionResult:
    """Outcome of one extractor for one field."""

    field: str
    value: Any
    source: FieldSource
    confidence: float = 0.0
    valid: bool = False
    duration_ms: int = 0
    warning: Optional[str] = None

    def as_dict(self) -> dict:
        return {
            "source": self.source.value,
            "confidence": round(self.confidence, 3),
            "valid": self.valid,
            "duration_ms": self.duration_ms,
            "warning": self.warning,
        }


@dataclass
class PageCapture:
    """Captured DOM text + HTML for one visited URL."""

    url: str
    main_text: str
    html: str
    title: str
    duration_ms: int = 0


@dataclass
class ExtractionContext:
    """Everything captured during a single profile scrape."""

    vanity: str
    profile_url: str
    main: Optional[PageCapture] = None
    details: dict[str, PageCapture] = field(default_factory=dict)
    # page captures by section name (experience, education, ...)
    captures: dict[str, PageCapture] = field(default_factory=dict)


@dataclass
class FieldProvenance:
    field: str
    result: ExtractionResult


@dataclass
class Diagnostics:
    pages_visited: int = 0
    timings_ms: dict[str, int] = field(default_factory=dict)
    warnings: list[dict] = field(default_factory=list)
    schema_health: dict[str, str] = field(default_factory=dict)


@dataclass
class ExtractionOutcome:
    profile: ProfileData
    provenance: dict[str, FieldProvenance]
    diagnostics: Diagnostics


class ExtractionError(Exception):
    """Raised by an extractor when it cannot produce a result at all."""


class ScrapeError(Exception):
    def __init__(self, code: str, detail: str):
        self.code = code
        self.detail = detail
        super().__init__(detail)
