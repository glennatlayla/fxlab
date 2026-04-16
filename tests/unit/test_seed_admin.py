"""
Unit tests for the seed_admin CLI tool.

Purpose:
    Verify that seed_admin correctly creates an initial admin user on a
    fresh database, is idempotent (skips when users already exist), and
    produces secure bcrypt-hashed passwords.

Test coverage:
    - Happy path: empty users table → admin created with valid ULID, bcrypt hash, admin role.
    - Idempotent: users table not empty → no user created, no error.
    - Password generation: random, >= 20 chars, not repeated across invocations.
    - Custom email override.
    - Output format: prints credentials to stdout for operator capture.
    - BCrypt verification: generated hash verifiable with bcrypt.checkpw.
    - ULID format: 26 chars, Crockford base32.
    - Database error handling: connection failures → clear error, non-zero exit.
"""

from __future__ import annotations

import re
from unittest.mock import MagicMock, patch

import bcrypt
import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from libs.contracts.models import Base, User


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def db_session():
    """Create an in-memory SQLite database with the users table."""
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
def db_session_with_user(db_session: Session):
    """Database session pre-populated with one admin user."""
    import ulid as _ulid_mod

    existing = User(
        id=str(_ulid_mod.ULID()),
        email="existing@fxlab.io",
        hashed_password=bcrypt.hashpw(b"existing-pass", bcrypt.gensalt()).decode("utf-8"),
        role="admin",
        is_active=True,
    )
    db_session.add(existing)
    db_session.commit()
    yield db_session


# ---------------------------------------------------------------------------
# Tests: seed_admin_user()
# ---------------------------------------------------------------------------


class TestSeedAdminUser:
    """Tests for the core seed_admin_user function."""

    def test_creates_admin_on_empty_database(self, db_session: Session) -> None:
        """When users table is empty, seed_admin_user creates exactly one admin."""
        from services.api.cli.seed_admin import seed_admin_user

        result = seed_admin_user(db_session)

        assert result is not None, "Expected a SeedResult when users table is empty"
        assert result.created is True

        users = db_session.query(User).all()
        assert len(users) == 1

        user = users[0]
        assert user.email == "admin@fxlab.io"
        assert user.role == "admin"
        assert user.is_active is True

    def test_skips_when_users_exist(self, db_session_with_user: Session) -> None:
        """When users table is not empty, seed_admin_user is a no-op."""
        from services.api.cli.seed_admin import seed_admin_user

        result = seed_admin_user(db_session_with_user)

        assert result is not None
        assert result.created is False
        assert result.plaintext_password is None

        users = db_session_with_user.query(User).all()
        assert len(users) == 1  # No new user added
        assert users[0].email == "existing@fxlab.io"  # Original user unchanged

    def test_password_is_bcrypt_verifiable(self, db_session: Session) -> None:
        """Generated password can be verified against the stored hash."""
        from services.api.cli.seed_admin import seed_admin_user

        result = seed_admin_user(db_session)

        user = db_session.query(User).first()
        assert user is not None

        # The plaintext password must verify against the stored bcrypt hash
        assert bcrypt.checkpw(
            result.plaintext_password.encode("utf-8"),
            user.hashed_password.encode("utf-8"),
        )

    def test_password_meets_minimum_length(self, db_session: Session) -> None:
        """Generated password is at least 20 characters (128+ bits of entropy)."""
        from services.api.cli.seed_admin import seed_admin_user

        result = seed_admin_user(db_session)
        assert len(result.plaintext_password) >= 20

    def test_password_is_random_across_invocations(self) -> None:
        """Two seed calls produce different passwords (not hardcoded)."""
        from services.api.cli.seed_admin import seed_admin_user

        passwords = []
        for _ in range(2):
            engine = create_engine(
                "sqlite:///:memory:",
                connect_args={"check_same_thread": False},
                poolclass=StaticPool,
            )
            Base.metadata.create_all(engine)
            factory = sessionmaker(bind=engine, autocommit=False, autoflush=False)
            session = factory()
            result = seed_admin_user(session)
            passwords.append(result.plaintext_password)
            session.close()
            engine.dispose()

        assert passwords[0] != passwords[1], "Passwords must be randomly generated"

    def test_user_id_is_valid_ulid(self, db_session: Session) -> None:
        """Created user has a valid 26-character ULID as primary key."""
        from services.api.cli.seed_admin import seed_admin_user

        seed_admin_user(db_session)
        user = db_session.query(User).first()

        assert user is not None
        assert len(user.id) == 26
        # ULID uses Crockford base32: digits + uppercase letters excluding I, L, O, U
        assert re.match(r"^[0-9A-HJKMNP-TV-Z]{26}$", user.id), (
            f"User ID is not a valid ULID: {user.id}"
        )

    def test_custom_email_override(self, db_session: Session) -> None:
        """Caller can specify a custom email address."""
        from services.api.cli.seed_admin import seed_admin_user

        result = seed_admin_user(db_session, email="ops@fxlab.io")
        user = db_session.query(User).first()

        assert user.email == "ops@fxlab.io"
        assert result.email == "ops@fxlab.io"

    def test_result_contains_all_fields(self, db_session: Session) -> None:
        """SeedResult has email, plaintext_password, and created flag."""
        from services.api.cli.seed_admin import seed_admin_user

        result = seed_admin_user(db_session)

        assert result.email == "admin@fxlab.io"
        assert isinstance(result.plaintext_password, str)
        assert len(result.plaintext_password) > 0
        assert result.created is True

    def test_idempotent_repeated_calls(self, db_session: Session) -> None:
        """Calling seed_admin_user twice only creates one user."""
        from services.api.cli.seed_admin import seed_admin_user

        result1 = seed_admin_user(db_session)
        result2 = seed_admin_user(db_session)

        assert result1.created is True
        assert result2.created is False

        users = db_session.query(User).all()
        assert len(users) == 1


