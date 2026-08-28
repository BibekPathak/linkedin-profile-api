"""Minimal thread-safe service metrics (no external deps).

Tracks profile scrape outcomes, per-field extraction success, timing and cache
hit rate. Exposed as JSON at GET /metrics.
"""
from __future__ import annotations

import threading
import time
from collections import defaultdict
from typing import Optional


class Metrics:
    def __init__(self):
        self._lock = threading.Lock()
        self._started = time.time()
        self._scraped = 0
        self._success = 0
        self._partial = 0
        self._failed = 0
        self._cache_hits = 0
        self._cache_misses = 0
        self._total_ms: list[int] = []
        self._field_success: dict[str, tuple[int, int]] = defaultdict(lambda: (0, 0))  # field -> (ok, attempted)

    # -- records -----------------------------------------------------------
    def record_scrape(self, status: str, duration_ms: int, field_status: Optional[dict[str, bool]] = None) -> None:
        with self._lock:
            self._scraped += 1
            if status == "success":
                self._success += 1
            elif status == "partial":
                self._partial += 1
            else:
                self._failed += 1
            self._total_ms.append(duration_ms)
            # keep a bounded window for the average
            if len(self._total_ms) > 500:
                self._total_ms = self._total_ms[-500:]
            if field_status:
                for field, ok in field_status.items():
                    ok_, attempted = self._field_success[field]
                    self._field_success[field] = (ok_ + (1 if ok else 0), attempted + 1)

    def record_cache(self, hit: bool) -> None:
        with self._lock:
            if hit:
                self._cache_hits += 1
            else:
                self._cache_misses += 1

    # -- views -------------------------------------------------------------
    def summary(self) -> dict:
        with self._lock:
            total_cache = self._cache_hits + self._cache_misses
            avg = round(sum(self._total_ms) / len(self._total_ms)) if self._total_ms else 0
            per_field = {}
            for field, (ok, attempted) in self._field_success.items():
                per_field[field] = round(ok / attempted * 100, 1) if attempted else None
            return {
                "uptime_seconds": int(time.time() - self._started),
                "profiles_scraped": self._scraped,
                "success": self._success,
                "partial": self._partial,
                "failed": self._failed,
                "success_rate": round(self._success / self._scraped * 100, 1) if self._scraped else 0.0,
                "avg_scrape_ms": avg,
                "cache_hits": self._cache_hits,
                "cache_misses": self._cache_misses,
                "cache_hit_rate": round(self._cache_hits / total_cache * 100, 1) if total_cache else 0.0,
                "field_extraction_success_rate": per_field,
            }


metrics = Metrics()
