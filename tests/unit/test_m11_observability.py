"""
Unit tests for M11: Alerting + Observability Hardening.

Coverage:
- MockDependencyHealthRepository
    - check() returns all four standard dependencies
    - check() overall_status is OK by default
    - set_dependency_status() overrides a single dependency
    - overall_status reflects DEGRADED when any dep is DEGRADED
    - overall_status reflects DOWN when any dep is DOWN
    - DOWN beats DEGRADED in overall_status
    - clear() resets all overrides back to OK
    - count() returns 4 (standard dependency set)
- MockDiagnosticsRepository
    - snapshot() defaults all counts to 0
    - set_snapshot() updates counts correctly
    - clear() resets counts to 0
    - snapshot() always returns a DiagnosticsSnapshot with generated_at
- GET /health/dependencies
    - 200 with dependencies list, overall_status, generated_at
    - each dependency has name, status, latency_ms, detail fields
    - overall_status OK when all deps are OK
    - overall_status DOWN when any dep is DOWN (via DI override)
    - four dependencies are returned by default
- GET /health/diagnostics
    - 200 with all four count fields and generated_at
    - counts reflect values from injected repo
    - all counts 0 for clean system

All tests MUST FAIL before GREEN (S4) and MUST PASS after GREEN.

Known lessons:
    LL-007: DependencyHealthRecord.detail and overall_status are str="" not Optional[str].
    LL-008: Route handlers use JSONResponse; no response_model=.
"""

from __future__ import annotations

from datetime import datetime

import pytest
from fastapi.testclient import TestClient

from libs.contracts.mocks.mock_dependency_health_repository import (
    MockDependencyHealthRepository,
)
from libs.contracts.mocks.mock_diagnostics_repository import MockDiagnosticsRepository
from libs.contracts.observability import DependencyStatus

AUTH_HEADERS = {"Authorization": "Bearer TEST_TOKEN"}

# ---------------------------------------------------------------------------
# MockDependencyHealthRepository tests
# ---------------------------------------------------------------------------


class TestMockDependencyHealthRepository:
    """
    Verify MockDependencyHealthRepository honours the DependencyHealthRepositoryInterface
    contract and correctly computes overall_status from individual dependency states.
    """

    def test_check_returns_four_dependencies(self) -> None:
        """
        GIVEN a fresh MockDependencyHealthRepository
        WHEN check() is called
        THEN four dependency records are returned (database, queues, artifact_store,
             feed_health_service).
        """
        repo = MockDependencyHealthRepository()
        resp = repo.check(correlation_id="c")
        assert len(resp.dependencies) == 4, (
            f"Expected 4 dependencies, got {len(resp.dependencies)}: {resp.dependencies}"
        )

    def test_check_default_overall_status_is_ok(self) -> None:
        """
        GIVEN no overrides set
        WHEN check() is called
        THEN overall_status is 'OK'.
        """
        repo = MockDependencyHealthRepository()
        resp = repo.check(correlation_id="c")
        assert resp.overall_status == "OK", f"overall_status wrong: {resp.overall_status}"

    def test_check_all_deps_are_ok_by_default(self) -> None:
        """
        GIVEN no overrides set
        WHEN check() is called
        THEN all dependency records have status 'OK'.
        """
        repo = MockDependencyHealthRepository()
        resp = repo.check(correlation_id="c")
        for dep in resp.dependencies:
            assert dep.status == DependencyStatus.OK, (
                f"Dep {dep.name} expected OK, got {dep.status}"
            )

    def test_set_dependency_status_overrides_single_dep(self) -> None:
        """
        GIVEN set_dependency_status("queues", DEGRADED) is called
        WHEN check() is called
        THEN the queues dependency has status DEGRADED and others are OK.
        """
        repo = MockDependencyHealthRepository()
        repo.set_dependency_status("queues", DependencyStatus.DEGRADED, detail="high latency")
        resp = repo.check(correlation_id="c")
        queues_dep = next((d for d in resp.dependencies if d.name == "queues"), None)
        assert queues_dep is not None, "queues dependency missing"
        assert queues_dep.status == DependencyStatus.DEGRADED
        assert queues_dep.detail == "high latency"

    def test_overall_status_is_degraded_when_any_dep_degraded(self) -> None:
        """
        GIVEN one dependency set to DEGRADED and all others OK
        WHEN check() is called
        THEN overall_status is 'DEGRADED'.
        """
        repo = MockDependencyHealthRepository()
        repo.set_dependency_status("artifact_store", DependencyStatus.DEGRADED)
        resp = repo.check(correlation_id="c")
        assert resp.overall_status == "DEGRADED", f"Expected DEGRADED, got {resp.overall_status}"

    def test_overall_status_is_down_when_any_dep_down(self) -> None:
        """
        GIVEN one dependency set to DOWN
        WHEN check() is called
        THEN overall_status is 'DOWN'.
        """
        repo = MockDependencyHealthRepository()
        repo.set_dependency_status("database", DependencyStatus.DOWN, detail="connection refused")
        resp = repo.check(correlation_id="c")
        assert resp.overall_status == "DOWN", f"Expected DOWN, got {resp.overall_status}"

    def test_down_beats_degraded_in_overall_status(self) -> None:
        """
        GIVEN one dependency DEGRADED and another DOWN
        WHEN check() is called
        THEN overall_status is 'DOWN' (DOWN beats DEGRADED).
        """
        repo = MockDependencyHealthRepository()
        repo.set_dependency_status("queues", DependencyStatus.DEGRADED)
        repo.set_dependency_status("database", DependencyStatus.DOWN)
        resp = repo.check(correlation_id="c")
        assert resp.overall_status == "DOWN", (
            f"Expected DOWN over DEGRADED, got {resp.overall_status}"
        )

    def test_clear_resets_all_overrides(self) -> None:
        """
        GIVEN overrides set for one dependency
        WHEN clear() is called and check() is called again
        THEN overall_status is 'OK'.
        """
        repo = MockDependencyHealthRepository()
        repo.set_dependency_status("database", DependencyStatus.DOWN)
        repo.clear()
        resp = repo.check(correlation_id="c")
        assert resp.overall_status == "OK"

    def test_count_returns_four(self) -> None:
        """
        GIVEN a MockDependencyHealthRepository
        WHEN count() is called
        THEN 4 is returned (the four standard dependencies).
        """
        repo = MockDependencyHealthRepository()
        assert repo.count() == 4

    def test_check_response_has_generated_at(self) -> None:
        """
        GIVEN a fresh repo
        WHEN check() is called
        THEN the response has a generated_at datetime field.
        """
        repo = MockDependencyHealthRepository()
        resp = repo.check(correlation_id="c")
        assert isinstance(resp.generated_at, datetime)