# ---------------------------------------------------------------------------
# Tests: format_credentials_output()
# ---------------------------------------------------------------------------


class TestFormatCredentialsOutput:
    """Tests for the credential output formatting."""

    def test_output_contains_email_and_password(self) -> None:
        """Output string includes the email and plaintext password."""
        from services.api.cli.seed_admin import SeedResult, format_credentials_output

        result = SeedResult(email="admin@fxlab.io", plaintext_password="s3cret-p@ss", created=True)
        output = format_credentials_output(result)

        assert "admin@fxlab.io" in output
        assert "s3cret-p@ss" in output

    def test_output_contains_change_warning(self) -> None:
        """Output reminds operator to change the password."""
        from services.api.cli.seed_admin import SeedResult, format_credentials_output

        result = SeedResult(email="admin@fxlab.io", plaintext_password="p@ss", created=True)
        output = format_credentials_output(result)

        assert "change" in output.lower() or "rotate" in output.lower()

    def test_skipped_output_does_not_contain_password(self) -> None:
        """When seed was skipped, output should NOT contain any password."""
        from services.api.cli.seed_admin import SeedResult, format_credentials_output

        result = SeedResult(email="admin@fxlab.io", plaintext_password=None, created=False)
        output = format_credentials_output(result)

        assert "already exist" in output.lower() or "skip" in output.lower()


# ---------------------------------------------------------------------------
# Tests: CLI __main__ execution
# ---------------------------------------------------------------------------


class TestCLIEntrypoint:
    """Tests for the __main__ entrypoint behaviour."""

    def test_main_exits_zero_on_success(self, db_session: Session) -> None:
        """main() returns 0 on successful seed."""
        from services.api.cli.seed_admin import main

        with patch("services.api.cli.seed_admin._create_session", return_value=db_session):
            exit_code = main(argv=[])

        assert exit_code == 0

    def test_main_exits_zero_when_skipped(self, db_session_with_user: Session) -> None:
        """main() returns 0 when seed is skipped (idempotent, not an error)."""
        from services.api.cli.seed_admin import main

        with patch("services.api.cli.seed_admin._create_session", return_value=db_session_with_user):
            exit_code = main(argv=[])

        assert exit_code == 0

    def test_main_exits_nonzero_on_db_error(self) -> None:
        """main() returns 1 when database is unreachable."""
        from services.api.cli.seed_admin import main

        mock_session = MagicMock(spec=Session)
        mock_session.query.side_effect = Exception("Connection refused")

        with patch("services.api.cli.seed_admin._create_session", return_value=mock_session):
            exit_code = main(argv=[])

        assert exit_code == 1
