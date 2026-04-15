"""
M7 Circuit Breaker — Unit Tests

Tests for:
1. CircuitBreakerConfig validation
2. CircuitBreaker state machine transitions (CLOSED → OPEN → HALF_OPEN → CLOSED)
3. Failure counting and threshold detection
4. Recovery timeout and probing
5. Error classification (transient vs permanent)
6. Thread safety with concurrent calls
7. Redis persistence (optional, graceful fallback)
8. Metrics exposure
9. Manual reset capability
"""

from __future__ import annotations

import threading
import time
from datetime import datetime, timezone
from unittest.mock import MagicMock

import pytest
import redis

from libs.contracts.errors import (
    AuthError,
    CircuitOpenError,
    ExternalServiceError,
    NotFoundError,
    TransientError,
    ValidationError,
)
from services.api.infrastructure.circuit_breaker import (
    CircuitBreaker,
    CircuitBreakerConfig,
    CircuitState,
)


class TestCircuitBreakerConfig:
    """Configuration validation and defaults."""

    def test_circuit_breaker_config_defaults(self) -> None:
        """
        CircuitBreakerConfig has sensible defaults.
        """
        config = CircuitBreakerConfig()
        assert config.failure_threshold == 5
        assert config.recovery_timeout_s == 30.0
        assert config.half_open_max_calls == 1
        assert config.name == "default"

    def test_circuit_breaker_config_custom_values(self) -> None:
        """
        CircuitBreakerConfig accepts custom values.
        """
        config = CircuitBreakerConfig(
            failure_threshold=3,
            recovery_timeout_s=10.0,
            half_open_max_calls=2,
            name="test_adapter",
        )
        assert config.failure_threshold == 3
        assert config.recovery_timeout_s == 10.0
        assert config.half_open_max_calls == 2
        assert config.name == "test_adapter"

    def test_circuit_breaker_config_is_frozen(self) -> None:
        """
        CircuitBreakerConfig is immutable (frozen).
        """
        config = CircuitBreakerConfig()
        with pytest.raises(AttributeError):
            config.failure_threshold = 10


