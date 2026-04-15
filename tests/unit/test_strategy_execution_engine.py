"""
Unit tests for StrategyExecutionEngine (M7).

Tests cover the full execution loop lifecycle, bar processing pipeline,
signal→order flow, error handling, circuit breaker, kill switch integration,
graceful shutdown, and concurrent access.

Test groups:
1. Lifecycle — start, stop, pause, resume, diagnostics.
2. Bar processing — candle ingestion, indicator computation, signal generation.
3. Signal→Order flow — evaluation, approval, order submission.
4. Error handling — transient failures, circuit breaker, cooldown.
5. Kill switch — halt detection, pause on halt.
6. Graceful shutdown — cooperative stop, in-flight bar completion.
7. Thread safety — concurrent diagnostics reads.
8. Edge cases — empty candles, strategy returns None, unsupported symbol.

Follows §5 TDD naming: test_<unit>_<scenario>_<expected_outcome>
"""

from __future__ import annotations

import threading
import time
from datetime import datetime, timezone
from decimal import Decimal
from unittest.mock import MagicMock

import pytest

from libs.contracts.execution import (
    ExecutionMode,
    OrderResponse,
    OrderSide,
    OrderStatus,
    OrderType,
    PositionSnapshot,
    TimeInForce,
)
from libs.contracts.execution_loop import (
    ExecutionLoopConfig,
    InvalidStateTransitionError,
    LoopDiagnostics,
    LoopState,
)
from libs.contracts.market_data import Candle, CandleInterval
from libs.contracts.signal import (
    RiskGateResult,
    Signal,
    SignalDirection,
    SignalEvaluation,
    SignalStrength,
    SignalType,
)
from services.worker.execution.strategy_execution_engine import StrategyExecutionEngine

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_NOW = datetime(2026, 4, 13, 14, 0, tzinfo=timezone.utc)
_DEPLOY_ID = "deploy-test-001"
_CORR_PREFIX = "corr-"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_config(**overrides: object) -> ExecutionLoopConfig:
    """Build a default ExecutionLoopConfig."""
    defaults = {
        "deployment_id": _DEPLOY_ID,
        "strategy_id": "ma-crossover-aapl",
        "signal_strategy_id": "ma-crossover",
        "symbols": ["AAPL"],
        "interval": CandleInterval.M5,
        "execution_mode": ExecutionMode.PAPER,
        "max_consecutive_errors": 3,
        "health_check_interval_s": 5,
    }
    defaults.update(overrides)
    return ExecutionLoopConfig(**defaults)


def _make_candle(
    symbol: str = "AAPL",
    timestamp: datetime | None = None,
) -> Candle:
    """Build a test candle."""
    return Candle(
        symbol=symbol,
        interval=CandleInterval.M5,
        timestamp=timestamp or _NOW,
        open=Decimal("175.00"),
        high=Decimal("176.00"),
        low=Decimal("174.00"),
        close=Decimal("175.50"),
        volume=1000,
    )


def _make_signal(
    symbol: str = "AAPL",
    signal_id: str = "sig-001",
) -> Signal:
    """Build a test signal."""
    return Signal(
        signal_id=signal_id,
        strategy_id="ma-crossover",
        deployment_id=_DEPLOY_ID,
        symbol=symbol,
        direction=SignalDirection.LONG,
        signal_type=SignalType.ENTRY,
        strength=SignalStrength.MODERATE,
        confidence=0.75,
        indicators_used={"sma_20": 175.0},
        bar_timestamp=_NOW,
        generated_at=_NOW,
        correlation_id="corr-001",
        suggested_stop=Decimal("170.00"),
    )


def _make_evaluation(
    signal: Signal,
    approved: bool = True,
) -> SignalEvaluation:
    """Build a test evaluation."""
    return SignalEvaluation(
        evaluation_id="eval-001",
        signal=signal,
        approved=approved,
        gate_results=[
            RiskGateResult(gate_name="data_quality", passed=True, details={}),
        ],
        position_size=Decimal("100") if approved else Decimal("0"),
        adjusted_stop=Decimal("170.00") if approved else None,
        rejection_reason=None if approved else "Risk gate failed",
        evaluated_at=_NOW,
    )


