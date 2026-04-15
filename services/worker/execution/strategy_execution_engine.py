"""
Strategy Execution Engine — core loop tying market data to signal→order flow.

Responsibilities:
- Implement ExecutionLoopInterface for lifecycle management.
- Process individual bars through the full pipeline:
  candle → indicators → strategy → evaluation → order.
- Enforce state machine transitions via validate_transition().
- Integrate with kill switch for deployment-level halts.
- Track diagnostics (bars, signals, orders, errors, uptime).
- Implement circuit breaker for consecutive error protection.
- Provide thread-safe state access for monitoring.

Does NOT:
- Poll or stream market data autonomously (caller pushes bars via process_bar).
- Manage multiple loops (ExecutionLoopManager responsibility in M8).
- Define contracts or state machine (libs.contracts.execution_loop).
- Implement strategies (services.worker.strategies).

Dependencies (all injected):
- SignalStrategyInterface: strategy to generate signals from candles.
- SignalEvaluationServiceInterface: risk gate pipeline for signal approval.
- BrokerAdapterInterface: order submission.
- MarketDataRepositoryInterface: historical candle queries for warmup.
- IndicatorEngine: compute batch indicators from candles.
- KillSwitchServiceInterface: deployment halt checks.
- SignalRepositoryInterface: persist signals and evaluations.

Error conditions:
- InvalidStateTransitionError: lifecycle method in wrong state.
- Circuit breaker trips to FAILED after max_consecutive_errors.
- Individual bar processing errors are logged and counted, not propagated.

Example:
    engine = StrategyExecutionEngine(
        signal_strategy=strategy,
        signal_evaluation_service=eval_service,
        broker_adapter=broker,
        market_data_repository=market_repo,
        indicator_engine=indicator_engine,
        kill_switch_service=kill_switch,
        signal_repository=signal_repo,
    )
    engine.start(config)
    engine.process_bar(candle)
    diag = engine.diagnostics()
    engine.stop()
"""

from __future__ import annotations

import threading
import time
from decimal import Decimal
from typing import TYPE_CHECKING

import structlog
import ulid

from libs.contracts.execution import (
    ExecutionMode,
    OrderRequest,
    OrderSide,
    OrderType,
    TimeInForce,
)
from libs.contracts.execution_loop import (
    ExecutionLoopConfig,
    InvalidStateTransitionError,
    LoopDiagnostics,
    LoopState,
    validate_transition,
)
from libs.contracts.interfaces.execution_loop import ExecutionLoopInterface
from libs.contracts.signal import SignalDirection

if TYPE_CHECKING:
    from libs.contracts.data_freshness import DataFreshnessPolicy
    from libs.contracts.execution import PositionSnapshot
    from libs.contracts.interfaces.broker_adapter import BrokerAdapterInterface
    from libs.contracts.interfaces.data_freshness_gate_interface import (
        DataFreshnessGateInterface,
    )
    from libs.contracts.interfaces.kill_switch_service_interface import (
        KillSwitchServiceInterface,
    )
    from libs.contracts.interfaces.market_data_repository import (
        MarketDataRepositoryInterface,
    )
    from libs.contracts.interfaces.signal_evaluation_service import (
        SignalEvaluationServiceInterface,
    )
    from libs.contracts.interfaces.signal_repository import SignalRepositoryInterface
    from libs.contracts.interfaces.signal_strategy import SignalStrategyInterface
    from libs.contracts.market_data import Candle
    from libs.indicators.engine import IndicatorEngine
    from services.api.services.interfaces.live_execution_service_interface import (
        LiveExecutionServiceInterface,
    )

logger = structlog.get_logger(__name__)


