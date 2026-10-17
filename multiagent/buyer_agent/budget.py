"""Hourly cap on paid calls (AM-15). In-memory, single process."""

import time
from collections import deque
from collections.abc import Callable

WORST_CASE_CALLS = 12 + 8 + 2  # views + claims + Groq; logical calls, SDK retries not counted
WINDOW_S = 3600.0


class CallBudget:
    # ponytail: reserves worst case, no refunds; in-memory, single process
    def __init__(self, limit_per_hour: int, clock: Callable[[], float] = time.monotonic) -> None:
        self._limit = limit_per_hour
        self._clock = clock
        self._taken: deque[tuple[float, int]] = deque()
        self._used = 0

    def try_take(self, n: int) -> bool:
        now = self._clock()
        while self._taken and now - self._taken[0][0] >= WINDOW_S:
            self._used -= self._taken.popleft()[1]
        if n < 0 or self._used + n > self._limit:
            return False
        self._taken.append((now, n))
        self._used += n
        return True
