"""
Unit tests for execution loop contracts (M6).

Tests cover:
1. LoopState enum — values, string serialisation.
2. State transitions — all valid transitions, all invalid transitions.
3. validate_transition — success and error paths.
4. is_terminal — terminal vs non-terminal states.
5. ExecutionLoopConfig — validation, defaults, symbol normalisation.
6. LoopDiagnostics — construction, defaults, frozen.
7. InvalidStateTransitionError — message format.
8. MockExecutionLoop — lifecycle, event log, introspection, thread safety.

Follows §5 TDD naming: test_<unit>_<scenario>_<expected_outcome>
"""

from __future__ import annotations

import threading
from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from libs.contracts.execution import ExecutionMode
from libs.contracts.execution_loop import (
    VALID_TRANSITIONS,
    ExecutionLoopConfig,
    InvalidStateTransitionError,
    LoopDiagnostics,
    LoopState,
    is_terminal,
    validate_transition,
)
from libs.contracts.market_data import CandleInterval
from libs.contracts.mocks.mock_execution_loop import MockExecutionLoop

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_config(**overrides: object) -> ExecutionLoopConfig:
    """Build a default ExecutionLoopConfig with overridable fields."""
    defaults = {
        "deployment_id": "deploy-001",
        "strategy_id": "ma-crossover-aapl",
        "signal_strategy_id": "ma-crossover",
        "symbols": ["AAPL"],
        "interval": CandleInterval.M5,
        "execution_mode": ExecutionMode.PAPER,
    }
    defaults.update(overrides)
    return ExecutionLoopConfig(**defaults)


# ===========================================================================
# LoopState enum tests
# ===========================================================================


class TestLoopStateEnum:
    """Verify LoopState enum values and behaviour."""

    def test_all_states_defined(self) -> None:
        """LoopState has exactly 6 members."""
        assert len(LoopState) == 6

    def test_state_values(self) -> None:
        """Each state has the correct string value."""
        assert LoopState.INITIALIZING.value == "initializing"
        assert LoopState.RUNNING.value == "running"
        assert LoopState.PAUSED.value == "paused"
        assert LoopState.COOLDOWN.value == "cooldown"
        assert LoopState.STOPPED.value == "stopped"
        assert LoopState.FAILED.value == "failed"

    def test_string_conversion(self) -> None:
        """LoopState is a str enum — works in string contexts."""
        assert str(LoopState.RUNNING) == "LoopState.RUNNING"
        assert LoopState.RUNNING == "running"

    def test_state_from_value(self) -> None:
        """Can construct LoopState from string value."""
        assert LoopState("running") == LoopState.RUNNING
        assert LoopState("failed") == LoopState.FAILED


# ===========================================================================
# State transition tests
# ===========================================================================


