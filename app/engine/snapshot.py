"""In-memory snapshot store.

Stores the most recent ProfileData per vanity name so the diff/changes endpoints
can compare against a previous scrape. Volatile: resets on process restart
(documented limitation — Render's free filesystem is ephemeral anyway).
"""
from __future__ import annotations

import threading
from typing import Optional


class SnapshotStore:
    def __init__(self, max_snapshots: int = 2000):
        self._store: dict[str, dict] = {}
        self._lock = threading.Lock()
        self._max = max_snapshots

    def save(self, vanity: str, profile: dict) -> None:
        with self._lock:
            if len(self._store) >= self._max:
                # drop oldest (dict preserves insertion order)
                self._store.pop(next(iter(self._store)))
            self._store[vanity] = profile

    def get(self, vanity: str) -> Optional[dict]:
        with self._lock:
            return self._store.get(vanity)

    def has(self, vanity: str) -> bool:
        with self._lock:
            return vanity in self._store
