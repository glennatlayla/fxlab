"""
Thread-safe circuit breaker with optional Redis-backed state persistence.

Responsibilities:
- Implement circuit breaker state machine (CLOSED → OPEN → HALF_OPEN → CLOSED).
- Protect against cascading failures in external API calls.
- Track failure counts and recovery probes.
- Persist state to Redis for cross-process visibility (if Redis client provided).
- Fall back to in-memory state if Redis is unavailable.
- Distinguish between retriable (TransientError, ExternalServiceError) and
  permanent errors (AuthError, NotFoundError, ValidationError).
- Expose metrics for monitoring and observability.

Does NOT:
- Perform retry logic (see task_retry.py for that).
- Execute I/O operations (only calls the wrapped callable).
- Retry permanent errors or CircuitOpenError itself.
- Modify or interpret exception messages.

Dependencies:
- threading.Lock: Thread-safe state protection.
- structlog: Structured logging for state transitions and failures.
- redis.Redis (optional): Durable state persistence across processes.
- dataclasses: CircuitBreakerConfig immutable container.
- datetime.datetime: Timestamping for recovery timeouts.
- libs.contracts.errors: Exception hierarchy (TransientError, CircuitOpenError, etc).

Error conditions:
- TransientError: Increments failure count, may trip circuit.
- ExternalServiceError (non-CircuitOpenError): Increments failure count, may trip circuit.
- CircuitOpenError: Raised when circuit is OPEN, never counts as a failure.
- AuthError, NotFoundError, ValidationError: Pass through without affecting state.

Example:
    from services.api.infrastructure.circuit_breaker import (
        CircuitBreaker,
        CircuitBreakerConfig,
    )
    import redis
    import structlog

    logger = structlog.get_logger(__name__)

    config = CircuitBreakerConfig(
        failure_threshold=5,
        recovery_timeout_s=30.0,
        half_open_max_calls=1,
        name="alpaca_broker",
    )
    redis_client = redis.Redis(host="localhost", port=6379)
    breaker = CircuitBreaker(config=config, redis_client=redis_client)

    def call_broker():
        return broker.get_account()

    try:
        account = breaker.execute(call_broker)
    except CircuitOpenError as e:
        logger.warning("broker.circuit_open", adapter_name=e.adapter_name)
    except (TransientError, ExternalServiceError) as e:
        logger.error("broker.external_error", error=str(e))
"""

from __future__ import annotations

import sys
import threading
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from typing import Any, TypeVar, cast

import redis
import structlog

from libs.contracts.errors import (
    AuthError,
    CircuitOpenError,
    ExternalServiceError,
    NotFoundError,
    TransientError,
    ValidationError,
)

logger = structlog.get_logger(__name__)

T = TypeVar("T")


class CircuitState(str, Enum):  # noqa: UP042 — StrEnum requires Python 3.11+
    """
    Circuit breaker state machine.

    CLOSED: Normal operation. All calls pass through.
    OPEN: Failure threshold exceeded. All calls immediately fail with CircuitOpenError.
    HALF_OPEN: Recovery probe mode. Limited calls allowed to test if service recovered.
    """

    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


@dataclass(frozen=True)
class CircuitBreakerConfig:
    """
    Immutable configuration for circuit breaker behavior.

    Attributes:
        failure_threshold: Number of consecutive failures (TransientError or
            ExternalServiceError) required to trip the circuit from CLOSED to OPEN.
            Default 5.
        recovery_timeout_s: Time in seconds to wait while OPEN before transitioning
            to HALF_OPEN to probe for recovery. Default 30.0.
        half_open_max_calls: Maximum number of calls allowed while HALF_OPEN to
            probe the service. On the first success, circuit transitions to CLOSED.
            On any failure, circuit transitions back to OPEN. Default 1.
        name: Adapter or service name for logging and metrics. Used in CircuitOpenError
            and structured log output. Default "default".

    Example:
        config = CircuitBreakerConfig(
            failure_threshold=5,
            recovery_timeout_s=30.0,
            half_open_max_calls=1,
            name="alpaca",
        )
    """

    failure_threshold: int = 5
    recovery_timeout_s: float = 30.0
    half_open_max_calls: int = 1
    name: str = "default"


