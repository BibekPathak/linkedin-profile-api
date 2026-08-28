from pydantic import BaseModel, Field
from typing import Any, Optional


class ProfileUrlInput(BaseModel):
    url: str = Field(..., description="LinkedIn profile URL, e.g. https://www.linkedin.com/in/<vanity>/")


class Experience(BaseModel):
    title: Optional[str] = None
    company: Optional[str] = None
    company_linkedin_url: Optional[str] = None
    date_range: Optional[str] = None
    location: Optional[str] = None
    description: Optional[str] = None


class Education(BaseModel):
    school: Optional[str] = None
    degree: Optional[str] = None
    field_of_study: Optional[str] = None
    date_range: Optional[str] = None
    description: Optional[str] = None


class Certification(BaseModel):
    name: Optional[str] = None
    issuer: Optional[str] = None
    date_range: Optional[str] = None


class Language(BaseModel):
    name: Optional[str] = None
    proficiency: Optional[str] = None


class Skill(BaseModel):
    name: Optional[str] = None
    endorsements: Optional[int] = None


class ProfileData(BaseModel):
    name: Optional[str] = None
    headline: Optional[str] = None
    location: Optional[str] = None
    about: Optional[str] = None
    connections: Optional[str] = None
    profile_urn: Optional[str] = None
    vanity_name: Optional[str] = None
    profile_images: list[str] = Field(default_factory=list)
    experience: list[Experience] = Field(default_factory=list)
    education: list[Education] = Field(default_factory=list)
    skills: list[Skill] = Field(default_factory=list)
    certifications: list[Certification] = Field(default_factory=list)
    languages: list[Language] = Field(default_factory=list)
    scraped_at: Optional[str] = None
    cached: Optional[bool] = None


class ErrorResponse(BaseModel):
    error: str
    detail: Optional[str] = None


# ---- debug / metadata / diff ------------------------------------------------

class SourceInfo(BaseModel):
    source: str
    confidence: float = 0.0
    status: str = "missing"  # success | fallback | missing
    duration_ms: int = 0


class ProfileMetadata(BaseModel):
    sources: dict[str, SourceInfo] = Field(default_factory=dict)
    timings_ms: dict[str, int] = Field(default_factory=dict)
    pages_visited: int = 0
    warnings: list[dict] = Field(default_factory=list)
    schema_health: dict[str, str] = Field(default_factory=dict)


class ProfileDebugResponse(BaseModel):
    profile: ProfileData
    metadata: ProfileMetadata


class DiffRequest(BaseModel):
    url: str
    previous: dict[str, Any] = Field(..., description="Previous profile JSON to compare against")


class DiffResponse(BaseModel):
    url: str
    changed: bool
    changes: dict[str, Any] = Field(default_factory=dict)


class SnapshotResponse(BaseModel):
    url: str
    vanity_name: str
    saved: bool


class ChangesResponse(BaseModel):
    url: str
    vanity_name: str
    has_previous: bool
    changes: dict[str, Any] = Field(default_factory=dict)


class MetricsResponse(BaseModel):
    uptime_seconds: int = 0
    profiles_scraped: int = 0
    success: int = 0
    partial: int = 0
    failed: int = 0
    success_rate: float = 0.0
    avg_scrape_ms: int = 0
    cache_hits: int = 0
    cache_misses: int = 0
    cache_hit_rate: float = 0.0
    field_extraction_success_rate: dict[str, Optional[float]] = Field(default_factory=dict)