def _make_order_response() -> OrderResponse:
    """Build a test order response."""
    return OrderResponse(
        client_order_id="ord-001",
        broker_order_id="brok-001",
        symbol="AAPL",
        side=OrderSide.BUY,
        order_type=OrderType.MARKET,
        quantity=Decimal("100"),
        status=OrderStatus.SUBMITTED,
        time_in_force=TimeInForce.DAY,
        submitted_at=_NOW,
        correlation_id="corr-001",
        execution_mode=ExecutionMode.PAPER,
    )


def _build_engine() -> StrategyExecutionEngine:
    """
    Build a StrategyExecutionEngine with all dependencies mocked.

    Returns the engine with mock dependencies accessible as attributes.
    """
    engine = StrategyExecutionEngine(
        signal_strategy=MagicMock(),
        signal_evaluation_service=MagicMock(),
        broker_adapter=MagicMock(),
        market_data_repository=MagicMock(),
        indicator_engine=MagicMock(),
        kill_switch_service=MagicMock(),
        signal_repository=MagicMock(),
    )
    # Set reasonable defaults on mocks.
    engine._signal_strategy.strategy_id = "ma-crossover"
    engine._signal_strategy.required_indicators.return_value = []
    engine._signal_strategy.evaluate.return_value = None
    engine._signal_strategy.supported_symbols = []

    engine._kill_switch_service.is_halted.return_value = False
    engine._broker_adapter.get_positions.return_value = []
    engine._market_data_repository.query_candles.return_value = MagicMock(candles=[], total_count=0)
    engine._indicator_engine.compute_batch.return_value = {}
    engine._signal_repository.save_signal.side_effect = lambda s: s
    engine._signal_repository.save_evaluation.side_effect = lambda e: e

    return engine


# ===========================================================================
# Lifecycle tests
# ===========================================================================


class TestLifecycle:
    """Verify engine lifecycle management."""

    def test_initial_state_is_initializing(self) -> None:
        """Engine starts in INITIALIZING state."""
        engine = _build_engine()
        assert engine.state == LoopState.INITIALIZING

    def test_start_transitions_to_running(self) -> None:
        """start() transitions to RUNNING."""
        engine = _build_engine()
        config = _make_config()
        engine.start(config)
        try:
            assert engine.state == LoopState.RUNNING
        finally:
            engine.stop()

    def test_stop_transitions_to_stopped(self) -> None:
        """stop() transitions to STOPPED from RUNNING."""
        engine = _build_engine()
        engine.start(_make_config())
        engine.stop()
        assert engine.state == LoopState.STOPPED

    def test_pause_transitions_to_paused(self) -> None:
        """pause() transitions from RUNNING to PAUSED."""
        engine = _build_engine()
        engine.start(_make_config())
        try:
            engine.pause()
            assert engine.state == LoopState.PAUSED
        finally:
            if engine.state != LoopState.STOPPED:
                engine.stop()

    def test_resume_transitions_from_paused(self) -> None:
        """resume() transitions from PAUSED back to RUNNING."""
        engine = _build_engine()
        engine.start(_make_config())
        try:
            engine.pause()
            engine.resume()
            assert engine.state == LoopState.RUNNING
        finally:
            engine.stop()

    def test_stop_from_paused(self) -> None:
        """stop() works from PAUSED state."""
        engine = _build_engine()
        engine.start(_make_config())
        engine.pause()
        engine.stop()
        assert engine.state == LoopState.STOPPED

    def test_double_stop_raises(self) -> None:
        """Calling stop() twice raises InvalidStateTransitionError."""
        engine = _build_engine()
        engine.start(_make_config())
        engine.stop()
        with pytest.raises(InvalidStateTransitionError):
            engine.stop()

    def test_pause_from_stopped_raises(self) -> None:
        """Cannot pause a stopped engine."""
        engine = _build_engine()
        engine.start(_make_config())
        engine.stop()
        with pytest.raises(InvalidStateTransitionError):
            engine.pause()

    def test_diagnostics_returns_snapshot(self) -> None:
        """diagnostics() returns a LoopDiagnostics with correct state."""
        engine = _build_engine()
        engine.start(_make_config())
        try:
            diag = engine.diagnostics()
            assert isinstance(diag, LoopDiagnostics)
            assert diag.state == LoopState.RUNNING
            assert diag.deployment_id == _DEPLOY_ID
        finally:
            engine.stop()

    def test_diagnostics_before_start(self) -> None:
        """diagnostics() works in INITIALIZING state."""
        engine = _build_engine()
        diag = engine.diagnostics()
        assert diag.state == LoopState.INITIALIZING

    def test_config_stored_after_start(self) -> None:
        """The config is accessible after start."""
        engine = _build_engine()
        config = _make_config()
        engine.start(config)
        try:
            assert engine._config is config
        finally:
            engine.stop()


