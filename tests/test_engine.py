"""Unit tests for the adaptive extraction engine (no browser needed)."""
import asyncio

from app.engine.capture import capture_profile
from app.engine.engine import ExtractionEngine
from app.engine.parsing import parse_experience, parse_education, parse_certifications, parse_languages, parse_about
from app.engine.types import ExtractionContext, FieldSource, PageCapture
from app.engine.validation import score_confidence, is_healthy, expected_nonempty


def _cap(text: str) -> PageCapture:
    return PageCapture(url="https://x", main_text=text, html="", title="")


def run(coro):
    return asyncio.run(coro)


def test_parse_experience_entries():
    text = """Experience

Investment Associate

Sorin Investments · Full-time

Aug 2024 - Present · 2 yrs 1 mo

Bengaluru, Karnataka, India

Sorin is a Series A/B Fund, investing across sectors.

Investment Associate

PeerCapital

Jul 2022 - Jul 2024 · 2 yrs 1 mo

Bengaluru, Karnataka, India"""
    items = parse_experience(text)
    assert len(items) == 2
    assert items[0].title == "Investment Associate"
    assert items[0].company == "Sorin Investments"
    assert items[0].date_range == "Aug 2024 - Present · 2 yrs 1 mo"
    assert items[1].company == "PeerCapital"


def test_parse_education_entries():
    text = """Education

Indian Institute of Technology, Roorkee

Bachelor's degree, Bachelor of Technology (B.Tech.), Chemical Engineering

2014 – 2018

Delhi Public School Ghaziabad Society

Secondary and Senior Secondary

2010 – 2014"""
    items = parse_education(text)
    assert len(items) == 2
    assert items[0].school == "Indian Institute of Technology, Roorkee"
    assert items[0].date_range == "2014 – 2018"


def test_parse_certifications():
    text = """Licenses & certifications

Private Equity and Venture Capital

Coursera

Issued Jan 2017 · Expired Mar 2017

Show credential

Investment Strategy

Coursera

Issued Sep 2016 · Expired Oct 2016"""
    items = parse_certifications(text)
    assert len(items) == 2
    assert items[0].name == "Private Equity and Venture Capital"
    assert items[0].issuer == "Coursera"


def test_parse_languages_pairs():
    text = """Languages

English

Professional working proficiency

Hindi

Native or bilingual proficiency"""
    items = parse_languages(text)
    assert len(items) == 2
    assert items[0].name == "English"
    assert items[0].proficiency == "Professional working proficiency"


def test_parse_about_stops_at_activity():
    text = """Abhishek Pathak

About

I am an investor.

Activity

Post something"""
    assert parse_about(text) == "I am an investor."


def test_engine_uses_details_then_flight():
    from app.engine.engine import FIELD_EXTRACTORS

    ctx = ExtractionContext(vanity="abc", profile_url="https://x")
    ctx.main = _cap("Software Engineer\nSome Company · Full-time")
    ctx.details["experience"] = _cap(
        "Experience\n\nEngineer\n\nAcme · Full-time\n\nJan 2020 - Present · 2 yrs"
    )
    ctx.details["education"] = _cap("Education\n\nMIT\n\nBachelor's degree\n\n2015 – 2019")
    ctx.details["skills"] = _cap("Skills\n\nPython\n\nRust")
    ctx.details["certifications"] = _cap("Licenses & certifications\n\nNothing to see for now")
    ctx.details["languages"] = _cap("Languages\n\nNothing to see for now")

    outcome = run(ExtractionEngine(None).extract(ctx))
    p = outcome.profile
    assert p.name == "Software Engineer"
    assert len(p.experience) == 1
    assert p.experience[0].company == "Acme"
    assert len(p.education) == 1
    assert p.education[0].school == "MIT"
    assert len(p.skills) == 2
    assert p.certifications == []
    assert p.languages == []
    # provenance recorded
    assert outcome.provenance["experience"].result.source == FieldSource.DETAILS_PAGE
    assert outcome.provenance["experience"].result.confidence > 0.9


def test_engine_falls_back_when_details_missing():
    from app.engine.engine import FIELD_EXTRACTORS

    ctx = ExtractionContext(vanity="abc", profile_url="https://x")
    ctx.main = _cap("Software Engineer\nAcme · Full-time")
    # no details pages captured -> experience chain runs, flight grep on empty html -> missing
    outcome = run(ExtractionEngine(None).extract(ctx))
    p = outcome.profile
    assert p.name == "Software Engineer"
    # experience should be missing (no valid strategy)
    assert not outcome.provenance["experience"].result.valid


def test_confidence_scoring():
    assert score_confidence("name", "John Doe", FieldSource.MAIN_PROFILE) >= 0.9
    assert score_confidence("experience", [], FieldSource.DETAILS_PAGE) == 0.4
    assert score_confidence("skills", None, FieldSource.MISSING) == 0.0
    assert score_confidence("name", "x", FieldSource.FLIGHT_DATA) > 0


def test_schema_health():
    from app.engine.types import ExtractionResult
    r = ExtractionResult(field="experience", value=[], source=FieldSource.DETAILS_PAGE, valid=True)
    assert is_healthy(expect_nonempty=True, result=r) == "degraded"
    assert is_healthy(expect_nonempty=False, result=r) == "healthy"


def test_expected_nonempty_heuristics():
    assert expected_nonempty("experience", "Software Engineer\nAcme · Full-time")
    assert not expected_nonempty("experience", "Nothing here")
    assert expected_nonempty("education", "Studied at MIT University")


def test_empty_state_is_valid_not_degraded():
    """A profile that genuinely has no skills/certs/languages should report
    healthy empty lists, not degraded failures."""
    from app.engine.engine import ExtractionEngine

    ctx = ExtractionContext(vanity="abc", profile_url="https://x")
    ctx.main = _cap("John Doe\nEngineer\nAcme · Full-time\nKolkata, India")
    ctx.details["skills"] = _cap("Skills\n\nWhen you add new skills they’ll show up here\nAdd skills")
    ctx.details["certifications"] = _cap("Licenses & certifications\n\nNothing to see for now")
    ctx.details["languages"] = _cap("Languages\n\nNothing to see for now")
    ctx.details["experience"] = _cap("Experience\n\nEngineer\nAcme · Full-time\nJan 2020 - Present")
    ctx.details["education"] = _cap("Education\n\nNothing to see for now")

    outcome = run(ExtractionEngine(None).extract(ctx))
    p = outcome.profile
    assert p.skills == []
    assert p.certifications == []
    assert p.languages == []
    # provenance: details page valid, not missing
    assert outcome.provenance["skills"].result.valid is True
    assert outcome.provenance["skills"].result.source == FieldSource.DETAILS_PAGE
    # schema health: not degraded when nothing expected
    assert outcome.diagnostics.schema_health["skills"] == "healthy"
    assert outcome.diagnostics.schema_health["certifications"] == "healthy"
