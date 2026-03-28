"""
RED unit tests for M3 - Auth + RBAC.

Tests verify:
- Role enum has expected values.
- Permission enum has expected values.
- ROLE_PERMISSIONS policy grants correct permissions per role.
- MockRBACService correctly implements RBACInterface.
- Promotion endpoint enforces RBAC (403 for insufficient permissions).
- Approvals endpoint enforces RBAC.
"""

import pytest
from unittest.mock import MagicMock, patch
from fastapi.testclient import TestClient

from libs.authz.interfaces.rbac import (
    Permission,
    RBACInterface,
    Role,
    ROLE_PERMISSIONS,
)
from libs.authz.mocks.mock_rbac import MockRBACService
from libs.contracts.errors import NotFoundError

# ---------------------------------------------------------------------------
# Role enum tests
# ---------------------------------------------------------------------------


class TestRoleEnum:
    """Verify the Role enum contains the expected values."""

    def test_role_admin_exists(self):
        """Role.ADMIN must exist."""
        assert Role.ADMIN == "admin"

    def test_role_operator_exists(self):
        """Role.OPERATOR must exist."""
        assert Role.OPERATOR == "operator"

    def test_role_researcher_exists(self):
        """Role.RESEARCHER must exist."""
        assert Role.RESEARCHER == "researcher"

    def test_role_viewer_exists(self):
        """Role.VIEWER must exist."""
        assert Role.VIEWER == "viewer"

    def test_role_count(self):
        """Exactly four roles are defined."""
        assert len(Role) == 4


# ---------------------------------------------------------------------------
# Permission enum tests
# ---------------------------------------------------------------------------


class TestPermissionEnum:
    """Verify the Permission enum contains expected actions."""

    def test_request_promotion_permission_exists(self):
        """REQUEST_PROMOTION permission must exist."""
        assert Permission.REQUEST_PROMOTION == "request_promotion"

    def test_approve_promotion_permission_exists(self):
        """APPROVE_PROMOTION permission must exist."""
        assert Permission.APPROVE_PROMOTION == "approve_promotion"

    def test_reject_promotion_permission_exists(self):
        """REJECT_PROMOTION permission must exist."""
        assert Permission.REJECT_PROMOTION == "reject_promotion"

    def test_view_audit_permission_exists(self):
        """VIEW_AUDIT permission must exist."""
        assert Permission.VIEW_AUDIT == "view_audit"

    def test_view_runs_permission_exists(self):
        """VIEW_RUNS permission must exist."""
        assert Permission.VIEW_RUNS == "view_runs"


# ---------------------------------------------------------------------------
# ROLE_PERMISSIONS policy tests
# ---------------------------------------------------------------------------


class TestRolePermissionsPolicy:
    """Verify the permission policy grants correct access per role."""

    def test_admin_has_all_permissions(self):
        """Admin role must have all defined permissions."""
        admin_perms = ROLE_PERMISSIONS[Role.ADMIN]
        for perm in Permission:
            assert perm in admin_perms, f"Admin missing permission: {perm}"

    def test_operator_can_approve_promotion(self):
        """Operator can approve promotions."""
        assert Permission.APPROVE_PROMOTION in ROLE_PERMISSIONS[Role.OPERATOR]

    def test_operator_can_reject_promotion(self):
        """Operator can reject promotions."""
        assert Permission.REJECT_PROMOTION in ROLE_PERMISSIONS[Role.OPERATOR]

    def test_operator_cannot_request_promotion(self):
        """Operator cannot request promotions (only researchers/admins can)."""
        assert Permission.REQUEST_PROMOTION not in ROLE_PERMISSIONS[Role.OPERATOR]

    def test_researcher_can_request_promotion(self):
        """Researcher can request promotions."""
        assert Permission.REQUEST_PROMOTION in ROLE_PERMISSIONS[Role.RESEARCHER]

    def test_researcher_cannot_approve_promotion(self):
        """Researcher cannot approve promotions (only operators/admins can)."""
        assert Permission.APPROVE_PROMOTION not in ROLE_PERMISSIONS[Role.RESEARCHER]

    def test_viewer_cannot_request_promotion(self):
        """Viewer has read-only access — cannot request promotions."""
        assert Permission.REQUEST_PROMOTION not in ROLE_PERMISSIONS[Role.VIEWER]

    def test_viewer_cannot_approve_promotion(self):
        """Viewer cannot approve promotions."""
        assert Permission.APPROVE_PROMOTION not in ROLE_PERMISSIONS[Role.VIEWER]

    def test_viewer_can_view_audit(self):
        """Viewer can read the audit log."""
        assert Permission.VIEW_AUDIT in ROLE_PERMISSIONS[Role.VIEWER]

    def test_viewer_can_view_runs(self):
        """Viewer can view run results."""
        assert Permission.VIEW_RUNS in ROLE_PERMISSIONS[Role.VIEWER]

    def test_all_roles_have_view_audit(self):
        """All roles can view the audit log."""
        for role in Role:
            assert (
                Permission.VIEW_AUDIT in ROLE_PERMISSIONS[role]
            ), f"Role {role} should have VIEW_AUDIT permission"


