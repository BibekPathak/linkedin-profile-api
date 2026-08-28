import pytest
from app import scraper
from app.models import ProfileData


def test_clean():
    assert scraper._clean("  a   b  ") == "a b"
    assert scraper._clean("   ") is None
    assert scraper._clean(None) is None


def test_is_date_range():
    assert scraper._is_date_range("Aug 2024 - Present · 2 yrs 1 mo")
    assert scraper._is_date_range("2014 – 2018")
    assert not scraper._is_date_range("Investment Associate")
    assert not scraper._is_date_range("Sorin Investments · Full-time")


def test_parse_company():
    assert scraper._parse_company("Sorin Investments · Full-time") == "Sorin Investments"
    assert scraper._parse_company("Career break") == "Career break"
    assert scraper._parse_company(None) is None


def test_truncate_at_sidebar():
    lines = ["School A", "2014 - 2018", "More profiles for you", "Mohit Mittal"]
    assert scraper._truncate_at_sidebar(lines) == ["School A", "2014 - 2018"]


def test_parse_vanity():
    assert scraper.parse_vanity("https://www.linkedin.com/in/abc-123/") == "abc-123"
    with pytest.raises(scraper.ScrapeError):
        scraper.parse_vanity("https://example.com/x")
