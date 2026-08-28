"""Unit tests for service metrics."""
import pytest

from app.metrics import Metrics


def test_metrics_empty():
    m = Metrics()
    s = m.summary()
    assert s["profiles_scraped"] == 0
    assert s["success_rate"] == 0.0


def test_metrics_record():
    m = Metrics()
    m.record_scrape("success", 1000, {"experience": True, "education": True})
    m.record_scrape("partial", 2000, {"experience": True, "education": False})
    m.record_scrape("failed", 0)
    m.record_cache(hit=True)
    m.record_cache(hit=False)
    s = m.summary()
    assert s["profiles_scraped"] == 3
    assert s["success"] == 1
    assert s["partial"] == 1
    assert s["failed"] == 1
    assert s["success_rate"] == pytest.approx(33.3, abs=0.1)
    assert s["avg_scrape_ms"] == 1000  # (1000 + 2000) / 2
    assert s["cache_hit_rate"] == 50.0
    assert s["field_extraction_success_rate"]["experience"] == 100.0
    assert s["field_extraction_success_rate"]["education"] == 50.0


def test_metrics_field_never_attempted():
    m = Metrics()
    m.record_scrape("success", 500, {"experience": True})
    s = m.summary()
    assert s["field_extraction_success_rate"]["experience"] == 100.0
    assert s["field_extraction_success_rate"].get("skills") is None
