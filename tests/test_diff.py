"""Unit tests for the diff engine and snapshot store."""
from app.engine.diff import diff_profiles
from app.engine.snapshot import SnapshotStore


def test_diff_scalar_change():
    before = {"headline": "Software Engineer at X", "name": "A"}
    after = {"headline": "Senior Software Engineer at Y", "name": "A"}
    changes = diff_profiles(before, after)
    assert changes["headline"] == {"before": "Software Engineer at X", "after": "Senior Software Engineer at Y"}
    assert "name" not in changes


def test_diff_lists_added_removed_modified():
    before = {
        "experience": [
            {"title": "A", "company": "X", "date_range": "2020 - 2021"},
            {"title": "B", "company": "Y", "date_range": "2019 - 2020"},
        ],
        "skills": [{"name": "PHP"}],
    }
    after = {
        "experience": [
            {"title": "A", "company": "X", "date_range": "2020 - 2021"},  # unchanged
            {"title": "C", "company": "Z", "date_range": "2022 - 2023"},  # added
        ],
        "skills": [{"name": "Rust"}, {"name": "Solana"}],
    }
    changes = diff_profiles(before, after)
    assert "added" in changes["experience"]
    assert any(e["title"] == "C" for e in changes["experience"]["added"])
    assert "removed" in changes["experience"]
    assert any(e["title"] == "B" for e in changes["experience"]["removed"])
    assert changes["skills"]["added"] == [{"name": "Rust"}, {"name": "Solana"}]
    assert changes["skills"]["removed"] == [{"name": "PHP"}]


def test_diff_modified():
    before = {"experience": [{"title": "A", "company": "X", "date_range": "2020 - 2021"}]}
    after = {"experience": [{"title": "A", "company": "X", "date_range": "2020 - 2024"}]}
    changes = diff_profiles(before, after)
    mod = changes["experience"]["modified"]
    assert mod[0]["before"]["date_range"] == "2020 - 2021"
    assert mod[0]["after"]["date_range"] == "2020 - 2024"


def test_diff_no_changes():
    same = {"name": "A", "experience": [{"title": "T", "company": "C"}]}
    assert diff_profiles(same, same) == {}


def test_diff_reorder_no_false_positive():
    a = {"experience": [{"title": "T1", "company": "C1"}, {"title": "T2", "company": "C2"}]}
    b = {"experience": [{"title": "T2", "company": "C2"}, {"title": "T1", "company": "C1"}]}
    assert diff_profiles(a, b) == {}


def test_snapshot_store():
    store = SnapshotStore()
    assert not store.has("abc")
    store.save("abc", {"name": "John"})
    assert store.has("abc")
    assert store.get("abc") == {"name": "John"}
    assert store.get("nope") is None