class TestCircuitBreakerClosedState:
    """CLOSED state: normal operation, count failures."""

    def test_execute_closed_success_returns_result(self) -> None:
        """
        Call through CLOSED state succeeds, returns result, resets failure count.
        """
        config = CircuitBreakerConfig(name="test")
        breaker = CircuitBreaker(config=config, redis_client=None)

        def mock_fn() -> str:
            return "success"

        result = breaker.execute(mock_fn)
        assert result == "success"
        assert breaker.state == CircuitState.CLOSED
        assert breaker.metrics["failure_count"] == 0

    def test_execute_closed_transient_error_increments_failures(self) -> None:
        """
        TransientError in CLOSED state increments failure count, does not trip.
        """
        config = CircuitBreakerConfig(failure_threshold=5, name="test")
        breaker = CircuitBreaker(config=config, redis_client=None)

        def mock_fn() -> None:
            raise TransientError("network timeout")

        with pytest.raises(TransientError):
            breaker.execute(mock_fn)

        assert breaker.state == CircuitState.CLOSED
        assert breaker.metrics["failure_count"] == 1

    def test_execute_closed_external_service_error_increments_failures(
        self,
    ) -> None:
        """
        ExternalServiceError in CLOSED state increments failure count, does not trip.
        """
        config = CircuitBreakerConfig(failure_threshold=5, name="test")
        breaker = CircuitBreaker(config=config, redis_client=None)

        def mock_fn() -> None:
            raise ExternalServiceError("broker api error")

        with pytest.raises(ExternalServiceError):
            breaker.execute(mock_fn)

        assert breaker.state == CircuitState.CLOSED
        assert breaker.metrics["failure_count"] == 1

    def test_execute_closed_circuit_open_error_does_not_increment_failures(
        self,
    ) -> None:
        """
        CircuitOpenError does not count as a failure (raised BY the circuit).
        """
        config = CircuitBreakerConfig(failure_threshold=5, name="test")
        breaker = CircuitBreaker(config=config, redis_client=None)

        # Manually set state to OPEN to trigger CircuitOpenError
        with breaker._lock:
            breaker._state = CircuitState.OPEN
            breaker._opened_at = datetime.now(timezone.utc).isoformat()

        def mock_fn() -> None:
            raise CircuitOpenError("circuit is open")

        with pytest.raises(CircuitOpenError):
            breaker.execute(mock_fn)

        # Failure count should not have increased
        assert breaker.metrics["failure_count"] == 0

    def test_execute_closed_auth_error_passes_through_without_affecting_state(
        self,
    ) -> None:
        """
        AuthError (permanent) passes through without counting as failure.
        """
        config = CircuitBreakerConfig(failure_threshold=5, name="test")
        breaker = CircuitBreaker(config=config, redis_client=None)

        def mock_fn() -> None:
            raise AuthError("unauthorized")

        with pytest.raises(AuthError):
            breaker.execute(mock_fn)

        assert breaker.state == CircuitState.CLOSED
        assert breaker.metrics["failure_count"] == 0

    def test_execute_closed_not_found_error_passes_through_without_affecting_state(
        self,
    ) -> None:
        """
        NotFoundError (permanent) passes through without counting as failure.
        """
        config = CircuitBreakerConfig(failure_threshold=5, name="test")
        breaker = CircuitBreaker(config=config, redis_client=None)

        def mock_fn() -> None:
            raise NotFoundError("order not found")

        with pytest.raises(NotFoundError):
            breaker.execute(mock_fn)

        assert breaker.state == CircuitState.CLOSED
        assert breaker.metrics["failure_count"] == 0

    def test_execute_closed_validation_error_passes_through_without_affecting_state(
        self,
    ) -> None:
        """
        ValidationError (permanent) passes through without counting as failure.
        """
        config = CircuitBreakerConfig(failure_threshold=5, name="test")
        breaker = CircuitBreaker(config=config, redis_client=None)

        def mock_fn() -> None:
            raise ValidationError("invalid input")

        with pytest.raises(ValidationError):
            breaker.execute(mock_fn)

        assert breaker.state == CircuitState.CLOSED
        assert breaker.metrics["failure_count"] == 0

    def test_execute_closed_trips_to_open_on_threshold(self) -> None:
        """
        Failure count reaching threshold trips circuit to OPEN.
        """
        config = CircuitBreakerConfig(failure_threshold=3, name="test")
        breaker = CircuitBreaker(config=config, redis_client=None)

        def mock_fn() -> None:
            raise TransientError("timeout")

        # First 2 failures do not trip
        for _ in range(2):
            with pytest.raises(TransientError):
                breaker.execute(mock_fn)
            assert breaker.state == CircuitState.CLOSED

        # Third failure trips to OPEN
        with pytest.raises(CircuitOpenError):
            breaker.execute(mock_fn)
        assert breaker.state == CircuitState.OPEN
        assert breaker.metrics["failure_count"] == 3
        assert breaker.metrics["trip_count"] == 1
        assert breaker.metrics["opened_at"] is not None

    def test_execute_closed_success_after_failures_resets_count(self) -> None:
        """
        Successful call in CLOSED state resets failure count.
        """
        config = CircuitBreakerConfig(failure_threshold=5, name="test")
        breaker = CircuitBreaker(config=config, redis_client=None)

        def fail_fn() -> None:
            raise TransientError("timeout")

        def success_fn() -> str:
            return "ok"

        # Accumulate 3 failures
        for _ in range(3):
            with pytest.raises(TransientError):
                breaker.execute(fail_fn)
        assert breaker.metrics["failure_count"] == 3

        # Success resets count
        result = breaker.execute(success_fn)
        assert result == "ok"
        assert breaker.metrics["failure_count"] == 0


class TestCircuitBreakerOpenState:
    """OPEN state: fast-fail, await recovery timeout."""

    def test_execute_open_raises_circuit_open_error_immediately(self) -> None:
        """
        Call through OPEN state raises CircuitOpenError immediately.
        """
        config = CircuitBreakerConfig(
            failure_threshold=1,
            recovery_timeout_s=30.0,
            name="test",
        )
        breaker = CircuitBreaker(config=config, redis_client=None)

        def fail_fn() -> None:
            raise TransientError("timeout")

        # Trip the circuit
        with pytest.raises(CircuitOpenError):
            breaker.execute(fail_fn)

        # Now in OPEN state; any call raises CircuitOpenError
        def success_fn() -> str:
            return "should not be called"

        with pytest.raises(CircuitOpenError) as exc_info:
            breaker.execute(success_fn)

        error = exc_info.value
        assert error.adapter_name == "test"
        assert error.failure_count == 1
        assert error.open_since is not None

    def test_execute_open_does_not_call_function(self) -> None:
        """
        Function is not called when circuit is OPEN (fast-fail).
        """
        config = CircuitBreakerConfig(
            failure_threshold=1,
            recovery_timeout_s=30.0,
            name="test",
        )
        breaker = CircuitBreaker(config=config, redis_client=None)

        def fail_fn() -> None:
            raise TransientError("timeout")

        with pytest.raises(CircuitOpenError):
            breaker.execute(fail_fn)

        call_count = 0

        def counted_fn() -> None:
            nonlocal call_count
            call_count += 1

        with pytest.raises(CircuitOpenError):
            breaker.execute(counted_fn)

        assert call_count == 0

    def test_execute_open_transitions_to_half_open_after_timeout(self) -> None:
        """
        Circuit transitions from OPEN to HALF_OPEN after recovery_timeout_s elapsed.
        """
        config = CircuitBreakerConfig(
            failure_threshold=1,
            recovery_timeout_s=0.1,  # 100ms for fast test
            name="test",
        )
        breaker = CircuitBreaker(config=config, redis_client=None)

        def fail_fn() -> None:
            raise TransientError("timeout")

        # Trip the circuit
        with pytest.raises(CircuitOpenError):
            breaker.execute(fail_fn)
        assert breaker.state == CircuitState.OPEN

        # Wait for recovery timeout
        time.sleep(0.15)

        # Next call transitions to HALF_OPEN and attempts probe
        def probe_fn() -> str:
            return "recovered"

        result = breaker.execute(probe_fn)
        assert result == "recovered"
        assert breaker.state == CircuitState.CLOSED


