"""
Concrete RBAC service tests.

Tests for the database-backed RBACService that validates user roles
against the actual User record in the database, rather than trusting
JWT claims alone.

Dependencies:
    - libs.authz.interfaces.rbac (RBACInterface, Role, Permission)
    - libs.authz.services.rbac_service (ConcreteRBACService)
    - libs.contracts.models (User, Base)

Example:
    pytest tests/unit/test_h_rbac_service.py -v
"""

from __future__ import annotations

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from libs.authz.interfaces.rbac import Permission, Role
from libs.contracts.errors import NotFoundError
from libs.contracts.models import Base, User

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_session() -> Session:
    """Create an in-memory SQLite session with all tables."""
    engine = create_engine("sqlite:///:memory:", echo=False)
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine)
    return factory()


def _seed_user(session: Session, user_id: str, role: str) -> User:
    """Insert a test user with the given role and return it."""
    user = User(
        id=user_id,
        email=f"{user_id}@test.io",
        hashed_password="$2b$12$hashed",
        role=role,
        is_active=True,
    )
    session.add(user)
    session.commit()
    return user


# ---------------------------------------------------------------------------
# Test: Role enum alignment with ROLE_SCOPES
# ---------------------------------------------------------------------------


class TestRoleEnumAlignment:
    """Role enum must match the authoritative ROLE_SCOPES keys in auth.py."""

    def test_role_enum_has_reviewer_not_researcher(self) -> None:
        """Role.REVIEWER must exist; Role.RESEARCHER must not."""
        assert hasattr(Role, "REVIEWER"), "Role enum must define REVIEWER"
        assert Role.REVIEWER.value == "reviewer"

    def test_role_enum_values_match_check_constraint(self) -> None:
        """All Role enum values must be in the CHECK constraint set."""
        valid_roles = {"admin", "operator", "reviewer", "viewer"}
        enum_values = {r.value for r in Role}
        assert enum_values == valid_roles, (
            f"Role enum values {enum_values} don't match CHECK constraint roles {valid_roles}"
        )


# ---------------------------------------------------------------------------
# Test: ConcreteRBACService
# ---------------------------------------------------------------------------


class TestConcreteRBACServiceGetRole:
    """ConcreteRBACService.get_role must return the DB-stored role."""

    def test_get_role_returns_correct_role(self) -> None:
        """get_role returns the user's actual role from the database."""
        from libs.authz.services.rbac_service import ConcreteRBACService

        session = _make_session()
        _seed_user(session, "01HUSER0000000000000000001", "operator")
        svc = ConcreteRBACService(session=session)
        assert svc.get_role("01HUSER0000000000000000001") == Role.OPERATOR

    def test_get_role_raises_not_found_for_missing_user(self) -> None:
        """get_role raises NotFoundError for non-existent user_id."""
        import pytest

        from libs.authz.services.rbac_service import ConcreteRBACService

        session = _make_session()
        svc = ConcreteRBACService(session=session)
        with pytest.raises(NotFoundError):
            svc.get_role("01HUSER_DOES_NOT_EXIST_0001")


class TestConcreteRBACServiceSetRole:
    """ConcreteRBACService.set_role must update the DB record."""

    def test_set_role_updates_user_role(self) -> None:
        """set_role writes the new role to the database."""
        from libs.authz.services.rbac_service import ConcreteRBACService

        session = _make_session()
        _seed_user(session, "01HUSER0000000000000000001", "viewer")
        svc = ConcreteRBACService(session=session)
        svc.set_role("01HUSER0000000000000000001", Role.ADMIN)

        # Re-read from DB to confirm
        user = session.get(User, "01HUSER0000000000000000001")
        assert user is not None
        assert user.role == "admin"

    def test_set_role_raises_not_found_for_missing_user(self) -> None:
        """set_role raises NotFoundError for non-existent user_id."""
        import pytest

        from libs.authz.services.rbac_service import ConcreteRBACService

        session = _make_session()
        svc = ConcreteRBACService(session=session)
        with pytest.raises(NotFoundError):
            svc.set_role("01HUSER_DOES_NOT_EXIST_0001", Role.VIEWER)


class TestConcreteRBACServiceHasPermission:
    """ConcreteRBACService.has_permission must check the DB role."""

    def test_admin_has_all_permissions(self) -> None:
        """Admin role grants every permission."""
        from libs.authz.services.rbac_service import ConcreteRBACService

        session = _make_session()
        _seed_user(session, "01HADMIN000000000000000001", "admin")
        svc = ConcreteRBACService(session=session)
        for perm in Permission:
            assert svc.has_permission("01HADMIN000000000000000001", perm), (
                f"Admin should have {perm}"
            )

    def test_viewer_cannot_request_promotion(self) -> None:
        """Viewer role must not grant request_promotion."""
        from libs.authz.services.rbac_service import ConcreteRBACService

        session = _make_session()
        _seed_user(session, "01HVIEW0000000000000000001", "viewer")
        svc = ConcreteRBACService(session=session)
        assert not svc.has_permission("01HVIEW0000000000000000001", Permission.REQUEST_PROMOTION)

    def test_operator_can_approve_promotion(self) -> None:
        """Operator role grants approve_promotion."""
        from libs.authz.services.rbac_service import ConcreteRBACService

        session = _make_session()
        _seed_user(session, "01HOPER0000000000000000001", "operator")
        svc = ConcreteRBACService(session=session)
        assert svc.has_permission("01HOPER0000000000000000001", Permission.APPROVE_PROMOTION)

    def test_reviewer_can_request_promotion(self) -> None:
        """Reviewer role grants request_promotion."""
        from libs.authz.services.rbac_service import ConcreteRBACService

        session = _make_session()
        _seed_user(session, "01HREV00000000000000000001", "reviewer")
        svc = ConcreteRBACService(session=session)
        assert svc.has_permission("01HREV00000000000000000001", Permission.REQUEST_PROMOTION)

    def test_has_permission_raises_not_found(self) -> None:
        """has_permission raises NotFoundError for missing user."""
        import pytest

        from libs.authz.services.rbac_service import ConcreteRBACService

        session = _make_session()
        svc = ConcreteRBACService(session=session)
        with pytest.raises(NotFoundError):
            svc.has_permission("01HGHOST000000000000000001", Permission.VIEW_AUDIT)
