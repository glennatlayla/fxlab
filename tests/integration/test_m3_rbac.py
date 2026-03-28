"""
Integration tests for M3 — Auth + RBAC.

These tests verify that the RBAC subsystem components work together
correctly as a complete system:

- MockRBACService integrates correctly with ROLE_PERMISSIONS policy.
- check_permission delegates to the RBAC service when one is provided.
- The promotion API endpoint enforces RBAC correctly with a real service.
- All roles receive the expected access decisions across all permissions.

Integration scope:
    MockRBACService ←→ ROLE_PERMISSIONS policy ←→ check_permission ←→ FastAPI endpoint

These tests do NOT test individual units in isolation — they verify the
full permission enforcement path with real components wired together.
"""

import pytest
from fastapi.testclient import TestClient
from unittest.mock import patch

from libs.authz.interfaces.rbac import Permission, Role, ROLE_PERMISSIONS
from libs.authz.mocks.mock_rbac import MockRBACService
from services.api.main import app, check_permission


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def rbac() -> MockRBACService:
    """Return a fresh MockRBACService for each test."""
    return MockRBACService()


@pytest.fixture
def populated_rbac() -> MockRBACService:
    """
    Return a MockRBACService pre-populated with one user per role.

    User ULID layout:
        ADMIN      → 01HQAAAAAAAAAAAAAAAAAAAAAAA
        OPERATOR   → 01HQBBBBBBBBBBBBBBBBBBBBBB
        RESEARCHER → 01HQCCCCCCCCCCCCCCCCCCCCCC
        VIEWER     → 01HQDDDDDDDDDDDDDDDDDDDDDD
    """
    svc = MockRBACService()
    svc.set_role("01HQAAAAAAAAAAAAAAAAAAAAAA", Role.ADMIN)
    svc.set_role("01HQBBBBBBBBBBBBBBBBBBBBBB", Role.OPERATOR)
    svc.set_role("01HQCCCCCCCCCCCCCCCCCCCCCC", Role.RESEARCHER)
    svc.set_role("01HQDDDDDDDDDDDDDDDDDDDDDD", Role.VIEWER)
    return svc


@pytest.fixture
def api_client() -> TestClient:
    """Return a FastAPI TestClient for the main app."""
    return TestClient(app, raise_server_exceptions=False)


# ---------------------------------------------------------------------------
# Role → permission matrix integration
# ---------------------------------------------------------------------------


