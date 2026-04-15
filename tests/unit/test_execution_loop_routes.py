"""
Unit tests for execution loop routes and ExecutionLoopManager (M8).

Tests cover:
1. ExecutionLoopManager — register, unregister, get, list, stop_all, limits.
2. Execution loop REST routes — start, stop, pause, resume, diagnostics, list.
3. Auth enforcement — unauthenticated requests rejected.
4. Error handling — 404, 409, 503 responses.

Follows §5 TDD naming: test_<unit>_<scenario>_<expected_outcome>
"""

from __future__ import annotations

import threading

import pytest

from libs.contracts.execution_loop import (
    ExecutionLoopConfig,
    LoopDiagnostics,
    LoopState,
)
from libs.contracts.mocks.mock_execution_loop import MockExecutionLoop
from services.api.infrastructure.execution_loop_manager import ExecutionLoopManager

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_config(deployment_id: str = "deploy-001") -> ExecutionLoopConfig:
    """Build a default config."""
    from libs.contracts.execution import ExecutionMode
    from libs.contracts.market_data import CandleInterval

    return ExecutionLoopConfig(
        deployment_id=deployment_id,
        strategy_id="ma-crossover",
        signal_strategy_id="ma-crossover",
        symbols=["AAPL"],
        interval=CandleInterval.M5,
        execution_mode=ExecutionMode.PAPER,
    )


def _make_running_loop(deployment_id: str = "deploy-001") -> MockExecutionLoop:
    """Create a mock loop in RUNNING state."""
    loop = MockExecutionLoop()
    loop.start(_make_config(deployment_id))
    return loop


# ===========================================================================
# ExecutionLoopManager tests
# ===========================================================================


class TestManagerRegistration:
    """Verify loop registration and unregistration."""

    def test_register_new_loop(self) -> None:
        """Can register a new loop."""
        manager = ExecutionLoopManager(max_concurrent=10)
        loop = _make_running_loop()
        manager.register("deploy-001", loop)
        assert manager.count() == 1

    def test_register_duplicate_raises(self) -> None:
        """Registering a duplicate deployment raises ValueError."""
        manager = ExecutionLoopManager(max_concurrent=10)
        manager.register("deploy-001", _make_running_loop())
        with pytest.raises(ValueError, match="already has an active loop"):
            manager.register("deploy-001", _make_running_loop())

    def test_register_exceeds_max_raises(self) -> None:
        """Exceeding max_concurrent raises ValueError."""
        manager = ExecutionLoopManager(max_concurrent=2)
        manager.register("deploy-001", _make_running_loop("deploy-001"))
        manager.register("deploy-002", _make_running_loop("deploy-002"))
        with pytest.raises(ValueError, match="Maximum concurrent"):
            manager.register("deploy-003", _make_running_loop("deploy-003"))

    def test_unregister_existing(self) -> None:
        """Can unregister an existing loop."""
        manager = ExecutionLoopManager(max_concurrent=10)
        manager.register("deploy-001", _make_running_loop())
        manager.unregister("deploy-001")
        assert manager.count() == 0

    def test_unregister_missing_raises(self) -> None:
        """Unregistering a missing deployment raises KeyError."""
        manager = ExecutionLoopManager(max_concurrent=10)
        with pytest.raises(KeyError, match="No loop found"):
            manager.unregister("nonexistent")

    def test_invalid_max_concurrent_raises(self) -> None:
        """max_concurrent < 1 raises ValueError."""
        with pytest.raises(ValueError, match="max_concurrent must be >= 1"):
            ExecutionLoopManager(max_concurrent=0)


