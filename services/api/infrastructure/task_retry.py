"""
Task retry configuration and exponential backoff utilities.

Provides reusable retry logic with exponential backoff and jitter for
resilient handling of transient failures in Celery and other async operations.

Responsibilities:
- Define retry configuration (max retries, delays, backoff strategy).
- Compute exponential backoff delays with optional jitter.
- Wrap functions to automatically retry on transient errors.
- Distinguish between retriable (transient) and permanent errors.
- Log retry attempts using structlog.

Does NOT:
- Perform the actual I/O operations (that's the wrapped function's job).
- Retry on permanent failures (ValueError, TypeError, KeyError, PermissionError).
- Modify exception messages or stack traces.

Dependencies:
- structlog: Structured logging for retry events.
- dataclasses: TaskRetryConfig data container.

Error conditions:
- Transient errors (ConnectionError, TimeoutError, OSError): retry with backoff.
- Permanent errors (ValueError, TypeError, KeyError, PermissionError): fail fast.
- Max retries exhausted: re-raise the last exception.

Example:
    from services.api.infrastructure.task_retry import (
        DEFAULT_RETRY_CONFIG,
        with_retry,
    )
    import structlog

    logger = structlog.get_logger(__name__)

    def call_celery_inspect():
        return inspect.active()

    result = with_retry(call_celery_inspect, DEFAULT_RETRY_CONFIG, logger)
"""

from __future__ import annotations

import random
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, TypeVar

import structlog

logger = structlog.get_logger(__name__)

T = TypeVar("T")


@dataclass
class TaskRetryConfig:
    """
    Configuration for task retry behavior with exponential backoff.

    Attributes:
        max_retries: Maximum number of retry attempts (after initial attempt).
            Default 3. Total attempts = 1 + max_retries.
        base_delay_seconds: Initial delay between retries in seconds.
            Default 1.0. Multiplied by exponential_base^attempt.
        max_delay_seconds: Maximum delay between retries (cap).
            Default 30.0. Prevents unbounded backoff.
        exponential_base: Multiplier for exponential backoff.
            Default 2.0. Delay = base_delay * (exponential_base ^ attempt).
        jitter: Whether to add random jitter to computed delays.
            Default True. Jitter is ±10% of computed delay.

    Example:
        config = TaskRetryConfig(max_retries=5, base_delay_seconds=0.5)
        # Total attempts: 6 (1 initial + 5 retries)
        # Delays: 0.5s, 1.0s, 2.0s, 4.0s, 8.0s (with jitter ±10%)
    """

    max_retries: int = 3
    base_delay_seconds: float = 1.0
    max_delay_seconds: float = 30.0
    exponential_base: float = 2.0
    jitter: bool = True


# Module-level default configuration for convenience.
DEFAULT_RETRY_CONFIG = TaskRetryConfig()


def compute_delay(attempt: int, config: TaskRetryConfig) -> float:
    """
    Compute the delay for a given retry attempt with exponential backoff.

    Implements exponential backoff: delay = base_delay * (exponential_base ^ attempt).
    Optionally adds jitter (±10% of computed delay) and caps at max_delay_seconds.

    Args:
        attempt: Zero-indexed retry attempt number (0 = first retry, 1 = second, etc).
        config: TaskRetryConfig specifying backoff strategy.

    Returns:
        Delay in seconds to wait before the next attempt.

    Example:
        config = TaskRetryConfig(base_delay_seconds=1.0, exponential_base=2.0, jitter=False)
        compute_delay(0, config)  # 1.0 * 2^0 = 1.0s
        compute_delay(1, config)  # 1.0 * 2^1 = 2.0s
        compute_delay(2, config)  # 1.0 * 2^2 = 4.0s
    """
    # Exponential backoff formula.
    exponent = attempt
    delay = config.base_delay_seconds * (config.exponential_base**exponent)

    # Cap at max delay.
    delay = min(delay, config.max_delay_seconds)

    # Apply jitter if enabled (±10% of delay).
    if config.jitter:
        jitter_factor = 1.0 + random.uniform(-0.1, 0.1)
        delay = delay * jitter_factor

    return delay


def with_retry(
    fn: Callable[[], T],
    config: TaskRetryConfig,
    logger: Any,
) -> T:
    """
    Wrap a function to automatically retry on transient errors.

    Implements exponential backoff with optional jitter. Retries on transient
    errors (ConnectionError, TimeoutError, OSError) but fails fast on permanent
    errors (ValueError, TypeError, KeyError, PermissionError).

    Args:
        fn: Callable that takes no arguments and returns T.
            Must be idempotent or safe to retry.
        config: TaskRetryConfig specifying retry strategy.
        logger: structlog logger instance for logging retry attempts.

    Returns:
        Return value from fn on success.

    Raises:
        Same exception as fn raises on permanent errors or after max retries exhausted.
        The original exception is re-raised after all retries are exhausted.

    Example:
        def call_redis():
            return redis_client.get("key")

        result = with_retry(call_redis, DEFAULT_RETRY_CONFIG, logger)
    """
    # Errors that should trigger a retry (transient).
    retriable_errors = (ConnectionError, TimeoutError, OSError)

    # Errors that should fail fast (permanent).
    permanent_errors = (ValueError, TypeError, KeyError, PermissionError)

    last_exception: Exception | None = None

    # Initial attempt + max_retries = total attempts.
    for attempt in range(1 + config.max_retries):
        try:
            return fn()
        except permanent_errors as exc:
            # Fail fast on permanent errors.
            logger.warning(
                "task_retry.permanent_error",
                error_type=type(exc).__name__,
                error_message=str(exc),
                attempt=attempt,
            )
            raise
        except retriable_errors as exc:
            # Record this exception to re-raise if retries exhausted.
            last_exception = exc

            # If we've exhausted retries, re-raise.
            if attempt >= config.max_retries:
                logger.error(
                    "task_retry.max_retries_exhausted",
                    error_type=type(exc).__name__,
                    error_message=str(exc),
                    total_attempts=attempt + 1,
                    max_retries=config.max_retries,
                )
                raise

            # Compute delay and wait.
            delay = compute_delay(attempt, config)
            logger.warning(
                "task_retry.transient_error_retrying",
                error_type=type(exc).__name__,
                error_message=str(exc),
                attempt=attempt,
                delay_seconds=delay,
                max_retries=config.max_retries,
            )
            time.sleep(delay)

    # Fallback: should not reach here (loop either returns or raises).
    if last_exception:
        raise last_exception
    # Should be unreachable.
    raise RuntimeError("Unexpected state in with_retry")