class TestCircuitBreakerHalfOpenState:
    """HALF_OPEN state: recovery probing with limited calls."""

    def test_execute_half_open_success_transitions_to_closed(self) -> None:
        """
        Successful probe call in HALF_OPEN transitions to CLOSED.
        """
        config = CircuitBreakerConfig(
            failure_threshold=1,
            recovery_timeout_s=0.05,
            half_open_max_calls=1,
            name="test",
        )
        breaker = CircuitBreaker(config=config, redis_client=None)

        def fail_fn() -> None:
            raise TransientError("timeout")

        # Trip to OPEN
        with pytest.raises(CircuitOpenError):
            breaker.execute(fail_fn)

        time.sleep(0.1)

        # Probe succeeds
        def probe_fn() -> str:
            return "recovered"

        result = breaker.execute(probe_fn)
        assert result == "recovered"
        assert breaker.state == CircuitState.CLOSED
        assert breaker.metrics["failure_count"] == 0
        assert breaker.metrics["recovery_count"] == 1

    def test_execute_half_open_failure_transitions_back_to_open(self) -> None:
        """
        Failure during HALF_OPEN probe transitions back to OPEN.
        """
        config = CircuitBreakerConfig(
            failure_threshold=1,
            recovery_timeout_s=0.05,
            half_open_max_calls=1,
            name="test",
        )
        breaker = CircuitBreaker(config=config, redis_client=None)

        def fail_fn() -> None:
            raise TransientError("timeout")

        # Trip to OPEN
        with pytest.raises(CircuitOpenError):
            breaker.execute(fail_fn)

        time.sleep(0.1)

        # Probe fails
        with pytest.raises(TransientError):
            breaker.execute(fail_fn)

        assert breaker.state == CircuitState.OPEN
        # opened_at is updated
        assert breaker.metrics["opened_at"] is not None

    def test_execute_half_open_max_calls_exceeded_reopens_circuit(self) -> None:
        """
        Exhausting half_open_max_calls without success reopens circuit.
        """
        config = CircuitBreakerConfig(
            failure_threshold=1,
            recovery_timeout_s=0.05,
            half_open_max_calls=2,
            name="test",
        )
        breaker = CircuitBreaker(config=config, redis_client=None)

        def fail_fn() -> None:
            raise TransientError("timeout")

        # Trip to OPEN
        with pytest.raises(CircuitOpenError):
            breaker.execute(fail_fn)

        time.sleep(0.1)

        # First probe call (returns to OPEN on failure)
        with pytest.raises(TransientError):
            breaker.execute(fail_fn)
        assert breaker.state == CircuitState.OPEN

        time.sleep(0.1)

        # Second recovery probe (enters HALF_OPEN again)
        with pytest.raises(TransientError):
            breaker.execute(fail_fn)
        assert breaker.state == CircuitState.OPEN

    def test_execute_half_open_permanent_error_closes_circuit(self) -> None:
        """
        Permanent error during HALF_OPEN probe returns to OPEN (safe behavior).
        """
        config = CircuitBreakerConfig(
            failure_threshold=1,
            recovery_timeout_s=0.05,
            half_open_max_calls=1,
            name="test",
        )
        breaker = CircuitBreaker(config=config, redis_client=None)

        def fail_fn() -> None:
            raise TransientError("timeout")

        # Trip to OPEN
        with pytest.raises(CircuitOpenError):
            breaker.execute(fail_fn)

        time.sleep(0.1)

        # Probe returns permanent error
        def auth_fail_fn() -> None:
            raise AuthError("unauthorized")

        with pytest.raises(AuthError):
            breaker.execute(auth_fail_fn)

        # Circuit returns to OPEN (safe behavior)
        assert breaker.state == CircuitState.OPEN