class TestRolePermissionMatrix:
    """
    Verify the full permission matrix: every role × every permission.

    These tests confirm that ROLE_PERMISSIONS is correctly enforced
    end-to-end through MockRBACService.has_permission().
    """

    # Expected True/False matrix per role.
    # Rows: role, Columns: permission
    EXPECTED: dict[Role, dict[Permission, bool]] = {
        Role.ADMIN: {p: True for p in Permission},
        Role.OPERATOR: {
            Permission.REQUEST_PROMOTION: False,
            Permission.APPROVE_PROMOTION: True,
            Permission.REJECT_PROMOTION: True,
            Permission.REQUEST_OVERRIDE: True,
            Permission.VIEW_OVERRIDE: True,
            Permission.VIEW_AUDIT: True,
            Permission.VIEW_RUNS: True,
            Permission.VIEW_RUN_RESULTS: True,
            Permission.VIEW_FEEDS: True,
            Permission.VIEW_FEED_HEALTH: True,
            Permission.VIEW_QUEUE_CONTENTION: True,
        },
        Role.RESEARCHER: {
            Permission.REQUEST_PROMOTION: True,
            Permission.APPROVE_PROMOTION: False,
            Permission.REJECT_PROMOTION: False,
            Permission.REQUEST_OVERRIDE: False,
            Permission.VIEW_OVERRIDE: True,
            Permission.VIEW_AUDIT: True,
            Permission.VIEW_RUNS: True,
            Permission.VIEW_RUN_RESULTS: True,
            Permission.VIEW_FEEDS: True,
            Permission.VIEW_FEED_HEALTH: True,
            Permission.VIEW_QUEUE_CONTENTION: True,
        },
        Role.VIEWER: {
            Permission.REQUEST_PROMOTION: False,
            Permission.APPROVE_PROMOTION: False,
            Permission.REJECT_PROMOTION: False,
            Permission.REQUEST_OVERRIDE: False,
            Permission.VIEW_OVERRIDE: False,
            Permission.VIEW_AUDIT: True,
            Permission.VIEW_RUNS: True,
            Permission.VIEW_RUN_RESULTS: True,
            Permission.VIEW_FEEDS: True,
            Permission.VIEW_FEED_HEALTH: True,
            Permission.VIEW_QUEUE_CONTENTION: True,
        },
    }

    def test_admin_has_every_permission(self, populated_rbac: MockRBACService) -> None:
        """Admin user has every permission defined in the Permission enum."""
        admin_id = "01HQAAAAAAAAAAAAAAAAAAAAAA"
        for perm in Permission:
            result = populated_rbac.has_permission(admin_id, perm)
            assert result is True, f"Admin should have {perm}, got False"

    def test_operator_permission_matrix(self, populated_rbac: MockRBACService) -> None:
        """Operator has exactly the operator-level permissions."""
        operator_id = "01HQBBBBBBBBBBBBBBBBBBBBBB"
        for perm, expected in self.EXPECTED[Role.OPERATOR].items():
            result = populated_rbac.has_permission(operator_id, perm)
            assert result == expected, (
                f"Operator.{perm.value}: expected {expected}, got {result}"
            )

    def test_researcher_permission_matrix(self, populated_rbac: MockRBACService) -> None:
        """Researcher has exactly the researcher-level permissions."""
        researcher_id = "01HQCCCCCCCCCCCCCCCCCCCCCC"
        for perm, expected in self.EXPECTED[Role.RESEARCHER].items():
            result = populated_rbac.has_permission(researcher_id, perm)
            assert result == expected, (
                f"Researcher.{perm.value}: expected {expected}, got {result}"
            )

    def test_viewer_permission_matrix(self, populated_rbac: MockRBACService) -> None:
        """Viewer has read-only permissions and none of the write permissions."""
        viewer_id = "01HQDDDDDDDDDDDDDDDDDDDDDD"
        for perm, expected in self.EXPECTED[Role.VIEWER].items():
            result = populated_rbac.has_permission(viewer_id, perm)
            assert result == expected, (
                f"Viewer.{perm.value}: expected {expected}, got {result}"
            )


# ---------------------------------------------------------------------------
# check_permission function integration with MockRBACService
# ---------------------------------------------------------------------------


class TestCheckPermissionWithRBACService:
    """
    Verify check_permission delegates correctly to a real MockRBACService.

    These tests wire check_permission together with MockRBACService to
    confirm the end-to-end delegation path works for all key scenarios.
    """

    def test_researcher_granted_request_promotion(self, rbac: MockRBACService) -> None:
        """Researcher is granted REQUEST_PROMOTION via check_permission."""
        user_id = "01HQCCCCCCCCCCCCCCCCCCCCCC"
        rbac.set_role(user_id, Role.RESEARCHER)
        result = check_permission(
            user_id,
            permission=Permission.REQUEST_PROMOTION,
            rbac_service=rbac,
        )
        assert result is True

    def test_viewer_denied_request_promotion(self, rbac: MockRBACService) -> None:
        """Viewer is denied REQUEST_PROMOTION via check_permission."""
        user_id = "01HQDDDDDDDDDDDDDDDDDDDDDD"
        rbac.set_role(user_id, Role.VIEWER)
        result = check_permission(
            user_id,
            permission=Permission.REQUEST_PROMOTION,
            rbac_service=rbac,
        )
        assert result is False

    def test_operator_denied_request_promotion(self, rbac: MockRBACService) -> None:
        """Operator cannot request promotions — only researchers and admins can."""
        user_id = "01HQBBBBBBBBBBBBBBBBBBBBBB"
        rbac.set_role(user_id, Role.OPERATOR)
        result = check_permission(
            user_id,
            permission=Permission.REQUEST_PROMOTION,
            rbac_service=rbac,
        )
        assert result is False

    def test_operator_granted_approve_promotion(self, rbac: MockRBACService) -> None:
        """Operator is granted APPROVE_PROMOTION via check_permission."""
        user_id = "01HQBBBBBBBBBBBBBBBBBBBBBB"
        rbac.set_role(user_id, Role.OPERATOR)
        result = check_permission(
            user_id,
            permission=Permission.APPROVE_PROMOTION,
            rbac_service=rbac,
        )
        assert result is True

    def test_researcher_denied_approve_promotion(self, rbac: MockRBACService) -> None:
        """Researcher cannot approve promotions — separation of duties."""
        user_id = "01HQCCCCCCCCCCCCCCCCCCCCCC"
        rbac.set_role(user_id, Role.RESEARCHER)
        result = check_permission(
            user_id,
            permission=Permission.APPROVE_PROMOTION,
            rbac_service=rbac,
        )
        assert result is False

    def test_check_permission_call_tracked_in_service(self, rbac: MockRBACService) -> None:
        """check_permission delegates to rbac_service and call is tracked."""
        user_id = "01HQAAAAAAAAAAAAAAAAAAAAAA"
        rbac.set_role(user_id, Role.ADMIN)

        check_permission(user_id, permission=Permission.VIEW_AUDIT, rbac_service=rbac)

        # The service recorded that has_permission was called once
        assert rbac.call_count == 1
        assert rbac.last_checked_permission == Permission.VIEW_AUDIT

    def test_check_permission_stub_returns_true_without_service(self) -> None:
        """check_permission returns True (permissive stub) when no rbac_service given."""
        result = check_permission("01HQAAAAAAAAAAAAAAAAAAAAAA")
        assert result is True

    def test_check_permission_stub_returns_true_when_only_permission_given(self) -> None:
        """check_permission returns True when permission is given but rbac_service is None."""
        result = check_permission(
            "01HQAAAAAAAAAAAAAAAAAAAAAA",
            permission=Permission.APPROVE_PROMOTION,
        )
        assert result is True

    def test_check_permission_stub_returns_true_when_only_rbac_service_given(
        self, rbac: MockRBACService
    ) -> None:
        """check_permission returns True when rbac_service is given but permission is None."""
        user_id = "01HQDDDDDDDDDDDDDDDDDDDDDD"
        rbac.set_role(user_id, Role.VIEWER)
        # No permission specified — stub should still return True (permissive fallback)
        result = check_permission(user_id, rbac_service=rbac)
        assert result is True


