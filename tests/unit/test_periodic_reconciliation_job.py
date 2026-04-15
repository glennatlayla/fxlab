"""
Unit tests for PeriodicReconciliationJob.

Tests cover:
1. check_and_reconcile() iterates active live deployments and calls
   ReconciliationService.run_reconciliation for each.
2. Non-active or non-live deployments are skipped.
3. A failure for one deployment does not abort the tick — remaining
   deployments are still reconciled.
4. check_and_reconcile() returns the list of deployment_ids successfully
   reconciled.
5. start/stop lifecycle is idempotent and thread-safe.
6. Disabled mode (check_interval_seconds <= 0) — start() is a no-op.

Rationale:
Startup-only reconciliation is not enough for production trading. A crash
or network partition that happens mid-day is only caught at the *next*
restart. Periodic reconciliation bounds the window in which a divergence
between internal state and broker state can go undetected.

Follows §5 TDD naming: test_<unit>_<scenario>_<expected_outcome>
"""

from __future__ import annotations

import time
from typing import Any
from unittest.mock import MagicMock

import pytest

from libs.contracts.reconciliation import ReconciliationTrigger


# ---------------------------------------------------------------------------
# Helpers / fakes
# ---------------------------------------------------------------------------


class _FakeDeploymentRepo:
    """
    Minimal deployment repo that mimics list_by_state.

    Tests populate .deployments as a list of dicts with keys:
    id, state, execution_mode.
    """

    def __init__(self, deployments: list[dict[str, Any]]) -> None:
        self.deployments = deployments
        self.calls: int = 0

    def list_by_state(self, *, state: str) -> list[dict[str, Any]]:
        self.calls += 1
        return [d for d in self.deployments if d.get("state") == state]


class _FakeReconciliationService:
    """
    Captures run_reconciliation calls. `fail_for` is a set of deployment
    ids that should raise on run.
    """

    def __init__(self, fail_for: set[str] | None = None) -> None:
        self.calls: list[tuple[str, ReconciliationTrigger]] = []
        self._fail_for = fail_for or set()

    def run_reconciliation(
        self,
        *,
        deployment_id: str,
        trigger: ReconciliationTrigger,
    ) -> Any:
        self.calls.append((deployment_id, trigger))
        if deployment_id in self._fail_for:
            raise RuntimeError(f"Simulated reconciliation failure for {deployment_id}")
        return MagicMock(
            report_id=f"report-{deployment_id}",
            deployment_id=deployment_id,
            discrepancies=[],
        )

    def get_report(self, *, report_id: str) -> Any:  # pragma: no cover - iface shim
        raise NotImplementedError

    def list_reports(  # pragma: no cover - iface shim
        self, *, deployment_id: str, limit: int = 20
    ) -> list[Any]:
        raise NotImplementedError


def _build_job(
    *,
    deployments: list[dict[str, Any]],
    fail_for: set[str] | None = None,
    check_interval_seconds: float = 0.05,
) -> tuple[Any, _FakeReconciliationService, _FakeDeploymentRepo]:
    from services.api.infrastructure.periodic_reconciliation_job import (
        PeriodicReconciliationJob,
    )

    repo = _FakeDeploymentRepo(deployments)
    svc = _FakeReconciliationService(fail_for=fail_for)
    job = PeriodicReconciliationJob(
        reconciliation_service=svc,
        deployment_repo=repo,
        check_interval_seconds=check_interval_seconds,
    )
    return job, svc, repo


# ===========================================================================
# Test: check_and_reconcile iteration
# ===========================================================================


class TestCheckAndReconcile:
    def test_reconciles_each_active_live_deployment(self) -> None:
        deployments = [
            {"id": "dep-1", "state": "active", "execution_mode": "live"},
            {"id": "dep-2", "state": "active", "execution_mode": "live"},
        ]
        job, svc, _repo = _build_job(deployments=deployments)

        reconciled = job.check_and_reconcile()

        assert sorted(reconciled) == ["dep-1", "dep-2"]
        called_ids = sorted(c[0] for c in svc.calls)
        assert called_ids == ["dep-1", "dep-2"]
        assert all(c[1] == ReconciliationTrigger.SCHEDULED for c in svc.calls)

    def test_skips_non_live_deployments(self) -> None:
        deployments = [
            {"id": "dep-live", "state": "active", "execution_mode": "live"},
            {"id": "dep-paper", "state": "active", "execution_mode": "paper"},
            {"id": "dep-shadow", "state": "active", "execution_mode": "shadow"},
        ]
        job, svc, _repo = _build_job(deployments=deployments)

        reconciled = job.check_and_reconcile()

        assert reconciled == ["dep-live"]
        assert [c[0] for c in svc.calls] == ["dep-live"]

    def test_skips_non_active_deployments(self) -> None:
        deployments = [
            {"id": "dep-stopped", "state": "stopped", "execution_mode": "live"},
            {"id": "dep-draft", "state": "draft", "execution_mode": "live"},
        ]
        job, svc, _repo = _build_job(deployments=deployments)

        reconciled = job.check_and_reconcile()

        assert reconciled == []
        assert svc.calls == []

    def test_per_deployment_failure_does_not_abort_tick(self) -> None:
        deployments = [
            {"id": "dep-ok-1", "state": "active", "execution_mode": "live"},
            {"id": "dep-fail", "state": "active", "execution_mode": "live"},
            {"id": "dep-ok-2", "state": "active", "execution_mode": "live"},
        ]
        job, svc, _repo = _build_job(
            deployments=deployments,
            fail_for={"dep-fail"},
        )

        reconciled = job.check_and_reconcile()

        # The failed deployment is NOT in reconciled, but the others are.
        assert sorted(reconciled) == ["dep-ok-1", "dep-ok-2"]
        # run_reconciliation was invoked for all three (the job attempts all)
        assert sorted(c[0] for c in svc.calls) == ["dep-fail", "dep-ok-1", "dep-ok-2"]

    def test_empty_active_set_returns_empty_list(self) -> None:
        job, svc, _repo = _build_job(deployments=[])

        reconciled = job.check_and_reconcile()

        assert reconciled == []
        assert svc.calls == []