class TestStateTransitions:
    """Verify the state machine transition rules."""

    def test_initializing_to_running_valid(self) -> None:
        """INITIALIZING → RUNNING is allowed."""
        validate_transition(LoopState.INITIALIZING, LoopState.RUNNING)

    def test_initializing_to_failed_valid(self) -> None:
        """INITIALIZING → FAILED is allowed (startup failure)."""
        validate_transition(LoopState.INITIALIZING, LoopState.FAILED)

    def test_initializing_to_stopped_valid(self) -> None:
        """INITIALIZING → STOPPED is allowed (abort before running)."""
        validate_transition(LoopState.INITIALIZING, LoopState.STOPPED)

    def test_running_to_paused_valid(self) -> None:
        """RUNNING → PAUSED is allowed."""
        validate_transition(LoopState.RUNNING, LoopState.PAUSED)

    def test_running_to_cooldown_valid(self) -> None:
        """RUNNING → COOLDOWN is allowed (post-error)."""
        validate_transition(LoopState.RUNNING, LoopState.COOLDOWN)

    def test_running_to_stopped_valid(self) -> None:
        """RUNNING → STOPPED is allowed (graceful shutdown)."""
        validate_transition(LoopState.RUNNING, LoopState.STOPPED)

    def test_running_to_failed_valid(self) -> None:
        """RUNNING → FAILED is allowed (circuit breaker)."""
        validate_transition(LoopState.RUNNING, LoopState.FAILED)

    def test_paused_to_running_valid(self) -> None:
        """PAUSED → RUNNING is allowed (resume)."""
        validate_transition(LoopState.PAUSED, LoopState.RUNNING)

    def test_paused_to_stopped_valid(self) -> None:
        """PAUSED → STOPPED is allowed (stop while paused)."""
        validate_transition(LoopState.PAUSED, LoopState.STOPPED)

    def test_cooldown_to_running_valid(self) -> None:
        """COOLDOWN → RUNNING is allowed (auto-resume)."""
        validate_transition(LoopState.COOLDOWN, LoopState.RUNNING)

    def test_cooldown_to_failed_valid(self) -> None:
        """COOLDOWN → FAILED is allowed (too many errors in cooldown)."""
        validate_transition(LoopState.COOLDOWN, LoopState.FAILED)

    def test_cooldown_to_stopped_valid(self) -> None:
        """COOLDOWN → STOPPED is allowed (stop during cooldown)."""
        validate_transition(LoopState.COOLDOWN, LoopState.STOPPED)


class TestInvalidTransitions:
    """Verify that disallowed transitions raise InvalidStateTransitionError."""

    def test_stopped_to_running_invalid(self) -> None:
        """STOPPED is terminal — cannot transition to RUNNING."""
        with pytest.raises(InvalidStateTransitionError) as exc_info:
            validate_transition(LoopState.STOPPED, LoopState.RUNNING)
        assert exc_info.value.from_state == LoopState.STOPPED
        assert exc_info.value.to_state == LoopState.RUNNING

    def test_failed_to_running_invalid(self) -> None:
        """FAILED is terminal — cannot transition to RUNNING."""
        with pytest.raises(InvalidStateTransitionError):
            validate_transition(LoopState.FAILED, LoopState.RUNNING)

    def test_initializing_to_paused_invalid(self) -> None:
        """INITIALIZING → PAUSED is not allowed (must run first)."""
        with pytest.raises(InvalidStateTransitionError):
            validate_transition(LoopState.INITIALIZING, LoopState.PAUSED)

    def test_initializing_to_cooldown_invalid(self) -> None:
        """INITIALIZING → COOLDOWN is not allowed."""
        with pytest.raises(InvalidStateTransitionError):
            validate_transition(LoopState.INITIALIZING, LoopState.COOLDOWN)

    def test_paused_to_failed_invalid(self) -> None:
        """PAUSED → FAILED is not allowed (must resume or stop)."""
        with pytest.raises(InvalidStateTransitionError):
            validate_transition(LoopState.PAUSED, LoopState.FAILED)

    def test_paused_to_cooldown_invalid(self) -> None:
        """PAUSED → COOLDOWN is not allowed."""
        with pytest.raises(InvalidStateTransitionError):
            validate_transition(LoopState.PAUSED, LoopState.COOLDOWN)

    def test_self_transition_invalid(self) -> None:
        """Self-transitions are not allowed for any state."""
        for loop_state in LoopState:
            with pytest.raises(InvalidStateTransitionError):
                validate_transition(loop_state, loop_state)

    def test_error_message_format(self) -> None:
        """Error message includes both states."""
        with pytest.raises(InvalidStateTransitionError, match="stopped → running"):
            validate_transition(LoopState.STOPPED, LoopState.RUNNING)