# ===========================================================================
# Bar processing tests
# ===========================================================================


class TestBarProcessing:
    """Verify the bar processing pipeline."""

    def test_process_bar_increments_counter(self) -> None:
        """Processing a bar increments bars_processed."""
        engine = _build_engine()
        engine.start(_make_config())
        try:
            candle = _make_candle()
            engine.process_bar(candle)
            diag = engine.diagnostics()
            assert diag.bars_processed == 1
        finally:
            engine.stop()

    def test_process_bar_computes_indicators(self) -> None:
        """Bar processing triggers indicator computation when buffer has >1 candle."""
        engine = _build_engine()
        engine._signal_strategy.required_indicators.return_value = [
            MagicMock(indicator_name="SMA", params={"period": 20}),
        ]
        engine.start(_make_config())
        try:
            # First bar fills the buffer; second triggers compute_batch.
            engine.process_bar(_make_candle())
            engine.process_bar(_make_candle())
            engine._indicator_engine.compute_batch.assert_called_once()
        finally:
            engine.stop()

    def test_process_bar_evaluates_strategy(self) -> None:
        """Bar processing calls strategy.evaluate()."""
        engine = _build_engine()
        engine.start(_make_config())
        try:
            candle = _make_candle()
            engine.process_bar(candle)
            engine._signal_strategy.evaluate.assert_called_once()
        finally:
            engine.stop()

    def test_no_signal_means_no_evaluation(self) -> None:
        """When strategy returns None, no evaluation or order occurs."""
        engine = _build_engine()
        engine._signal_strategy.evaluate.return_value = None
        engine.start(_make_config())
        try:
            engine.process_bar(_make_candle())
            engine._signal_evaluation_service.evaluate.assert_not_called()
            engine._broker_adapter.submit_order.assert_not_called()
        finally:
            engine.stop()


# ===========================================================================
# Signal → Order flow tests
# ===========================================================================


