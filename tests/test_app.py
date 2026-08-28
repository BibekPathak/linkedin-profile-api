import pytest
from app.engine.capture import parse_vanity
from app.engine.types import ScrapeError
from app import models
from app import main
from app.engine.parsing import clean, is_date_range, parse_company, truncate_at_sidebar


def test_clean():
    assert clean("  a   b  ") == "a b"
    assert clean("   ") is None
    assert clean(None) is None


def test_is_date_range():
    assert is_date_range("Aug 2024 - Present · 2 yrs 1 mo")
    assert is_date_range("2014 – 2018")
    assert not is_date_range("Investment Associate")
    assert not is_date_range("Sorin Investments · Full-time")


def test_parse_company():
    assert parse_company("Sorin Investments · Full-time") == "Sorin Investments"
    assert parse_company("Career break") == "Career break"
    assert parse_company(None) is None


def test_truncate_at_sidebar():
    lines = ["School A", "2014 - 2018", "More profiles for you", "Mohit Mittal"]
    assert truncate_at_sidebar(lines) == ["School A", "2014 - 2018"]


def test_parse_vanity():
    assert parse_vanity("https://www.linkedin.com/in/abc-123/") == "abc-123"
    with pytest.raises(ScrapeError):
        parse_vanity("https://example.com/x")


def test_models_defaults():
    p = models.ProfileData()
    assert p.name is None
    assert p.experience == []
    assert p.profile_images == []
    assert p.skills == []


def test_models_input():
    inp = models.ProfileUrlInput(url="https://www.linkedin.com/in/abc/")
    assert inp.url == "https://www.linkedin.com/in/abc/"


def test_health_endpoint_smoke():
    assert main.app.title == "LinkedIn Profile API"
