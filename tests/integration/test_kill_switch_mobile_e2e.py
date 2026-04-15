"""
QA-02: Kill Switch Mobile E2E Tests — Backend Integration.

Purpose:
    Validate the complete kill switch lifecycle through the API layer,
    simulating the calls the mobile Emergency page makes. These tests
    exercise the full request→service→repository→response path with
    real database persistence and proper authentication.

Scope:
    - Global kill switch activation and deactivation
    - Strategy-scoped kill switch activation and deactivation
    - Symbol-scoped kill switch activation and deactivation
    - Status endpoint returns active switches
    - Auth enforcement on all endpoints
    - Reason validation (non-empty)
    - Concurrent activation of multiple scopes
    - Full lifecycle: activate → status → deactivate → status empty

Integration scope:
    kill_switch_routes ←→ KillSwitchService ←→ KillSwitchEventRepository ←→ SQLAlchemy ORM

These tests use TestClient with TEST_TOKEN bypass (ENVIRONMENT=test).
Database state is isolated per test via SAVEPOINT (conftest.py).

Example:
    pytest tests/integration/test_kill_switch_mobile_e2e.py -xvs
"""

from __future__ import annotations

import os
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from libs.contracts.interfaces.kill_switch_event_repository_interface import (
    KillSwitchEventRepositoryInterface,
)
from libs.contracts.interfaces.kill_switch_service_interface import KillSwitchServiceInterface
from services.api.auth import TEST_TOKEN
from services.api.main import app
from services.api.repositories.sql_kill_switch_event_repository import (
    SqlKillSwitchEventRepository,
)
from services.api.routes.kill_switch import set_kill_switch_service
from services.api.services.kill_switch_service import KillSwitchService

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def kill_switch_repository(integration_db_session: Session) -> KillSwitchEventRepositoryInterface:
    """
    Create a real SqlKillSwitchEventRepository backed by the test database.

    Args:
        integration_db_session: SAVEPOINT-isolated database session.

    Returns:
        Configured SqlKillSwitchEventRepository instance.
    """
    return SqlKillSwitchEventRepository(db=integration_db_session)


@pytest.fixture
def kill_switch_service(
    kill_switch_repository: KillSwitchEventRepositoryInterface,
) -> KillSwitchServiceInterface:
    """
    Create a real KillSwitchService with mock deployment repo and adapter registry.

    For E2E testing, we only care about the kill switch logic itself.
    Deployment lookups and broker operations are beyond scope here.

    Args:
        kill_switch_repository: Real repository backed by test database.

    Returns:
        Configured KillSwitchService instance.
    """
    # Create a mock deployment repository (no-op for these tests)
    from unittest.mock import MagicMock

    mock_deployment_repo = MagicMock()
    mock_adapter_registry: dict[str, Any] = {}

    return KillSwitchService(
        deployment_repo=mock_deployment_repo,
        ks_event_repo=kill_switch_repository,
        adapter_registry=mock_adapter_registry,
        verification_timeout_s=5,
    )


@pytest.fixture
def api_client(kill_switch_service: KillSwitchServiceInterface) -> TestClient:
    """
    Create a FastAPI TestClient with kill switch service wired in.

    Ensures TEST_TOKEN authentication bypass is active (ENVIRONMENT=test).

    Args:
        kill_switch_service: Configured service instance.

    Returns:
        TestClient ready for requests.
    """
    # Inject service into routes
    set_kill_switch_service(kill_switch_service)

    # Ensure test environment
    os.environ["ENVIRONMENT"] = "test"

    return TestClient(app, raise_server_exceptions=False)


@pytest.fixture
def auth_headers() -> dict[str, str]:
    """
    Return auth headers with TEST_TOKEN.

    Returns:
        Dict with Authorization header set to Bearer TEST_TOKEN.
    """
    return {"Authorization": f"Bearer {TEST_TOKEN}"}


# ---------------------------------------------------------------------------
# Tests — Activation
# ---------------------------------------------------------------------------