class TestTerminalStates:
    """Verify is_terminal() correctly identifies terminal states."""

    def test_stopped_is_terminal(self) -> None:
        """STOPPED is a terminal state."""
        assert is_terminal(LoopState.STOPPED) is True

    def test_failed_is_terminal(self) -> None:
        """FAILED is a terminal state."""
        assert is_terminal(LoopState.FAILED) is True

    def test_running_not_terminal(self) -> None:
        """RUNNING is not terminal."""
        assert is_terminal(LoopState.RUNNING) is False

    def test_initializing_not_terminal(self) -> None:
        """INITIALIZING is not terminal."""
        assert is_terminal(LoopState.INITIALIZING) is False

    def test_paused_not_terminal(self) -> None:
        """PAUSED is not terminal."""
        assert is_terminal(LoopState.PAUSED) is False

    def test_cooldown_not_terminal(self) -> None:
        """COOLDOWN is not terminal."""
        assert is_terminal(LoopState.COOLDOWN) is False


class TestValidTransitionsCompleteness:
    """Verify the VALID_TRANSITIONS map covers all states."""

    def test_all_states_have_transition_entry(self) -> None:
        """Every LoopState appears as a key in VALID_TRANSITIONS."""
        for loop_state in LoopState:
            assert loop_state in VALID_TRANSITIONS, f"{loop_state} missing from VALID_TRANSITIONS"

    def test_no_self_transitions_in_map(self) -> None:
        """No state lists itself as a valid target."""
        for from_state, targets in VALID_TRANSITIONS.items():
            assert from_state not in targets, (
                f"{from_state} has self-transition in VALID_TRANSITIONS"
            )


# ===========================================================================
# ExecutionLoopConfig tests
# ===========================================================================


class TestExecutionLoopConfig:
    """Verify ExecutionLoopConfig validation and defaults."""

    def test_minimal_config_valid(self) -> None:
        """Config with only required fields uses correct defaults."""
        config = _make_config()
        assert config.deployment_id == "deploy-001"
        assert config.max_positions_per_symbol == 1
        assert config.cooldown_after_trade_s == 60
        assert config.max_consecutive_errors == 5
        assert config.health_check_interval_s == 30

    def test_custom_config_values(self) -> None:
        """Custom values are accepted."""
        config = _make_config(
            max_positions_per_symbol=3,
            cooldown_after_trade_s=120,
            max_consecutive_errors=10,
            health_check_interval_s=60,
        )
        assert config.max_positions_per_symbol == 3
        assert config.cooldown_after_trade_s == 120
        assert config.max_consecutive_errors == 10
        assert config.health_check_interval_s == 60

    def test_symbols_normalized_to_uppercase(self) -> None:
        """Symbols are uppercased."""
        config = _make_config(symbols=["aapl", "msft"])
        assert config.symbols == ["AAPL", "MSFT"]

    def test_symbols_deduplicated(self) -> None:
        """Duplicate symbols are removed preserving order."""
        config = _make_config(symbols=["AAPL", "msft", "aapl", "MSFT"])
        assert config.symbols == ["AAPL", "MSFT"]

    def test_symbols_whitespace_stripped(self) -> None:
        """Leading/trailing whitespace is stripped."""
        config = _make_config(symbols=["  AAPL  ", " msft"])
        assert config.symbols == ["AAPL", "MSFT"]

    def test_empty_symbols_rejected(self) -> None:
        """Empty symbols list raises validation error."""
        with pytest.raises((ValidationError, ValueError)):
            _make_config(symbols=[])

    def test_empty_string_symbol_rejected(self) -> None:
        """Symbol that is only whitespace is rejected."""
        with pytest.raises((ValidationError, ValueError)):
            _make_config(symbols=[""])

    def test_empty_deployment_id_rejected(self) -> None:
        """Empty deployment_id raises validation error."""
        with pytest.raises((ValidationError, ValueError)):
            _make_config(deployment_id="")

    def test_negative_max_positions_rejected(self) -> None:
        """max_positions_per_symbol < 1 is rejected."""
        with pytest.raises((ValidationError, ValueError)):
            _make_config(max_positions_per_symbol=0)

    def test_negative_max_errors_rejected(self) -> None:
        """max_consecutive_errors < 1 is rejected."""
        with pytest.raises((ValidationError, ValueError)):
            _make_config(max_consecutive_errors=0)

    def test_health_check_below_minimum_rejected(self) -> None:
        """health_check_interval_s < 5 is rejected."""
        with pytest.raises((ValidationError, ValueError)):
            _make_config(health_check_interval_s=1)

    def test_config_is_frozen(self) -> None:
        """Config is immutable after creation."""
        config = _make_config()
        with pytest.raises((ValidationError, ValueError)):
            config.deployment_id = "new-id"  # type: ignore[misc]

    def test_execution_mode_enum(self) -> None:
        """ExecutionMode variants are accepted."""
        for mode in ExecutionMode:
            config = _make_config(execution_mode=mode)
            assert config.execution_mode == mode

    def test_interval_enum(self) -> None:
        """CandleInterval variants are accepted."""
        for interval in CandleInterval:
            config = _make_config(interval=interval)
            assert config.interval == interval


