"""Structured diff for profile data.

Compares two ProfileData dumps (previous vs current) and returns:
  - scalar fields: {before, after}
  - list fields:   {added, removed, modified}

List items are matched on a stable identity key so reorderings don't show as
add+remove.
"""
from __future__ import annotations

from typing import Any

SCALAR_FIELDS = ["name", "headline", "location", "connections", "about", "profile_urn"]
LIST_FIELDS = ["experience", "education", "skills", "certifications", "languages", "profile_images"]

# Identity key per list field — used to match items across snapshots.
IDENTITY_KEYS = {
    "experience": ("title", "company"),
    "education": ("school",),
    "certifications": ("name",),
    "languages": ("name",),
    "skills": ("name",),
    "profile_images": (),
}


def _item_key(item: Any, field: str) -> Any:
    if not isinstance(item, dict):
        return str(item)
    keys = IDENTITY_KEYS.get(field, ())
    parts = []
    for k in keys:
        v = (item.get(k) or "").strip().lower()
        if v:
            parts.append(v)
    if parts:
        return tuple(parts)
    # no identity key (e.g. images) → use full serialization
    return str(item)


def _jsonable(item: Any) -> Any:
    if hasattr(item, "model_dump"):
        return item.model_dump()
    if isinstance(item, dict):
        return {k: _jsonable(v) for k, v in item.items()}
    if isinstance(item, (list, tuple)):
        return [_jsonable(x) for x in item]
    return item


def diff_profiles(previous: dict, current: dict) -> dict:
    changes: dict[str, Any] = {}

    for field in SCALAR_FIELDS:
        before = _jsonable(previous.get(field))
        after = _jsonable(current.get(field))
        if before != after:
            changes[field] = {"before": before, "after": after}

    for field in LIST_FIELDS:
        prev_items = _jsonable(previous.get(field)) or []
        curr_items = _jsonable(current.get(field)) or []

        prev_by_key = {_item_key(it, field): it for it in prev_items}
        curr_by_key = {_item_key(it, field): it for it in curr_items}

        added = []
        removed = []
        modified = []

        for key, item in curr_by_key.items():
            if key not in prev_by_key:
                added.append(item)
            else:
                prev_item = prev_by_key[key]
                if prev_item != item:
                    modified.append({"before": prev_item, "after": item})

        for key, item in prev_by_key.items():
            if key not in curr_by_key:
                removed.append(item)

        # de-duplicate by key for non-dict identity collisions (e.g. duplicate skills)
        def dedupe(items: list) -> list:
            seen: set = set()
            out = []
            for it in items:
                k = _item_key(it, field)
                if k not in seen:
                    seen.add(k)
                    out.append(it)
            return out

        added = dedupe(added)
        removed = dedupe(removed)

        if added or removed or modified:
            changes[field] = {}
            if added:
                changes[field]["added"] = added
            if removed:
                changes[field]["removed"] = removed
            if modified:
                changes[field]["modified"] = modified

    return changes
