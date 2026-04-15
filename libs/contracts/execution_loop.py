"""
Execution loop contracts — lifecycle, state machine, and configuration.

Responsibilities:
- Define the LoopState enum governing execution loop lifecycle.
- Define ExecutionLoopConfig for configuring loop behaviour per deployment.
- Define LoopDiagnostics for real-time monitoring of loop health and counters.
- Define valid state transitions and provide a transition-validation helper.

Does NOT:
- Implement execution logic (StrategyExecutionEngine responsibility).
- Start or stop loops (ExecutionLoopInterface responsibility).
- Persist loop state (repository layer responsibility).

Dependencies:
- libs.contracts.execution: ExecutionMode
- libs.contracts.market_data: CandleInterval

Error conditions:
- InvalidStateTransitionError: if a disallowed state transition is attempted.
- ValidationError (Pydantic): if config fields violate constraints.

Example:
    config = ExecutionLoopConfig(
        deployment_id="deploy-001",
        strategy_id="ma-crossover-aapl",
        signal_strategy_id="ma-crossover",
        symbols=["AAPL"],
        interval=CandleInterval.M5,
        execution_mode=ExecutionMode.PAPER,
    )
    diag = LoopDiagnostics(
        state=LoopState.RUNNING,
        deployment_id="deploy-001",
    )
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum

from pydantic import BaseModel, Field, field_validator

from libs.contracts.execution import ExecutionMode
from libs.contracts.market_data import CandleInterval

# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------


class InvalidStateTransitionError(Exception):
    """
    Raised when an execution loop attempts a disallowed state transition.

    Attributes:
        from_state: The current state.
        to_state: The requested target state.

    Example:
        raise InvalidStateTransitionError(
            from_state=LoopState.STOPPED,
            to_state=LoopState.RUNNING,
        )
    """

    def __init__(self, *, from_state: LoopState, to_state: LoopState) -> None:
        self.from_state = from_state
        self.to_state = to_state
        super().__init__(f"Invalid state transition: {from_state.value} → {to_state.value}")


# ---------------------------------------------------------------------------
# LoopState enum
# ---------------------------------------------------------------------------


class LoopState(str, Enum):  # noqa: UP042 — Python 3.10 compatibility (no StrEnum)
    """
    Execution loop lifecycle states.

    State machine governs how a strategy execution loop transitions between
    lifecycle phases.  Every transition must pass through validate_transition()
    before being applied.

    States:
    - INITIALIZING: Loop is starting up (loading config, warming indicators).
    - RUNNING: Actively processing bars and generating signals.
    - PAUSED: Temporarily halted (manual pause or kill switch triggered).
    - COOLDOWN: Post-error cooldown period before automatic retry.
    - STOPPED: Graceful shutdown completed.
    - FAILED: Unrecoverable error — circuit breaker tripped.

    Valid transitions (see VALID_TRANSITIONS constant):
        INITIALIZING → RUNNING, FAILED, STOPPED
        RUNNING      → PAUSED, COOLDOWN, STOPPED, FAILED
        PAUSED       → RUNNING, STOPPED
        COOLDOWN     → RUNNING, FAILED, STOPPED
        STOPPED      → (terminal)
        FAILED       → (terminal)

    Example:
        state = LoopState.INITIALIZING
        validate_transition(state, LoopState.RUNNING)  # OK
        validate_transition(state, LoopState.PAUSED)   # raises
    """

    INITIALIZING = "initializing"
    RUNNING = "running"
    PAUSED = "paused"
    COOLDOWN = "cooldown"
    STOPPED = "stopped"
    FAILED = "failed"


# ---------------------------------------------------------------------------
# Valid state transitions
# ---------------------------------------------------------------------------

VALID_TRANSITIONS: dict[LoopState, frozenset[LoopState]] = {
    LoopState.INITIALIZING: frozenset(
        {
            LoopState.RUNNING,
            LoopState.FAILED,
            LoopState.STOPPED,
        }
    ),
    LoopState.RUNNING: frozenset(
        {
            LoopState.PAUSED,
            LoopState.COOLDOWN,
            LoopState.STOPPED,
            LoopState.FAILED,
        }
    ),
    LoopState.PAUSED: frozenset(
        {
            LoopState.RUNNING,
            LoopState.STOPPED,
        }
    ),
    LoopState.COOLDOWN: frozenset(
        {
            LoopState.RUNNING,
            LoopState.FAILED,
            LoopState.STOPPED,
        }
    ),
    # Terminal states — no outgoing transitions.
    LoopState.STOPPED: frozenset(),
    LoopState.FAILED: frozenset(),
}


def validate_transition(from_state: LoopState, to_state: LoopState) -> None:
    """
    Validate that a state transition is allowed.

    Checks the transition against the VALID_TRANSITIONS map and raises
    InvalidStateTransitionError if the transition is disallowed.

    Args:
        from_state: Current loop state.
        to_state: Desired target state.

    Raises:
        InvalidStateTransitionError: If the transition is not in VALID_TRANSITIONS.

    Example:
        validate_transition(LoopState.RUNNING, LoopState.PAUSED)   # OK
        validate_transition(LoopState.STOPPED, LoopState.RUNNING)  # raises
    """
    allowed = VALID_TRANSITIONS.get(from_state, frozenset())
    if to_state not in allowed:
        raise InvalidStateTransitionError(from_state=from_state, to_state=to_state)


def is_terminal(state: LoopState) -> bool:
    """
    Check whether a loop state is terminal (no further transitions allowed).

    Args:
        state: The loop state to check.

    Returns:
        True if the state is terminal (STOPPED or FAILED), False otherwise.

    Example:
        is_terminal(LoopState.STOPPED)  # True
        is_terminal(LoopState.RUNNING)  # False
    """
    return len(VALID_TRANSITIONS.get(state, frozenset())) == 0


# ---------------------------------------------------------------------------
# ExecutionLoopConfig
# ---------------------------------------------------------------------------


class ExecutionLoopConfig(BaseModel):
    """
    Configuration for a strategy execution loop.

    Immutable configuration that defines how a loop behaves: which strategy
    to run, against which symbols, on what interval, and operational limits.

    Responsibilities:
    - Carry all parameters needed to initialise an execution loop.
    - Validate parameter constraints at construction time.

    Does NOT:
    - Start or manage the loop (ExecutionLoopInterface does that).
    - Persist itself (infrastructure/repository layer responsibility).

    Attributes:
        deployment_id: Unique deployment identifier.
        strategy_id: Human-readable strategy name for this deployment.
        signal_strategy_id: Registry key for the SignalStrategy implementation.
        symbols: List of ticker symbols the loop will process.
        interval: Candle interval for bar polling / streaming.
        execution_mode: Shadow, paper, or live trading mode.
        max_positions_per_symbol: Maximum concurrent positions per symbol.
        cooldown_after_trade_s: Seconds to wait after a trade before next signal.
        max_consecutive_errors: Error count that trips the circuit breaker.
        health_check_interval_s: Seconds between health check cycles.

    Example:
        config = ExecutionLoopConfig(
            deployment_id="deploy-001",
            strategy_id="ma-crossover-aapl",
            signal_strategy_id="ma-crossover",
            symbols=["AAPL", "MSFT"],
            interval=CandleInterval.M5,
            execution_mode=ExecutionMode.PAPER,
        )
    """

    model_config = {"frozen": True}

    deployment_id: str = Field(
        ...,
        min_length=1,
        max_length=128,
        description="Unique deployment identifier.",
    )
    strategy_id: str = Field(
        ...,
        min_length=1,
        max_length=128,
        description="Human-readable strategy name for this deployment.",
    )
    signal_strategy_id: str = Field(
        ...,
        min_length=1,
        max_length=128,
        description="Registry key for the SignalStrategy implementation.",
    )
    symbols: list[str] = Field(
        ...,
        min_length=1,
        description="Ticker symbols the loop will process (at least one required).",
    )
    interval: CandleInterval = Field(
        ...,
        description="Candle interval for bar polling / streaming.",
    )
    execution_mode: ExecutionMode = Field(
        ...,
        description="Shadow, paper, or live trading mode.",
    )
    max_positions_per_symbol: int = Field(
        default=1,
        ge=1,
        le=100,
        description="Maximum concurrent positions per symbol.",
    )
    cooldown_after_trade_s: int = Field(
        default=60,
        ge=0,
        le=86400,
        description="Seconds to wait after a trade before next signal.",
    )
    max_consecutive_errors: int = Field(
        default=5,
        ge=1,
        le=100,
        description="Error count that trips the circuit breaker to FAILED state.",
    )
    health_check_interval_s: int = Field(
        default=30,
        ge=5,
        le=3600,
        description="Seconds between health check cycles.",
    )

    @field_validator("symbols")
    @classmethod
    def _normalize_symbols(cls, v: list[str]) -> list[str]:
        """Normalize symbols to uppercase and validate non-empty entries."""
        normalized = []
        for sym in v:
            stripped = sym.strip().upper()
            if not stripped:
                raise ValueError("Symbol must not be empty or whitespace-only")
            normalized.append(stripped)
        # Deduplicate while preserving order.
        seen: set[str] = set()
        deduped: list[str] = []
        for sym in normalized:
            if sym not in seen:
                seen.add(sym)
                deduped.append(sym)
        return deduped


# ---------------------------------------------------------------------------
# LoopDiagnostics
# ---------------------------------------------------------------------------


class LoopDiagnostics(BaseModel):
    """
    Runtime diagnostics snapshot for an execution loop.

    Provides real-time counters and timestamps that describe loop health
    and throughput.  Designed as an atomic read — callers should snapshot
    the entire object under a lock.

    Responsibilities:
    - Carry a complete point-in-time view of loop metrics.
    - Support serialisation for API responses and WebSocket events.

    Does NOT:
    - Update itself (the execution engine updates the underlying counters).
    - Persist to database (monitoring / API layer may choose to persist).

    Attributes:
        state: Current lifecycle state.
        deployment_id: Which deployment this loop belongs to.
        bars_processed: Total bars ingested since loop start.
        signals_generated: Raw signals produced by the strategy.
        signals_approved: Signals that passed all risk gates.
        signals_rejected: Signals rejected by the evaluation pipeline.
        orders_submitted: Orders sent to the broker.
        orders_filled: Orders confirmed filled.
        errors: Total error count since loop start.
        last_bar_at: Timestamp of the most recent bar processed.
        last_signal_at: Timestamp of the most recent signal generated.
        last_order_at: Timestamp of the most recent order submitted.
        uptime_seconds: Wall-clock seconds since loop entered RUNNING.
        consecutive_errors: Current streak of consecutive errors.

    Example:
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
            uptime_seconds=7200.5,
        )
    """

    model_config = {"frozen": True}

    state: LoopState = Field(
        ...,
        description="Current lifecycle state.",
    )
    deployment_id: str = Field(
        ...,
        min_length=1,
        description="Which deployment this loop belongs to.",
    )
    bars_processed: int = Field(
        default=0,
        ge=0,
        description="Total bars ingested since loop start.",
    )
    signals_generated: int = Field(
        default=0,
        ge=0,
        description="Raw signals produced by the strategy.",
    )
    signals_approved: int = Field(
        default=0,
        ge=0,
        description="Signals that passed all risk gates.",
    )
    signals_rejected: int = Field(
        default=0,
        ge=0,
        description="Signals rejected by the evaluation pipeline.",
    )
    orders_submitted: int = Field(
        default=0,
        ge=0,
        description="Orders sent to the broker.",
    )
    orders_filled: int = Field(
        default=0,
        ge=0,
        description="Orders confirmed filled.",
    )
    errors: int = Field(
        default=0,
        ge=0,
        description="Total error count since loop start.",
    )
    last_bar_at: datetime | None = Field(
        default=None,
        description="Timestamp of the most recent bar processed.",
    )
    last_signal_at: datetime | None = Field(
        default=None,
        description="Timestamp of the most recent signal generated.",
    )
    last_order_at: datetime | None = Field(
        default=None,
        description="Timestamp of the most recent order submitted.",
    )
    uptime_seconds: float = Field(
        default=0.0,
        ge=0.0,
        description="Wall-clock seconds since loop entered RUNNING.",
    )
    consecutive_errors: int = Field(
        default=0,
        ge=0,
        description="Current streak of consecutive errors (resets on success).",
    )