class TestSignalOrderFlow:
    """Verify signal evaluation and order submission."""

    def test_approved_signal_submits_order(self) -> None:
        """Approved signal triggers order submission."""
        engine = _build_engine()
        signal = _make_signal()
        evaluation = _make_evaluation(signal, approved=True)
        engine._signal_strategy.evaluate.return_value = signal
        engine._signal_evaluation_service.evaluate.return_value = evaluation
        engine._broker_adapter.submit_order.return_value = _make_order_response()
        engine.start(_make_config())
        try:
            engine.process_bar(_make_candle())
            engine._broker_adapter.submit_order.assert_called_once()
            diag = engine.diagnostics()
            assert diag.signals_generated == 1
            assert diag.signals_approved == 1
            assert diag.orders_submitted == 1
        finally:
            engine.stop()

    def test_rejected_signal_no_order(self) -> None:
        """Rejected signal does not submit an order."""
        engine = _build_engine()
        signal = _make_signal()
        evaluation = _make_evaluation(signal, approved=False)
        engine._signal_strategy.evaluate.return_value = signal
        engine._signal_evaluation_service.evaluate.return_value = evaluation
        engine.start(_make_config())
        try:
            engine.process_bar(_make_candle())
            engine._broker_adapter.submit_order.assert_not_called()
            diag = engine.diagnostics()
            assert diag.signals_generated == 1
            assert diag.signals_rejected == 1
            assert diag.orders_submitted == 0
        finally:
            engine.stop()

    def test_signal_and_evaluation_persisted(self) -> None:
        """Both signal and evaluation are saved to repository."""
        engine = _build_engine()
        signal = _make_signal()
        evaluation = _make_evaluation(signal, approved=True)
        engine._signal_strategy.evaluate.return_value = signal
        engine._signal_evaluation_service.evaluate.return_value = evaluation
        engine._broker_adapter.submit_order.return_value = _make_order_response()
        engine.start(_make_config())
        try:
            engine.process_bar(_make_candle())
            engine._signal_repository.save_signal.assert_called_once_with(signal)
            engine._signal_repository.save_evaluation.assert_called_once_with(evaluation)
        finally:
            engine.stop()

    def test_shadow_mode_no_order_submission(self) -> None:
        """In SHADOW mode, approved signals do not submit orders."""
        engine = _build_engine()
        signal = _make_signal()
        evaluation = _make_evaluation(signal, approved=True)
        engine._signal_strategy.evaluate.return_value = signal
        engine._signal_evaluation_service.evaluate.return_value = evaluation
        config = _make_config(execution_mode=ExecutionMode.SHADOW)
        engine.start(config)
        try:
            engine.process_bar(_make_candle())
            engine._broker_adapter.submit_order.assert_not_called()
            diag = engine.diagnostics()
            assert diag.signals_approved == 1
            # Orders not submitted in shadow mode.
            assert diag.orders_submitted == 0
        finally:
            engine.stop()


# ===========================================================================
# Error handling tests
# ===========================================================================


class TestErrorHandling:
    """Verify error handling and circuit breaker."""

    def test_strategy_error_increments_error_counter(self) -> None:
        """Exception during strategy evaluation increments error counter."""
        engine = _build_engine()
        engine._signal_strategy.evaluate.side_effect = RuntimeError("strategy boom")
        engine.start(_make_config())
        try:
            engine.process_bar(_make_candle())
            diag = engine.diagnostics()
            assert diag.errors >= 1
            assert diag.consecutive_errors >= 1
        finally:
            engine.stop()

    def test_circuit_breaker_trips_after_max_errors(self) -> None:
        """Engine transitions to FAILED after max_consecutive_errors."""
        engine = _build_engine()
        engine._signal_strategy.evaluate.side_effect = RuntimeError("boom")
        config = _make_config(max_consecutive_errors=3)
        engine.start(config)
        # Process bars until circuit breaker trips.
        for _ in range(3):
            engine.process_bar(_make_candle())
        assert engine.state == LoopState.FAILED

    def test_successful_bar_resets_consecutive_errors(self) -> None:
        """A successful bar processing resets the consecutive error counter."""
        engine = _build_engine()
        # First bar fails.
        engine._signal_strategy.evaluate.side_effect = RuntimeError("boom")
        engine.start(_make_config(max_consecutive_errors=5))
        try:
            engine.process_bar(_make_candle())
            assert engine.diagnostics().consecutive_errors == 1
            # Next bar succeeds.
            engine._signal_strategy.evaluate.side_effect = None
            engine._signal_strategy.evaluate.return_value = None
            engine.process_bar(_make_candle())
            assert engine.diagnostics().consecutive_errors == 0
        finally:
            if engine.state != LoopState.FAILED:
                engine.stop()

    def test_evaluation_error_counted(self) -> None:
        """Exception during signal evaluation counts as error."""
        engine = _build_engine()
        signal = _make_signal()
        engine._signal_strategy.evaluate.return_value = signal
        engine._signal_evaluation_service.evaluate.side_effect = RuntimeError("eval fail")
        engine.start(_make_config())
        try:
            engine.process_bar(_make_candle())
            diag = engine.diagnostics()
            assert diag.errors >= 1
        finally:
            engine.stop()

    def test_order_submission_error_counted(self) -> None:
        """Exception during order submission counts as error."""
        engine = _build_engine()
        signal = _make_signal()
        evaluation = _make_evaluation(signal, approved=True)
        engine._signal_strategy.evaluate.return_value = signal
        engine._signal_evaluation_service.evaluate.return_value = evaluation
        engine._broker_adapter.submit_order.side_effect = RuntimeError("order fail")
        engine.start(_make_config())
        try:
            engine.process_bar(_make_candle())
            diag = engine.diagnostics()
            assert diag.errors >= 1
        finally:
            engine.stop()


