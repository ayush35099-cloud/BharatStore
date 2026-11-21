"""
BharatStore In-Memory Thread-Safe TTL Cache
Optimizes repeated read-heavy catalog, store hubs, and multi-store price comparisons.
"""

import time
import threading
from typing import Any, Optional, Dict, Tuple, List


class TTLCache:
    def __init__(self, default_ttl_sec: float = 60.0):
        self._cache: Dict[str, Tuple[Any, float]] = {}
        self._lock = threading.Lock()
        self._default_ttl = default_ttl_sec

    def get(self, key: str) -> Optional[Any]:
        with self._lock:
            entry = self._cache.get(key)
            if not entry:
                return None
            val, expiry = entry
            if time.time() > expiry:
                del self._cache[key]
                return None
            return val

    def set(self, key: str, val: Any, ttl: Optional[float] = None) -> None:
        with self._lock:
            t = ttl if ttl is not None else self._default_ttl
            self._cache[key] = (val, time.time() + t)

    def delete(self, key: str) -> None:
        with self._lock:
            self._cache.pop(key, None)

    def invalidate_prefix(self, prefix: str) -> None:
        with self._lock:
            keys_to_del = [k for k in self._cache if k.startswith(prefix)]
            for k in keys_to_del:
                del self._cache[k]

    def clear(self) -> None:
        with self._lock:
            self._cache.clear()

    def stats(self) -> Dict[str, Any]:
        with self._lock:
            now = time.time()
            active_keys = [k for k, (_, exp) in self._cache.items() if exp > now]
            return {
                "total_entries": len(self._cache),
                "active_entries": len(active_keys),
                "keys": active_keys
            }


# Singleton cache instance across Flask processes
app_cache = TTLCache(default_ttl_sec=60.0)
