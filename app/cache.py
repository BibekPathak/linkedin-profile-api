import time
import threading
from typing import Any, Optional


class TTLCache:
    """Very small thread-safe in-memory cache with TTL."""

    def __init__(self, ttl_seconds: int = 600, max_size: int = 200):
        self._ttl = ttl_seconds
        self._max = max_size
        self._store: dict[str, tuple[float, Any]] = {}
        self._lock = threading.Lock()

    def get(self, key: str) -> Optional[Any]:
        with self._lock:
            item = self._store.get(key)
            if item is None:
                return None
            created, value = item
            if time.time() - created > self._ttl:
                del self._store[key]
                return None
            return value

    def set(self, key: str, value: Any) -> None:
        with self._lock:
            if len(self._store) >= self._max:
                self._store.clear()
            self._store[key] = (time.time(), value)

    def clear(self) -> None:
        with self._lock:
            self._store.clear()
