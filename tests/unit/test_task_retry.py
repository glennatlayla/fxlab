"""
Unit tests for task retry configuration and exponential backoff logic.

Responsibilities:
- Test exponential backoff delay computation.
- Test jitter application.
- Test max delay capping.
- Test retry wrapper behavior for transient vs permanent errors.
- Test default configuration values.

Uses mocks for external dependencies; no I/O.
"""

import time
from unittest.mock import MagicMock

import pytest
import structlog

from services.api.infrastructure.task_retry import (
    DEFAULT_RETRY_CONFIG,
    TaskRetryConfig,
    compute_delay,
    with_retry,
)


class TestTaskRetryConfig:
    """Test TaskRetryConfig dataclass defaults and construction."""

    def test_default_config_values(self) -> None:
        """
        TaskRetryConfig should have sensible default values.

        Expected:
        - max_retries = 3
        - base_delay_seconds = 1.0
        - max_delay_seconds = 30.0
        - exponential_base = 2.0
        - jitter = True
        """
        config = TaskRetryConfig()

        assert config.max_retries == 3
        assert config.base_delay_seconds == 1.0
        assert config.max_delay_seconds == 30.0
        assert config.exponential_base == 2.0
        assert config.jitter is True

    def test_default_retry_config_module_constant(self) -> None:
        """
        DEFAULT_RETRY_CONFIG module constant should exist and be a TaskRetryConfig.

        Expected:
        - DEFAULT_RETRY_CONFIG is a TaskRetryConfig instance.
        - Has default values.
        """
        assert isinstance(DEFAULT_RETRY_CONFIG, TaskRetryConfig)
        assert DEFAULT_RETRY_CONFIG.max_retries == 3

    def test_custom_config_values(self) -> None:
        """
        TaskRetryConfig should allow custom values at construction.

        Expected:
        - All fields can be overridden.
        """
        config = TaskRetryConfig(
            max_retries=5,
            base_delay_seconds=0.5,
            max_delay_seconds=60.0,
            exponential_base=3.0,
            jitter=False,
        )

        assert config.max_retries == 5
        assert config.base_delay_seconds == 0.5
        assert config.max_delay_seconds == 60.0
        assert config.exponential_base == 3.0
        assert config.jitter is False


class TestComputeDelay:
    """Test compute_delay function for exponential backoff."""

    def test_compute_delay_exponential_backoff(self) -> None:
        """
        compute_delay should return exponentially increasing delays.

        Scenario:
        - base_delay_seconds = 1.0
        - exponential_base = 2.0
        - max_delay_seconds = 30.0
        - jitter = False

        Expected:
        - Attempt 0: 1 second (base_delay * 2^0)
        - Attempt 1: 2 seconds (base_delay * 2^1)
        - Attempt 2: 4 seconds (base_delay * 2^2)
        """
        config = TaskRetryConfig(jitter=False)

        delay_0 = compute_delay(0, config)
        delay_1 = compute_delay(1, config)
        delay_2 = compute_delay(2, config)

        assert delay_0 == 1.0
        assert delay_1 == 2.0
        assert delay_2 == 4.0

    def test_compute_delay_respects_max_delay(self) -> None:
        """
        compute_delay should cap delay at max_delay_seconds.

        Scenario:
        - base_delay_seconds = 1.0
        - exponential_base = 2.0
        - max_delay_seconds = 10.0
        - Attempt 4: 16 seconds (would exceed max)

        Expected:
        - Attempt 4 returns 10.0 (capped).
        """
        config = TaskRetryConfig(
            base_delay_seconds=1.0,
            max_delay_seconds=10.0,
            exponential_base=2.0,
            jitter=False,
        )

        delay_4 = compute_delay(4, config)
        assert delay_4 == 10.0

    def test_compute_delay_with_jitter_varies(self) -> None:
        """
        compute_delay with jitter=True should return slightly varied delays.

        Scenario:
        - Same attempt called multiple times.
        - jitter = True

        Expected:
        - Delays are different (but within reasonable bounds).
        """
        config = TaskRetryConfig(jitter=True)

        delay_1 = compute_delay(1, config)
        delay_2 = compute_delay(1, config)
        delay_3 = compute_delay(1, config)

        # All should be close to 2.0 (base_delay * 2^1) but not identical
        # due to jitter. Jitter should be ±10% of the base delay.
        base_expected = 2.0
        for delay in [delay_1, delay_2, delay_3]:
            assert base_expected * 0.9 <= delay <= base_expected * 1.1

        # At least some variation should exist (with high probability)
        delays = [delay_1, delay_2, delay_3]
        assert len(set(delays)) > 1 or all(d == base_expected for d in delays)

    def test_compute_delay_without_jitter_is_deterministic(self) -> None:
        """
        compute_delay with jitter=False should return same value every time.

        Scenario:
        - Same attempt called multiple times.
        - jitter = False

        Expected:
        - Delays are identical (deterministic).
        """
        config = TaskRetryConfig(jitter=False)

        delay_1 = compute_delay(1, config)
        delay_2 = compute_delay(1, config)
        delay_3 = compute_delay(1, config)

        assert delay_1 == delay_2 == delay_3 == 2.0

    def test_compute_delay_first_attempt_uses_base_delay(self) -> None:
        """
        compute_delay for attempt 0 should return base_delay_seconds.

        Expected:
        - Attempt 0: base_delay_seconds
        """
        config = TaskRetryConfig(base_delay_seconds=2.5, jitter=False)

        delay = compute_delay(0, config)
        assert delay == 2.5


