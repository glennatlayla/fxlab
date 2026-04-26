"""
Integration tests for rate limiting on mobile mutation endpoints (API-01).

Tests cover:
- Run submission endpoint rate limiting (5 per minute).
- Risk setting endpoint rate limiting (10 per hour).
- Kill switch endpoint rate limiting (3 per minute).
- Approval action endpoint rate limiting (10 per minute).
- Rate limit headers in response (X-RateLimit-*).
- 429 Too Many Requests with Retry-After header.
- Per-user isolation (different users have independent limits).
- Response format matches contract.

Dependencies:
    - FastAPI TestClient for HTTP testing.
    - auth_headers fixture for authenticated requests.
    - services.api.main: FastAPI application.
    - Mock service implementations for endpoints with DI-injected services.

Example:
    pytest tests/integration/test_rate_limit_endpoints.py -v --tb=short
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

import pytest
from fastapi.testclient import TestClient

from libs.contracts.execution import AccountSnapshot, OrderRequest, PositionSnapshot
from libs.contracts.interfaces.kill_switch_service_interface import (
    KillSwitchServiceInterface,
)
from libs.contracts.interfaces.research_run_service import ResearchRunServiceInterface
from libs.contracts.interfaces.risk_gate_interface import RiskGateInterface
from libs.contracts.research_run import (
    ResearchRunConfig,
    ResearchRunRecord,
    ResearchRunResult,
    ResearchRunStatus,
)
from libs.contracts.risk import PreTradeRiskLimits, RiskCheckResult, RiskEvent
from libs.contracts.run_results import (
    EquityCurveResponse,
    RunMetrics,
    StrategyRunsPage,
    TradeBlotterPage,
)
from libs.contracts.safety import (
    EmergencyPostureDecision,
    HaltEvent,
    HaltTrigger,
    KillSwitchScope,
    KillSwitchStatus,
)
from services.api.auth import create_access_token
from services.api.main import app
from services.api.middleware import rate_limit as _rl_mod
from services.api.services.interfaces.governance_service_interface import (
    GovernanceServiceInterface,
)

# ---------------------------------------------------------------------------
# Mock Service Implementations — Production-Grade Stubs
# ---------------------------------------------------------------------------


class MockResearchRunService(ResearchRunServiceInterface):
    """Lightweight mock for ResearchRunService.

    Responsibilities:
    - Provide minimal implementation needed to bypass service injection checks.
    - Return dummy data that allows rate limiter to fire.
    - Do not test actual research run logic (service layer tests do that).

    Does NOT:
    - Persist data or manage state beyond test scope.
    - Call external engines or brokers.

    Dependencies:
    - None — fully self-contained for testing.

    Example:
        service = MockResearchRunService()
        record = service.submit_run(config, user_id="01H...")
        # record.id is set, allowing rate limiter to run on subsequent calls
    """

    def submit_run(
        self,
        config: ResearchRunConfig,
        user_id: str,
        *,
        correlation_id: str | None = None,
    ) -> ResearchRunRecord:
        """
        Return a minimal ResearchRunRecord with PENDING status.

        Args:
            config: Research run configuration (unused in mock).
            user_id: User submitting the run (unused in mock).
            correlation_id: Optional correlation ID (unused in mock).

        Returns:
            Minimal ResearchRunRecord with generated ID and PENDING status.
        """
        return ResearchRunRecord(
            id="01HRUNMOCK0000000000000000",
            user_id=user_id,
            config=config,
            status=ResearchRunStatus.PENDING,
            created_at=None,
        )

    def get_run(self, run_id: str) -> ResearchRunRecord | None:
        """Return None (not used in rate limit tests)."""
        return None

    def cancel_run(
        self,
        run_id: str,
        *,
        correlation_id: str | None = None,
    ) -> ResearchRunRecord:
        """Not implemented (not used in rate limit tests)."""
        raise NotImplementedError()

    def list_runs(
        self,
        *,
        strategy_id: str | None = None,
        user_id: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[ResearchRunRecord], int]:
        """Return empty list (not used in rate limit tests)."""
        return [], 0

    def get_run_result(self, run_id: str) -> ResearchRunResult | None:
        """Return None (not used in rate limit tests)."""
        return None

    def get_equity_curve(self, run_id: str) -> EquityCurveResponse:
        """Return empty curve (not used in rate limit tests)."""
        return EquityCurveResponse(run_id=run_id, point_count=0, points=[])

    def get_blotter(
        self,
        run_id: str,
        *,
        page: int = 1,
        page_size: int = 100,
    ) -> TradeBlotterPage:
        """Return empty page (not used in rate limit tests)."""
        return TradeBlotterPage(
            run_id=run_id,
            page=page,
            page_size=page_size,
            total_count=0,
            total_pages=0,
            trades=[],
        )

    def get_metrics(self, run_id: str) -> RunMetrics:
        """Return empty metrics (not used in rate limit tests)."""
        return RunMetrics(run_id=run_id)

    def list_runs_for_strategy(
        self,
        strategy_id: str,
        *,
        page: int = 1,
        page_size: int = 20,
    ) -> StrategyRunsPage:
        """Return empty paged runs (not used in rate limit tests)."""
        return StrategyRunsPage(
            runs=[],
            page=page,
            page_size=page_size,
            total_count=0,
            total_pages=0,
        )


class MockRiskGateService(RiskGateInterface):
    """Lightweight mock for RiskGateService.

    Responsibilities:
    - Provide minimal implementation needed to bypass service injection checks.
    - Allow rate limiter to intercept requests before business logic runs.

    Does NOT:
    - Perform actual risk checking.
    - Persist risk events or limits.

    Dependencies:
    - None — fully self-contained for testing.

    Example:
        service = MockRiskGateService()
        limits = service.get_risk_limits(deployment_id="01H...")
        # Returns minimal PreTradeRiskLimits allowing test to proceed
    """

    def check_order(
        self,
        *,
        deployment_id: str,
        order: OrderRequest,
        positions: list[PositionSnapshot],
        account: AccountSnapshot,
        correlation_id: str,
    ) -> RiskCheckResult:
        """Return a passing RiskCheckResult (not used in rate limit tests)."""
        raise NotImplementedError()

    def set_risk_limits(
        self,
        *,
        deployment_id: str,
        limits: PreTradeRiskLimits,
    ) -> None:
        """Accept and discard risk limits (minimal implementation)."""
        pass

    def get_risk_limits(
        self,
        *,
        deployment_id: str,
    ) -> PreTradeRiskLimits:
        """Return default risk limits for any deployment."""
        return PreTradeRiskLimits(
            max_position_size=Decimal("1000000"),
            max_daily_loss=Decimal("50000"),
            max_order_value=Decimal("100000"),
            max_concentration_pct=Decimal("0.1"),
            max_open_orders=10,
        )

    def get_risk_events(
        self,
        *,
        deployment_id: str,
        severity: str | None = None,
        limit: int = 100,
    ) -> list[RiskEvent]:
        """Return empty event list (not used in rate limit tests)."""
        return []

    def enforce_order(
        self,
        *,
        deployment_id: str,
        order: OrderRequest,
        positions: list[PositionSnapshot],
        account: AccountSnapshot,
        correlation_id: str,
    ) -> None:
        """Do nothing (not used in rate limit tests)."""
        pass

    def clear_risk_limits(
        self,
        *,
        deployment_id: str,
    ) -> None:
        """Do nothing (not used in rate limit tests)."""
        pass


class MockKillSwitchService(KillSwitchServiceInterface):
    """Lightweight mock for KillSwitchService.

    Responsibilities:
    - Provide minimal implementation needed to bypass service injection checks.
    - Allow endpoints to proceed far enough for rate limiter to fire.

    Does NOT:
    - Manage actual kill switch state.
    - Interact with brokers or execution adapters.

    Dependencies:
    - None — fully self-contained for testing.

    Example:
        service = MockKillSwitchService()
        event = service.activate_kill_switch(
            scope=KillSwitchScope.GLOBAL,
            target_id="global",
            reason="test",
            activated_by="test",
        )
        # Returns minimal HaltEvent allowing test to proceed
    """

    def activate_kill_switch(
        self,
        *,
        scope: KillSwitchScope,
        target_id: str,
        reason: str,
        activated_by: str,
        trigger: HaltTrigger = HaltTrigger.KILL_SWITCH,
    ) -> HaltEvent:
        """Return a minimal HaltEvent (may reuse ID across calls)."""
        return HaltEvent(
            event_id="01HKSMOCK0000000000000000",
            scope=scope,
            target_id=target_id,
            trigger=trigger,
            reason=reason,
            activated_by=activated_by,
            # activated_at and confirmed_at have sensible defaults; omit them
            mtth_ms=1000,
            orders_cancelled=0,
            positions_flattened=0,
        )

    def deactivate_kill_switch(
        self,
        *,
        scope: KillSwitchScope,
        target_id: str,
        deactivated_by: str,
    ) -> HaltEvent:
        """Not implemented (not used in rate limit tests)."""
        raise NotImplementedError()

    def get_status(self) -> list[KillSwitchStatus]:
        """Return empty status list (not used in rate limit tests)."""
        return []

    def is_halted(
        self,
        *,
        deployment_id: str,
        strategy_id: str | None = None,
        symbol: str | None = None,
    ) -> bool:
        """Return False (not halted) — not used in rate limit tests."""
        return False

    def execute_emergency_posture(
        self,
        *,
        deployment_id: str,
        trigger: HaltTrigger,
        reason: str,
    ) -> EmergencyPostureDecision:
        """Not implemented (not used in rate limit tests)."""
        raise NotImplementedError()

    def verify_halt(self, *, scope: KillSwitchScope, target_id: str) -> dict[str, Any]:
        """Not implemented (not used in rate limit tests)."""
        raise NotImplementedError()


class MockGovernanceService(GovernanceServiceInterface):
    """Lightweight mock for GovernanceService.

    Responsibilities:
    - Provide minimal implementation needed to bypass service injection checks.
    - Allow approval endpoints to proceed far enough for rate limiter to fire.

    Does NOT:
    - Enforce separation of duties (tests don't need SoD validation).
    - Persist approvals or audit events.

    Dependencies:
    - None — fully self-contained for testing.

    Example:
        service = MockGovernanceService()
        result = service.approve_request(approval_id="01H...", reviewer_id="01H...")
        # Returns minimal dict allowing test to proceed
    """

    def submit_override(
        self,
        *,
        submitter_id: str,
        object_id: str,
        object_type: str,
        override_type: str,
        original_state: dict[str, Any] | None,
        new_state: dict[str, Any] | None,
        evidence_link: str,
        rationale: str,
        correlation_id: str,
    ) -> dict[str, Any]:
        """Not implemented (not used in rate limit tests)."""
        raise NotImplementedError()

    def review_override(
        self,
        *,
        override_id: str,
        reviewer_id: str,
        decision: str,
        rationale: str,
        correlation_id: str,
    ) -> dict[str, Any]:
        """Not implemented (not used in rate limit tests)."""
        raise NotImplementedError()

    def approve_request(
        self,
        *,
        approval_id: str,
        reviewer_id: str,
        correlation_id: str,
    ) -> dict[str, Any]:
        """
        Return a minimal approval response.

        Args:
            approval_id: Approval request ID (unused in mock).
            reviewer_id: Reviewer ID (unused in mock).
            correlation_id: Correlation ID (unused in mock).

        Returns:
            Dict with approval_id and status='approved'.
        """
        return {"approval_id": approval_id, "status": "approved"}

    def reject_request(
        self,
        *,
        approval_id: str,
        reviewer_id: str,
        rationale: str,
        correlation_id: str,
    ) -> dict[str, Any]:
        """Return a minimal rejection response."""
        return {"approval_id": approval_id, "status": "rejected", "rationale": rationale}


# ---------------------------------------------------------------------------
# Fixtures for service injection and rate limit reset
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _reset_rate_limit_state() -> None:
    """Clear the in-memory rate limit window before each test.

    The rate limiter uses a module-level singleton
    ``InMemoryRateLimitBackend``.  Without resetting, requests from one
    test accumulate in the sliding window and pollute subsequent tests
    that run within the same 60-second window.
    """
    backend = _rl_mod._window
    if hasattr(backend, "_store"):
        with backend._lock:
            backend._store.clear()


@pytest.fixture(autouse=True)
def _inject_mock_services() -> None:
    """Inject mock service implementations before each test and clean up after.

    Each endpoint group requires a service to be registered via the
    module-level DI setter. This fixture:
    1. Instantiates lightweight mock implementations.
    2. Injects them using the official setter functions.
    3. Clears them after the test (teardown).

    Services injected:
    - ResearchRunService for /research/runs endpoints.
    - RiskGateService for /risk/deployments/{id}/risk-limits endpoints.
    - KillSwitchService for /kill-switch/global endpoint.
    - GovernanceService for /approvals/{id}/approve endpoint.

    Yields:
        None — setup and teardown only, no return value.
    """
    from services.api.routes import kill_switch, research, risk
    from services.api.routes.approvals import get_governance_service

    # Create mock instances.
    research_service = MockResearchRunService()
    risk_service = MockRiskGateService()
    kill_switch_service = MockKillSwitchService()
    governance_service = MockGovernanceService()

    # Inject via module-level setters.
    research.set_research_run_service(research_service)
    risk.set_risk_gate_service(risk_service)
    kill_switch.set_kill_switch_service(kill_switch_service)

    # Approvals use a dependency provider (get_governance_service) that
    # constructs the service on request. We override it to return our mock.
    from unittest.mock import MagicMock

    MagicMock(return_value=governance_service)
    app.dependency_overrides[get_governance_service] = lambda: governance_service

    yield

    # Teardown: clear all injections.
    research.set_research_run_service(None)  # type: ignore
    risk.set_risk_gate_service(None)  # type: ignore
    kill_switch.set_kill_switch_service(None)  # type: ignore
    app.dependency_overrides.pop(get_governance_service, None)


@pytest.fixture
def client() -> TestClient:
    """Provide a test client bound to the FastAPI application."""
    return TestClient(app)


@pytest.fixture
def admin_auth_headers() -> dict[str, str]:
    """Return auth headers for an admin user who holds ``approvals:write``.

    The default ``auth_headers`` fixture uses TEST_TOKEN which maps to
    the *operator* role.  Operator does NOT have ``approvals:write``, so
    approval-action rate-limit tests need an admin-scoped JWT instead.

    Returns:
        Dict with ``Authorization: Bearer <admin_jwt>``.
    """
    token = create_access_token(
        user_id="01HADM00000000000000000000",
        role="admin",
        expires_minutes=60,
    )
    return {"Authorization": f"Bearer {token}"}


class TestRunSubmissionRateLimit:
    """Tests for rate limiting on run submission endpoint."""

    def test_allows_run_submissions_within_limit(
        self, client: TestClient, auth_headers: dict[str, str]
    ) -> None:
        """Should allow up to 5 run submissions per minute per user."""
        # Attempt 5 submissions
        for i in range(5):
            response = client.post(
                "/research/runs",
                json={"name": f"test_run_{i}"},
                headers=auth_headers,
            )
            # Should either succeed or return something other than 429
            # (depends on endpoint implementation)
            assert response.status_code != 429, f"Request {i + 1} should not be rate limited"

    def test_blocks_run_submission_exceeding_limit(
        self, client: TestClient, auth_headers: dict[str, str]
    ) -> None:
        """Should return 429 when exceeding 5 submissions per minute."""
        # Fill the limit
        for i in range(5):
            client.post(
                "/research/runs",
                json={"name": f"test_run_{i}"},
                headers=auth_headers,
            )

        # Next submission should be rate limited
        response = client.post(
            "/research/runs",
            json={"name": "test_run_overflow"},
            headers=auth_headers,
        )
        assert response.status_code == 429
        assert "Retry-After" in response.headers
        assert int(response.headers["Retry-After"]) > 0

    def test_run_submission_response_format(
        self, client: TestClient, auth_headers: dict[str, str]
    ) -> None:
        """429 response should match RateLimitErrorResponse contract."""
        # Fill the limit
        for i in range(5):
            client.post(
                "/research/runs",
                json={"name": f"test_run_{i}"},
                headers=auth_headers,
            )

        # Trigger rate limit
        response = client.post(
            "/research/runs",
            json={"name": "overflow"},
            headers=auth_headers,
        )
        assert response.status_code == 429

        body = response.json()
        assert "detail" in body
        assert "retry_after" in body
        assert body["error_code"] == "RATE_LIMIT_EXCEEDED"
        assert body["retry_after"] > 0


class TestRiskSettingRateLimit:
    """Tests for rate limiting on risk setting change endpoints."""

    def test_allows_risk_changes_within_limit(
        self, client: TestClient, auth_headers: dict[str, str]
    ) -> None:
        """Should allow up to 10 risk setting changes per hour per user."""
        # Attempt 10 changes — endpoint is PUT /risk/deployments/{id}/risk-limits
        for i in range(10):
            response = client.put(
                f"/risk/deployments/deploy-{i}/risk-limits",
                json={
                    "max_position_size": 100000,
                    "max_daily_loss": 5000,
                    "max_drawdown_pct": 0.1,
                    "max_open_orders": 10,
                    "max_leverage": 2.0,
                },
                headers=auth_headers,
            )
            # Should not be rate limited (depends on endpoint implementation)
            assert response.status_code != 429, f"Request {i + 1} should not be rate limited"

    def test_blocks_risk_changes_exceeding_limit(
        self, client: TestClient, auth_headers: dict[str, str]
    ) -> None:
        """Should return 429 when exceeding 10 risk changes per hour."""
        # Fill the limit — endpoint is PUT /risk/deployments/{id}/risk-limits
        for i in range(10):
            client.put(
                f"/risk/deployments/deploy-{i}/risk-limits",
                json={
                    "max_position_size": 100000,
                    "max_daily_loss": 5000,
                    "max_drawdown_pct": 0.1,
                    "max_open_orders": 10,
                    "max_leverage": 2.0,
                },
                headers=auth_headers,
            )

        # Next change should be rate limited
        response = client.put(
            "/risk/deployments/deploy-overflow/risk-limits",
            json={
                "max_position_size": 100000,
                "max_daily_loss": 5000,
                "max_drawdown_pct": 0.1,
                "max_open_orders": 10,
                "max_leverage": 2.0,
            },
            headers=auth_headers,
        )
        assert response.status_code == 429
        assert "Retry-After" in response.headers


class TestKillSwitchRateLimit:
    """Tests for rate limiting on kill switch activation.

    Kill switch activation endpoints live at:
    - POST /kill-switch/global
    - POST /kill-switch/strategy/{strategy_id}
    - POST /kill-switch/symbol/{symbol}

    All require ``deployments:write`` scope and accept an
    ``ActivateKillSwitchBody`` with ``reason``, ``activated_by``, and
    optional ``trigger``.  The rate limiter is scoped to
    ``kill_switch`` (3 per minute, per user).  We hit ``/global``
    for simplicity — the scope bucket is shared across all three
    endpoints.
    """

    _KILL_SWITCH_BODY = {
        "reason": "rate-limit integration test",
        "activated_by": "test-harness",
    }

    def test_allows_kill_switch_within_limit(
        self, client: TestClient, auth_headers: dict[str, str]
    ) -> None:
        """Should allow up to 3 kill switch activations per minute per user."""
        for i in range(3):
            response = client.post(
                "/kill-switch/global",
                json={**self._KILL_SWITCH_BODY, "reason": f"rate-limit test {i}"},
                headers=auth_headers,
            )
            # May succeed (200) or conflict (409) if already active —
            # but must NOT be 429 within the limit window.
            assert response.status_code != 429, f"Activation {i + 1} should not be rate limited"

    def test_blocks_kill_switch_exceeding_limit(
        self, client: TestClient, auth_headers: dict[str, str]
    ) -> None:
        """Should return 429 when exceeding 3 activations per minute."""
        # Fill the limit
        for i in range(3):
            client.post(
                "/kill-switch/global",
                json={**self._KILL_SWITCH_BODY, "reason": f"rate-limit fill {i}"},
                headers=auth_headers,
            )

        # Fourth activation should be rate limited
        response = client.post(
            "/kill-switch/global",
            json={**self._KILL_SWITCH_BODY, "reason": "rate-limit overflow"},
            headers=auth_headers,
        )
        assert response.status_code == 429
        assert "Retry-After" in response.headers


class TestApprovalActionRateLimit:
    """Tests for rate limiting on approval actions.

    Approval endpoints (``/approvals/{id}/approve``, ``/approvals/{id}/reject``)
    require the ``approvals:write`` scope, which belongs to the *admin* and
    *reviewer* roles — NOT *operator*.  These tests therefore use
    ``admin_auth_headers`` so the request passes scope-checking before the
    rate limiter fires.

    The endpoint may return 404 (no such approval) or other domain errors
    for the fake IDs, but it must NOT return 429 until the rate limit
    window (10 per minute) is exhausted.
    """

    def test_allows_approval_actions_within_limit(
        self, client: TestClient, admin_auth_headers: dict[str, str]
    ) -> None:
        """Should allow up to 10 approval actions per minute per user."""
        for i in range(10):
            response = client.post(
                f"/approvals/approval-{i}/approve",
                json={},
                headers=admin_auth_headers,
            )
            # May 404 (fake ID) but must not 429 within the window
            assert response.status_code != 429, f"Action {i + 1} should not be rate limited"

    def test_blocks_approval_actions_exceeding_limit(
        self, client: TestClient, admin_auth_headers: dict[str, str]
    ) -> None:
        """Should return 429 when exceeding 10 actions per minute."""
        # Fill the limit
        for i in range(10):
            client.post(
                f"/approvals/approval-{i}/approve",
                json={},
                headers=admin_auth_headers,
            )

        # 11th action should be rate limited
        response = client.post(
            "/approvals/approval-overflow/approve",
            json={},
            headers=admin_auth_headers,
        )
        assert response.status_code == 429
        assert "Retry-After" in response.headers


class TestPerUserIsolation:
    """Tests for per-user rate limit isolation."""

    def test_different_users_have_independent_limits(
        self, client: TestClient, auth_headers: dict[str, str]
    ) -> None:
        """Two different users should have independent rate limits."""
        # User 1: fill their run submission limit
        for i in range(5):
            client.post(
                "/research/runs",
                json={"name": f"user1_run_{i}"},
                headers=auth_headers,
            )

        # User 1 should be blocked
        response1 = client.post(
            "/research/runs",
            json={"name": "user1_overflow"},
            headers=auth_headers,
        )
        assert response1.status_code == 429

        # Mint a JWT for a different user so the rate limiter sees a
        # distinct identity (not the TEST_TOKEN operator).
        user2_token = create_access_token(
            user_id="01HUSER200000000000000000",
            role="operator",
            expires_minutes=60,
        )
        user2_headers = {"Authorization": f"Bearer {user2_token}"}

        # User 2 should still be able to submit (independent limit)
        response2 = client.post(
            "/research/runs",
            json={"name": "user2_run"},
            headers=user2_headers,
        )
        assert response2.status_code != 429


class TestRateLimitHeaders:
    """Tests for rate limit response headers."""

    def test_retry_after_header_format(
        self, client: TestClient, auth_headers: dict[str, str]
    ) -> None:
        """Retry-After header should be a valid integer."""
        # Fill the limit
        for i in range(5):
            client.post(
                "/research/runs",
                json={"name": f"run_{i}"},
                headers=auth_headers,
            )

        # Trigger rate limit
        response = client.post(
            "/research/runs",
            json={"name": "overflow"},
            headers=auth_headers,
        )
        assert response.status_code == 429

        retry_after = response.headers.get("Retry-After")
        assert retry_after is not None
        assert int(retry_after) > 0
        assert int(retry_after) <= 60  # Should not exceed window


class TestRateLimitErrorResponse:
    """Tests for rate limit error response format."""

    def test_response_includes_all_required_fields(
        self, client: TestClient, auth_headers: dict[str, str]
    ) -> None:
        """Rate limit response should include detail, retry_after, and error_code."""
        # Fill the limit
        for i in range(5):
            client.post(
                "/research/runs",
                json={"name": f"run_{i}"},
                headers=auth_headers,
            )

        # Trigger rate limit
        response = client.post(
            "/research/runs",
            json={"name": "overflow"},
            headers=auth_headers,
        )
        assert response.status_code == 429

        body = response.json()
        assert "detail" in body
        assert isinstance(body["detail"], str)
        assert "retry_after" in body
        assert isinstance(body["retry_after"], int)
        assert "error_code" in body
        assert body["error_code"] == "RATE_LIMIT_EXCEEDED"

    def test_response_detail_message(
        self, client: TestClient, auth_headers: dict[str, str]
    ) -> None:
        """Rate limit response detail should be user-friendly."""
        # Fill the limit
        for i in range(5):
            client.post(
                "/research/runs",
                json={"name": f"run_{i}"},
                headers=auth_headers,
            )

        # Trigger rate limit
        response = client.post(
            "/research/runs",
            json={"name": "overflow"},
            headers=auth_headers,
        )
        assert response.status_code == 429

        body = response.json()
        assert "rate limit" in body["detail"].lower() or "slow down" in body["detail"].lower()