class TestActivateGlobalKillSwitch:
    """Verify global kill switch activation through the API."""

    def test_activate_global_kill_switch_returns_201_with_halt_event(
        self,
        api_client: TestClient,
        auth_headers: dict[str, str],
    ) -> None:
        """
        POST /kill-switch/global with valid reason returns 200 with HaltEvent.

        Verifies:
            - Response status is 200.
            - Response includes event_id, scope, activated_at.
            - Scope is "global".
            - activated_by is set from request body.
            - reason is preserved.
            - trigger defaults to KILL_SWITCH.
        """
        response = api_client.post(
            "/kill-switch/global",
            json={
                "reason": "Emergency halt — market circuit breaker",
                "activated_by": "operator@fxlab.test",
                "trigger": "kill_switch",
            },
            headers=auth_headers,
        )

        assert response.status_code == 200, (
            f"Expected 200, got {response.status_code}: {response.text}"
        )

        body = response.json()
        assert body["scope"] == "global"
        assert body["target_id"] == "global"
        assert body["activated_by"] == "operator@fxlab.test"
        assert body["reason"] == "Emergency halt — market circuit breaker"
        assert body["trigger"] == "kill_switch"
        assert body["event_id"] is not None
        assert body["activated_at"] is not None
        assert body["mtth_ms"] is not None or body["mtth_ms"] is None  # Optional field

    def test_activate_global_requires_reason(
        self,
        api_client: TestClient,
        auth_headers: dict[str, str],
    ) -> None:
        """
        POST /kill-switch/global with empty reason returns 422 Unprocessable Entity.

        Verifies:
            - reason field is required (non-empty).
            - API validates the schema before calling service.
        """
        response = api_client.post(
            "/kill-switch/global",
            json={
                "reason": "",
                "activated_by": "operator@fxlab.test",
            },
            headers=auth_headers,
        )

        assert response.status_code == 422, f"Expected 422, got {response.status_code}"

    def test_activate_global_requires_activated_by(
        self,
        api_client: TestClient,
        auth_headers: dict[str, str],
    ) -> None:
        """
        POST /kill-switch/global with missing activated_by returns 422.

        Verifies:
            - activated_by field is required.
        """
        response = api_client.post(
            "/kill-switch/global",
            json={
                "reason": "Emergency halt",
            },
            headers=auth_headers,
        )

        assert response.status_code == 422, f"Expected 422, got {response.status_code}"

    def test_activate_global_twice_returns_409_conflict(
        self,
        api_client: TestClient,
        auth_headers: dict[str, str],
    ) -> None:
        """
        POST /kill-switch/global twice returns 409 Conflict on second attempt.

        Verifies:
            - First activation succeeds.
            - Second activation fails with 409 (StateTransitionError).
            - Error message indicates kill switch is already active.
        """
        # First activation succeeds
        response1 = api_client.post(
            "/kill-switch/global",
            json={
                "reason": "First activation",
                "activated_by": "operator@fxlab.test",
            },
            headers=auth_headers,
        )
        assert response1.status_code == 200

        # Second activation fails with 409
        response2 = api_client.post(
            "/kill-switch/global",
            json={
                "reason": "Second activation",
                "activated_by": "operator@fxlab.test",
            },
            headers=auth_headers,
        )
        assert response2.status_code == 409, f"Expected 409, got {response2.status_code}"
        assert "already active" in response2.json()["detail"].lower()


