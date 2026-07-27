"""Circuit breaker — spec §10.1."""

from ai_engine.llm.circuit_breaker import CircuitBreaker, CircuitState


def make_breaker(**overrides) -> CircuitBreaker:
    defaults = dict(failure_threshold=0.20, window_seconds=300, open_duration_seconds=600, half_open_ratio=0.10)
    defaults.update(overrides)
    return CircuitBreaker(**defaults)


def test_starts_closed_and_allows_requests():
    cb = make_breaker()
    assert cb.state is CircuitState.CLOSED
    assert cb.allow_request() is True


def test_opens_after_exceeding_failure_threshold():
    cb = make_breaker()
    for _ in range(4):
        cb.record(success=True)
    for _ in range(3):
        cb.record(success=False)
    # 3/7 ≈ 0.43 > 0.20 threshold
    assert cb.state is CircuitState.OPEN


def test_stays_closed_under_threshold():
    cb = make_breaker()
    for _ in range(9):
        cb.record(success=True)
    cb.record(success=False)
    # 1/10 = 0.10 < 0.20 threshold
    assert cb.state is CircuitState.CLOSED


def test_open_circuit_blocks_requests_immediately():
    cb = make_breaker(open_duration_seconds=600)
    for _ in range(5):
        cb.record(success=False)
    assert cb.state is CircuitState.OPEN
    assert cb.allow_request() is False


def test_half_open_transitions_to_closed_on_success():
    cb = make_breaker(open_duration_seconds=0.0)  # cooldown already elapsed
    for _ in range(5):
        cb.record(success=False)
    assert cb.state is CircuitState.OPEN
    cb.allow_request()  # triggers OPEN -> HALF_OPEN since cooldown is 0
    assert cb.state is CircuitState.HALF_OPEN
    cb.record(success=True)
    assert cb.state is CircuitState.CLOSED


def test_half_open_reopens_on_failure():
    cb = make_breaker(open_duration_seconds=0.0)
    for _ in range(5):
        cb.record(success=False)
    cb.allow_request()
    assert cb.state is CircuitState.HALF_OPEN
    cb.record(success=False)
    assert cb.state is CircuitState.OPEN