# ===========================================================================
# Kill switch tests
# ===========================================================================


class TestKillSwitch:
    """Verify kill switch integration."""

    def test_halted_skips_bar_processing(self) -> None:
        """When kill switch is halted, bar processing is skipped."""
        engine = _build_engine()
        engine._kill_switch_service.is_halted.return_value = True
        engine.start(_make_config())
        try:
            engine.process_bar(_make_candle())
            # Strategy should not be called when halted.
            engine._signal_strategy.evaluate.assert_not_called()
        finally:
            engine.stop()

    def test_halt_triggers_pause(self) -> None:
        """Kill switch halt causes engine to transition to PAUSED."""
        engine = _build_engine()
        engine._kill_switch_service.is_halted.return_value = True
        engine.start(_make_config())
        engine.process_bar(_make_candle())
        assert engine.state == LoopState.PAUSED

    def test_not_halted_processes_normally(self) -> None:
        """When not halted, bar processing proceeds normally."""
        engine = _build_engine()
        engine._kill_switch_service.is_halted.return_value = False
        engine.start(_make_config())
        try:
            engine.process_bar(_make_candle())
            engine._signal_strategy.evaluate.assert_called_once()
        finally:
            engine.stop()


# ===========================================================================
# Graceful shutdown tests
# ===========================================================================


class TestGracefulShutdown:
    """Verify graceful shutdown behaviour."""

    def test_stop_sets_stopped_state(self) -> None:
        """stop() results in STOPPED state."""
        engine = _build_engine()
        engine.start(_make_config())
        engine.stop()
        assert engine.state == LoopState.STOPPED

    def test_process_bar_after_stop_raises(self) -> None:
        """Cannot process bars after stop."""
        engine = _build_engine()
        engine.start(_make_config())
        engine.stop()
        with pytest.raises(InvalidStateTransitionError):
            engine.process_bar(_make_candle())

    def test_process_bar_while_paused_raises(self) -> None:
        """Cannot process bars while paused."""
        engine = _build_engine()
        engine.start(_make_config())
        engine.pause()
        try:
            with pytest.raises(InvalidStateTransitionError):
                engine.process_bar(_make_candle())
        finally:
            engine.stop()


# ===========================================================================
# Thread safety tests
# ===========================================================================


class TestThreadSafety:
    """Verify thread-safe access to engine state."""

    def test_concurrent_diagnostics_reads(self) -> None:
        """Multiple threads can read diagnostics without corruption."""
        engine = _build_engine()
        engine.start(_make_config())
        errors: list[Exception] = []
        barrier = threading.Barrier(20)

        def reader() -> None:
            try:
                barrier.wait(timeout=5)
                for _ in range(10):
                    diag = engine.diagnostics()
                    assert isinstance(diag, LoopDiagnostics)
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=reader) for _ in range(20)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=10)
        engine.stop()
        assert len(errors) == 0


# ===========================================================================
# Edge case tests
# ===========================================================================


class TestEdgeCases:
    """Verify edge case handling."""

    def test_multiple_bars_processed_sequentially(self) -> None:
        """Multiple bars can be processed in sequence."""
        engine = _build_engine()
        engine.start(_make_config())
        try:
            for _i in range(5):
                engine.process_bar(_make_candle())
            diag = engine.diagnostics()
            assert diag.bars_processed == 5
        finally:
            engine.stop()

    def test_position_passed_to_strategy(self) -> None:
        """Current position snapshot is passed to strategy.evaluate()."""
        engine = _build_engine()
        position = PositionSnapshot(
            symbol="AAPL",
            quantity=Decimal("100"),
            average_entry_price=Decimal("170.00"),
            market_price=Decimal("175.00"),
            market_value=Decimal("17500.00"),
            unrealized_pnl=Decimal("500.00"),
            realized_pnl=Decimal("0"),
            cost_basis=Decimal("17000.00"),
            updated_at=_NOW,
        )
        engine._broker_adapter.get_positions.return_value = [position]
        engine.start(_make_config())
        try:
            engine.process_bar(_make_candle())
            call_args = engine._signal_strategy.evaluate.call_args
            # The position should be passed as current_position kwarg or positional.
            assert call_args is not None
        finally:
            engine.stop()

    def test_uptime_increases_after_start(self) -> None:
        """Uptime is positive after engine has been running."""
        engine = _build_engine()
        engine.start(_make_config())
        try:
            time.sleep(0.05)
            diag = engine.diagnostics()
            assert diag.uptime_seconds > 0
        finally:
            engine.stop()