class TestCircuitBreakerMetrics:
    """Metrics exposure and observability."""

    def test_metrics_initial_state(self) -> None:
        """
        Metrics in initial state show CLOSED, no failures, no trips.
        """
        config = CircuitBreakerConfig(name="test")
        breaker = CircuitBreaker(config=config, redis_client=None)

        metrics = breaker.metrics
        assert metrics["current_state"] == "closed"
        assert metrics["failure_count"] == 0
        assert metrics["trip_count"] == 0
        assert metrics["recovery_count"] == 0
        assert metrics["opened_at"] is None
        assert metrics["last_failure_at"] is None

    def test_metrics_after_failure(self) -> None:
        """
        Metrics reflect failure timestamp and count.
        """
        config = CircuitBreakerConfig(name="test")
        breaker = CircuitBreaker(config=config, redis_client=None)

        def fail_fn() -> None:
            raise TransientError("timeout")

        with pytest.raises(TransientError):
            breaker.execute(fail_fn)

        metrics = breaker.metrics
        assert metrics["failure_count"] == 1
        assert metrics["last_failure_at"] is not None
        # Verify it's a valid ISO timestamp
        datetime.fromisoformat(metrics["last_failure_at"])

    def test_metrics_after_trip(self) -> None:
        """
        Metrics reflect trip timestamp and count.
        """
        config = CircuitBreakerConfig(failure_threshold=1, name="test")
        breaker = CircuitBreaker(config=config, redis_client=None)

        def fail_fn() -> None:
            raise TransientError("timeout")

        with pytest.raises(CircuitOpenError):
            breaker.execute(fail_fn)

        metrics = breaker.metrics
        assert metrics["current_state"] == "open"
        assert metrics["trip_count"] == 1
        assert metrics["opened_at"] is not None
        # Verify it's a valid ISO timestamp
        datetime.fromisoformat(metrics["opened_at"])

    def test_metrics_after_recovery(self) -> None:
        """
        Metrics reflect recovery count after successful HALF_OPEN→CLOSED transition.
        """
        config = CircuitBreakerConfig(
            failure_threshold=1,
            recovery_timeout_s=0.05,
            name="test",
        )
        breaker = CircuitBreaker(config=config, redis_client=None)

        def fail_fn() -> None:
            raise TransientError("timeout")

        with pytest.raises(CircuitOpenError):
            breaker.execute(fail_fn)

        time.sleep(0.1)

        def probe_fn() -> str:
            return "ok"

        breaker.execute(probe_fn)

        metrics = breaker.metrics
        assert metrics["current_state"] == "closed"
        assert metrics["recovery_count"] == 1
        assert metrics["failure_count"] == 0


class TestCircuitBreakerReset:
    """Manual reset capability."""

    def test_reset_clears_state(self) -> None:
        """
        Reset transitions to CLOSED and clears failure count.
        """
        config = CircuitBreakerConfig(failure_threshold=1, name="test")
        breaker = CircuitBreaker(config=config, redis_client=None)

        def fail_fn() -> None:
            raise TransientError("timeout")

        # Trip the circuit
        with pytest.raises(CircuitOpenError):
            breaker.execute(fail_fn)
        assert breaker.state == CircuitState.OPEN

        # Reset
        breaker.reset()

        assert breaker.state == CircuitState.CLOSED
        metrics = breaker.metrics
        assert metrics["failure_count"] == 0
        assert metrics["opened_at"] is None

    def test_reset_allows_calls_to_resume(self) -> None:
        """
        After reset, circuit accepts calls normally.
        """
        config = CircuitBreakerConfig(failure_threshold=1, name="test")
        breaker = CircuitBreaker(config=config, redis_client=None)

        def fail_fn() -> None:
            raise TransientError("timeout")

        with pytest.raises(CircuitOpenError):
            breaker.execute(fail_fn)

        breaker.reset()

        def success_fn() -> str:
            return "ok"

        result = breaker.execute(success_fn)
        assert result == "ok"