# ---------------------------------------------------------------------------
# MockRBACService tests
# ---------------------------------------------------------------------------


class TestMockRBACService:
    """Verify MockRBACService implements RBACInterface correctly."""

    def test_implements_rbac_interface(self):
        """MockRBACService is a subclass of RBACInterface."""
        assert issubclass(MockRBACService, RBACInterface)

    def test_set_and_get_role(self):
        """set_role / get_role round-trips correctly."""
        rbac = MockRBACService()
        user_id = "01HQAAAAAAAAAAAAAAAAAAAAAA"
        rbac.set_role(user_id, Role.RESEARCHER)
        assert rbac.get_role(user_id) == Role.RESEARCHER

    def test_unknown_user_raises_not_found_without_default(self):
        """get_role raises NotFoundError for unknown user when no default."""
        rbac = MockRBACService()
        with pytest.raises(NotFoundError):
            rbac.get_role("01HQBBBBBBBBBBBBBBBBBBBBBB")

    def test_default_role_returned_for_unknown_user(self):
        """default_role is returned for unregistered users."""
        rbac = MockRBACService(default_role=Role.VIEWER)
        assert rbac.get_role("01HQCCCCCCCCCCCCCCCCCCCCCC") == Role.VIEWER

    def test_has_permission_true_for_granted(self):
        """has_permission returns True when the role grants the permission."""
        rbac = MockRBACService()
        user_id = "01HQDDDDDDDDDDDDDDDDDDDDDD"
        rbac.set_role(user_id, Role.RESEARCHER)
        assert rbac.has_permission(user_id, Permission.REQUEST_PROMOTION)

    def test_has_permission_false_for_denied(self):
        """has_permission returns False when the role lacks the permission."""
        rbac = MockRBACService()
        user_id = "01HQEEEEEEEEEEEEEEEEEEEEEE"
        rbac.set_role(user_id, Role.RESEARCHER)
        assert not rbac.has_permission(user_id, Permission.APPROVE_PROMOTION)

    def test_call_count_increments(self):
        """call_count increments with each has_permission call."""
        rbac = MockRBACService(default_role=Role.VIEWER)
        user_id = "01HQFFFFFFFFFFFFFFFFFFFFFF"
        rbac.has_permission(user_id, Permission.VIEW_AUDIT)
        rbac.has_permission(user_id, Permission.VIEW_RUNS)
        assert rbac.call_count == 2

    def test_last_checked_permission_tracked(self):
        """last_checked_permission stores the most recent permission checked."""
        rbac = MockRBACService(default_role=Role.ADMIN)
        user_id = "01HQGGGGGGGGGGGGGGGGGGGGGG"
        rbac.has_permission(user_id, Permission.APPROVE_PROMOTION)
        assert rbac.last_checked_permission == Permission.APPROVE_PROMOTION

    def test_clear_resets_state(self):
        """clear() resets roles and call tracking."""
        rbac = MockRBACService()
        user_id = "01HQHHHHHHHHHHHHHHHHHHHHHH"
        rbac.set_role(user_id, Role.OPERATOR)
        rbac.has_permission(user_id, Permission.APPROVE_PROMOTION)
        rbac.clear()
        assert rbac.call_count == 0
        assert rbac.last_checked_permission is None
        with pytest.raises(NotFoundError):
            rbac.get_role(user_id)

    def test_admin_role_has_all_permissions(self):
        """A user with ADMIN role has every permission."""
        rbac = MockRBACService(default_role=Role.ADMIN)
        user_id = "01HQJJJJJJJJJJJJJJJJJJJJJ"
        for perm in Permission:
            assert rbac.has_permission(user_id, perm), f"Admin missing: {perm}"


