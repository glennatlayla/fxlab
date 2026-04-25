"""
Unit tests for the reset_password CLI tool.

Purpose:
    Verify that reset_password correctly resets a user's password,
    performs pre-write and post-write bcrypt verification, handles
    missing/inactive users, and produces operator-friendly output.

Test coverage:
    - Happy path: existing active user → password reset, bcrypt verified.
    - User not found → ResetResult with reset=False, error message.
    - Inactive user → ResetResult with reset=False, error message.
    - Password verification: new password verifiable against stored hash.
    - Password randomness: two resets produce different passwords.
    - Output format: contains email, password, verification notice.
    - CLI entrypoint: exit codes for success, not-found, and DB error.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import bcrypt
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from libs.contracts.models import Base, User

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_user(email: str = "admin@fxlab.io", role: str = "admin", is_active: bool = True) -> User:
    """Create a User with a known bcrypt-hashed password."""
    import ulid as _ulid_mod

    return User(
        id=str(_ulid_mod.ULID()),
        email=email,
        hashed_password=bcrypt.hashpw(b"old-password-123", bcrypt.gensalt()).decode("utf-8"),
        role=role,
        is_active=is_active,
    )


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
# Tests: reset_user_password()
# ---------------------------------------------------------------------------


class TestResetUserPassword:
    """Tests for the core reset_user_password function."""

    def test_resets_active_user_password(self, db_with_admin: Session) -> None:
        """Active user gets a new password, result.reset is True."""
        from services.api.cli.reset_password import reset_user_password

        result = reset_user_password(db_with_admin, "admin@fxlab.io")

        assert result.reset is True
        assert result.plaintext_password is not None
        assert result.email == "admin@fxlab.io"
        assert result.error is None

    def test_new_password_is_bcrypt_verifiable(self, db_with_admin: Session) -> None:
        """The new plaintext password verifies against the stored hash."""
        from services.api.cli.reset_password import reset_user_password

        result = reset_user_password(db_with_admin, "admin@fxlab.io")
        db_with_admin.commit()

        user = db_with_admin.query(User).filter(User.email == "admin@fxlab.io").first()
        assert bcrypt.checkpw(
            result.plaintext_password.encode("utf-8"),
            user.hashed_password.encode("utf-8"),
        )

    def test_old_password_no_longer_works(self, db_with_admin: Session) -> None:
        """After reset, the old password must NOT verify."""
        from services.api.cli.reset_password import reset_user_password

        reset_user_password(db_with_admin, "admin@fxlab.io")
        db_with_admin.commit()

        user = db_with_admin.query(User).filter(User.email == "admin@fxlab.io").first()
        assert not bcrypt.checkpw(b"old-password-123", user.hashed_password.encode("utf-8"))

    def test_password_meets_minimum_length(self, db_with_admin: Session) -> None:
        """Generated password is at least 20 characters."""
        from services.api.cli.reset_password import reset_user_password

        result = reset_user_password(db_with_admin, "admin@fxlab.io")
        assert len(result.plaintext_password) >= 20

    def test_password_is_random_across_resets(self, db_with_admin: Session) -> None:
        """Two consecutive resets produce different passwords."""
        from services.api.cli.reset_password import reset_user_password

        result1 = reset_user_password(db_with_admin, "admin@fxlab.io")
        db_with_admin.commit()
        result2 = reset_user_password(db_with_admin, "admin@fxlab.io")

        assert result1.plaintext_password != result2.plaintext_password

    def test_user_not_found_returns_error(self, db_session: Session) -> None:
        """Non-existent email → reset=False with descriptive error."""
        from services.api.cli.reset_password import reset_user_password

        result = reset_user_password(db_session, "nobody@fxlab.io")

        assert result.reset is False
        assert result.plaintext_password is None
        assert "nobody@fxlab.io" in result.error

    def test_inactive_user_returns_error(self, db_with_inactive_user: Session) -> None:
        """Inactive user → reset=False, must activate first."""
        from services.api.cli.reset_password import reset_user_password

        result = reset_user_password(db_with_inactive_user, "admin@fxlab.io")

        assert result.reset is False
        assert result.plaintext_password is None
        assert "deactivated" in result.error.lower() or "inactive" in result.error.lower()


# ---------------------------------------------------------------------------
# Tests: format_reset_output()
# ---------------------------------------------------------------------------


class TestFormatResetOutput:
    """Tests for the output formatting."""

    def test_success_output_contains_credentials(self) -> None:
        """Successful reset output includes email and password."""
        from services.api.cli.reset_password import ResetResult, format_reset_output

        result = ResetResult(email="admin@fxlab.io", plaintext_password="new-pass-123", reset=True)
        output = format_reset_output(result)

        assert "admin@fxlab.io" in output
        assert "new-pass-123" in output

    def test_success_output_mentions_verification(self) -> None:
        """Output confirms the password was verified."""
        from services.api.cli.reset_password import ResetResult, format_reset_output

        result = ResetResult(email="admin@fxlab.io", plaintext_password="pass", reset=True)
        output = format_reset_output(result)

        assert "verified" in output.lower()

    def test_failure_output_contains_error(self) -> None:
        """Failed reset output includes the error message."""
        from services.api.cli.reset_password import ResetResult, format_reset_output

        result = ResetResult(
            email="nobody@fxlab.io",
            plaintext_password=None,
            reset=False,
            error="No user found",
        )
        output = format_reset_output(result)

        assert "No user found" in output


# ---------------------------------------------------------------------------
# Tests: CLI main()
# ---------------------------------------------------------------------------


class TestCLIEntrypoint:
    """Tests for the __main__ entrypoint."""

    def test_main_exits_zero_on_success(self, db_with_admin: Session) -> None:
        """main() returns 0 on successful reset."""
        from services.api.cli.reset_password import main

        with patch("services.api.cli.reset_password._create_session", return_value=db_with_admin):
            exit_code = main(argv=["--email", "admin@fxlab.io"])

        assert exit_code == 0

    def test_main_exits_one_on_user_not_found(self, db_session: Session) -> None:
        """main() returns 1 when user doesn't exist."""
        from services.api.cli.reset_password import main

        with patch("services.api.cli.reset_password._create_session", return_value=db_session):
            exit_code = main(argv=["--email", "nobody@fxlab.io"])

        assert exit_code == 1

    def test_main_exits_one_on_db_error(self) -> None:
        """main() returns 1 on database error."""
        from services.api.cli.reset_password import main

        mock_session = MagicMock(spec=Session)
        mock_session.query.side_effect = Exception("Connection refused")

        with patch("services.api.cli.reset_password._create_session", return_value=mock_session):
            exit_code = main(argv=["--email", "admin@fxlab.io"])

        assert exit_code == 1
