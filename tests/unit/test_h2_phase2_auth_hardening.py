"""
Phase 2 authentication hardening tests — H2.2 and H2.3.

Verifies production-safety requirements for authentication & session security:

  H2.2 — Token blacklist TTL cleanup job purges expired entries.
  H2.3 — Multi-key JWT_SECRET_KEY support for zero-downtime key rotation.

Dependencies:
    - services.api.services.token_blacklist_service
    - services.api.jobs.token_blacklist_cleanup
    - services.api.auth (_get_secret_key, _validate_token, create_access_token)

Example:
    pytest tests/unit/test_h2_phase2_auth_hardening.py -v
"""

from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import jwt
import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from libs.contracts.models import Base, RevokedToken

# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def db_session() -> Session:
    """In-memory SQLite session with all tables created."""
    engine = create_engine(
        "sqlite://",
        poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )

    @event.listens_for(engine, "connect")
    def _set_sqlite_pragma(dbapi_connection: object, connection_record: object) -> None:
        cursor = dbapi_connection.cursor()  # type: ignore[attr-defined]
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.close()

    Base.metadata.create_all(engine)
    _SessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False)
    session = _SessionLocal()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


# ---------------------------------------------------------------------------
# H2.2 — Token blacklist TTL cleanup job
# ---------------------------------------------------------------------------


class TestTokenBlacklistCleanupJob:
    """
    The cleanup job must purge expired blacklist entries and leave unexpired ones.

    Rationale:
        Without periodic cleanup the revoked_tokens table grows unbounded.
        Every token validation hits this table, so it must stay lean.
        The cleanup job should be idempotent and safe to run concurrently.
    """

    def test_cleanup_job_purges_expired_entries(self, db_session: Session) -> None:
        """run_token_blacklist_cleanup deletes entries where expires_at <= now."""
        now = datetime.now(timezone.utc)
        # Insert expired entry
        db_session.add(
            RevokedToken(
                jti="expired-jti-001",
                revoked_at=now - timedelta(hours=2),
                expires_at=now - timedelta(hours=1),
                reason="logout",
            )
        )
        # Insert still-valid entry
        db_session.add(
            RevokedToken(
                jti="valid-jti-001",
                revoked_at=now - timedelta(minutes=5),
                expires_at=now + timedelta(hours=1),
                reason="logout",
            )
        )
        db_session.commit()

        from services.api.jobs.token_blacklist_cleanup import run_token_blacklist_cleanup

        result = run_token_blacklist_cleanup(db_session)

        assert result["status"] == "success"
        assert result["deleted_count"] == 1

        # Verify the valid entry still exists
        remaining = db_session.get(RevokedToken, "valid-jti-001")
        assert remaining is not None

        # Verify the expired entry is gone
        deleted = db_session.get(RevokedToken, "expired-jti-001")
        assert deleted is None

    def test_cleanup_job_returns_zero_when_nothing_expired(self, db_session: Session) -> None:
        """When all entries are still valid, cleanup deletes nothing."""
        now = datetime.now(timezone.utc)
        db_session.add(
            RevokedToken(
                jti="valid-jti-002",
                revoked_at=now,
                expires_at=now + timedelta(hours=1),
                reason="logout",
            )
        )
        db_session.commit()

        from services.api.jobs.token_blacklist_cleanup import run_token_blacklist_cleanup

        result = run_token_blacklist_cleanup(db_session)

        assert result["status"] == "success"
        assert result["deleted_count"] == 0

    def test_cleanup_job_handles_empty_table(self, db_session: Session) -> None:
        """Cleanup on an empty table returns zero without error."""
        from services.api.jobs.token_blacklist_cleanup import run_token_blacklist_cleanup

        result = run_token_blacklist_cleanup(db_session)

        assert result["status"] == "success"
        assert result["deleted_count"] == 0

    def test_cleanup_job_purges_multiple_expired(self, db_session: Session) -> None:
        """Multiple expired entries are all purged in one call."""
        now = datetime.now(timezone.utc)
        for i in range(5):
            db_session.add(
                RevokedToken(
                    jti=f"expired-batch-{i:03d}",
                    revoked_at=now - timedelta(hours=10),
                    expires_at=now - timedelta(hours=i + 1),
                    reason="batch-test",
                )
            )
        db_session.commit()

        from services.api.jobs.token_blacklist_cleanup import run_token_blacklist_cleanup

        result = run_token_blacklist_cleanup(db_session)

        assert result["status"] == "success"
        assert result["deleted_count"] == 5

    def test_cleanup_job_handles_db_error_gracefully(self) -> None:
        """Database error during cleanup returns error status, does not raise."""
        mock_session = MagicMock(spec=Session)
        mock_session.execute.side_effect = RuntimeError("DB connection lost")

        from services.api.jobs.token_blacklist_cleanup import run_token_blacklist_cleanup

        result = run_token_blacklist_cleanup(mock_session)

        assert result["status"] == "error"
        assert "deleted_count" in result
        assert result["deleted_count"] == 0

    def test_cleanup_job_is_idempotent(self, db_session: Session) -> None:
        """Running cleanup twice yields zero on the second call."""
        now = datetime.now(timezone.utc)
        db_session.add(
            RevokedToken(
                jti="idempotent-jti-001",
                revoked_at=now - timedelta(hours=2),
                expires_at=now - timedelta(hours=1),
                reason="test",
            )
        )
        db_session.commit()

        from services.api.jobs.token_blacklist_cleanup import run_token_blacklist_cleanup

        result1 = run_token_blacklist_cleanup(db_session)
        assert result1["deleted_count"] == 1

        result2 = run_token_blacklist_cleanup(db_session)
        assert result2["deleted_count"] == 0


