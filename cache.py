"""In-memory cache for AIX runs.

Prevents huge (>70KB) JSON roundtrips through the host LLM agent.
"""

from __future__ import annotations

import time
import uuid
from typing import Any, Dict, Optional


class RunCache:
    def __init__(self, ttl_seconds: int = 86400, max_items: int = 100):
        self._cache: Dict[str, Dict[str, Any]] = {}
        self._ttl_seconds = ttl_seconds
        self._max_items = max_items

    def store(self, run_result: Dict[str, Any]) -> str:
        """Stores a run result and returns a unique run_id."""
        self._evict_expired()
        if len(self._cache) >= self._max_items:
            oldest_key = min(self._cache.keys(), key=lambda k: self._cache[k]["stored_at"])
            del self._cache[oldest_key]

        run_id = f"run_{uuid.uuid4().hex[:8]}"
        self._cache[run_id] = {
            "run": run_result,
            "stored_at": time.time(),
        }
        return run_id

    def get(self, run_id: str) -> Optional[Dict[str, Any]]:
        """Retrieves a cached run result if still valid."""
        entry = self._cache.get(run_id)
        if not entry:
            return None
        if time.time() - entry["stored_at"] > self._ttl_seconds:
            del self._cache[run_id]
            return None
        return entry["run"]

    def update(self, run_id: str, updated_run: Dict[str, Any]) -> bool:
        """Updates an existing run in place."""
        if run_id in self._cache:
            self._cache[run_id]["run"] = updated_run
            self._cache[run_id]["stored_at"] = time.time()
            return True
        return False

    def _evict_expired(self) -> None:
        now = time.time()
        expired = [k for k, v in self._cache.items() if now - v["stored_at"] > self._ttl_seconds]
        for k in expired:
            del self._cache[k]


# Global singleton instance
run_cache = RunCache()
