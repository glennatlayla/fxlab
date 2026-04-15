"""
Unit tests for token revocation blacklist (AUTH-3).

Tests cover:
- TokenBlacklistService: is_revoked, revoke, purge_expired.
- Auth integration: revoked JTI is rejected at token validation.
- Backward compatibility: tokens without JTI are accepted.

Dependencies:
    - SQLAlchemy: In-memory SQLite engine.
    - libs.contracts.models: RevokedToken ORM model.
    - services.api.services.token_blacklist_service: TokenBlacklistService.
    - services.api.auth: create_access_token, _validate_token.

Example:
    pytest tests/unit/test_token_revocation.py -v
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import jwt
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from libs.contracts.models import Base, RevokedToken
from services.api.services.token_blacklist_service import TokenBlacklistService

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def db_session() -> Session:
    """Create an in-memory SQLite session with all tables."""
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    TestingSessionLocal = sessionmaker(bind=engine)
    session = TestingSessionLocal()
    yield session
    session.close()


@pytest.fixture()
def service(db_session: Session) -> TokenBlacklistService:
    """Create a TokenBlacklistService backed by the in-memory DB."""
    return TokenBlacklistService(db_session)


# ---------------------------------------------------------------------------
# TokenBlacklistService.is_revoked
# ---------------------------------------------------------------------------


class TestIsRevoked:
    """Tests for TokenBlacklistService.is_revoked method."""

    def test_is_revoked_returns_false_for_unknown_jti(self, service: TokenBlacklistService) -> None:
        """Unknown JTI should not be flagged as revoked."""
        assert service.is_revoked("nonexistent-jti") is False

    def test_is_revoked_returns_true_for_revoked_jti(
        self, db_session: Session, service: TokenBlacklistService
    ) -> None:
        """A JTI added to the blacklist should be reported as revoked."""
        jti = "revoked-jti-001"
        record = RevokedToken(
            jti=jti,
            revoked_at=datetime.now(timezone.utc),
            expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
            reason="test",
        )
        db_session.add(record)
        db_session.flush()

        assert service.is_revoked(jti) is True

    def test_is_revoked_returns_true_on_db_error(self, service: TokenBlacklistService) -> None:
        """On database error, is_revoked should return True (fail-secure).

        A fintech trading platform must deny access when the revocation
        check cannot be performed, rather than allowing potentially
        revoked tokens through during a database outage.
        """
        with patch.object(service, "_db") as mock_db:
            mock_db.get.side_effect = Exception("connection lost")
            assert service.is_revoked("any-jti") is True


# ---------------------------------------------------------------------------
# TokenBlacklistService.revoke
# ---------------------------------------------------------------------------


class TestRevoke:
    """Tests for TokenBlacklistService.revoke method."""

    def test_revoke_adds_jti_to_blacklist(
        self, db_session: Session, service: TokenBlacklistService
    ) -> None:
        """After revoke(), the JTI should appear in the blacklist."""
        jti = "revoke-me-001"
        expires_at = datetime.now(timezone.utc) + timedelta(hours=1)

        service.revoke(jti, expires_at, reason="logout")
        db_session.flush()

        assert service.is_revoked(jti) is True

    def test_revoke_stores_reason(
        self, db_session: Session, service: TokenBlacklistService
    ) -> None:
        """Revoked token should persist the reason."""
        jti = "revoke-reason-001"
        expires_at = datetime.now(timezone.utc) + timedelta(hours=1)

        service.revoke(jti, expires_at, reason="compromised")
        db_session.flush()

        record = db_session.get(RevokedToken, jti)
        assert record is not None
        assert record.reason == "compromised"

    def test_revoke_without_reason_stores_none(
        self, db_session: Session, service: TokenBlacklistService
    ) -> None:
        """Revoking without explicit reason should store None."""
        jti = "revoke-no-reason-001"
        expires_at = datetime.now(timezone.utc) + timedelta(hours=1)

        service.revoke(jti, expires_at)
        db_session.flush()

        record = db_session.get(RevokedToken, jti)
        assert record is not None
        assert record.reason is None


# ---------------------------------------------------------------------------
# TokenBlacklistService.purge_expired
# ---------------------------------------------------------------------------


class TestPurgeExpired:
    """Tests for TokenBlacklistService.purge_expired method."""

    def test_purge_expired_removes_expired_entries(
        self, db_session: Session, service: TokenBlacklistService
    ) -> None:
        """purge_expired() should delete entries whose expires_at is in the past."""
        past = datetime.now(timezone.utc) - timedelta(hours=1)
        future = datetime.now(timezone.utc) + timedelta(hours=1)

        db_session.add(
            RevokedToken(
                jti="expired-001",
                revoked_at=datetime.now(timezone.utc) - timedelta(hours=2),
                expires_at=past,
                reason="old",
            )
        )
        db_session.add(
            RevokedToken(
                jti="active-001",
                revoked_at=datetime.now(timezone.utc),
                expires_at=future,
                reason="recent",
            )
        )
        db_session.flush()

        purged_count = service.purge_expired()

        assert purged_count == 1
        assert service.is_revoked("expired-001") is False
        assert service.is_revoked("active-001") is True

    def test_purge_expired_returns_zero_when_none_expired(
        self, db_session: Session, service: TokenBlacklistService
    ) -> None:
        """purge_expired() should return 0 when nothing to purge."""
        future = datetime.now(timezone.utc) + timedelta(hours=1)
        db_session.add(
            RevokedToken(
                jti="still-valid-001",
                revoked_at=datetime.now(timezone.utc),
                expires_at=future,
                reason="recent",
            )
        )
        db_session.flush()

        assert service.purge_expired() == 0

    def test_purge_expired_empty_table_returns_zero(self, service: TokenBlacklistService) -> None:
        """purge_expired() on an empty table should return 0."""
        assert service.purge_expired() == 0


# ---------------------------------------------------------------------------
# Auth integration — revoked token rejected at validation
# ---------------------------------------------------------------------------


class TestAuthRevocationIntegration:
    """Tests for JTI-based revocation check in the auth validation path."""

    def test_revoked_jti_rejected_at_validate_token(self) -> None:
        """A token whose JTI is in the blacklist should be rejected with 401."""
        from services.api.auth import _validate_token, create_access_token

        token = create_access_token(
            user_id="01HABCDEF00000000000000000",
            role="viewer",
        )

        # Decode to get the JTI — use the same test fallback secret
        from services.api.auth import _get_secret_key

        secret = _get_secret_key()
        decoded = jwt.decode(
            token,
            secret,
            algorithms=["HS256"],
            audience="fxlab-api",
        )
        jti = decoded["jti"]

        # Mock the DB session and blacklist service — patch at the source
        # module because auth.py imports them locally inside _validate_token.
        mock_db = MagicMock()
        mock_blacklist = MagicMock()
        mock_blacklist.is_revoked.return_value = True

        with (
            patch("services.api.db.SessionLocal", return_value=mock_db),
            patch(
                "services.api.services.token_blacklist_service.TokenBlacklistService",
                return_value=mock_blacklist,
            ),
        ):
            from fastapi import HTTPException

            # _validate_token takes the raw JWT string, not a request object
            with pytest.raises(HTTPException) as exc_info:
                _validate_token(token)

            assert exc_info.value.status_code == 401
            assert "revoked" in exc_info.value.detail.lower()
            mock_blacklist.is_revoked.assert_called_once_with(jti)

    def test_token_without_jti_accepted(self) -> None:
        """Tokens without a jti claim (backward compat) should skip revocation check."""
        from services.api.auth import _get_secret_key, _validate_token

        secret = _get_secret_key()
        now = datetime.now(timezone.utc)
        # Craft a token without jti
        payload = {
            "sub": "01HABCDEF00000000000000000",
            "role": "viewer",
            "email": "test@example.com",
            "scope": "read",
            "aud": "fxlab-api",
            "iss": "fxlab",
            "iat": now,
            "nbf": now,
            "exp": now + timedelta(hours=1),
        }
        token = jwt.encode(payload, secret, algorithm="HS256")

        # _validate_token takes the raw JWT string, not a request object
        user = _validate_token(token)
        assert user.user_id == "01HABCDEF00000000000000000"