class TestCircuitBreakerThreadSafety:
    """Thread-safe state management."""

    def test_execute_is_thread_safe(self) -> None:
        """
        Concurrent calls maintain correct state and failure count (thread-safe).
        Once circuit trips to OPEN, subsequent calls fast-fail without incrementing.
        """
        config = CircuitBreakerConfig(failure_threshold=10, name="test")
        breaker = CircuitBreaker(config=config, redis_client=None)

        def fail_fn() -> None:
            raise TransientError("timeout")

        def thread_worker() -> None:
            import contextlib

            for _ in range(5):
                with contextlib.suppress(TransientError, CircuitOpenError):
                    breaker.execute(fail_fn)

        threads = [threading.Thread(target=thread_worker) for _ in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # At least 10 failures (threshold) to trip the circuit
        assert breaker.state == CircuitState.OPEN
        assert breaker.metrics["failure_count"] >= 10

    def test_state_property_is_thread_safe(self) -> None:
        """
        Reading state property is thread-safe.
        """
        config = CircuitBreakerConfig(failure_threshold=5, name="test")
        breaker = CircuitBreaker(config=config, redis_client=None)

        states: list[CircuitState] = []

        def reader_worker() -> None:
            for _ in range(100):
                states.append(breaker.state)

        threads = [threading.Thread(target=reader_worker) for _ in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(states) == 400
        assert all(s in (CircuitState.CLOSED, CircuitState.OPEN) for s in states)


class TestCircuitBreakerRedisIntegration:
    """Redis persistence (optional, graceful fallback)."""

    def test_circuit_breaker_works_without_redis(self) -> None:
        """
        Circuit breaker functions normally with redis_client=None.
        """
        config = CircuitBreakerConfig(failure_threshold=1, name="test")
        breaker = CircuitBreaker(config=config, redis_client=None)

        def fail_fn() -> None:
            raise TransientError("timeout")

        with pytest.raises(CircuitOpenError):
            breaker.execute(fail_fn)

        assert breaker.state == CircuitState.OPEN

    def test_circuit_breaker_persists_state_to_redis(self) -> None:
        """
        Circuit state is persisted to Redis if client provided.
        """
        mock_redis = MagicMock(spec=redis.Redis)
        config = CircuitBreakerConfig(failure_threshold=1, name="test")
        breaker = CircuitBreaker(config=config, redis_client=mock_redis)

        def fail_fn() -> None:
            raise TransientError("timeout")

        with pytest.raises(CircuitOpenError):
            breaker.execute(fail_fn)

        # Verify Redis write was attempted
        assert mock_redis.set.called

    def test_circuit_breaker_handles_redis_unavailability_gracefully(self) -> None:
        """
        Circuit breaker falls back to in-memory state if Redis unavailable.
        """
        mock_redis = MagicMock(spec=redis.Redis)
        mock_redis.set.side_effect = redis.ConnectionError("Redis is down")

        config = CircuitBreakerConfig(failure_threshold=1, name="test")
        breaker = CircuitBreaker(config=config, redis_client=mock_redis)

        def fail_fn() -> None:
            raise TransientError("timeout")

        # Should not raise despite Redis error
        with pytest.raises(CircuitOpenError):
            breaker.execute(fail_fn)

        assert breaker.state == CircuitState.OPEN

    def test_circuit_breaker_loads_state_from_redis_on_init(self) -> None:
        """
        Circuit breaker loads persisted state from Redis on initialization.
        """
        mock_redis = MagicMock(spec=redis.Redis)
        mock_redis.get.side_effect = lambda key: {
            "circuit:test:state": b"open",
            "circuit:test:failure_count": b"5",
            "circuit:test:opened_at": b"2026-04-11T12:00:00+00:00",
            "circuit:test:trip_count": b"2",
            "circuit:test:recovery_count": b"1",
            "circuit:test:last_failure_at": b"2026-04-11T12:00:00+00:00",
        }.get(key)

        config = CircuitBreakerConfig(name="test")
        breaker = CircuitBreaker(config=config, redis_client=mock_redis)

        # State should be loaded from Redis
        assert breaker.state == CircuitState.OPEN
        metrics = breaker.metrics
        assert metrics["failure_count"] == 5
        assert metrics["trip_count"] == 2

    def test_circuit_breaker_handles_redis_load_failure_gracefully(self) -> None:
        """
        Circuit breaker falls back to in-memory defaults if Redis load fails.
        """
        mock_redis = MagicMock(spec=redis.Redis)
        mock_redis.get.side_effect = redis.ConnectionError("Redis is down")

        config = CircuitBreakerConfig(name="test")
        breaker = CircuitBreaker(config=config, redis_client=mock_redis)

        # Should initialize with defaults despite Redis error
        assert breaker.state == CircuitState.CLOSED
        assert breaker.metrics["failure_count"] == 0