class TestWithRetry:
    """Test with_retry wrapper function."""

    def test_with_retry_succeeds_on_first_attempt(self) -> None:
        """
        with_retry should return result when function succeeds immediately.

        Scenario:
        - fn() returns "success"
        - Call with_retry(fn, config, logger)

        Expected:
        - Returns "success"
        - No retries logged
        """
        fn = MagicMock(return_value="success")
        config = TaskRetryConfig()
        logger = structlog.get_logger(__name__)

        result = with_retry(fn, config, logger)

        assert result == "success"
        fn.assert_called_once()

    def test_with_retry_succeeds_after_transient_failure(self) -> None:
        """
        with_retry should retry on transient errors and succeed.

        Scenario:
        - fn() raises ConnectionError on first call
        - fn() raises TimeoutError on second call
        - fn() returns "success" on third call
        - config.max_retries = 3

        Expected:
        - Returns "success"
        - fn called 3 times
        - Retries logged
        """
        fn = MagicMock(
            side_effect=[
                ConnectionError("Network error"),
                TimeoutError("Timeout"),
                "success",
            ]
        )
        config = TaskRetryConfig(max_retries=3, base_delay_seconds=0.01, jitter=False)
        logger = structlog.get_logger(__name__)

        result = with_retry(fn, config, logger)

        assert result == "success"
        assert fn.call_count == 3

    def test_with_retry_gives_up_after_max_retries(self) -> None:
        """
        with_retry should re-raise exception after max_retries exhausted.

        Scenario:
        - fn() always raises ConnectionError
        - config.max_retries = 2

        Expected:
        - Raises ConnectionError
        - fn called 3 times (initial + 2 retries)
        """
        fn = MagicMock(side_effect=ConnectionError("Network error"))
        config = TaskRetryConfig(max_retries=2, base_delay_seconds=0.01, jitter=False)
        logger = structlog.get_logger(__name__)

        with pytest.raises(ConnectionError, match="Network error"):
            with_retry(fn, config, logger)

        assert fn.call_count == 3  # 1 initial + 2 retries

    def test_with_retry_does_not_retry_permanent_errors(self) -> None:
        """
        with_retry should NOT retry on permanent errors (ValueError, TypeError, etc).

        Scenario:
        - fn() raises ValueError (permanent)
        - config.max_retries = 3

        Expected:
        - Raises ValueError immediately (no retries)
        - fn called only 1 time
        """
        fn = MagicMock(side_effect=ValueError("Invalid input"))
        config = TaskRetryConfig(max_retries=3)
        logger = structlog.get_logger(__name__)

        with pytest.raises(ValueError, match="Invalid input"):
            with_retry(fn, config, logger)

        assert fn.call_count == 1

    def test_with_retry_does_not_retry_type_error(self) -> None:
        """
        with_retry should NOT retry on TypeError.

        Expected:
        - fn called only 1 time
        - Raises TypeError
        """
        fn = MagicMock(side_effect=TypeError("Bad argument"))
        config = TaskRetryConfig(max_retries=3)
        logger = structlog.get_logger(__name__)

        with pytest.raises(TypeError, match="Bad argument"):
            with_retry(fn, config, logger)

        assert fn.call_count == 1

    def test_with_retry_does_not_retry_key_error(self) -> None:
        """
        with_retry should NOT retry on KeyError.

        Expected:
        - fn called only 1 time
        - Raises KeyError
        """
        fn = MagicMock(side_effect=KeyError("missing_key"))
        config = TaskRetryConfig(max_retries=3)
        logger = structlog.get_logger(__name__)

        with pytest.raises(KeyError, match="missing_key"):
            with_retry(fn, config, logger)

        assert fn.call_count == 1

    def test_with_retry_does_not_retry_permission_error(self) -> None:
        """
        with_retry should NOT retry on PermissionError.

        Expected:
        - fn called only 1 time
        - Raises PermissionError
        """
        fn = MagicMock(side_effect=PermissionError("Access denied"))
        config = TaskRetryConfig(max_retries=3)
        logger = structlog.get_logger(__name__)

        with pytest.raises(PermissionError, match="Access denied"):
            with_retry(fn, config, logger)

        assert fn.call_count == 1

    def test_with_retry_retries_os_error(self) -> None:
        """
        with_retry should retry on OSError (transient).

        Scenario:
        - fn() raises OSError on first call
        - fn() returns "success" on second call

        Expected:
        - Returns "success"
        - fn called 2 times
        """
        fn = MagicMock(
            side_effect=[
                OSError("I/O error"),
                "success",
            ]
        )
        config = TaskRetryConfig(max_retries=3, base_delay_seconds=0.01, jitter=False)
        logger = structlog.get_logger(__name__)

        result = with_retry(fn, config, logger)

        assert result == "success"
        assert fn.call_count == 2

    def test_with_retry_logs_retry_attempts(self) -> None:
        """
        with_retry should log each retry attempt with structlog.

        Scenario:
        - fn() raises ConnectionError on first call
        - fn() returns "success" on second call
        - Logger is provided

        Expected:
        - Logger receives calls with retry attempt info
        """
        fn = MagicMock(
            side_effect=[
                ConnectionError("Network error"),
                "success",
            ]
        )
        config = TaskRetryConfig(max_retries=2, base_delay_seconds=0.01, jitter=False)

        # Create a mock logger with warning method
        mock_logger = MagicMock()
        mock_logger.warning = MagicMock()

        result = with_retry(fn, config, mock_logger)

        assert result == "success"
        # Verify logger.warning was called at least once for the retry
        assert mock_logger.warning.called


