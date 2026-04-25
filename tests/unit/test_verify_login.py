"""
Unit tests for the end-to-end login verification module.

Purpose:
    Verify that verify_login correctly exercises the full auth flow:
    user lookup, active check, bcrypt verification, and JWT generation.

Test coverage:
    - Happy path: valid credentials → passed=True.
    - User not found → passed=False, stage="user_lookup".
    - Inactive user → passed=False, stage="user_active".
    - Wrong password → passed=False, stage="bcrypt_verify".
    - Diagnostic detail includes hash length and prefix on bcrypt failure.
"""

from __future__ import annotations

import os

import bcrypt
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from libs.contracts.models import Base, User

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

KNOWN_PASSWORD = "test-password-e2e-123"


def _make_user(
    email: str = "admin@fxlab.io",
    password: str = KNOWN_PASSWORD,
    role: str = "admin",
    is_active: bool = True,
) -> User:
    """Create a User with a known password."""
    import ulid as _ulid_mod

    return User(
        id=str(_ulid_mod.ULID()),
        email=email,
        hashed_password=bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8"),
        role=role,
        is_active=is_active,
    )


@pytest.fixture(autouse=True)
def _ensure_jwt_secret():
    """Ensure JWT_SECRET_KEY is set for token generation tests."""
    original = os.environ.get("JWT_SECRET_KEY")
    if not original or len(original) < 32:
        os.environ["JWT_SECRET_KEY"] = "test-secret-key-that-is-at-least-32-bytes-long!!"
    yield
    if original is None:
        os.environ.pop("JWT_SECRET_KEY", None)
    else:
        os.environ["JWT_SECRET_KEY"] = original


@pytest.fixture()
def db_session():
    """In-memory SQLite with users table."""
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autocommit=False, autoflush=False)
    session = factory()
    yield session
    session.close()
    engine.dispose()


@pytest.fixture()
def db_with_admin(db_session: Session):
    """Database with one active admin user."""
    user = _make_user()
    db_session.add(user)
    db_session.commit()
    yield db_session


@pytest.fixture()
def db_with_inactive_user(db_session: Session):
    """Database with one inactive user."""
    user = _make_user(is_active=False)
    db_session.add(user)
    db_session.commit()
    yield db_session


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestVerifyLogin:
    """Tests for the verify_login function."""

    def test_valid_credentials_pass(self, db_with_admin: Session) -> None:
        """Correct email + password → passed=True."""
        from services.api.cli.verify_login import verify_login

        result = verify_login(db_with_admin, "admin@fxlab.io", KNOWN_PASSWORD)

        assert result.passed is True
        assert result.stage is None
        assert result.email == "admin@fxlab.io"

    def test_user_not_found_fails(self, db_session: Session) -> None:
        """Non-existent email → passed=False, stage=user_lookup."""
        from services.api.cli.verify_login import verify_login

        result = verify_login(db_session, "nobody@fxlab.io", "anything")

        assert result.passed is False
        assert result.stage == "user_lookup"
        assert "nobody@fxlab.io" in result.detail

    def test_inactive_user_fails(self, db_with_inactive_user: Session) -> None:
        """Inactive user → passed=False, stage=user_active."""
        from services.api.cli.verify_login import verify_login

        result = verify_login(db_with_inactive_user, "admin@fxlab.io", KNOWN_PASSWORD)

        assert result.passed is False
        assert result.stage == "user_active"

    def test_wrong_password_fails(self, db_with_admin: Session) -> None:
        """Wrong password → passed=False, stage=bcrypt_verify."""
        from services.api.cli.verify_login import verify_login

        result = verify_login(db_with_admin, "admin@fxlab.io", "wrong-password")

        assert result.passed is False
        assert result.stage == "bcrypt_verify"

    def test_bcrypt_failure_includes_diagnostics(self, db_with_admin: Session) -> None:
        """BCrypt failure detail includes hash length and prefix."""
        from services.api.cli.verify_login import verify_login

        result = verify_login(db_with_admin, "admin@fxlab.io", "wrong-password")

        assert "hash length=" in result.detail.lower() or "Hash length=" in result.detail
        assert "$2b$" in result.detail  # bcrypt hash prefix

    def test_detail_message_on_success(self, db_with_admin: Session) -> None:
        """Successful verification includes JWT token length in detail."""
        from services.api.cli.verify_login import verify_login

        result = verify_login(db_with_admin, "admin@fxlab.io", KNOWN_PASSWORD)

        assert "jwt" in result.detail.lower() or "JWT" in result.detail
        assert "chars" in result.detail

    def test_seed_then_verify_e2e(self, db_session: Session) -> None:
        """Full cycle: seed a user, then verify login works."""
        from services.api.cli.seed_admin import seed_admin_user
        from services.api.cli.verify_login import verify_login

        seed_result = seed_admin_user(db_session)
        db_session.commit()

        login_result = verify_login(
            db_session,
            seed_result.email,
            seed_result.plaintext_password,
        )

        assert login_result.passed is True, (
            f"Seeded user failed login verification: "
            f"stage={login_result.stage}, detail={login_result.detail}"
        )

    def test_reset_then_verify_e2e(self, db_with_admin: Session) -> None:
        """Full cycle: reset a password, then verify login works."""
        from services.api.cli.reset_password import reset_user_password
        from services.api.cli.verify_login import verify_login

        reset_result = reset_user_password(db_with_admin, "admin@fxlab.io")
        db_with_admin.commit()

        login_result = verify_login(
            db_with_admin,
            reset_result.email,
            reset_result.plaintext_password,
        )

        assert login_result.passed is True, (
            f"Reset password failed login verification: "
            f"stage={login_result.stage}, detail={login_result.detail}"
        )
