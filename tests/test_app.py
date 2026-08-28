from app import main, models, scraper


def test_parse_vanity():
    assert (
        scraper.parse_vanity("https://www.linkedin.com/in/bibek-pathak-27630b292/")
        == "bibek-pathak-27630b292"
    )
    assert (
        scraper.parse_vanity("linkedin.com/in/abc")
        == "abc"
    )


def test_parse_vanity_invalid():
    try:
        scraper.parse_vanity("https://example.com/not-linkedin")
        assert False, "should raise"
    except scraper.ScrapeError as e:
        assert e.code == "INVALID_URL"


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