# ---------------------------------------------------------------------------
# H2.3 — Multi-key JWT_SECRET_KEY rotation support
# ---------------------------------------------------------------------------


class TestMultiKeyJWTRotation:
    """
    JWT validation must accept tokens signed with the current key OR the
    previous key during a rotation window.

    Rationale:
        Key rotation without multi-key support causes immediate 401 for all
        in-flight tokens. In a trading platform, this means every open
        session drops — potentially mid-trade. Supporting current + previous
        keys allows zero-downtime rotation:
            1. Set JWT_SECRET_KEY=newkey,oldkey (comma-separated)
            2. All new tokens signed with newkey
            3. Old tokens (signed with oldkey) still validate
            4. After old tokens expire (~30 min), remove oldkey from the list
    """

    def test_single_key_still_works(self) -> None:
        """When JWT_SECRET_KEY is a single key, behavior is unchanged."""
        secret = "a" * 48
        env = {
            "ENVIRONMENT": "production",
            "JWT_SECRET_KEY": secret,
        }
        with patch.dict(os.environ, env, clear=False):
            from services.api.auth import _get_signing_key, _get_validation_keys

            signing = _get_signing_key()
            assert signing == secret

            validation = _get_validation_keys()
            assert validation == [secret]

    def test_comma_separated_keys_returns_list(self) -> None:
        """JWT_SECRET_KEY=newkey,oldkey returns both for validation."""
        new_key = "n" * 48
        old_key = "o" * 48
        env = {
            "ENVIRONMENT": "production",
            "JWT_SECRET_KEY": f"{new_key},{old_key}",
        }
        with patch.dict(os.environ, env, clear=False):
            from services.api.auth import _get_signing_key, _get_validation_keys

            signing = _get_signing_key()
            assert signing == new_key, "Signing key must be the FIRST key"

            validation = _get_validation_keys()
            assert len(validation) == 2
            assert validation[0] == new_key
            assert validation[1] == old_key

    def test_token_signed_with_old_key_validates(self) -> None:
        """During rotation, tokens signed with the previous key are accepted."""
        old_key = "o" * 48
        new_key = "n" * 48
        # Sign a token with the OLD key
        now = datetime.now(timezone.utc)
        payload = {
            "sub": "01HABCDEF00000000000000000",
            "role": "operator",
            "email": "test@example.com",
            "scope": "strategies:write",
            "jti": "test-jti-rotation-001",
            "aud": "fxlab-api",
            "iss": "fxlab",
            "iat": now,
            "nbf": now,
            "exp": now + timedelta(minutes=30),
        }
        old_token = jwt.encode(payload, old_key, algorithm="HS256")

        env = {
            "ENVIRONMENT": "production",
            "JWT_SECRET_KEY": f"{new_key},{old_key}",
        }
        with (
            patch.dict(os.environ, env, clear=False),
            patch("services.api.auth._get_keycloak_validator", return_value=None),
            patch(
                "services.api.services.token_blacklist_service.TokenBlacklistService"
            ) as mock_blacklist_cls,
        ):
            mock_blacklist = MagicMock()
            mock_blacklist.is_revoked.return_value = False
            mock_blacklist_cls.return_value = mock_blacklist

            from services.api.auth import _validate_token

            user = _validate_token(old_token)
            assert user.user_id == "01HABCDEF00000000000000000"

    def test_token_signed_with_current_key_validates(self) -> None:
        """Tokens signed with the current (first) key validate normally."""
        new_key = "n" * 48
        old_key = "o" * 48
        now = datetime.now(timezone.utc)
        payload = {
            "sub": "01HABCDEF00000000000000000",
            "role": "operator",
            "email": "test@example.com",
            "scope": "strategies:write",
            "jti": "test-jti-rotation-002",
            "aud": "fxlab-api",
            "iss": "fxlab",
            "iat": now,
            "nbf": now,
            "exp": now + timedelta(minutes=30),
        }
        new_token = jwt.encode(payload, new_key, algorithm="HS256")

        env = {
            "ENVIRONMENT": "production",
            "JWT_SECRET_KEY": f"{new_key},{old_key}",
        }
        with (
            patch.dict(os.environ, env, clear=False),
            patch("services.api.auth._get_keycloak_validator", return_value=None),
            patch(
                "services.api.services.token_blacklist_service.TokenBlacklistService"
            ) as mock_blacklist_cls,
        ):
            mock_blacklist = MagicMock()
            mock_blacklist.is_revoked.return_value = False
            mock_blacklist_cls.return_value = mock_blacklist

            from services.api.auth import _validate_token

            user = _validate_token(new_token)
            assert user.user_id == "01HABCDEF00000000000000000"

    def test_token_signed_with_unknown_key_rejected(self) -> None:
        """Tokens signed with a key not in the rotation list are rejected."""
        new_key = "n" * 48
        old_key = "o" * 48
        rogue_key = "r" * 48

        now = datetime.now(timezone.utc)
        payload = {
            "sub": "01HABCDEF00000000000000000",
            "role": "operator",
            "aud": "fxlab-api",
            "iss": "fxlab",
            "iat": now,
            "nbf": now,
            "exp": now + timedelta(minutes=30),
        }
        rogue_token = jwt.encode(payload, rogue_key, algorithm="HS256")

        env = {
            "ENVIRONMENT": "production",
            "JWT_SECRET_KEY": f"{new_key},{old_key}",
        }
        from fastapi import HTTPException

        with (
            patch.dict(os.environ, env, clear=False),
            patch("services.api.auth._get_keycloak_validator", return_value=None),
        ):
            from services.api.auth import _validate_token

            with pytest.raises(HTTPException) as exc_info:
                _validate_token(rogue_token)
            assert exc_info.value.status_code == 401

    def test_signing_always_uses_first_key(self) -> None:
        """create_access_token must sign with the first (current) key."""
        new_key = "n" * 48
        old_key = "o" * 48
        env = {
            "ENVIRONMENT": "production",
            "JWT_SECRET_KEY": f"{new_key},{old_key}",
        }
        with patch.dict(os.environ, env, clear=False):
            from services.api.auth import create_access_token

            token = create_access_token(
                user_id="01HABCDEF00000000000000000",
                role="operator",
            )

            # Should decode with new_key
            payload = jwt.decode(
                token,
                new_key,
                algorithms=["HS256"],
                audience="fxlab-api",
                issuer="fxlab",
            )
            assert payload["sub"] == "01HABCDEF00000000000000000"

            # Should NOT decode with old_key
            with pytest.raises(jwt.InvalidSignatureError):
                jwt.decode(
                    token,
                    old_key,
                    algorithms=["HS256"],
                    audience="fxlab-api",
                    issuer="fxlab",
                )

    def test_minimum_key_length_enforced_for_each_key(self) -> None:
        """Each key in the comma-separated list must meet the 32-byte minimum."""
        env = {
            "ENVIRONMENT": "production",
            "JWT_SECRET_KEY": f"{'a' * 48},short",
        }
        with patch.dict(os.environ, env, clear=False):
            from services.api.auth import _get_validation_keys

            with pytest.raises(RuntimeError, match="32 bytes"):
                _get_validation_keys()

    def test_empty_key_in_list_rejected(self) -> None:
        """Trailing comma or empty key segment is rejected."""
        env = {
            "ENVIRONMENT": "production",
            "JWT_SECRET_KEY": f"{'a' * 48},",
        }
        with patch.dict(os.environ, env, clear=False):
            from services.api.auth import _get_validation_keys

            with pytest.raises(RuntimeError, match="empty"):
                _get_validation_keys()

    def test_max_three_keys_enforced(self) -> None:
        """At most 3 keys allowed (current + 2 previous) to bound validation cost."""
        keys = ",".join(["k" * 48 for _ in range(4)])
        env = {
            "ENVIRONMENT": "production",
            "JWT_SECRET_KEY": keys,
        }
        with patch.dict(os.environ, env, clear=False):
            from services.api.auth import _get_validation_keys

            with pytest.raises(RuntimeError, match="3"):
                _get_validation_keys()


