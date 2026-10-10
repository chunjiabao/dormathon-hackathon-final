"""In-process sliding-window rate limiter keyed by IP, application and workspace.

Single-instance only: state lives in memory. For multi-instance deployments use a shared store.
"""

import threading
import time
from collections import defaultdict, deque

from app.config import get_settings
from app.errors import ApiError

WINDOW_S = 60.0


class RateLimiter:
    def __init__(self) -> None:
        self._hits: dict[str, deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()

    def check(self, limits: dict[str, int]) -> None:
        """Atomically check all keys; record a hit only if every key is under its limit."""
        now = time.monotonic()
        with self._lock:
            for key, limit in limits.items():
                q = self._hits[key]
                while q and now - q[0] > WINDOW_S:
                    q.popleft()
                if len(q) >= limit:
                    raise ApiError(429, "rate_limited", "Too many requests. Please slow down.")
            for key in limits:
                self._hits[key].append(now)

    def reset(self) -> None:
        with self._lock:
            self._hits.clear()


limiter = RateLimiter()


def check_chat_limits(ip: str, application_id: str, workspace_id: str) -> None:
    s = get_settings()
    limiter.check(
        {
            f"ip:{ip}": s.rate_limit_ip_per_min,
            f"app:{application_id}": s.rate_limit_app_per_min,
            f"ws:{workspace_id}": s.rate_limit_workspace_per_min,
        }
    )