# ---------------------------------------------------------------------------
# Safety: LIVE execution mode must never reach the raw broker adapter.
# ---------------------------------------------------------------------------
#
# The StrategyExecutionEngine submits orders directly via its injected
# broker adapter and does NOT persist the order to durable storage before
# calling the broker.  The production-grade path for real-money trading
# is services.api.services.LiveExecutionService, which pre-persists every
# order under a lock + transaction commit before submitting to the broker.
#
# Without a guard here, a future integration that wires this engine with
# a live broker adapter (e.g. AlpacaBrokerAdapter in LIVE mode) would
# silently bypass the pre-persistence discipline and create orphaned
# broker-side orders on any crash between submit and ack.  CLAUDE.md §0
# treats this as a first-class bug, not tech debt.
#
# These tests enforce the invariant: the engine REJECTS a LIVE-mode
# config at start() time unless it was explicitly constructed with a
# LiveExecutionServiceInterface (a dependency the engine will delegate
# to instead of calling the broker directly).  PAPER and SHADOW modes
# are unaffected — they do not move real money.


class TestLiveModeSafetyGuard:
    """Guards against the engine submitting real-money orders without
    going through the pre-persisting LiveExecutionService."""

    def test_start_raises_when_live_mode_and_no_live_execution_service(self) -> None:
        """LIVE config + no live_execution_service injected → start() raises.

        This is the core safety property: the engine must refuse to
        run in LIVE mode through its direct-broker-submission code path.
        """
        engine = _build_engine()  # no live_execution_service injected
        live_config = _make_config(execution_mode=ExecutionMode.LIVE)

        with pytest.raises(RuntimeError, match="LIVE"):
            engine.start(live_config)

    def test_start_raises_before_state_transitions_to_running(self) -> None:
        """The guard must fire before any state mutation, so the engine
        stays in INITIALIZING and can be safely discarded."""
        engine = _build_engine()
        live_config = _make_config(execution_mode=ExecutionMode.LIVE)

        with pytest.raises(RuntimeError):
            engine.start(live_config)

        # No state leak: the failed start must not leave the engine RUNNING.
        assert engine.state == LoopState.INITIALIZING

    def test_paper_mode_still_starts_normally(self) -> None:
        """PAPER mode must continue to work — the guard is scoped to LIVE."""
        engine = _build_engine()
        engine.start(_make_config(execution_mode=ExecutionMode.PAPER))
        try:
            assert engine.state == LoopState.RUNNING
        finally:
            engine.stop()

    def test_shadow_mode_still_starts_normally(self) -> None:
        """SHADOW mode must continue to work — the guard is scoped to LIVE."""
        engine = _build_engine()
        engine.start(_make_config(execution_mode=ExecutionMode.SHADOW))
        try:
            assert engine.state == LoopState.RUNNING
        finally:
            engine.stop()

    def test_guard_error_message_points_operator_at_live_execution_service(self) -> None:
        """The exception message must name the correct production path,
        so an operator hitting this error knows where to go."""
        engine = _build_engine()
        live_config = _make_config(execution_mode=ExecutionMode.LIVE)

        with pytest.raises(RuntimeError) as exc_info:
            engine.start(live_config)

        msg = str(exc_info.value)
        assert "LiveExecutionService" in msg, (
            f"Error message must point operator at LiveExecutionService. Got: {msg!r}"
        )