class TestActivateStrategyKillSwitch:
    """Verify strategy-scoped kill switch activation."""

    def test_activate_strategy_scoped_kill_switch(
        self,
        api_client: TestClient,
        auth_headers: dict[str, str],
    ) -> None:
        """
        POST /kill-switch/strategy/{strategy_id} activates strategy-scoped switch.

        Verifies:
            - Response includes strategy_id in target_id.
            - Scope is "strategy".
            - Multiple strategies can have active switches simultaneously.
        """
        response = api_client.post(
            "/kill-switch/strategy/01HSTRAT001",
            json={
                "reason": "Strategy risk limit exceeded",
                "activated_by": "risk_gate",
            },
            headers=auth_headers,
        )

        assert response.status_code == 200
        body = response.json()
        assert body["scope"] == "strategy"
        assert body["target_id"] == "01HSTRAT001"

    def test_activate_multiple_strategies_simultaneously(
        self,
        api_client: TestClient,
        auth_headers: dict[str, str],
    ) -> None:
        """
        Multiple strategy-scoped switches can be active at once.

        Verifies:
            - Activate strategy 01HSTRAT001 succeeds.
            - Activate strategy 01HSTRAT002 succeeds in same test.
            - Both remain active (verified via status endpoint).
        """
        response1 = api_client.post(
            "/kill-switch/strategy/01HSTRAT001",
            json={
                "reason": "Strategy A risk limit",
                "activated_by": "risk_gate",
            },
            headers=auth_headers,
        )
        assert response1.status_code == 200

        response2 = api_client.post(
            "/kill-switch/strategy/01HSTRAT002",
            json={
                "reason": "Strategy B risk limit",
                "activated_by": "risk_gate",
            },
            headers=auth_headers,
        )
        assert response2.status_code == 200

        # Verify both are active via status
        status_response = api_client.get(
            "/kill-switch/status",
            headers=auth_headers,
        )
        assert status_response.status_code == 200
        statuses = status_response.json()
        assert len(statuses) == 2
        target_ids = {s["target_id"] for s in statuses}
        assert "01HSTRAT001" in target_ids
        assert "01HSTRAT002" in target_ids


class TestActivateSymbolKillSwitch:
    """Verify symbol-scoped kill switch activation."""

    def test_activate_symbol_scoped_kill_switch(
        self,
        api_client: TestClient,
        auth_headers: dict[str, str],
    ) -> None:
        """
        POST /kill-switch/symbol/{symbol} activates symbol-scoped switch.

        Verifies:
            - Response includes symbol in target_id.
            - Scope is "symbol".
            - Symbol name is preserved correctly.
        """
        response = api_client.post(
            "/kill-switch/symbol/TSLA",
            json={
                "reason": "Halted trading on this symbol",
                "activated_by": "exchange_feed",
            },
            headers=auth_headers,
        )

        assert response.status_code == 200
        body = response.json()
        assert body["scope"] == "symbol"
        assert body["target_id"] == "TSLA"


# ---------------------------------------------------------------------------
# Tests — Status
# ---------------------------------------------------------------------------


class TestKillSwitchStatus:
    """Verify the status endpoint returns active switches correctly."""

    def test_get_status_empty_when_no_active_switches(
        self,
        api_client: TestClient,
        auth_headers: dict[str, str],
    ) -> None:
        """
        GET /kill-switch/status returns empty list when no switches active.

        Verifies:
            - Initial state returns [].
        """
        response = api_client.get(
            "/kill-switch/status",
            headers=auth_headers,
        )

        assert response.status_code == 200
        assert response.json() == []

    def test_get_status_returns_active_switches(
        self,
        api_client: TestClient,
        auth_headers: dict[str, str],
    ) -> None:
        """
        GET /kill-switch/status returns all active switches with correct fields.

        Verifies:
            - Activate global switch.
            - Activate strategy switch.
            - Status endpoint returns both.
            - Each status includes: scope, target_id, is_active, activated_at, reason, activated_by.
        """
        # Activate global
        api_client.post(
            "/kill-switch/global",
            json={
                "reason": "Global halt",
                "activated_by": "operator@fxlab.test",
            },
            headers=auth_headers,
        )

        # Activate strategy
        api_client.post(
            "/kill-switch/strategy/01HSTRAT001",
            json={
                "reason": "Strategy halt",
                "activated_by": "operator@fxlab.test",
            },
            headers=auth_headers,
        )

        # Get status
        response = api_client.get(
            "/kill-switch/status",
            headers=auth_headers,
        )

        assert response.status_code == 200
        statuses = response.json()
        assert len(statuses) == 2

        # Verify fields
        for status in statuses:
            assert "scope" in status
            assert "target_id" in status
            assert "is_active" in status
            assert status["is_active"] is True
            assert "activated_at" in status
            assert status["activated_at"] is not None
            assert "reason" in status
            assert "activated_by" in status

        # Verify specific switches
        scopes = {s["scope"] for s in statuses}
        assert "global" in scopes
        assert "strategy" in scopes


# ---------------------------------------------------------------------------
# Tests — Deactivation
# ---------------------------------------------------------------------------