# ===========================================================================
# Test: Background lifecycle
# ===========================================================================


class TestBackgroundLifecycle:
    def test_start_then_stop_runs_at_least_one_tick(self) -> None:
        deployments = [
            {"id": "dep-1", "state": "active", "execution_mode": "live"},
        ]
        job, svc, _repo = _build_job(
            deployments=deployments,
            check_interval_seconds=0.05,
        )

        assert job.is_running is False
        job.start()
        try:
            assert job.is_running is True
            # Wait up to 2s for at least one tick to run.
            deadline = time.time() + 2.0
            while time.time() < deadline and not svc.calls:
                time.sleep(0.02)
        finally:
            job.stop()

        assert job.is_running is False
        assert len(svc.calls) >= 1
        assert svc.calls[0][0] == "dep-1"

    def test_start_is_idempotent(self) -> None:
        job, _svc, _repo = _build_job(deployments=[])
        job.start()
        try:
            job.start()  # second call is a no-op, not an error
            assert job.is_running is True
        finally:
            job.stop()

    def test_stop_when_not_running_is_noop(self) -> None:
        job, _svc, _repo = _build_job(deployments=[])
        # should not raise
        job.stop()
        assert job.is_running is False

    def test_disabled_interval_start_is_noop(self) -> None:
        deployments = [
            {"id": "dep-1", "state": "active", "execution_mode": "live"},
        ]
        job, svc, _repo = _build_job(
            deployments=deployments,
            check_interval_seconds=0,
        )
        job.start()
        try:
            # give scheduler a moment — no tick should happen
            time.sleep(0.1)
            assert job.is_running is False
            assert svc.calls == []
        finally:
            job.stop()

    def test_construction_rejects_missing_dependencies(self) -> None:
        from services.api.infrastructure.periodic_reconciliation_job import (
            PeriodicReconciliationJob,
        )

        # No service and no factory → ValueError
        with pytest.raises((TypeError, ValueError)):
            PeriodicReconciliationJob(
                reconciliation_service=None,
                reconciliation_service_factory=None,
                deployment_repo=MagicMock(),
                check_interval_seconds=10.0,
            )
        # Missing deployment_repo → ValueError
        with pytest.raises((TypeError, ValueError)):
            PeriodicReconciliationJob(
                reconciliation_service=MagicMock(),
                deployment_repo=None,  # type: ignore[arg-type]
                check_interval_seconds=10.0,
            )
        # Both service AND factory → ValueError (must be exactly one)
        with pytest.raises((TypeError, ValueError)):
            PeriodicReconciliationJob(
                reconciliation_service=MagicMock(),
                reconciliation_service_factory=lambda: MagicMock(),
                deployment_repo=MagicMock(),
                check_interval_seconds=10.0,
            )


# ===========================================================================
# Test: Factory-mode wiring (recommended for production — fresh session per tick)
# ===========================================================================


class TestFactoryMode:
    def test_factory_is_called_each_tick(self) -> None:
        """
        When a factory is supplied, each call to check_and_reconcile builds
        a fresh ReconciliationService — this is how production wires a
        thread-safe, per-tick session + repos.
        """
        from services.api.infrastructure.periodic_reconciliation_job import (
            PeriodicReconciliationJob,
        )

        deployments = [
            {"id": "dep-1", "state": "active", "execution_mode": "live"},
        ]
        repo = _FakeDeploymentRepo(deployments)

        call_count = 0
        services_built: list[_FakeReconciliationService] = []

        def factory() -> _FakeReconciliationService:
            nonlocal call_count
            call_count += 1
            svc = _FakeReconciliationService()
            services_built.append(svc)
            return svc

        job = PeriodicReconciliationJob(
            reconciliation_service_factory=factory,
            deployment_repo=repo,
            check_interval_seconds=0.05,
        )

        job.check_and_reconcile()
        job.check_and_reconcile()

        assert call_count == 2, "Factory should be called once per tick"
        assert len(services_built[0].calls) == 1
        assert services_built[0].calls[0][0] == "dep-1"
        assert len(services_built[1].calls) == 1

    def test_factory_exception_skips_tick_cleanly(self) -> None:
        """
        If the factory itself raises (e.g. DB unavailable), the tick logs
        and returns [] without crashing the scheduler thread.
        """
        from services.api.infrastructure.periodic_reconciliation_job import (
            PeriodicReconciliationJob,
        )

        deployments = [
            {"id": "dep-1", "state": "active", "execution_mode": "live"},
        ]
        repo = _FakeDeploymentRepo(deployments)

        def bad_factory() -> Any:
            raise RuntimeError("db unavailable")

        job = PeriodicReconciliationJob(
            reconciliation_service_factory=bad_factory,
            deployment_repo=repo,
            check_interval_seconds=0.05,
        )

        # Should not raise
        result = job.check_and_reconcile()
        assert result == []