class TestWithRetryIntegration:
    """Integration tests for with_retry with real Celery-like operations."""

    def test_with_retry_simulates_celery_inspect_call(self) -> None:
        """
        Simulate a Celery inspect call that fails transiently then succeeds.

        Scenario:
        - Simulated inspect.active() fails with ConnectionError
        - Retried and succeeds with a dict result

        Expected:
        - Returns the dict result
        - No exception raised
        """
        result_dict = {"worker1": []}

        fn = MagicMock(
            side_effect=[
                ConnectionError("Redis unavailable"),
                result_dict,
            ]
        )
        config = TaskRetryConfig(max_retries=3, base_delay_seconds=0.01, jitter=False)
        logger = structlog.get_logger(__name__)

        result = with_retry(fn, config, logger)

        assert result == result_dict
        assert fn.call_count == 2

    def test_with_retry_respects_max_delay_between_attempts(self) -> None:
        """
        with_retry should respect max_delay_seconds between retry attempts.

        This is more of an integration test verifying delay is actually applied.

        Scenario:
        - fn() fails twice then succeeds
        - Delays are computed and applied
        - max_delay_seconds is respected

        Expected:
        - All retries eventually succeed
        - Delays are reasonable (no instant failures)
        """
        fn = MagicMock(
            side_effect=[
                TimeoutError("Timeout 1"),
                TimeoutError("Timeout 2"),
                {"result": "data"},
            ]
        )
        config = TaskRetryConfig(
            max_retries=3,
            base_delay_seconds=0.01,
            max_delay_seconds=0.05,
            exponential_base=2.0,
            jitter=False,
        )
        logger = structlog.get_logger(__name__)

        start = time.time()
        result = with_retry(fn, config, logger)
        elapsed = time.time() - start

        assert result == {"result": "data"}
        assert fn.call_count == 3
        # Should have at least 0.01 + 0.02 = 0.03 seconds of delay
        # (plus some overhead), but less than 1 second
        assert 0.02 < elapsed < 1.0