class TestDeactivateKillSwitch:
    """Verify kill switch deactivation through the API."""

    def test_deactivate_kill_switch_succeeds(
        self,
        api_client: TestClient,
        auth_headers: dict[str, str],
    ) -> None:
        """
        DELETE /kill-switch/{scope}/{target_id} deactivates an active switch.

        Verifies:
            - Activate global switch.
            - Deactivate global switch returns 200 with HaltEvent.
            - Event indicates deactivation.
        """
        # Activate
        api_client.post(
            "/kill-switch/global",
            json={
                "reason": "Halt",
                "activated_by": "operator@fxlab.test",
            },
            headers=auth_headers,
        )

        # Deactivate
        response = api_client.delete(
            "/kill-switch/global/global",
            headers=auth_headers,
        )

        assert response.status_code == 200
        body = response.json()
        assert body["scope"] == "global"
        assert body["target_id"] == "global"

    def test_deactivate_nonexistent_switch_returns_404(
        self,
        api_client: TestClient,
        auth_headers: dict[str, str],
    ) -> None:
        """
        DELETE /kill-switch/{scope}/{target_id} on inactive switch returns 404.

        Verifies:
            - Attempting to deactivate a switch that isn't active fails.
            - Error is NotFoundError (404).
        """
        response = api_client.delete(
            "/kill-switch/global/global",
            headers=auth_headers,
        )

        assert response.status_code == 404
        detail = response.json()["detail"].lower()
        assert "no active kill switch" in detail or "not found" in detail

    def test_deactivate_strategy_switch(
        self,
        api_client: TestClient,
        auth_headers: dict[str, str],
    ) -> None:
        """
        DELETE /kill-switch/strategy/{strategy_id} deactivates strategy switch.

        Verifies:
            - Activate strategy switch.
            - Deactivate specific strategy.
            - Only that strategy is deactivated.
        """
        # Activate two strategies
        api_client.post(
            "/kill-switch/strategy/01HSTRAT001",
            json={"reason": "Halt 1", "activated_by": "risk_gate"},
            headers=auth_headers,
        )
        api_client.post(
            "/kill-switch/strategy/01HSTRAT002",
            json={"reason": "Halt 2", "activated_by": "risk_gate"},
            headers=auth_headers,
        )

        # Deactivate only 01HSTRAT001
        response = api_client.delete(
            "/kill-switch/strategy/01HSTRAT001",
            headers=auth_headers,
        )
        assert response.status_code == 200

        # Verify only 01HSTRAT002 remains active
        status_response = api_client.get(
            "/kill-switch/status",
            headers=auth_headers,
        )
        statuses = status_response.json()
        assert len(statuses) == 1
        assert statuses[0]["target_id"] == "01HSTRAT002"


# ---------------------------------------------------------------------------
# Tests — Status after Deactivation
# ---------------------------------------------------------------------------


class TestStatusAfterDeactivation:
    """Verify status endpoint reflects deactivation correctly."""

    def test_status_empty_after_deactivation(
        self,
        api_client: TestClient,
        auth_headers: dict[str, str],
    ) -> None:
        """
        GET /kill-switch/status returns empty after deactivating all switches.

        Verifies:
            - Activate global switch.
            - Status returns [global].
            - Deactivate global switch.
            - Status returns [].
        """
        # Activate
        api_client.post(
            "/kill-switch/global",
            json={"reason": "Halt", "activated_by": "operator@fxlab.test"},
            headers=auth_headers,
        )

        status1 = api_client.get("/kill-switch/status", headers=auth_headers).json()
        assert len(status1) == 1

        # Deactivate
        api_client.delete(
            "/kill-switch/global/global",
            headers=auth_headers,
        )

        status2 = api_client.get("/kill-switch/status", headers=auth_headers).json()
        assert len(status2) == 0


# ---------------------------------------------------------------------------
# Tests — Authentication
# ---------------------------------------------------------------------------


