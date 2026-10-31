"""In-memory login throttle: too many failed attempts for a username locks it briefly.

Per process, which is fine for a single small server. Pure apart from the clock,
which is injected.
"""

import time
from collections import deque
from collections.abc import Callable

MAX_FAILURES = 10
WINDOW_SECONDS = 15 * 60


class LoginThrottle:
    def __init__(
        self,
        max_failures: int = MAX_FAILURES,
        window_seconds: float = WINDOW_SECONDS,
        now: Callable[[], float] = time.monotonic,
    ) -> None:
        self.max_failures = max_failures
        self.window_seconds = window_seconds
        self.now = now
        self._failures: dict[str, deque[float]] = {}

    def _recent(self, key: str) -> deque[float]:
        attempts = self._failures.setdefault(key, deque())
        cutoff = self.now() - self.window_seconds
        while attempts and attempts[0] < cutoff:
            attempts.popleft()
        return attempts

    def is_locked(self, key: str) -> bool:
        return len(self._recent(key)) >= self.max_failures

    def record_failure(self, key: str) -> None:
        self._recent(key).append(self.now())

    def reset(self, key: str) -> None:
        self._failures.pop(key, None)