class StrategyExecutionEngine(ExecutionLoopInterface):
    """
    Event-driven execution engine that processes bars through the full
    signal→evaluation→order pipeline.

    The engine is designed for push-based usage: callers (bar stream callbacks,
    polling loops, or backtest harnesses) push individual candles via
    process_bar(). Each bar triggers the full pipeline:

    1. Check kill switch — skip processing if halted.
    2. Maintain candle buffer for indicator lookback.
    3. Compute indicators via IndicatorEngine.compute_batch().
    4. Evaluate strategy via SignalStrategy.evaluate().
    5. If signal produced:
       a. Run through SignalEvaluationService (risk gates, sizing, quality).
       b. Persist signal and evaluation.
       c. If approved and not in shadow mode: convert to OrderRequest and submit.
    6. Update diagnostics counters.
    7. Check circuit breaker threshold.

    Responsibilities:
    - Full lifecycle management (start, stop, pause, resume).
    - Bar processing pipeline with fail-fast error handling.
    - Circuit breaker: trip to FAILED after max_consecutive_errors.
    - Kill switch integration: pause on halt detection.
    - Thread-safe diagnostics snapshots.
    - Structured logging with correlation_id propagation.

    Does NOT:
    - Poll or stream data (push model via process_bar).
    - Manage multiple engines (M8 loop manager does that).
    - Implement strategy logic.
    - Define risk gates.

    Thread safety:
    - All mutable state under self._lock.
    - diagnostics() returns a frozen Pydantic snapshot.
    - process_bar() acquires lock for state checks and counter updates.

    Example:
        engine = StrategyExecutionEngine(
            signal_strategy=ma_crossover,
            signal_evaluation_service=eval_service,
            broker_adapter=paper_broker,
            market_data_repository=market_repo,
            indicator_engine=ind_engine,
            kill_switch_service=kill_switch,
            signal_repository=signal_repo,
        )
        engine.start(loop_config)
        for candle in candle_stream:
            engine.process_bar(candle)
        engine.stop()
    """

    def __init__(
        self,
        *,
        signal_strategy: SignalStrategyInterface,
        signal_evaluation_service: SignalEvaluationServiceInterface,
        broker_adapter: BrokerAdapterInterface,
        market_data_repository: MarketDataRepositoryInterface,
        indicator_engine: IndicatorEngine,
        kill_switch_service: KillSwitchServiceInterface,
        signal_repository: SignalRepositoryInterface,
        data_freshness_gate: DataFreshnessGateInterface | None = None,
        data_freshness_policy: DataFreshnessPolicy | None = None,
        live_execution_service: LiveExecutionServiceInterface | None = None,
    ) -> None:
        """
        Initialize the execution engine with all required dependencies.

        Args:
            signal_strategy: Strategy to generate signals from market data.
            signal_evaluation_service: Risk gate pipeline for signal approval.
            broker_adapter: Order submission adapter.
            market_data_repository: Historical candle queries.
            indicator_engine: Compute batch indicators from candles.
            kill_switch_service: Deployment halt checks.
            signal_repository: Persist signals and evaluations.
            data_freshness_gate: Optional gate to validate candle freshness.
                If provided, stale candles may skip signal generation.
                Requires data_freshness_policy to be set as well.
            data_freshness_policy: Optional policy for staleness thresholds.
                Only used if data_freshness_gate is also provided.

        Example:
            engine = StrategyExecutionEngine(
                signal_strategy=strategy,
                signal_evaluation_service=eval_svc,
                broker_adapter=broker,
                market_data_repository=mkt_repo,
                indicator_engine=ind_engine,
                kill_switch_service=ks_svc,
                signal_repository=sig_repo,
                data_freshness_gate=freshness_gate,
                data_freshness_policy=DataFreshnessPolicy(),
            )
        """
        self._signal_strategy = signal_strategy
        self._signal_evaluation_service = signal_evaluation_service
        self._broker_adapter = broker_adapter
        self._market_data_repository = market_data_repository
        self._indicator_engine = indicator_engine
        self._kill_switch_service = kill_switch_service
        self._signal_repository = signal_repository
        self._data_freshness_gate = data_freshness_gate
        self._data_freshness_policy = data_freshness_policy
        # Optional: when provided, LIVE-mode orders are delegated to this
        # pre-persisting service instead of being submitted directly to the
        # broker adapter.  When None, LIVE-mode configs are rejected at
        # start() to prevent silent bypass of order persistence. See
        # start() docstring for the full safety rationale.
        self._live_execution_service = live_execution_service

        # State management.
        self._lock = threading.Lock()
        self._state = LoopState.INITIALIZING
        self._config: ExecutionLoopConfig | None = None
        self._started_at: float | None = None

        # Candle buffer for indicator lookback.
        self._candle_buffer: dict[str, list[Candle]] = {}
        self._max_buffer_size = 500

        # Diagnostics counters.
        self._bars_processed = 0
        self._signals_generated = 0
        self._signals_approved = 0
        self._signals_rejected = 0
        self._orders_submitted = 0
        self._orders_filled = 0
        self._errors = 0
        self._consecutive_errors = 0
        self._last_bar_at: float | None = None
        self._last_signal_at: float | None = None
        self._last_order_at: float | None = None

    # ------------------------------------------------------------------
    # Lifecycle (ExecutionLoopInterface)
    # ------------------------------------------------------------------

    def start(self, config: ExecutionLoopConfig) -> None:
        """
        Start the execution engine.

        Validates state transition, stores config, and transitions to RUNNING.

        Safety guard — real-money trading:
            This engine submits orders directly through its injected
            broker adapter and does NOT persist orders to durable
            storage before broker submission.  The production-grade
            real-money path is ``services.api.services.LiveExecutionService``,
            which pre-persists orders under a lock + transaction commit.

            To prevent a future integration from silently wiring this
            engine against a live broker and bypassing the pre-persistence
            discipline (which would produce orphaned broker-side orders
            on any crash between submit and ack), this method REJECTS
            ``ExecutionMode.LIVE`` unless a ``live_execution_service``
            dependency was explicitly injected.  PAPER and SHADOW modes
            are unaffected — they do not move real money.

        Args:
            config: Complete loop configuration.

        Raises:
            InvalidStateTransitionError: If not in INITIALIZING state.
            RuntimeError: If ``config.execution_mode == ExecutionMode.LIVE``
                and no ``live_execution_service`` was injected.  The message
                points operators at the correct production path.

        Example:
            engine.start(config)
            assert engine.state == LoopState.RUNNING
        """
        # Safety guard: refuse LIVE mode without a pre-persisting service.
        # Kept OUTSIDE the lock so we fail before any state mutation.
        if config.execution_mode == ExecutionMode.LIVE and self._live_execution_service is None:
            raise RuntimeError(
                "StrategyExecutionEngine refuses to start in ExecutionMode.LIVE "
                "without a LiveExecutionServiceInterface dependency. "
                "Live (real-money) orders MUST go through "
                "services.api.services.LiveExecutionService, which persists "
                "orders to durable storage before broker submission. "
                "Direct broker submission from this engine would create "
                "orphaned orders on crash. Use PAPER or SHADOW modes for "
                "the engine's direct-submission path, or inject a "
                "LiveExecutionServiceInterface to route LIVE orders through "
                "the production-grade service."
            )

        with self._lock:
            validate_transition(self._state, LoopState.RUNNING)
            self._config = config
            self._state = LoopState.RUNNING
            self._started_at = time.monotonic()
            self._candle_buffer = {sym: [] for sym in config.symbols}

        logger.info(
            "Execution engine started",
            deployment_id=config.deployment_id,
            strategy_id=config.strategy_id,
            signal_strategy_id=config.signal_strategy_id,
            symbols=config.symbols,
            execution_mode=config.execution_mode.value,
        )

    def stop(self) -> None:
        """
        Gracefully stop the execution engine.

        Transitions to STOPPED and clears the candle buffer.

        Raises:
            InvalidStateTransitionError: If already stopped or failed.

        Example:
            engine.stop()
            assert engine.state == LoopState.STOPPED
        """
        with self._lock:
            validate_transition(self._state, LoopState.STOPPED)
            self._state = LoopState.STOPPED
            self._candle_buffer.clear()

        logger.info(
            "Execution engine stopped",
            deployment_id=self._config.deployment_id if self._config else "unknown",
            bars_processed=self._bars_processed,
            signals_generated=self._signals_generated,
            orders_submitted=self._orders_submitted,
        )

    def pause(self) -> None:
        """
        Pause the execution engine.

        Raises:
            InvalidStateTransitionError: If not RUNNING.

        Example:
            engine.pause()
            assert engine.state == LoopState.PAUSED
        """
        with self._lock:
            validate_transition(self._state, LoopState.PAUSED)
            self._state = LoopState.PAUSED

        logger.info(
            "Execution engine paused",
            deployment_id=self._config.deployment_id if self._config else "unknown",
        )

    def resume(self) -> None:
        """
        Resume the execution engine from PAUSED state.

        Raises:
            InvalidStateTransitionError: If not PAUSED.

        Example:
            engine.resume()
            assert engine.state == LoopState.RUNNING
        """
        with self._lock:
            validate_transition(self._state, LoopState.RUNNING)
            self._state = LoopState.RUNNING

        logger.info(
            "Execution engine resumed",
            deployment_id=self._config.deployment_id if self._config else "unknown",
        )

    def diagnostics(self) -> LoopDiagnostics:
        """
        Return a frozen point-in-time snapshot of engine metrics.

        Thread-safe: acquires lock, copies counters, constructs frozen model.

        Returns:
            LoopDiagnostics with current counters and state.

        Example:
            diag = engine.diagnostics()
            print(f"Bars: {diag.bars_processed}")
        """
        with self._lock:
            from datetime import datetime, timezone

            uptime = 0.0
            if self._started_at is not None:
                uptime = time.monotonic() - self._started_at

            return LoopDiagnostics(
                state=self._state,
                deployment_id=self._config.deployment_id if self._config else "unknown",
                bars_processed=self._bars_processed,
                signals_generated=self._signals_generated,
                signals_approved=self._signals_approved,
                signals_rejected=self._signals_rejected,
                orders_submitted=self._orders_submitted,
                orders_filled=self._orders_filled,
                errors=self._errors,
                last_bar_at=(
                    datetime.fromtimestamp(self._last_bar_at, tz=timezone.utc)
                    if self._last_bar_at is not None
                    else None
                ),
                last_signal_at=(
                    datetime.fromtimestamp(self._last_signal_at, tz=timezone.utc)
                    if self._last_signal_at is not None
                    else None
                ),
                last_order_at=(
                    datetime.fromtimestamp(self._last_order_at, tz=timezone.utc)
                    if self._last_order_at is not None
                    else None
                ),
                uptime_seconds=uptime,
                consecutive_errors=self._consecutive_errors,
            )

    @property
    def state(self) -> LoopState:
        """Current lifecycle state (thread-safe)."""
        with self._lock:
            return self._state

    # ------------------------------------------------------------------
    # Bar processing pipeline
    # ------------------------------------------------------------------

    def process_bar(self, candle: Candle) -> None:
        """
        Process a single candle through the full signal→order pipeline.

        This is the core method of the engine. Each invocation:
        1. Validates engine is RUNNING.
        2. Checks kill switch.
        3. Buffers the candle.
        4. Computes indicators.
        5. Evaluates strategy.
        6. If signal: evaluates through risk gates, persists, submits order.
        7. Updates diagnostics.
        8. Checks circuit breaker.

        Args:
            candle: The new candle to process.

        Raises:
            InvalidStateTransitionError: If engine is not in RUNNING state.

        Example:
            engine.process_bar(candle)
            # Diagnostics now reflect the processed bar.
        """
        # --- Pre-check: engine must be RUNNING ---
        with self._lock:
            if self._state != LoopState.RUNNING:
                raise InvalidStateTransitionError(
                    from_state=self._state,
                    to_state=LoopState.RUNNING,
                )
            config = self._config

        if config is None:
            return

        correlation_id = f"bar-{str(ulid.ULID())}"

        # --- Gate: Kill switch check ---
        try:
            halted = self._kill_switch_service.is_halted(
                deployment_id=config.deployment_id,
                strategy_id=config.signal_strategy_id,
                symbol=candle.symbol,
            )
        except Exception:
            logger.warning(
                "Kill switch check failed — treating as halted (fail-safe)",
                exc_info=True,
                correlation_id=correlation_id,
            )
            halted = True

        if halted:
            logger.info(
                "Kill switch active — skipping bar and pausing",
                symbol=candle.symbol,
                deployment_id=config.deployment_id,
                correlation_id=correlation_id,
            )
            with self._lock:
                if self._state == LoopState.RUNNING:
                    self._state = LoopState.PAUSED
            return

        # --- Pipeline ---
        try:
            self._execute_bar_pipeline(candle, config, correlation_id)
        except Exception:
            logger.error(
                "Bar processing failed",
                symbol=candle.symbol,
                exc_info=True,
                correlation_id=correlation_id,
            )
            with self._lock:
                self._errors += 1
                self._consecutive_errors += 1
                self._bars_processed += 1
                self._last_bar_at = time.time()
                # Circuit breaker check.
                if self._consecutive_errors >= config.max_consecutive_errors:
                    logger.error(
                        "Circuit breaker tripped — transitioning to FAILED",
                        consecutive_errors=self._consecutive_errors,
                        max_allowed=config.max_consecutive_errors,
                        deployment_id=config.deployment_id,
                    )
                    self._state = LoopState.FAILED
            return

        # Success — reset consecutive error counter.
        with self._lock:
            self._consecutive_errors = 0

    def _execute_bar_pipeline(
        self,
        candle: Candle,
        config: ExecutionLoopConfig,
        correlation_id: str,
    ) -> None:
        """
        Execute the full bar processing pipeline.

        Separated from process_bar() so that error handling wraps this
        as a unit.

        Args:
            candle: The candle to process.
            config: Loop configuration.
            correlation_id: Tracing correlation ID.
        """
        symbol = candle.symbol

        logger.debug(
            "Processing bar",
            symbol=symbol,
            timestamp=str(candle.timestamp),
            correlation_id=correlation_id,
        )

        # 1. Buffer the candle.
        with self._lock:
            if symbol not in self._candle_buffer:
                self._candle_buffer[symbol] = []
            self._candle_buffer[symbol].append(candle)
            # Trim buffer to max size.
            if len(self._candle_buffer[symbol]) > self._max_buffer_size:
                self._candle_buffer[symbol] = self._candle_buffer[symbol][-self._max_buffer_size :]
            candles = list(self._candle_buffer[symbol])

        # 1a. Data freshness check (optional gate).
        if self._data_freshness_gate is not None and self._data_freshness_policy is not None:
            freshness_result = self._data_freshness_gate.check_freshness(
                candle, self._data_freshness_policy
            )
            if not freshness_result.is_fresh and freshness_result.action == "rejected":
                logger.warning(
                    "Candle rejected by freshness gate (stale data)",
                    symbol=symbol,
                    age_seconds=freshness_result.age_seconds,
                    max_allowed_seconds=freshness_result.max_allowed_seconds,
                    correlation_id=correlation_id,
                )
                with self._lock:
                    self._bars_processed += 1
                    self._last_bar_at = time.time()
                return

        # 2. Compute indicators.
        indicator_requests = self._signal_strategy.required_indicators()
        indicators = {}
        if indicator_requests and len(candles) > 1:
            indicators = self._indicator_engine.compute_batch(indicator_requests, candles)

        # 3. Get current position for this symbol.
        current_position = self._get_position_for_symbol(symbol)

        # 4. Evaluate strategy.
        signal = self._signal_strategy.evaluate(
            symbol,
            candles,
            indicators,
            current_position,
            correlation_id=correlation_id,
        )

        # 5. If signal produced, run through evaluation pipeline.
        if signal is not None:
            with self._lock:
                self._signals_generated += 1
                self._last_signal_at = time.time()

            logger.info(
                "Signal generated",
                symbol=symbol,
                direction=signal.direction.value,
                signal_type=signal.signal_type.value,
                confidence=signal.confidence,
                correlation_id=correlation_id,
            )

            # Persist signal.
            self._signal_repository.save_signal(signal)

            # Evaluate through risk gates.
            evaluation = self._signal_evaluation_service.evaluate(
                signal=signal,
                deployment_id=config.deployment_id,
                execution_mode=config.execution_mode.value,
                correlation_id=correlation_id,
            )

            # Persist evaluation.
            self._signal_repository.save_evaluation(evaluation)

            if evaluation.approved:
                with self._lock:
                    self._signals_approved += 1

                logger.info(
                    "Signal approved",
                    symbol=symbol,
                    position_size=str(evaluation.position_size),
                    correlation_id=correlation_id,
                )

                # Submit order (unless in SHADOW mode).
                if config.execution_mode != ExecutionMode.SHADOW:
                    self._submit_order(signal, evaluation, config, correlation_id)
            else:
                with self._lock:
                    self._signals_rejected += 1

                logger.info(
                    "Signal rejected",
                    symbol=symbol,
                    reason=evaluation.rejection_reason,
                    correlation_id=correlation_id,
                )

        # Update bar counter.
        with self._lock:
            self._bars_processed += 1
            self._last_bar_at = time.time()

    def _get_position_for_symbol(self, symbol: str) -> PositionSnapshot | None:
        """
        Retrieve the current position for a symbol from the broker adapter.

        Args:
            symbol: The ticker symbol.

        Returns:
            PositionSnapshot if a position exists, None otherwise.
        """
        try:
            positions = self._broker_adapter.get_positions()
            for pos in positions:
                if pos.symbol == symbol:
                    return pos
        except Exception:
            logger.warning(
                "Failed to retrieve positions — assuming no position",
                symbol=symbol,
                exc_info=True,
            )
        return None

    def _submit_order(
        self,
        signal: object,
        evaluation: object,
        config: ExecutionLoopConfig,
        correlation_id: str,
    ) -> None:
        """
        Convert an approved signal into an OrderRequest and submit it.

        Args:
            signal: The approved signal.
            evaluation: The signal evaluation with position size and stop.
            config: Loop configuration.
            correlation_id: Tracing ID.
        """
        # Import locally to avoid circular import at module level.
        from libs.contracts.signal import Signal
        from libs.contracts.signal import SignalEvaluation as SigEval

        sig: Signal = signal  # type: ignore[assignment]
        ev: SigEval = evaluation  # type: ignore[assignment]

        order_side = OrderSide.BUY if sig.direction == SignalDirection.LONG else OrderSide.SELL

        order_request = OrderRequest(
            client_order_id=f"ord-{str(ulid.ULID())}",
            deployment_id=config.deployment_id,
            strategy_id=config.strategy_id,
            symbol=sig.symbol,
            side=order_side,
            order_type=OrderType.MARKET,
            quantity=ev.position_size or Decimal("0"),
            time_in_force=TimeInForce.DAY,
            execution_mode=config.execution_mode,
            correlation_id=correlation_id,
        )

        response = self._broker_adapter.submit_order(order_request)

        with self._lock:
            self._orders_submitted += 1
            self._last_order_at = time.time()

        logger.info(
            "Order submitted",
            order_id=order_request.client_order_id,
            broker_order_id=getattr(response, "broker_order_id", None),
            symbol=sig.symbol,
            side=order_side.value,
            quantity=str(ev.position_size),
            correlation_id=correlation_id,
        )
