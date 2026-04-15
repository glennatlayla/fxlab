"""
Mock execution loop for unit testing.

Responsibilities:
- Provide an in-memory implementation of ExecutionLoopInterface.
- Enforce state machine transitions using validate_transition().
- Record lifecycle events for test assertions.
- Provide introspection helpers (event_log, transition_count, etc.).

Does NOT:
- Process market data or generate signals (it's a mock).
- Start threads or connect to external services.
- Persist any state beyond the test lifecycle.

Dependencies:
- libs.contracts.interfaces.execution_loop: ExecutionLoopInterface
- libs.contracts.execution_loop: (all contracts)

Example:
    loop = MockExecutionLoop()
    loop.start(config)
    assert loop.state == LoopState.RUNNING
    assert loop.start_count == 1
    loop.stop()
    assert loop.event_log == ["start", "stop"]
"""

from __future__ import annotations

import threading

from libs.contracts.execution_loop import (
    ExecutionLoopConfig,
    LoopDiagnostics,
    LoopState,
    validate_transition,
)
from libs.contracts.interfaces.execution_loop import ExecutionLoopInterface


class MockExecutionLoop(ExecutionLoopInterface):
    """
    In-memory mock of ExecutionLoopInterface for unit testing.

    Enforces the state machine exactly as a real implementation would,
    but performs no actual bar processing. All lifecycle calls are recorded
    in an event log for assertion.

    Responsibilities:
    - Simulate the loop lifecycle state machine.
    - Track lifecycle events for test assertions.
    - Allow configurable diagnostics for downstream tests.

    Does NOT:
    - Process market data.
    - Generate signals or submit orders.
    - Start background threads.

    Thread safety:
    - All state mutations are protected by a threading.Lock.

    Example:
        loop = MockExecutionLoop()
        loop.start(config)
        assert loop.state == LoopState.RUNNING
        diag = loop.diagnostics()
        assert diag.bars_processed == 0
        loop.stop()
        assert loop.event_log == ["start", "stop"]
    """

    def __init__(self) -> None:
        """Initialise mock with INITIALIZING state and empty event log."""
        self._lock = threading.Lock()
        self._state = LoopState.INITIALIZING
        self._config: ExecutionLoopConfig | None = None
        self._event_log: list[str] = []
        self._diagnostics_override: LoopDiagnostics | None = None

        # Counters for test introspection.
        self._start_count = 0
        self._stop_count = 0
        self._pause_count = 0
        self._resume_count = 0

    def start(self, config: ExecutionLoopConfig) -> None:
        """
        Start the mock loop — validates transition, records event.

        Args:
            config: Loop configuration.

        Raises:
            InvalidStateTransitionError: If not in INITIALIZING state.

        Example:
            loop.start(config)
            assert loop.state == LoopState.RUNNING
        """
        with self._lock:
            validate_transition(self._state, LoopState.RUNNING)
            self._config = config
            self._state = LoopState.RUNNING
            self._event_log.append("start")
            self._start_count += 1

    def stop(self) -> None:
        """
        Stop the mock loop — validates transition, records event.

        Raises:
            InvalidStateTransitionError: If in a terminal state.

        Example:
            loop.stop()
            assert loop.state == LoopState.STOPPED
        """
        with self._lock:
            validate_transition(self._state, LoopState.STOPPED)
            self._state = LoopState.STOPPED
            self._event_log.append("stop")
            self._stop_count += 1

    def pause(self) -> None:
        """
        Pause the mock loop — validates transition, records event.

        Raises:
            InvalidStateTransitionError: If not RUNNING.

        Example:
            loop.pause()
            assert loop.state == LoopState.PAUSED
        """
        with self._lock:
            validate_transition(self._state, LoopState.PAUSED)
            self._state = LoopState.PAUSED
            self._event_log.append("pause")
            self._pause_count += 1

    def resume(self) -> None:
        """
        Resume the mock loop — validates transition, records event.

        Raises:
            InvalidStateTransitionError: If not PAUSED.

        Example:
            loop.resume()
            assert loop.state == LoopState.RUNNING
        """
        with self._lock:
            validate_transition(self._state, LoopState.RUNNING)
            self._state = LoopState.RUNNING
            self._event_log.append("resume")
            self._resume_count += 1

    def diagnostics(self) -> LoopDiagnostics:
        """
        Return diagnostics snapshot.

        If a diagnostics_override has been set via set_diagnostics(), returns
        that instead of the default zero-counters snapshot.

        Returns:
            LoopDiagnostics snapshot.

        Example:
            diag = loop.diagnostics()
            assert diag.bars_processed == 0
        """
        with self._lock:
            if self._diagnostics_override is not None:
                return self._diagnostics_override
            deployment_id = self._config.deployment_id if self._config else "mock"
            return LoopDiagnostics(
                state=self._state,
                deployment_id=deployment_id,
            )

    @property
    def state(self) -> LoopState:
        """Current lifecycle state (thread-safe read)."""
        with self._lock:
            return self._state

    # ------------------------------------------------------------------
    # Introspection helpers (test-only)
    # ------------------------------------------------------------------

    @property
    def event_log(self) -> list[str]:
        """Return copy of the ordered event log."""
        with self._lock:
            return list(self._event_log)

    @property
    def start_count(self) -> int:
        """Number of times start() was called successfully."""
        with self._lock:
            return self._start_count

    @property
    def stop_count(self) -> int:
        """Number of times stop() was called successfully."""
        with self._lock:
            return self._stop_count

    @property
    def pause_count(self) -> int:
        """Number of times pause() was called successfully."""
        with self._lock:
            return self._pause_count

    @property
    def resume_count(self) -> int:
        """Number of times resume() was called successfully."""
        with self._lock:
            return self._resume_count

    @property
    def config(self) -> ExecutionLoopConfig | None:
        """Return the config passed to start(), or None if not started."""
        with self._lock:
            return self._config

    def set_diagnostics(self, diag: LoopDiagnostics) -> None:
        """
        Override the diagnostics snapshot returned by diagnostics().

        Useful for testing downstream code that reads diagnostics.

        Args:
            diag: The diagnostics snapshot to return.

        Example:
            loop.set_diagnostics(LoopDiagnostics(
                state=LoopState.RUNNING,
                deployment_id="d1",
                bars_processed=100,
            ))
        """
        with self._lock:
            self._diagnostics_override = diag

    def force_state(self, state: LoopState) -> None:
        """
        Force the loop into a specific state without transition validation.

        Test-only escape hatch for setting up specific test scenarios
        (e.g., starting from COOLDOWN or FAILED state).

        Args:
            state: The state to force.

        Example:
            loop.force_state(LoopState.COOLDOWN)
            assert loop.state == LoopState.COOLDOWN
        """
        with self._lock:
            self._state = state

    def clear(self) -> None:
        """Reset mock to initial state for test reuse."""
        with self._lock:
            self._state = LoopState.INITIALIZING
            self._config = None
            self._event_log.clear()
            self._diagnostics_override = None
            self._start_count = 0
            self._stop_count = 0
            self._pause_count = 0
            self._resume_count = 0