class CircuitBreaker:
    """
    Thread-safe circuit breaker with optional Redis-backed persistence.

    Implements the circuit breaker pattern to prevent cascading failures when
    calling unreliable external services. Tracks consecutive failures and
    automatically blocks calls (fast-fail) when a threshold is exceeded, then
    probes for recovery after a configurable timeout.

    Responsibilities:
    - Execute callables through circuit breaker state machine.
    - Maintain state (CLOSED, OPEN, HALF_OPEN) with thread-safe locking.
    - Persist state to Redis for visibility across processes (if Redis provided).
    - Track failure counts, recovery events, and metrics.
    - Log state transitions and failures at appropriate levels.

    Does NOT:
    - Retry operations (that is task_retry.py's job).
    - Execute I/O directly (only wraps the passed callable).
    - Modify exception messages or stack traces.

    Dependencies:
    - config: CircuitBreakerConfig specifying thresholds and timeouts.
    - redis_client: Optional redis.Redis instance for state persistence.
        If None, state is in-memory only (acceptable for dev/test).

    Attributes (via properties):
    - state: Current CircuitState (CLOSED, OPEN, or HALF_OPEN).
    - metrics: Dict with trip_count, recovery_count, current_state, failure_count,
               last_failure_at, opened_at.

    Example:
        config = CircuitBreakerConfig(failure_threshold=5, name="broker")
        breaker = CircuitBreaker(config=config, redis_client=redis_client)

        def call_broker():
            return broker.get_account()

        try:
            result = breaker.execute(call_broker)
        except CircuitOpenError as e:
            logger.warning("circuit_open", adapter_name=e.adapter_name)
    """

    def __init__(
        self,
        config: CircuitBreakerConfig,
        redis_client: redis.Redis | None = None,
    ) -> None:
        """
        Initialize the circuit breaker.

        Args:
            config: CircuitBreakerConfig with threshold, timeout, and name.
            redis_client: Optional redis.Redis client for state persistence.
                If None, state is maintained in-memory.

        Returns:
            None

        Raises:
            None (all initialization errors are handled and logged).

        Example:
            config = CircuitBreakerConfig(failure_threshold=5, name="alpaca")
            breaker = CircuitBreaker(config=config, redis_client=redis_client)
        """
        self._config = config
        self._redis_client = redis_client
        self._lock = threading.Lock()

        # In-memory state (fallback or primary if no Redis).
        self._state = CircuitState.CLOSED
        self._failure_count = 0
        self._opened_at: str | None = None
        self._half_open_calls = 0
        self._trip_count = 0
        self._recovery_count = 0
        self._last_failure_at: str | None = None

        # Attempt to load state from Redis on startup.
        self._load_state_from_redis()

    def _redis_key(self, suffix: str) -> str:
        """
        Generate a Redis key for this circuit breaker.

        Args:
            suffix: Key suffix (e.g., "state", "failure_count").

        Returns:
            Fully-qualified Redis key (e.g., "circuit:alpaca:state").

        Example:
            key = breaker._redis_key("state")  # "circuit:alpaca:state"
        """
        return f"circuit:{self._config.name}:{suffix}"

    def _load_state_from_redis(self) -> None:
        """
        Attempt to load persisted state from Redis on startup.

        Reads keys: circuit:<name>:state, circuit:<name>:failure_count,
        circuit:<name>:opened_at, circuit:<name>:trip_count,
        circuit:<name>:recovery_count, circuit:<name>:last_failure_at.

        If any key is missing or Redis is unavailable, falls back to
        initialized in-memory defaults. Logs a warning if Redis read fails.

        Args:
            None

        Returns:
            None (modifies in-memory state).

        Raises:
            None (all errors caught and logged, fallback to in-memory state).

        Example:
            breaker._load_state_from_redis()
            # State now matches Redis if available, else in-memory defaults.
        """
        if not self._redis_client:
            return

        try:
            state_str = cast(bytes | None, self._redis_client.get(self._redis_key("state")))
            if state_str is not None:
                self._state = CircuitState(state_str.decode("utf-8"))

            failure_count_str = cast(
                bytes | None, self._redis_client.get(self._redis_key("failure_count"))
            )
            if failure_count_str is not None:
                self._failure_count = int(failure_count_str.decode("utf-8"))

            opened_at_str = cast(bytes | None, self._redis_client.get(self._redis_key("opened_at")))
            if opened_at_str is not None:
                self._opened_at = opened_at_str.decode("utf-8")

            trip_count_str = cast(
                bytes | None, self._redis_client.get(self._redis_key("trip_count"))
            )
            if trip_count_str is not None:
                self._trip_count = int(trip_count_str.decode("utf-8"))

            recovery_count_str = cast(
                bytes | None, self._redis_client.get(self._redis_key("recovery_count"))
            )
            if recovery_count_str is not None:
                self._recovery_count = int(recovery_count_str.decode("utf-8"))

            last_failure_at_str = cast(
                bytes | None, self._redis_client.get(self._redis_key("last_failure_at"))
            )
            if last_failure_at_str is not None:
                self._last_failure_at = last_failure_at_str.decode("utf-8")

            logger.info(
                "circuit_breaker.state_loaded_from_redis",
                adapter_name=self._config.name,
                state=self._state.value,
                failure_count=self._failure_count,
            )
        except Exception as exc:
            logger.warning(
                "circuit_breaker.redis_load_failed",
                adapter_name=self._config.name,
                error_type=type(exc).__name__,
                error_message=str(exc),
                detail="Falling back to in-memory state.",
            )

    def _persist_state_to_redis(self) -> None:
        """
        Persist current circuit state to Redis.

        Writes keys: circuit:<name>:state, circuit:<name>:failure_count,
        circuit:<name>:opened_at, circuit:<name>:trip_count,
        circuit:<name>:recovery_count, circuit:<name>:last_failure_at.

        If redis_client is None or write fails, logs a warning and continues.
        State remains in-memory; Redis persistence is optional for resilience.

        Args:
            None

        Returns:
            None (modifies Redis if available).

        Raises:
            None (all errors caught and logged).

        Example:
            breaker._persist_state_to_redis()
            # Circuit state now visible across processes via Redis.
        """
        if not self._redis_client:
            return

        try:
            self._redis_client.set(self._redis_key("state"), self._state.value, ex=86400)  # 24h TTL
            self._redis_client.set(
                self._redis_key("failure_count"), str(self._failure_count), ex=86400
            )
            if self._opened_at:
                self._redis_client.set(self._redis_key("opened_at"), self._opened_at, ex=86400)
            self._redis_client.set(self._redis_key("trip_count"), str(self._trip_count), ex=86400)
            self._redis_client.set(
                self._redis_key("recovery_count"), str(self._recovery_count), ex=86400
            )
            if self._last_failure_at:
                self._redis_client.set(
                    self._redis_key("last_failure_at"), self._last_failure_at, ex=86400
                )
        except Exception as exc:
            logger.warning(
                "circuit_breaker.redis_persist_failed",
                adapter_name=self._config.name,
                error_type=type(exc).__name__,
                error_message=str(exc),
                detail="State remains in-memory; Redis persistence will retry on next change.",
            )

    @property
    def state(self) -> CircuitState:
        """
        Get the current circuit breaker state (thread-safe).

        Returns:
            CircuitState: CLOSED, OPEN, or HALF_OPEN.

        Example:
            if breaker.state == CircuitState.OPEN:
                logger.info("Circuit is open, fast-failing")
        """
        with self._lock:
            return self._state

    @property
    def metrics(self) -> dict[str, Any]:
        """
        Get current circuit breaker metrics.

        Provides visibility into circuit health and failure history for
        monitoring, alerting, and debugging.

        Returns:
            Dict with keys:
            - current_state: CircuitState (CLOSED, OPEN, HALF_OPEN)
            - failure_count: Current consecutive failures
            - trip_count: Total number of times circuit has tripped (CLOSED→OPEN)
            - recovery_count: Total number of successful recoveries (HALF_OPEN→CLOSED)
            - opened_at: ISO 8601 timestamp when circuit last transitioned to OPEN
                        (None if circuit is CLOSED)
            - last_failure_at: ISO 8601 timestamp of most recent failure (None if no failures)

        Example:
            metrics = breaker.metrics
            # {
            #     "current_state": "open",
            #     "failure_count": 5,
            #     "trip_count": 2,
            #     "recovery_count": 1,
            #     "opened_at": "2026-04-11T16:45:30.123456+00:00",
            #     "last_failure_at": "2026-04-11T16:45:25.654321+00:00",
            # }
        """
        with self._lock:
            return {
                "current_state": self._state.value,
                "failure_count": self._failure_count,
                "trip_count": self._trip_count,
                "recovery_count": self._recovery_count,
                "opened_at": self._opened_at,
                "last_failure_at": self._last_failure_at,
            }

    def reset(self) -> None:
        """
        Force reset the circuit to CLOSED state and clear failure counts.

        Used for manual recovery, admin intervention, or testing. After reset,
        the circuit accepts calls normally and does not hold prior failure history.

        Logs an informational event at reset time.

        Args:
            None

        Returns:
            None (modifies circuit state).

        Raises:
            None

        Example:
            breaker.reset()
            # Circuit is now CLOSED, failure_count=0, opened_at=None
        """
        with self._lock:
            old_state = self._state
            self._state = CircuitState.CLOSED
            self._failure_count = 0
            self._opened_at = None
            self._half_open_calls = 0
            logger.info(
                "circuit_breaker.reset",
                adapter_name=self._config.name,
                old_state=old_state.value,
                new_state=self._state.value,
            )
            self._persist_state_to_redis()

    def execute(self, fn: Callable[[], T]) -> T:
        """
        Execute a callable through the circuit breaker state machine.

        Routes the call through the appropriate state handler (CLOSED, OPEN, HALF_OPEN).

        State-specific behavior:
        - CLOSED: Execute fn. On success, reset failure count. On TransientError or
                  ExternalServiceError (not CircuitOpenError), increment failures.
                  If failures >= threshold, trip to OPEN and raise CircuitOpenError.
                  Permanent errors (AuthError, NotFoundError, ValidationError) pass
                  through without affecting circuit state.
        - OPEN: Check if recovery_timeout_s elapsed since opened_at. If not, raise
                CircuitOpenError immediately. If yes, transition to HALF_OPEN.
        - HALF_OPEN: Allow up to half_open_max_calls probe calls. On first success,
                     transition to CLOSED. On any failure, transition back to OPEN.

        Args:
            fn: Zero-argument callable that returns T.
                Must be idempotent or safe to execute multiple times (in HALF_OPEN).
                Should be a thin wrapper around the external call (no retries).

        Returns:
            Return value from fn on success.

        Raises:
            CircuitOpenError: Circuit is OPEN and recovery timeout not yet elapsed.
                Contains adapter_name, open_since (ISO timestamp), failure_count.
            TransientError: fn raised TransientError and circuit is still CLOSED
                or HALF_OPEN transitions back to OPEN.
            ExternalServiceError: fn raised ExternalServiceError and circuit is still
                CLOSED or HALF_OPEN transitions back to OPEN.
            AuthError, NotFoundError, ValidationError: fn raised permanent error;
                passed through without affecting circuit state.

        Example:
            def call_broker():
                return broker.get_account()

            try:
                account = breaker.execute(call_broker)
            except CircuitOpenError as e:
                logger.warning("broker_unavailable", adapter=e.adapter_name)
            except TransientError:
                logger.error("transient_failure")
        """
        with self._lock:
            if self._state == CircuitState.CLOSED:
                return self._execute_closed(fn)
            elif self._state == CircuitState.OPEN:
                return self._execute_open(fn)
            else:  # HALF_OPEN
                return self._execute_half_open(fn)

    def _execute_closed(self, fn: Callable[[], T]) -> T:
        """
        Execute callable in CLOSED state (normal operation).

        Attempts to call fn. On success, resets failure count. On TransientError or
        ExternalServiceError, increments failure count and checks if threshold reached.
        Permanent errors pass through without affecting state.

        Args:
            fn: Callable to execute.

        Returns:
            Return value from fn on success.

        Raises:
            CircuitOpenError: If failures >= threshold (transitioned to OPEN).
            TransientError, ExternalServiceError: If fn raises (counted as failures).
            AuthError, NotFoundError, ValidationError: If fn raises (not counted).

        Example:
            # Called internally by execute() when state is CLOSED.
            result = breaker._execute_closed(call_broker)
        """
        try:
            result = fn()
            # Success: reset failure count.
            self._failure_count = 0
            logger.debug(
                "circuit_breaker.call_succeeded",
                adapter_name=self._config.name,
                state="closed",
            )
            return result
        except (AuthError, NotFoundError, ValidationError):
            # Permanent errors: pass through without affecting circuit.
            logger.warning(
                "circuit_breaker.permanent_error_closed",
                adapter_name=self._config.name,
                error_type=type(sys.exc_info()[1]).__name__,
                detail="Permanent error passed through; circuit unaffected.",
            )
            raise
        except (TransientError, ExternalServiceError) as exc:
            # Retriable errors: increment failure count.
            self._failure_count += 1
            self._last_failure_at = datetime.now(timezone.utc).isoformat()
            logger.warning(
                "circuit_breaker.failure_closed",
                adapter_name=self._config.name,
                failure_count=self._failure_count,
                failure_threshold=self._config.failure_threshold,
                error_type=type(exc).__name__,
                error_message=str(exc),
            )

            # Check if threshold reached.
            if self._failure_count >= self._config.failure_threshold:
                self._state = CircuitState.OPEN
                self._opened_at = datetime.now(timezone.utc).isoformat()
                self._trip_count += 1
                logger.error(
                    "circuit_breaker.tripped",
                    adapter_name=self._config.name,
                    state="closed",
                    new_state="open",
                    failure_count=self._failure_count,
                    recovery_timeout_s=self._config.recovery_timeout_s,
                    trip_count=self._trip_count,
                )
                self._persist_state_to_redis()
                raise CircuitOpenError(
                    f"Circuit {self._config.name} is open due to {self._failure_count} "
                    f"consecutive failures.",
                    adapter_name=self._config.name,
                    open_since=self._opened_at,
                    failure_count=self._failure_count,
                ) from exc
            raise

    def _execute_open(self, fn: Callable[[], T]) -> T:
        """
        Execute callable in OPEN state (fast-fail mode).

        Checks if recovery_timeout_s has elapsed since opened_at. If not, immediately
        raises CircuitOpenError. If yes, transitions to HALF_OPEN and delegates to
        _execute_half_open().

        Args:
            fn: Callable to execute (passed through to HALF_OPEN if recovery ready).

        Returns:
            Return value from fn (only if recovery timeout elapsed and fn succeeds).

        Raises:
            CircuitOpenError: Circuit is OPEN and recovery timeout not yet elapsed.

        Example:
            # Called internally by execute() when state is OPEN.
            result = breaker._execute_open(call_broker)
        """
        assert self._opened_at is not None, "OPEN state without opened_at timestamp"

        opened_dt = datetime.fromisoformat(self._opened_at)
        now_dt = datetime.now(timezone.utc)
        elapsed = (now_dt - opened_dt).total_seconds()

        if elapsed < self._config.recovery_timeout_s:
            logger.debug(
                "circuit_breaker.call_failed_open",
                adapter_name=self._config.name,
                state="open",
                elapsed_s=round(elapsed, 2),
                recovery_timeout_s=self._config.recovery_timeout_s,
                remaining_s=round(self._config.recovery_timeout_s - elapsed, 2),
            )
            raise CircuitOpenError(
                f"Circuit {self._config.name} is open. "
                f"Recovery probe in {self._config.recovery_timeout_s - elapsed:.1f}s.",
                adapter_name=self._config.name,
                open_since=self._opened_at,
                failure_count=self._failure_count,
            )

        # Recovery timeout elapsed, transition to HALF_OPEN.
        self._state = CircuitState.HALF_OPEN
        self._half_open_calls = 0
        logger.info(
            "circuit_breaker.recovery_probe_started",
            adapter_name=self._config.name,
            state="open",
            new_state="half_open",
            recovery_timeout_s=self._config.recovery_timeout_s,
            opened_at=self._opened_at,
        )
        self._persist_state_to_redis()
        return self._execute_half_open(fn)

    def _execute_half_open(self, fn: Callable[[], T]) -> T:
        """
        Execute callable in HALF_OPEN state (recovery probe mode).

        Allows up to half_open_max_calls probe calls. On the first success,
        transitions to CLOSED and resets failures. On any failure, transitions
        back to OPEN.

        Args:
            fn: Callable to execute (the probe call).

        Returns:
            Return value from fn on success (and transitions to CLOSED).

        Raises:
            CircuitOpenError: If half_open_max_calls exceeded without success.
            TransientError, ExternalServiceError: If probe call fails (transitions to OPEN).

        Example:
            # Called internally by execute() when state is HALF_OPEN.
            result = breaker._execute_half_open(call_broker)
        """
        if self._half_open_calls >= self._config.half_open_max_calls:
            logger.warning(
                "circuit_breaker.half_open_max_calls_exceeded",
                adapter_name=self._config.name,
                half_open_calls=self._half_open_calls,
                half_open_max_calls=self._config.half_open_max_calls,
            )
            raise CircuitOpenError(
                f"Circuit {self._config.name} exhausted probe calls in HALF_OPEN.",
                adapter_name=self._config.name,
                open_since=self._opened_at or "",
                failure_count=self._failure_count,
            )

        self._half_open_calls += 1

        try:
            result = fn()
            # Success: transition to CLOSED.
            self._state = CircuitState.CLOSED
            self._failure_count = 0
            self._opened_at = None
            self._half_open_calls = 0
            self._recovery_count += 1
            logger.info(
                "circuit_breaker.recovered",
                adapter_name=self._config.name,
                state="half_open",
                new_state="closed",
                recovery_count=self._recovery_count,
                trip_count=self._trip_count,
            )
            self._persist_state_to_redis()
            return result
        except (AuthError, NotFoundError, ValidationError):
            # Permanent error during probe: fail fast, return to OPEN.
            self._state = CircuitState.OPEN
            logger.error(
                "circuit_breaker.probe_failed_permanent",
                adapter_name=self._config.name,
                state="half_open",
                new_state="open",
                error_type=type(sys.exc_info()[1]).__name__,
                detail="Permanent error during recovery probe; circuit returned to OPEN.",
            )
            self._persist_state_to_redis()
            raise
        except (TransientError, ExternalServiceError) as exc:
            # Transient error during probe: return to OPEN, increment opened_at.
            self._state = CircuitState.OPEN
            self._opened_at = datetime.now(timezone.utc).isoformat()
            self._half_open_calls = 0
            logger.error(
                "circuit_breaker.probe_failed_transient",
                adapter_name=self._config.name,
                state="half_open",
                new_state="open",
                error_type=type(exc).__name__,
                error_message=str(exc),
                detail="Transient error during recovery probe; circuit returned to OPEN.",
            )
            self._persist_state_to_redis()
            raise