# ---------------------------------------------------------------------------
# MockDiagnosticsRepository tests
# ---------------------------------------------------------------------------


class TestMockDiagnosticsRepository:
    """
    Verify MockDiagnosticsRepository honours the DiagnosticsRepositoryInterface contract.
    """

    def test_snapshot_defaults_all_counts_to_zero(self) -> None:
        """
        GIVEN a fresh MockDiagnosticsRepository
        WHEN snapshot() is called
        THEN all four count fields are 0.
        """
        repo = MockDiagnosticsRepository()
        snap = repo.snapshot(correlation_id="c")
        assert snap.queue_contention_count == 0
        assert snap.feed_health_count == 0
        assert snap.parity_critical_count == 0
        assert snap.certification_blocked_count == 0

    def test_set_snapshot_updates_counts(self) -> None:
        """
        GIVEN set_snapshot(parity_critical_count=3, feed_health_count=5) is called
        WHEN snapshot() is called
        THEN the values are correctly reflected.
        """
        repo = MockDiagnosticsRepository()
        repo.set_snapshot(parity_critical_count=3, feed_health_count=5)
        snap = repo.snapshot(correlation_id="c")
        assert snap.parity_critical_count == 3
        assert snap.feed_health_count == 5
        assert snap.queue_contention_count == 0
        assert snap.certification_blocked_count == 0

    def test_set_snapshot_all_fields(self) -> None:
        """
        GIVEN all four fields set via set_snapshot()
        WHEN snapshot() is called
        THEN all four fields match the set values.
        """
        repo = MockDiagnosticsRepository()
        repo.set_snapshot(
            queue_contention_count=2,
            feed_health_count=10,
            parity_critical_count=1,
            certification_blocked_count=3,
        )
        snap = repo.snapshot(correlation_id="c")
        assert snap.queue_contention_count == 2
        assert snap.feed_health_count == 10
        assert snap.parity_critical_count == 1
        assert snap.certification_blocked_count == 3

    def test_clear_resets_all_counts_to_zero(self) -> None:
        """
        GIVEN counts set via set_snapshot()
        WHEN clear() is called and snapshot() is called
        THEN all counts are 0.
        """
        repo = MockDiagnosticsRepository()
        repo.set_snapshot(parity_critical_count=5)
        repo.clear()
        snap = repo.snapshot(correlation_id="c")
        assert snap.parity_critical_count == 0

    def test_snapshot_always_has_generated_at(self) -> None:
        """
        GIVEN a fresh repo
        WHEN snapshot() is called
        THEN generated_at is a datetime.
        """
        repo = MockDiagnosticsRepository()
        snap = repo.snapshot(correlation_id="c")
        assert isinstance(snap.generated_at, datetime)


