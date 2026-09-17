"""
Circuit breaker — spec §10.1. Hardcoded rather than in thresholds.yaml: it
protects the LLM transport, not a calibration value routing depends on.

In-memory, per-process state; a multi-instance deployment would move it to
Redis.
"""

from __future__ import annotations

import logging
import time
from collections import deque
from dataclasses import dataclass, field
from enum import Enum

logger = logging.getLogger(__name__)


class CircuitState(Enum):
    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


class CircuitOpenError(Exception):
    pass


@dataclass
class CircuitBreaker:
    failure_threshold: float = 0.20  # >20% errors
    window_seconds: float = 300.0  # 5 minutes
    open_duration_seconds: float = 600.0  # 10 minutes
    half_open_ratio: float = 0.10  # try 10% of traffic while half-open

    _events: deque = field(default_factory=deque)  # (timestamp, success: bool)
    _state: CircuitState = CircuitState.CLOSED
    _opened_at: float = 0.0
    _half_open_counter: int = 0

    def _prune(self, now: float) -> None:
        while self._events and now - self._events[0][0] > self.window_seconds:
            self._events.popleft()

    def _failure_rate(self) -> float:
        if not self._events:
            return 0.0
        failures = sum(1 for _, ok in self._events if not ok)
        return failures / len(self._events)

    def allow_request(self) -> bool:
        now = time.time()
        self._prune(now)

        if self._state is CircuitState.OPEN:
            if now - self._opened_at >= self.open_duration_seconds:
                self._state = CircuitState.HALF_OPEN
                self._half_open_counter = 0
                logger.warning("circuit_breaker: OPEN -> HALF_OPEN after cooldown")
            else:
                return False

        if self._state is CircuitState.HALF_OPEN:
            self._half_open_counter += 1
            # Allow roughly half_open_ratio of attempts through.
            return (self._half_open_counter % max(1, round(1 / self.half_open_ratio))) == 0

        return True

    def record(self, success: bool) -> None:
        now = time.time()
        self._events.append((now, success))
        self._prune(now)

        if self._state is CircuitState.HALF_OPEN:
            if success:
                self._state = CircuitState.CLOSED
                self._events.clear()
                logger.warning("circuit_breaker: HALF_OPEN -> CLOSED, recovered")
            else:
                self._state = CircuitState.OPEN
                self._opened_at = now
                logger.error("circuit_breaker: HALF_OPEN -> OPEN, still failing")
            return

        if self._state is CircuitState.CLOSED and len(self._events) >= 5:
            rate = self._failure_rate()
            if rate > self.failure_threshold:
                self._state = CircuitState.OPEN
                self._opened_at = now
                # This is an OPS alert per spec §10.1, not just a log line:
                # circuit open means HITL volume is about to spike and
                # needs more reviewers, not just an engineer's attention.
                logger.error(
                    "circuit_breaker: CLOSED -> OPEN (failure_rate=%.2f > %.2f) — "
                    "ALERT: HITL volume will spike, staff the review queue",
                    rate,
                    self.failure_threshold,
                )


# Module-level singleton — one breaker per ai-engine process, shared across
# all requests it serves.
CIRCUIT = CircuitBreaker()