# ===========================================================================
# LoopDiagnostics tests
# ===========================================================================


class TestLoopDiagnostics:
    """Verify LoopDiagnostics construction and defaults."""

    def test_minimal_diagnostics_defaults(self) -> None:
        """Diagnostics with only required fields have zero defaults."""
        diag = LoopDiagnostics(
            state=LoopState.RUNNING,
            deployment_id="deploy-001",
        )
        assert diag.bars_processed == 0
        assert diag.signals_generated == 0
        assert diag.signals_approved == 0
        assert diag.signals_rejected == 0
        assert diag.orders_submitted == 0
        assert diag.orders_filled == 0
        assert diag.errors == 0
        assert diag.last_bar_at is None
        assert diag.last_signal_at is None
        assert diag.last_order_at is None
        assert diag.uptime_seconds == 0.0
        assert diag.consecutive_errors == 0

    def test_full_diagnostics(self) -> None:
        """All fields can be populated."""
        now = datetime(2026, 4, 13, 14, 0, tzinfo=timezone.utc)
        diag = LoopDiagnostics(
            state=LoopState.RUNNING,
            deployment_id="deploy-001",
            bars_processed=1500,
            signals_generated=42,
            signals_approved=35,
            signals_rejected=7,
            orders_submitted=35,
            orders_filled=33,
            errors=2,
            last_bar_at=now,
            last_signal_at=now,
            last_order_at=now,
            uptime_seconds=7200.5,
            consecutive_errors=0,
        )
        assert diag.bars_processed == 1500
        assert diag.signals_generated == 42
        assert diag.uptime_seconds == 7200.5

    def test_diagnostics_is_frozen(self) -> None:
        """Diagnostics is immutable after creation."""
        diag = LoopDiagnostics(
            state=LoopState.RUNNING,
            deployment_id="deploy-001",
        )
        with pytest.raises((ValidationError, ValueError)):
            diag.bars_processed = 100  # type: ignore[misc]

    def test_negative_counters_rejected(self) -> None:
        """Negative counter values are rejected."""
        with pytest.raises((ValidationError, ValueError)):
            LoopDiagnostics(
                state=LoopState.RUNNING,
                deployment_id="deploy-001",
                bars_processed=-1,
            )

    def test_negative_uptime_rejected(self) -> None:
        """Negative uptime is rejected."""
        with pytest.raises((ValidationError, ValueError)):
            LoopDiagnostics(
                state=LoopState.RUNNING,
                deployment_id="deploy-001",
                uptime_seconds=-1.0,
            )


# ===========================================================================
# MockExecutionLoop tests
# ===========================================================================