# ---------------------------------------------------------------------------
# GET /health/dependencies endpoint tests
# ---------------------------------------------------------------------------


class TestDependencyHealthEndpoint:
    """
    Unit tests for GET /health/dependencies.

    The endpoint must:
    - Return 200 with dependencies list, overall_status, generated_at.
    - Each dependency has name, status, latency_ms, detail fields.
    - overall_status is 'OK' when all deps are OK.
    - overall_status reflects injected DOWN state.
    - Return four dependencies by default.

    FAILS: services/api/routes/observability.py does not exist until GREEN (S4).
    """

    @pytest.fixture
    def healthy_repo(self) -> MockDependencyHealthRepository:
        """All dependencies OK."""
        return MockDependencyHealthRepository()

    @pytest.fixture
    def client_healthy(self, healthy_repo: MockDependencyHealthRepository) -> TestClient:
        from services.api.main import app
        from services.api.routes.observability import get_dependency_health_repository

        app.dependency_overrides[get_dependency_health_repository] = lambda: healthy_repo
        tc = TestClient(app)
        yield tc
        app.dependency_overrides.clear()

    def test_dependencies_returns_200(self, client_healthy: TestClient) -> None:
        """
        GIVEN all deps OK
        WHEN GET /health/dependencies is requested
        THEN 200 is returned.

        FAILS: endpoint does not exist until GREEN.
        """
        resp = client_healthy.get("/health/dependencies", headers=AUTH_HEADERS)
        assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text}"

    def test_dependencies_contains_required_keys(self, client_healthy: TestClient) -> None:
        """
        GIVEN all deps OK
        WHEN GET /health/dependencies is requested
        THEN response contains 'dependencies', 'overall_status', 'generated_at'.
        """
        resp = client_healthy.get("/health/dependencies", headers=AUTH_HEADERS)
        body = resp.json()
        for key in ("dependencies", "overall_status", "generated_at"):
            assert key in body, f"Missing key '{key}': {body}"

    def test_dependencies_list_has_four_entries(self, client_healthy: TestClient) -> None:
        """
        GIVEN healthy mock repo
        WHEN GET /health/dependencies is requested
        THEN dependencies list has 4 entries.
        """
        resp = client_healthy.get("/health/dependencies", headers=AUTH_HEADERS)
        body = resp.json()
        assert len(body["dependencies"]) == 4, f"Expected 4 dependencies: {body}"

    def test_dependencies_each_entry_has_required_fields(self, client_healthy: TestClient) -> None:
        """
        GIVEN healthy repo
        WHEN GET /health/dependencies is requested
        THEN each dependency entry has name, status, latency_ms, detail.
        """
        resp = client_healthy.get("/health/dependencies", headers=AUTH_HEADERS)
        body = resp.json()
        for dep in body["dependencies"]:
            for field in ("name", "status", "latency_ms", "detail"):
                assert field in dep, f"Missing field '{field}' in dep: {dep}"

    def test_dependencies_overall_status_ok_when_all_ok(self, client_healthy: TestClient) -> None:
        """
        GIVEN all deps OK
        WHEN GET /health/dependencies is requested
        THEN overall_status is 'OK'.
        """
        resp = client_healthy.get("/health/dependencies", headers=AUTH_HEADERS)
        body = resp.json()
        assert body["overall_status"] == "OK", f"Expected OK, got: {body['overall_status']}"

    def test_dependencies_overall_status_down_when_dep_is_down(self) -> None:
        """
        GIVEN 'database' set to DOWN via repo override
        WHEN GET /health/dependencies is requested
        THEN overall_status is 'DOWN'.

        FAILS: endpoint does not exist until GREEN.
        """
        from services.api.main import app
        from services.api.routes.observability import get_dependency_health_repository

        repo = MockDependencyHealthRepository()
        repo.set_dependency_status("database", DependencyStatus.DOWN, detail="timeout")
        app.dependency_overrides[get_dependency_health_repository] = lambda: repo
        tc = TestClient(app)
        try:
            resp = tc.get("/health/dependencies", headers=AUTH_HEADERS)
            body = resp.json()
            assert resp.status_code == 200
            assert body["overall_status"] == "DOWN", f"Expected DOWN, got: {body['overall_status']}"
        finally:
            app.dependency_overrides.clear()

    def test_dependencies_degraded_dep_detail_is_in_response(self) -> None:
        """
        GIVEN 'queues' set to DEGRADED with detail='high latency'
        WHEN GET /health/dependencies is requested
        THEN the queues entry in the response has the non-empty detail string.
        """
        from services.api.main import app
        from services.api.routes.observability import get_dependency_health_repository

        repo = MockDependencyHealthRepository()
        repo.set_dependency_status("queues", DependencyStatus.DEGRADED, detail="high latency")
        app.dependency_overrides[get_dependency_health_repository] = lambda: repo
        tc = TestClient(app)
        try:
            resp = tc.get("/health/dependencies", headers=AUTH_HEADERS)
            body = resp.json()
            queues_entry = next((d for d in body["dependencies"] if d["name"] == "queues"), None)
            assert queues_entry is not None, f"queues dep missing: {body}"
            assert queues_entry["detail"] == "high latency"
        finally:
            app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# GET /health/diagnostics endpoint tests