# ---------------------------------------------------------------------------
# H2.8 — Idempotency key window reduced to 1 hour + GC
# ---------------------------------------------------------------------------


class TestIdempotencyWindowReduction:
    """
    Idempotency key window must be 1 hour (reduced from 24 hours).

    Rationale:
        A 24-hour window consumes excessive memory and increases the chance
        of stale collisions — a legitimate retry 6 hours later would
        incorrectly replay a cached response from the morning session.
        For a trading platform, 1 hour is a conservative upper bound for
        retry scenarios.
    """

    def test_default_window_is_3600_seconds(self) -> None:
        """_WINDOW_SECONDS default should be 3600 (1 hour), not 86400."""
        # Clear env to test the default
        env_clean = {k: v for k, v in os.environ.items() if k != "IDEMPOTENCY_WINDOW"}
        with patch.dict(os.environ, env_clean, clear=True):
            # Force reimport to pick up default
            import importlib

            import services.api.middleware.idempotency as idem_mod

            importlib.reload(idem_mod)
            assert idem_mod._WINDOW_SECONDS == 3600, (
                f"Default idempotency window should be 3600s (1h), got {idem_mod._WINDOW_SECONDS}s"
            )

    def test_window_configurable_via_env(self) -> None:
        """IDEMPOTENCY_WINDOW env var overrides the default."""
        with patch.dict(os.environ, {"IDEMPOTENCY_WINDOW": "7200"}, clear=False):
            import importlib

            import services.api.middleware.idempotency as idem_mod

            importlib.reload(idem_mod)
            assert idem_mod._WINDOW_SECONDS == 7200

    def test_store_gc_removes_expired_entries(self) -> None:
        """IdempotencyStore GC should remove entries older than window."""
        import time

        from services.api.middleware.idempotency import IdempotencyStore

        store = IdempotencyStore(window_seconds=10)
        # Insert a "response" with a timestamp in the past
        with store._lock:
            store._store["old-key"] = (200, b"body", {}, time.time() - 20)
            store._store["fresh-key"] = (200, b"body", {}, time.time())

        # Trigger GC by starting a new request
        store.start_request("trigger-key")
        store.finish_request("trigger-key")

        cached_old = store.get_cached_response("old-key")
        cached_fresh = store.get_cached_response("fresh-key")

        assert cached_old is None, "Expired entry should be GC'd"
        assert cached_fresh is not None, "Fresh entry should survive GC"