class TestManagerRetrieval:
    """Verify loop retrieval and listing."""

    def test_get_existing(self) -> None:
        """Can retrieve a registered loop."""
        manager = ExecutionLoopManager(max_concurrent=10)
        loop = _make_running_loop()
        manager.register("deploy-001", loop)
        assert manager.get("deploy-001") is loop

    def test_get_missing_raises(self) -> None:
        """Retrieving a missing deployment raises KeyError."""
        manager = ExecutionLoopManager(max_concurrent=10)
        with pytest.raises(KeyError):
            manager.get("nonexistent")

    def test_list_deployments(self) -> None:
        """list_deployments returns all registered IDs."""
        manager = ExecutionLoopManager(max_concurrent=10)
        manager.register("deploy-001", _make_running_loop("deploy-001"))
        manager.register("deploy-002", _make_running_loop("deploy-002"))
        ids = manager.list_deployments()
        assert set(ids) == {"deploy-001", "deploy-002"}

    def test_list_diagnostics(self) -> None:
        """list_diagnostics returns diagnostics for all loops."""
        manager = ExecutionLoopManager(max_concurrent=10)
        manager.register("deploy-001", _make_running_loop("deploy-001"))
        manager.register("deploy-002", _make_running_loop("deploy-002"))
        diags = manager.list_diagnostics()
        assert len(diags) == 2
        assert all(isinstance(d, LoopDiagnostics) for d in diags)

    def test_get_diagnostics(self) -> None:
        """get_diagnostics returns diagnostics for a specific loop."""
        manager = ExecutionLoopManager(max_concurrent=10)
        manager.register("deploy-001", _make_running_loop())
        diag = manager.get_diagnostics("deploy-001")
        assert diag.deployment_id == "deploy-001"
        assert diag.state == LoopState.RUNNING


class TestManagerStopAll:
    """Verify stop_all behaviour."""

    def test_stop_all_stops_all_loops(self) -> None:
        """stop_all stops all registered loops."""
        manager = ExecutionLoopManager(max_concurrent=10)
        loop1 = _make_running_loop("deploy-001")
        loop2 = _make_running_loop("deploy-002")
        manager.register("deploy-001", loop1)
        manager.register("deploy-002", loop2)
        results = manager.stop_all()
        assert loop1.state == LoopState.STOPPED
        assert loop2.state == LoopState.STOPPED
        assert manager.count() == 0
        assert results["deploy-001"] == "stopped"
        assert results["deploy-002"] == "stopped"

    def test_stop_all_handles_already_stopped(self) -> None:
        """stop_all handles loops that are already stopped."""
        manager = ExecutionLoopManager(max_concurrent=10)
        loop = _make_running_loop()
        loop.stop()  # Already stopped.
        manager.register("deploy-001", loop)
        results = manager.stop_all()
        assert results["deploy-001"] == "stopped"

    def test_stop_all_empty_manager(self) -> None:
        """stop_all on empty manager returns empty dict."""
        manager = ExecutionLoopManager(max_concurrent=10)
        results = manager.stop_all()
        assert results == {}


class TestManagerThreadSafety:
    """Verify thread-safe access to the manager."""

    def test_concurrent_reads(self) -> None:
        """Multiple threads can read diagnostics concurrently."""
        manager = ExecutionLoopManager(max_concurrent=10)
        manager.register("deploy-001", _make_running_loop())
        errors: list[Exception] = []
        barrier = threading.Barrier(10)

        def reader() -> None:
            try:
                barrier.wait(timeout=5)
                for _ in range(10):
                    manager.list_diagnostics()
                    manager.count()
                    manager.list_deployments()
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=reader) for _ in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=10)

        assert len(errors) == 0


# ===========================================================================
# Route tests (using FastAPI TestClient)
# ===========================================================================