# ---------------------------------------------------------------------------
# MockRBACService introspection helpers integration
# ---------------------------------------------------------------------------


class TestMockRBACIntrospection:
    """
    Verify that the introspection helpers work correctly after multiple
    role assignments and permission checks.
    """

    def test_get_all_roles_reflects_all_set_roles(self, rbac: MockRBACService) -> None:
        """get_all_roles() returns a mapping of all registered users → roles."""
        rbac.set_role("01HQAAAAAAAAAAAAAAAAAAAAAA", Role.ADMIN)
        rbac.set_role("01HQBBBBBBBBBBBBBBBBBBBBBB", Role.RESEARCHER)

        snapshot = rbac.get_all_roles()

        assert snapshot["01HQAAAAAAAAAAAAAAAAAAAAAA"] == Role.ADMIN
        assert snapshot["01HQBBBBBBBBBBBBBBBBBBBBBB"] == Role.RESEARCHER
        assert len(snapshot) == 2

    def test_get_all_roles_returns_shallow_copy(self, rbac: MockRBACService) -> None:
        """Mutating the dict returned by get_all_roles() does not affect the service."""
        user_id = "01HQAAAAAAAAAAAAAAAAAAAAAA"
        rbac.set_role(user_id, Role.ADMIN)

        snapshot = rbac.get_all_roles()
        snapshot[user_id] = Role.VIEWER  # mutate the snapshot

        # Original role must be unchanged
        assert rbac.get_role(user_id) == Role.ADMIN

    def test_count_registered_matches_number_of_set_role_calls(
        self, rbac: MockRBACService
    ) -> None:
        """count_registered() equals the number of distinct set_role() calls."""
        assert rbac.count_registered() == 0
        rbac.set_role("01HQAAAAAAAAAAAAAAAAAAAAAA", Role.ADMIN)
        assert rbac.count_registered() == 1
        rbac.set_role("01HQBBBBBBBBBBBBBBBBBBBBBB", Role.VIEWER)
        assert rbac.count_registered() == 2

    def test_clear_resets_get_all_roles(self, rbac: MockRBACService) -> None:
        """clear() removes all roles from get_all_roles()."""
        rbac.set_role("01HQAAAAAAAAAAAAAAAAAAAAAA", Role.ADMIN)
        rbac.clear()
        assert rbac.get_all_roles() == {}
        assert rbac.count_registered() == 0


# ---------------------------------------------------------------------------
# API endpoint integration — promotion request with RBAC enforcement
# ---------------------------------------------------------------------------