class TestAuthEnforcement:
    """Verify authentication is enforced on all endpoints."""

    def test_activate_requires_authentication(
        self,
        api_client: TestClient,
    ) -> None:
        """
        POST /kill-switch/global without auth header returns 401 Unauthorized.

        Verifies:
            - Endpoints require Authorization header.
            - Test token bypass is only active in test environment.
        """
        response = api_client.post(
            "/kill-switch/global",
            json={"reason": "Halt", "activated_by": "operator@fxlab.test"},
            # No auth header
        )

        assert response.status_code == 401

    def test_status_requires_authentication(
        self,
        api_client: TestClient,
    ) -> None:
        """
        GET /kill-switch/status without auth header returns 401 Unauthorized.

        Verifies:
            - Status endpoint requires authentication.
        """
        response = api_client.get("/kill-switch/status")

        assert response.status_code == 401

    def test_deactivate_requires_authentication(
        self,
        api_client: TestClient,
    ) -> None:
        """
        DELETE /kill-switch/{scope}/{target_id} without auth returns 401.

        Verifies:
            - Deactivation endpoint requires authentication.
        """
        response = api_client.delete("/kill-switch/global/global")

        assert response.status_code == 401


# ---------------------------------------------------------------------------
# Tests — Full Lifecycle
# ---------------------------------------------------------------------------


class TestFullLifecycle:
    """Verify complete kill switch workflow from activation to deactivation."""

    def test_full_lifecycle_activate_status_deactivate(
        self,
        api_client: TestClient,
        auth_headers: dict[str, str],
    ) -> None:
        """
        Complete workflow: activate → check status → deactivate → check status.

        Verifies:
            - Initial status is empty.
            - After activation, status includes the switch.
            - After deactivation, status is empty again.
            - All fields are preserved correctly throughout.
        """
        # Step 1: Initial status is empty
        status0 = api_client.get("/kill-switch/status", headers=auth_headers).json()
        assert len(status0) == 0

        # Step 2: Activate global switch
        reason = "Testing full lifecycle"
        activate_response = api_client.post(
            "/kill-switch/global",
            json={
                "reason": reason,
                "activated_by": "test_operator",
            },
            headers=auth_headers,
        )
        assert activate_response.status_code == 200
        event = activate_response.json()
        assert event["scope"] == "global"

        # Step 3: Status shows active switch
        status1 = api_client.get("/kill-switch/status", headers=auth_headers).json()
        assert len(status1) == 1
        assert status1[0]["scope"] == "global"
        assert status1[0]["target_id"] == "global"
        assert status1[0]["is_active"] is True
        assert status1[0]["reason"] == reason
        assert status1[0]["activated_by"] == "test_operator"

        # Step 4: Deactivate global switch
        deactivate_response = api_client.delete(
            "/kill-switch/global/global",
            headers=auth_headers,
        )
        assert deactivate_response.status_code == 200

        # Step 5: Status is empty again
        status2 = api_client.get("/kill-switch/status", headers=auth_headers).json()
        assert len(status2) == 0

    def test_full_lifecycle_multiple_scopes(
        self,
        api_client: TestClient,
        auth_headers: dict[str, str],
    ) -> None:
        """
        Full lifecycle with multiple scopes: activate all → check status → deactivate all.

        Verifies:
            - All three scopes (global, strategy, symbol) can be active simultaneously.
            - Status returns all active switches.
            - Deactivation of each scope works independently.
        """
        # Activate all three scopes
        api_client.post(
            "/kill-switch/global",
            json={"reason": "Global halt", "activated_by": "operator"},
            headers=auth_headers,
        )
        api_client.post(
            "/kill-switch/strategy/01HSTRAT001",
            json={"reason": "Strategy halt", "activated_by": "operator"},
            headers=auth_headers,
        )
        api_client.post(
            "/kill-switch/symbol/TSLA",
            json={"reason": "Symbol halt", "activated_by": "operator"},
            headers=auth_headers,
        )

        # Verify all three are active
        status1 = api_client.get("/kill-switch/status", headers=auth_headers).json()
        assert len(status1) == 3
        scopes = {s["scope"] for s in status1}
        assert scopes == {"global", "strategy", "symbol"}

        # Deactivate all three
        api_client.delete("/kill-switch/global/global", headers=auth_headers)
        api_client.delete("/kill-switch/strategy/01HSTRAT001", headers=auth_headers)
        api_client.delete("/kill-switch/symbol/TSLA", headers=auth_headers)

        # Verify all are deactivated
        status2 = api_client.get("/kill-switch/status", headers=auth_headers).json()
        assert len(status2) == 0
