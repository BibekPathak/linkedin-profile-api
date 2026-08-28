from pydantic import BaseModel, Field, HttpUrl
from typing import Optional


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