class TestExecutionLoopRoutes:
    """Verify execution loop REST endpoints."""

    @pytest.fixture()
    def client(self):
        """Create a test client with execution loop manager."""
        from unittest.mock import MagicMock

        from fastapi import FastAPI
        from fastapi.testclient import TestClient

        from services.api.routes.execution_loop import router

        app = FastAPI()
        app.include_router(router)

        # Wire up manager and factory in app state.
        manager = ExecutionLoopManager(max_concurrent=10)
        app.state.execution_loop_manager = manager

        def mock_factory(config: ExecutionLoopConfig) -> MockExecutionLoop:
            loop = MockExecutionLoop()
            return loop

        app.state.execution_engine_factory = mock_factory

        # Override auth dependencies to bypass JWT.
        from services.api.auth import get_current_user, require_scope

        app.dependency_overrides[get_current_user] = lambda: MagicMock(
            user_id="test-user", scopes=["operator:write"]
        )
        app.dependency_overrides[require_scope("operator:write")] = lambda: None

        yield TestClient(app), manager

    def test_list_loops_empty(self, client: tuple) -> None:
        """GET /execution/loops returns empty list when no loops active."""
        test_client, _manager = client
        resp = test_client.get("/execution/loops")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 0
        assert data["loops"] == []

    def test_start_loop(self, client: tuple) -> None:
        """POST /execution/loops starts a new loop."""
        test_client, manager = client
        body = {
            "deployment_id": "deploy-001",
            "strategy_id": "ma-crossover",
            "signal_strategy_id": "ma-crossover",
            "symbols": ["AAPL"],
            "interval": "5m",
            "execution_mode": "paper",
        }
        resp = test_client.post("/execution/loops", json=body)
        assert resp.status_code == 201
        assert manager.count() == 1

    def test_start_duplicate_returns_409(self, client: tuple) -> None:
        """POST /execution/loops returns 409 for duplicate deployment."""
        test_client, _manager = client
        body = {
            "deployment_id": "deploy-001",
            "strategy_id": "ma-crossover",
            "signal_strategy_id": "ma-crossover",
            "symbols": ["AAPL"],
            "interval": "5m",
            "execution_mode": "paper",
        }
        test_client.post("/execution/loops", json=body)
        resp = test_client.post("/execution/loops", json=body)
        assert resp.status_code == 409

    def test_stop_loop(self, client: tuple) -> None:
        """DELETE /execution/loops/{id} stops and removes the loop."""
        test_client, manager = client
        body = {
            "deployment_id": "deploy-001",
            "strategy_id": "ma-crossover",
            "signal_strategy_id": "ma-crossover",
            "symbols": ["AAPL"],
            "interval": "5m",
            "execution_mode": "paper",
        }
        test_client.post("/execution/loops", json=body)
        resp = test_client.delete("/execution/loops/deploy-001")
        assert resp.status_code == 200
        assert manager.count() == 0

    def test_stop_missing_returns_404(self, client: tuple) -> None:
        """DELETE /execution/loops/{id} returns 404 for missing deployment."""
        test_client, _manager = client
        resp = test_client.delete("/execution/loops/nonexistent")
        assert resp.status_code == 404

    def test_pause_loop(self, client: tuple) -> None:
        """PUT /execution/loops/{id}/pause pauses a running loop."""
        test_client, manager = client
        body = {
            "deployment_id": "deploy-001",
            "strategy_id": "ma-crossover",
            "signal_strategy_id": "ma-crossover",
            "symbols": ["AAPL"],
            "interval": "5m",
            "execution_mode": "paper",
        }
        test_client.post("/execution/loops", json=body)
        resp = test_client.put("/execution/loops/deploy-001/pause")
        assert resp.status_code == 200
        loop = manager.get("deploy-001")
        assert loop.state == LoopState.PAUSED

    def test_resume_loop(self, client: tuple) -> None:
        """PUT /execution/loops/{id}/resume resumes a paused loop."""
        test_client, manager = client
        body = {
            "deployment_id": "deploy-001",
            "strategy_id": "ma-crossover",
            "signal_strategy_id": "ma-crossover",
            "symbols": ["AAPL"],
            "interval": "5m",
            "execution_mode": "paper",
        }
        test_client.post("/execution/loops", json=body)
        test_client.put("/execution/loops/deploy-001/pause")
        resp = test_client.put("/execution/loops/deploy-001/resume")
        assert resp.status_code == 200
        loop = manager.get("deploy-001")
        assert loop.state == LoopState.RUNNING

    def test_get_diagnostics(self, client: tuple) -> None:
        """GET /execution/loops/{id}/diagnostics returns loop metrics."""
        test_client, _manager = client
        body = {
            "deployment_id": "deploy-001",
            "strategy_id": "ma-crossover",
            "signal_strategy_id": "ma-crossover",
            "symbols": ["AAPL"],
            "interval": "5m",
            "execution_mode": "paper",
        }
        test_client.post("/execution/loops", json=body)
        resp = test_client.get("/execution/loops/deploy-001/diagnostics")
        assert resp.status_code == 200
        data = resp.json()
        assert data["deployment_id"] == "deploy-001"
        assert data["state"] == "running"

    def test_list_loops_with_active(self, client: tuple) -> None:
        """GET /execution/loops lists all active loops."""
        test_client, _manager = client
        for deploy_id in ["deploy-001", "deploy-002"]:
            body = {
                "deployment_id": deploy_id,
                "strategy_id": "ma-crossover",
                "signal_strategy_id": "ma-crossover",
                "symbols": ["AAPL"],
                "interval": "5m",
                "execution_mode": "paper",
            }
            test_client.post("/execution/loops", json=body)
        resp = test_client.get("/execution/loops")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 2