# ---------------------------------------------------------------------------


class TestDiagnosticsEndpoint:
    """
    Unit tests for GET /health/diagnostics.

    The endpoint must:
    - Return 200 with queue_contention_count, feed_health_count,
      parity_critical_count, certification_blocked_count, generated_at.
    - Reflect values from the injected DiagnosticsRepository.
    - Return all zeros for a clean (empty) system.

    FAILS: services/api/routes/observability.py does not exist until GREEN (S4).
    """

    @pytest.fixture
    def diagnostics_repo_clean(self) -> MockDiagnosticsRepository:
        """All counts 0 (clean system)."""
        return MockDiagnosticsRepository()

    @pytest.fixture
    def client_clean(self, diagnostics_repo_clean: MockDiagnosticsRepository) -> TestClient:
        from services.api.main import app
        from services.api.routes.observability import get_diagnostics_repository

        app.dependency_overrides[get_diagnostics_repository] = lambda: diagnostics_repo_clean
        tc = TestClient(app)
        yield tc
        app.dependency_overrides.clear()

    def test_diagnostics_returns_200(self, client_clean: TestClient) -> None:
        """
        GIVEN a clean diagnostics repo
        WHEN GET /health/diagnostics is requested
        THEN 200 is returned.

        FAILS: endpoint does not exist until GREEN.
        """
        resp = client_clean.get("/health/diagnostics", headers=AUTH_HEADERS)
        assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text}"

    def test_diagnostics_contains_required_keys(self, client_clean: TestClient) -> None:
        """
        GIVEN a clean diagnostics repo
        WHEN GET /health/diagnostics is requested
        THEN response contains all four count fields and generated_at.
        """
        resp = client_clean.get("/health/diagnostics", headers=AUTH_HEADERS)
        body = resp.json()
        for key in (
            "queue_contention_count",
            "feed_health_count",
            "parity_critical_count",
            "certification_blocked_count",
            "generated_at",
        ):
            assert key in body, f"Missing key '{key}': {body}"

    def test_diagnostics_all_zeros_for_clean_system(self, client_clean: TestClient) -> None:
        """
        GIVEN no events in the diagnostics repo
        WHEN GET /health/diagnostics is requested
        THEN all four count fields are 0.
        """
        resp = client_clean.get("/health/diagnostics", headers=AUTH_HEADERS)
        body = resp.json()
        assert body["queue_contention_count"] == 0
        assert body["feed_health_count"] == 0
        assert body["parity_critical_count"] == 0
        assert body["certification_blocked_count"] == 0

    def test_diagnostics_reflects_injected_counts(self) -> None:
        """
        GIVEN set_snapshot(parity_critical_count=3, feed_health_count=7) is called
        WHEN GET /health/diagnostics is requested
        THEN response reflects those counts.

        FAILS: endpoint does not exist until GREEN.
        """
        from services.api.main import app
        from services.api.routes.observability import get_diagnostics_repository

        repo = MockDiagnosticsRepository()
        repo.set_snapshot(parity_critical_count=3, feed_health_count=7)
        app.dependency_overrides[get_diagnostics_repository] = lambda: repo
        tc = TestClient(app)
        try:
            resp = tc.get("/health/diagnostics", headers=AUTH_HEADERS)
            body = resp.json()
            assert resp.status_code == 200
            assert body["parity_critical_count"] == 3
            assert body["feed_health_count"] == 7
        finally:
            app.dependency_overrides.clear()

    def test_diagnostics_certification_blocked_count_reflects_value(self) -> None:
        """
        GIVEN set_snapshot(certification_blocked_count=2) is called
        WHEN GET /health/diagnostics is requested
        THEN certification_blocked_count is 2.
        """
        from services.api.main import app
        from services.api.routes.observability import get_diagnostics_repository

        repo = MockDiagnosticsRepository()
        repo.set_snapshot(certification_blocked_count=2)
        app.dependency_overrides[get_diagnostics_repository] = lambda: repo
        tc = TestClient(app)
        try:
            resp = tc.get("/health/diagnostics", headers=AUTH_HEADERS)
            body = resp.json()
            assert body["certification_blocked_count"] == 2
        finally:
            app.dependency_overrides.clear()