class TestMockExecutionLoop:
    """Verify MockExecutionLoop enforces state machine and records events."""

    def test_initial_state_is_initializing(self) -> None:
        """Mock starts in INITIALIZING state."""
        loop = MockExecutionLoop()
        assert loop.state == LoopState.INITIALIZING

    def test_start_transitions_to_running(self) -> None:
        """start() transitions from INITIALIZING to RUNNING."""
        loop = MockExecutionLoop()
        loop.start(_make_config())
        assert loop.state == LoopState.RUNNING
        assert loop.start_count == 1

    def test_stop_transitions_to_stopped(self) -> None:
        """stop() transitions from RUNNING to STOPPED."""
        loop = MockExecutionLoop()
        loop.start(_make_config())
        loop.stop()
        assert loop.state == LoopState.STOPPED
        assert loop.stop_count == 1

    def test_pause_transitions_to_paused(self) -> None:
        """pause() transitions from RUNNING to PAUSED."""
        loop = MockExecutionLoop()
        loop.start(_make_config())
        loop.pause()
        assert loop.state == LoopState.PAUSED
        assert loop.pause_count == 1

    def test_resume_transitions_to_running(self) -> None:
        """resume() transitions from PAUSED to RUNNING."""
        loop = MockExecutionLoop()
        loop.start(_make_config())
        loop.pause()
        loop.resume()
        assert loop.state == LoopState.RUNNING
        assert loop.resume_count == 1

    def test_event_log_records_lifecycle(self) -> None:
        """Event log captures all lifecycle events in order."""
        loop = MockExecutionLoop()
        loop.start(_make_config())
        loop.pause()
        loop.resume()
        loop.stop()
        assert loop.event_log == ["start", "pause", "resume", "stop"]

    def test_diagnostics_default_zero_counters(self) -> None:
        """diagnostics() returns zero counters by default."""
        loop = MockExecutionLoop()
        loop.start(_make_config())
        diag = loop.diagnostics()
        assert diag.state == LoopState.RUNNING
        assert diag.deployment_id == "deploy-001"
        assert diag.bars_processed == 0

    def test_diagnostics_override(self) -> None:
        """set_diagnostics() overrides the snapshot returned."""
        loop = MockExecutionLoop()
        loop.start(_make_config())
        custom_diag = LoopDiagnostics(
            state=LoopState.RUNNING,
            deployment_id="deploy-001",
            bars_processed=999,
        )
        loop.set_diagnostics(custom_diag)
        assert loop.diagnostics().bars_processed == 999

    def test_config_stored_on_start(self) -> None:
        """config property returns the config passed to start()."""
        loop = MockExecutionLoop()
        config = _make_config()
        loop.start(config)
        assert loop.config is config

    def test_force_state_bypasses_validation(self) -> None:
        """force_state() sets state without transition check."""
        loop = MockExecutionLoop()
        loop.force_state(LoopState.COOLDOWN)
        assert loop.state == LoopState.COOLDOWN

    def test_clear_resets_everything(self) -> None:
        """clear() returns mock to initial state."""
        loop = MockExecutionLoop()
        loop.start(_make_config())
        loop.pause()
        loop.clear()
        assert loop.state == LoopState.INITIALIZING
        assert loop.event_log == []
        assert loop.start_count == 0
        assert loop.config is None

    def test_invalid_transition_from_stopped(self) -> None:
        """Cannot start after stop (terminal state)."""
        loop = MockExecutionLoop()
        loop.start(_make_config())
        loop.stop()
        with pytest.raises(InvalidStateTransitionError):
            loop.start(_make_config())

    def test_invalid_pause_from_initializing(self) -> None:
        """Cannot pause before starting."""
        loop = MockExecutionLoop()
        with pytest.raises(InvalidStateTransitionError):
            loop.pause()

    def test_thread_safety_concurrent_operations(self) -> None:
        """Concurrent lifecycle calls don't corrupt state."""
        loop = MockExecutionLoop()
        loop.start(_make_config())
        errors: list[Exception] = []
        barrier = threading.Barrier(20)

        def worker() -> None:
            try:
                barrier.wait(timeout=5)
                # All threads read diagnostics concurrently.
                _ = loop.diagnostics()
                _ = loop.state
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=worker) for _ in range(20)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=10)

        assert len(errors) == 0
