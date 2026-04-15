"""
Execution loop interface (port).

Responsibilities:
- Define the abstract contract for execution loop lifecycle management.
- Provide start, stop, pause, resume, and diagnostics methods.
- Expose current state as a read-only property.

Does NOT:
- Implement the execution engine (concrete service responsibility).
- Manage multiple loops (loop manager / infrastructure responsibility).
- Persist loop state (repository layer responsibility).

Dependencies:
- libs.contracts.execution_loop: ExecutionLoopConfig, LoopDiagnostics, LoopState

Error conditions:
- InvalidStateTransitionError: if a lifecycle method is called in the wrong state.

Example:
    loop: ExecutionLoopInterface = StrategyExecutionEngine(...)
    loop.start(config)
    diag = loop.diagnostics()
    loop.pause()
    loop.resume()
    loop.stop()
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from libs.contracts.execution_loop import (
    ExecutionLoopConfig,
    LoopDiagnostics,
    LoopState,
)


class ExecutionLoopInterface(ABC):
    """
    Port interface for strategy execution loop lifecycle management.

    Defines the contract that any execution loop implementation must satisfy.
    The loop processes market data bars, generates signals via a strategy,
    evaluates them through risk gates, and submits orders — all within a
    managed lifecycle governed by the LoopState state machine.

    Responsibilities:
    - Start a loop with a given configuration.
    - Stop, pause, and resume a running loop.
    - Provide a diagnostics snapshot for monitoring.
    - Expose current state.

    Does NOT:
    - Manage multiple loops (that's the loop manager's job).
    - Persist state to database.
    - Define the state machine (see execution_loop.py).

    Example:
        loop: ExecutionLoopInterface = StrategyExecutionEngine(...)
        loop.start(config)
        assert loop.state == LoopState.RUNNING
        diag = loop.diagnostics()
        print(f"Bars: {diag.bars_processed}, Signals: {diag.signals_generated}")
        loop.pause()
        assert loop.state == LoopState.PAUSED
        loop.resume()
        loop.stop()
        assert loop.state == LoopState.STOPPED
    """

    @abstractmethod
    def start(self, config: ExecutionLoopConfig) -> None:
        """
        Start the execution loop with the given configuration.

        Transitions from INITIALIZING → RUNNING after startup completes.
        Warms up indicator buffers with historical data before processing
        live bars.

        Args:
            config: Complete loop configuration (symbols, strategy, mode, etc.).

        Raises:
            InvalidStateTransitionError: If the loop is not in a startable state.
            ExternalServiceError: If required services are unavailable.

        Example:
            loop.start(ExecutionLoopConfig(
                deployment_id="deploy-001",
                strategy_id="ma-crossover-aapl",
                signal_strategy_id="ma-crossover",
                symbols=["AAPL"],
                interval=CandleInterval.M5,
                execution_mode=ExecutionMode.PAPER,
            ))
        """

    @abstractmethod
    def stop(self) -> None:
        """
        Gracefully stop the execution loop.

        Sets a cooperative stop event and waits for the current bar
        processing cycle to complete before transitioning to STOPPED.

        Raises:
            InvalidStateTransitionError: If the loop is already stopped/failed.

        Example:
            loop.stop()
            assert loop.state == LoopState.STOPPED
        """

    @abstractmethod
    def pause(self) -> None:
        """
        Pause the execution loop.

        Suspends bar processing while keeping the loop thread alive.
        The loop can be resumed later without re-initialisation.

        Raises:
            InvalidStateTransitionError: If the loop is not RUNNING.

        Example:
            loop.pause()
            assert loop.state == LoopState.PAUSED
        """

    @abstractmethod
    def resume(self) -> None:
        """
        Resume a paused execution loop.

        Transitions from PAUSED → RUNNING and resumes bar processing.

        Raises:
            InvalidStateTransitionError: If the loop is not PAUSED.

        Example:
            loop.resume()
            assert loop.state == LoopState.RUNNING
        """

    @abstractmethod
    def diagnostics(self) -> LoopDiagnostics:
        """
        Return a point-in-time snapshot of loop metrics.

        The returned LoopDiagnostics is frozen and safe to read from any thread.

        Returns:
            LoopDiagnostics with current counters, timestamps, and state.

        Example:
            diag = loop.diagnostics()
            print(f"State: {diag.state}, Bars: {diag.bars_processed}")
        """

    @property
    @abstractmethod
    def state(self) -> LoopState:
        """
        Current lifecycle state of the execution loop.

        Returns:
            LoopState enum value.

        Example:
            if loop.state == LoopState.RUNNING:
                loop.pause()
        """