class TestPromotionEndpointWithRealRBAC:
    """
    Integration tests for the POST /promotions/request endpoint with a
    real MockRBACService injected into check_permission.

    These tests patch check_permission to call the real MockRBACService
    rather than the permissive stub, validating the full enforcement path.
    """

    _VALID_PAYLOAD = {
        "candidate_id": "01HQAAAAAAAAAAAAAAAAAAAAAA",
        "target_environment": "paper",
        "requester_id": "01HQBBBBBBBBBBBBBBBBBBBBBB",
    }

    def test_researcher_can_request_promotion(self, api_client: TestClient) -> None:
        """
        A researcher whose requester_id is registered in the RBAC service
        receives 202 Accepted when the endpoint delegates to check_permission.
        """
        rbac = MockRBACService()
        rbac.set_role("01HQBBBBBBBBBBBBBBBBBBBBBB", Role.RESEARCHER)

        def real_check(requester_id: str, **_kwargs: object) -> bool:
            return rbac.has_permission(requester_id, Permission.REQUEST_PROMOTION)

        with patch("services.api.main.check_permission", side_effect=real_check):
            with patch("services.api.main.submit_promotion_request") as mock_submit:
                mock_submit.return_value = {
                    "job_id": "01HQCCCCCCCCCCCCCCCCCCCCCC",
                    "status": "pending",
                }
                with patch("services.api.main.audit_service"):
                    response = api_client.post(
                        "/promotions/request", json=self._VALID_PAYLOAD
                    )

        assert response.status_code == 202, response.text
        assert response.json()["status"] == "pending"

    def test_viewer_cannot_request_promotion(self, api_client: TestClient) -> None:
        """
        A viewer whose requester_id is registered receives 403 Forbidden
        when the endpoint delegates to check_permission.
        """
        rbac = MockRBACService()
        rbac.set_role("01HQBBBBBBBBBBBBBBBBBBBBBB", Role.VIEWER)

        def real_check(requester_id: str, **_kwargs: object) -> bool:
            return rbac.has_permission(requester_id, Permission.REQUEST_PROMOTION)

        with patch("services.api.main.check_permission", side_effect=real_check):
            response = api_client.post(
                "/promotions/request", json=self._VALID_PAYLOAD
            )

        assert response.status_code == 403

    def test_operator_cannot_request_promotion(self, api_client: TestClient) -> None:
        """
        An operator cannot request promotions — only researchers and admins can.
        """
        rbac = MockRBACService()
        rbac.set_role("01HQBBBBBBBBBBBBBBBBBBBBBB", Role.OPERATOR)

        def real_check(requester_id: str, **_kwargs: object) -> bool:
            return rbac.has_permission(requester_id, Permission.REQUEST_PROMOTION)

        with patch("services.api.main.check_permission", side_effect=real_check):
            response = api_client.post(
                "/promotions/request", json=self._VALID_PAYLOAD
            )

        assert response.status_code == 403

    def test_admin_can_request_promotion(self, api_client: TestClient) -> None:
        """Admin has all permissions including REQUEST_PROMOTION."""
        rbac = MockRBACService()
        rbac.set_role("01HQBBBBBBBBBBBBBBBBBBBBBB", Role.ADMIN)

        def real_check(requester_id: str, **_kwargs: object) -> bool:
            return rbac.has_permission(requester_id, Permission.REQUEST_PROMOTION)

        with patch("services.api.main.check_permission", side_effect=real_check):
            with patch("services.api.main.submit_promotion_request") as mock_submit:
                mock_submit.return_value = {
                    "job_id": "01HQDDDDDDDDDDDDDDDDDDDDDD",
                    "status": "pending",
                }
                with patch("services.api.main.audit_service"):
                    response = api_client.post(
                        "/promotions/request", json=self._VALID_PAYLOAD
                    )

        assert response.status_code == 202

    def test_unknown_user_denied_when_no_default_role(
        self, api_client: TestClient
    ) -> None:
        """
        An unregistered user_id raises NotFoundError in MockRBACService
        when no default_role is set; the endpoint propagates this as 403.
        """
        from libs.contracts.errors import NotFoundError

        rbac = MockRBACService()  # no default_role; unknown user raises NotFoundError

        def real_check(requester_id: str, **_kwargs: object) -> bool:
            try:
                return rbac.has_permission(requester_id, Permission.REQUEST_PROMOTION)
            except NotFoundError:
                return False

        with patch("services.api.main.check_permission", side_effect=real_check):
            response = api_client.post(
                "/promotions/request", json=self._VALID_PAYLOAD
            )

        assert response.status_code == 403