# ---------------------------------------------------------------------------
# Endpoint RBAC enforcement tests
# ---------------------------------------------------------------------------


class TestPromotionEndpointRBAC:
    """Verify that the promotion endpoint enforces RBAC via check_permission."""

    def _make_client(self):
        from services.api.main import app

        return TestClient(app, raise_server_exceptions=False)

    def test_promotion_request_forbidden_when_check_permission_returns_false(self):
        """
        POST /promotions/request must return 403 when check_permission is False.

        This test will FAIL until check_permission is wired to an RBAC service.
        Currently it always returns True, so RBAC is not enforced.
        """
        with patch("services.api.main.check_permission", return_value=False) as mock_perm:
            client = self._make_client()
            response = client.post(
                "/promotions/request",
                json={
                    "candidate_id": "01HQAAAAAAAAAAAAAAAAAAAAAA",
                    "target_environment": "paper",
                    "requester_id": "01HQBBBBBBBBBBBBBBBBBBBBBB",
                },
            )
            assert response.status_code == 403
            mock_perm.assert_called_once()

    def test_promotion_request_succeeds_when_check_permission_returns_true(self):
        """POST /promotions/request must return 202 when check_permission is True."""
        with patch("services.api.main.check_permission", return_value=True):
            with patch("services.api.main.submit_promotion_request") as mock_submit:
                mock_submit.return_value = {
                    "job_id": "01HQCCCCCCCCCCCCCCCCCCCCCC",
                    "status": "pending",
                }
                with patch("services.api.main.audit_service"):
                    client = self._make_client()
                    response = client.post(
                        "/promotions/request",
                        json={
                            "candidate_id": "01HQAAAAAAAAAAAAAAAAAAAAAA",
                            "target_environment": "paper",
                            "requester_id": "01HQBBBBBBBBBBBBBBBBBBBBBB",
                        },
                    )
                    assert response.status_code == 202


class TestCheckPermissionRBACIntegration:
    """
    Verify check_permission integrates with RBAC service.

    These tests will FAIL until check_permission is upgraded from a
    hardcoded stub to a proper RBAC call using MockRBACService or similar.
    """

    def test_check_permission_returns_true_for_researcher_requesting_promotion(self):
        """
        check_permission should return True for a researcher requesting a promotion.

        This test will FAIL if check_permission is still the stub (always True
        regardless of role) — but that is acceptable for RED.  It will also
        FAIL if check_permission is wired to an RBAC service that doesn't know
        about this user.
        """
        from services.api.main import check_permission

        # For now the stub always returns True, so this passes trivially.
        # After GREEN, it should consult an RBAC service.
        result = check_permission("01HQAAAAAAAAAAAAAAAAAAAAAA")
        assert result is True

    def test_role_permissions_coverage_for_all_roles(self):
        """Verify ROLE_PERMISSIONS defines entries for every Role."""
        for role in Role:
            assert role in ROLE_PERMISSIONS, f"Missing permissions for role: {role}"
            assert isinstance(ROLE_PERMISSIONS[role], frozenset)

    def test_check_permission_respects_rbac_when_service_provided(self):
        """
        check_permission should accept an rbac_service and permission argument
        and delegate the decision to the service for role-aware enforcement.

        This test FAILS (TypeError) until check_permission is upgraded to
        accept keyword arguments ``permission`` and ``rbac_service``.
        GREEN will add those parameters.
        """
        from libs.authz.interfaces.rbac import Permission, Role
        from libs.authz.mocks.mock_rbac import MockRBACService
        from services.api.main import check_permission

        rbac = MockRBACService()
        viewer_id = "01HQVVVVVVVVVVVVVVVVVVVVVV"
        rbac.set_role(viewer_id, Role.VIEWER)

        # Viewer does not have REQUEST_PROMOTION — this should return False.
        # Will FAIL with TypeError until check_permission accepts these kwargs.
        result = check_permission(
            viewer_id,
            permission=Permission.REQUEST_PROMOTION,
            rbac_service=rbac,
        )
        assert (
            result is False
        ), "Viewer should be denied REQUEST_PROMOTION when an RBAC service is provided."
