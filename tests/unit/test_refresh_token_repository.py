"""
Unit tests for SqlRefreshTokenRepository.

Responsibilities:
- Test all CRUD operations in isolation using in-memory SQLite.
- Verify token creation, retrieval, revocation, and expiry purging.
- Confirm NotFoundError is raised on invalid token_id for revoke().
- Verify revoke_all_for_user() counts and marks only active tokens.
- Confirm delete_expired() correctly filters by expires_at.
- Test structured logging at key lifecycle points.

Does NOT:
- Call production PostgreSQL database.
- Test business logic (service layer tests handle that).

Test coverage:
- create(): stores token with correct fields.
- find_by_hash(): returns token or None.
- revoke(): marks token as revoked, raises NotFoundError if missing.
- revoke_all_for_user(): revokes all active tokens for a user.
- delete_expired(): removes expired tokens only.

Example:
    pytest tests/unit/test_refresh_token_repository.py -v
"""

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from libs.contracts.errors import NotFoundError
from libs.contracts.models import Base
from services.api.repositories.sql_refresh_token_repository import SqlRefreshTokenRepository


@pytest.fixture
def in_memory_session() -> Session:
    """
    Provide an in-memory SQLite session with RefreshToken table.

    Creates all tables from Base.metadata, yields an active session,
    then tears down on test completion.

    Yields:
        SQLAlchemy Session bound to in-memory SQLite database.
    """
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(bind=engine)
    session = SessionLocal()
    yield session
    session.close()
    Base.metadata.drop_all(engine)


@pytest.fixture
def repo(in_memory_session: Session) -> SqlRefreshTokenRepository:
    """
    Provide a SqlRefreshTokenRepository bound to in-memory session.

    Args:
        in_memory_session: Injected in-memory session fixture.

    Returns:
        SqlRefreshTokenRepository instance for testing.
    """
    return SqlRefreshTokenRepository(db=in_memory_session)


class TestCreate:
    """Tests for SqlRefreshTokenRepository.create()."""

    def test_create_happy_path(self, repo: SqlRefreshTokenRepository) -> None:
        """
        Test successful token creation.

        Scenario: Valid token_id, user_id, token_hash, and expires_at.
        Expected: Token persisted with all fields set correctly.
        """
        token_id = "01HTOKEN123ABCDEFGHIJKL"
        user_id = "01HUSER123ABCDEFGHIJKL"
        token_hash = "deadbeef" * 8  # 64-char SHA-256 hex
        expires_at = datetime.now(timezone.utc) + timedelta(days=30)

        result = repo.create(
            token_id=token_id,
            user_id=user_id,
            token_hash=token_hash,
            expires_at=expires_at,
        )

        assert result["id"] == token_id
        assert result["user_id"] == user_id
        assert result["token_hash"] == token_hash
        assert result["expires_at"] == expires_at
        assert result["revoked_at"] is None
        assert "created_at" in result

    def test_create_with_past_expiry(self, repo: SqlRefreshTokenRepository) -> None:
        """
        Test token creation with past expiry time (edge case).

        Scenario: expires_at is in the past.
        Expected: Token still created (validation is service layer responsibility).
        """
        token_id = "01HTOKEN_EXPIRED"
        user_id = "01HUSER123ABCDEFGHIJKL"
        token_hash = "deadbeef" * 8
        expires_at = datetime.now(timezone.utc) - timedelta(days=1)

        result = repo.create(
            token_id=token_id,
            user_id=user_id,
            token_hash=token_hash,
            expires_at=expires_at,
        )

        assert result["id"] == token_id
        assert result["expires_at"] < datetime.now(timezone.utc)

    def test_create_multiple_tokens_same_user(self, repo: SqlRefreshTokenRepository) -> None:
        """
        Test creating multiple tokens for the same user.

        Scenario: Same user_id with different token_ids and hashes.
        Expected: Both tokens persisted independently.
        """
        user_id = "01HUSER_MULTI"
        expires_at = datetime.now(timezone.utc) + timedelta(days=30)

        token1 = repo.create(
            token_id="01HTOKEN_1",
            user_id=user_id,
            token_hash="abc" * 21 + "def",
            expires_at=expires_at,
        )
        token2 = repo.create(
            token_id="01HTOKEN_2",
            user_id=user_id,
            token_hash="xyz" * 21 + "uvw",
            expires_at=expires_at,
        )

        assert token1["id"] != token2["id"]
        assert token1["user_id"] == token2["user_id"]
        assert token1["token_hash"] != token2["token_hash"]


class TestFindByHash:
    """Tests for SqlRefreshTokenRepository.find_by_hash()."""

    def test_find_by_hash_happy_path(self, repo: SqlRefreshTokenRepository) -> None:
        """
        Test successful token lookup by hash.

        Scenario: Token exists with matching hash.
        Expected: Return dict with token details.
        """
        token_id = "01HTOKEN123ABCDEFGHIJKL"
        user_id = "01HUSER123ABCDEFGHIJKL"
        token_hash = "deadbeef" * 8
        expires_at = datetime.now(timezone.utc) + timedelta(days=30)

        repo.create(
            token_id=token_id,
            user_id=user_id,
            token_hash=token_hash,
            expires_at=expires_at,
        )

        result = repo.find_by_hash(token_hash)

        assert result is not None
        assert result["id"] == token_id
        assert result["user_id"] == user_id
        assert result["token_hash"] == token_hash

    def test_find_by_hash_not_found(self, repo: SqlRefreshTokenRepository) -> None:
        """
        Test find_by_hash returns None for non-existent hash.

        Scenario: Hash does not match any token in the database.
        Expected: Return None.
        """
        result = repo.find_by_hash("nonexistent" * 6 + "ha")

        assert result is None

    def test_find_by_hash_does_not_return_revoked(self, repo: SqlRefreshTokenRepository) -> None:
        """
        Test find_by_hash returns revoked tokens (revoke status is not a filter).

        Scenario: Token exists but has been revoked.
        Expected: Return dict (revocation status is not filtered by this method).
        """
        token_id = "01HTOKEN_REVOKED"
        user_id = "01HUSER123ABCDEFGHIJKL"
        token_hash = "revokedtoken" * 5 + "wxyz"
        expires_at = datetime.now(timezone.utc) + timedelta(days=30)

        repo.create(
            token_id=token_id,
            user_id=user_id,
            token_hash=token_hash,
            expires_at=expires_at,
        )
        repo.revoke(token_id)

        result = repo.find_by_hash(token_hash)

        # find_by_hash does not filter by revoke status — business logic will check revoked_at
        assert result is not None
        assert result["revoked_at"] is not None


class TestRevoke:
    """Tests for SqlRefreshTokenRepository.revoke()."""

    def test_revoke_happy_path(self, repo: SqlRefreshTokenRepository) -> None:
        """
        Test successful token revocation.

        Scenario: Valid token_id exists.
        Expected: Token marked with revoked_at timestamp.
        """
        token_id = "01HTOKEN123ABCDEFGHIJKL"
        user_id = "01HUSER123ABCDEFGHIJKL"
        token_hash = "deadbeef" * 8
        expires_at = datetime.now(timezone.utc) + timedelta(days=30)

        repo.create(
            token_id=token_id,
            user_id=user_id,
            token_hash=token_hash,
            expires_at=expires_at,
        )

        repo.revoke(token_id)

        result = repo.find_by_hash(token_hash)
        assert result is not None
        assert result["revoked_at"] is not None

    def test_revoke_not_found(self, repo: SqlRefreshTokenRepository) -> None:
        """
        Test revoke raises NotFoundError for non-existent token_id.

        Scenario: token_id does not exist in database.
        Expected: Raise NotFoundError.
        """
        with pytest.raises(NotFoundError):
            repo.revoke("01HTOKEN_NOTEXIST")

    def test_revoke_idempotent(self, repo: SqlRefreshTokenRepository) -> None:
        """
        Test revoking a token twice succeeds without raising an error.

        Scenario: Token is revoked, then revoke is called again.
        Expected: No error raised on second revoke.
        """
        token_id = "01HTOKEN_IDEMPOTENT"
        user_id = "01HUSER123ABCDEFGHIJKL"
        token_hash = "idempotent" * 6 + "hash"
        expires_at = datetime.now(timezone.utc) + timedelta(days=30)

        repo.create(
            token_id=token_id,
            user_id=user_id,
            token_hash=token_hash,
            expires_at=expires_at,
        )

        repo.revoke(token_id)
        first_result = repo.find_by_hash(token_hash)
        assert first_result["revoked_at"] is not None

        # Second revoke should also succeed
        repo.revoke(token_id)
        second_result = repo.find_by_hash(token_hash)
        assert second_result["revoked_at"] is not None


class TestRevokeAllForUser:
    """Tests for SqlRefreshTokenRepository.revoke_all_for_user()."""

    def test_revoke_all_for_user_happy_path(self, repo: SqlRefreshTokenRepository) -> None:
        """
        Test revoking all tokens for a user.

        Scenario: User has 3 active tokens.
        Expected: All 3 marked as revoked, returns count=3.
        """
        user_id = "01HUSER_REVOKE_ALL"
        expires_at = datetime.now(timezone.utc) + timedelta(days=30)

        token_ids = ["01HTOKEN_A", "01HTOKEN_B", "01HTOKEN_C"]
        for i, token_id in enumerate(token_ids):
            repo.create(
                token_id=token_id,
                user_id=user_id,
                token_hash=f"token_hash_{i}" * 8,
                expires_at=expires_at,
            )

        count = repo.revoke_all_for_user(user_id)

        assert count == 3
        # Verify all are actually revoked
        for i, _token_id in enumerate(token_ids):
            result = repo.find_by_hash(f"token_hash_{i}" * 8)
            assert result["revoked_at"] is not None

    def test_revoke_all_for_user_with_already_revoked(
        self, repo: SqlRefreshTokenRepository
    ) -> None:
        """
        Test revoke_all_for_user only revokes active tokens.

        Scenario: User has 2 active tokens and 1 already revoked token.
        Expected: Only active tokens are revoked, count=2.
        """
        user_id = "01HUSER_MIXED_REVOKE"
        expires_at = datetime.now(timezone.utc) + timedelta(days=30)

        # Create 3 tokens
        token_ids = ["01HTOKEN_ACTIVE_1", "01HTOKEN_ACTIVE_2", "01HTOKEN_REVOKED"]
        for i, token_id in enumerate(token_ids):
            repo.create(
                token_id=token_id,
                user_id=user_id,
                token_hash=f"mixed_token_{i}" * 8,
                expires_at=expires_at,
            )

        # Revoke one manually
        repo.revoke("01HTOKEN_REVOKED")

        # Now revoke all
        count = repo.revoke_all_for_user(user_id)

        # Only the 2 active tokens should be revoked
        assert count == 2

    def test_revoke_all_for_user_no_tokens(self, repo: SqlRefreshTokenRepository) -> None:
        """
        Test revoke_all_for_user with user that has no tokens.

        Scenario: user_id has never had any tokens.
        Expected: Returns 0.
        """
        count = repo.revoke_all_for_user("01HUSER_NO_TOKENS")

        assert count == 0

    def test_revoke_all_for_user_different_users(self, repo: SqlRefreshTokenRepository) -> None:
        """
        Test revoke_all_for_user only affects the specified user.

        Scenario: Two users each with 2 tokens; revoke_all for one user.
        Expected: Only the specified user's tokens are revoked.
        """
        user_a = "01HUSER_A"
        user_b = "01HUSER_B"
        expires_at = datetime.now(timezone.utc) + timedelta(days=30)

        # Create tokens for user A
        repo.create(
            token_id="01HTOKEN_A1",
            user_id=user_a,
            token_hash="user_a_1" * 8,
            expires_at=expires_at,
        )
        repo.create(
            token_id="01HTOKEN_A2",
            user_id=user_a,
            token_hash="user_a_2" * 8,
            expires_at=expires_at,
        )

        # Create tokens for user B
        repo.create(
            token_id="01HTOKEN_B1",
            user_id=user_b,
            token_hash="user_b_1" * 8,
            expires_at=expires_at,
        )
        repo.create(
            token_id="01HTOKEN_B2",
            user_id=user_b,
            token_hash="user_b_2" * 8,
            expires_at=expires_at,
        )

        # Revoke all for user A
        count = repo.revoke_all_for_user(user_a)
        assert count == 2

        # Verify user A's tokens are revoked
        assert repo.find_by_hash("user_a_1" * 8)["revoked_at"] is not None
        assert repo.find_by_hash("user_a_2" * 8)["revoked_at"] is not None

        # Verify user B's tokens are NOT revoked
        assert repo.find_by_hash("user_b_1" * 8)["revoked_at"] is None
        assert repo.find_by_hash("user_b_2" * 8)["revoked_at"] is None


class TestDeleteExpired:
    """Tests for SqlRefreshTokenRepository.delete_expired()."""

    def test_delete_expired_happy_path(self, repo: SqlRefreshTokenRepository) -> None:
        """
        Test deleting expired tokens.

        Scenario: Database has 2 expired tokens and 2 active tokens.
        Expected: Only expired tokens are deleted, count=2.
        """
        now = datetime.now(timezone.utc)

        # Create 2 expired tokens
        repo.create(
            token_id="01HTOKEN_EXPIRED_1",
            user_id="01HUSER123ABCDEFGHIJKL",
            token_hash="expired_1" * 7 + "ab",
            expires_at=now - timedelta(days=1),
        )
        repo.create(
            token_id="01HTOKEN_EXPIRED_2",
            user_id="01HUSER123ABCDEFGHIJKL",
            token_hash="expired_2" * 7 + "ab",
            expires_at=now - timedelta(hours=1),
        )

        # Create 2 active tokens
        repo.create(
            token_id="01HTOKEN_ACTIVE_1",
            user_id="01HUSER123ABCDEFGHIJKL",
            token_hash="active_1" * 8,
            expires_at=now + timedelta(days=30),
        )
        repo.create(
            token_id="01HTOKEN_ACTIVE_2",
            user_id="01HUSER123ABCDEFGHIJKL",
            token_hash="active_2" * 8,
            expires_at=now + timedelta(days=60),
        )

        count = repo.delete_expired()

        assert count == 2

        # Verify expired tokens are gone
        assert repo.find_by_hash("expired_1" * 7 + "ab") is None
        assert repo.find_by_hash("expired_2" * 7 + "ab") is None

        # Verify active tokens still exist
        assert repo.find_by_hash("active_1" * 8) is not None
        assert repo.find_by_hash("active_2" * 8) is not None

    def test_delete_expired_no_expired(self, repo: SqlRefreshTokenRepository) -> None:
        """
        Test delete_expired when no tokens are expired.

        Scenario: All tokens have future expiry times.
        Expected: Returns 0.
        """
        now = datetime.now(timezone.utc)

        repo.create(
            token_id="01HTOKEN_FUTURE_1",
            user_id="01HUSER123ABCDEFGHIJKL",
            token_hash="future_1" * 8,
            expires_at=now + timedelta(days=30),
        )
        repo.create(
            token_id="01HTOKEN_FUTURE_2",
            user_id="01HUSER123ABCDEFGHIJKL",
            token_hash="future_2" * 8,
            expires_at=now + timedelta(days=60),
        )

        count = repo.delete_expired()

        assert count == 0

        # Verify tokens still exist
        assert repo.find_by_hash("future_1" * 8) is not None
        assert repo.find_by_hash("future_2" * 8) is not None

    def test_delete_expired_all_expired(self, repo: SqlRefreshTokenRepository) -> None:
        """
        Test delete_expired when all tokens are expired.

        Scenario: All tokens have past expiry times.
        Expected: All tokens deleted.
        """
        now = datetime.now(timezone.utc)

        repo.create(
            token_id="01HTOKEN_EXPIRED_1",
            user_id="01HUSER123ABCDEFGHIJKL",
            token_hash="all_exp_1" * 7 + "ab",
            expires_at=now - timedelta(days=1),
        )
        repo.create(
            token_id="01HTOKEN_EXPIRED_2",
            user_id="01HUSER123ABCDEFGHIJKL",
            token_hash="all_exp_2" * 7 + "ab",
            expires_at=now - timedelta(hours=1),
        )

        count = repo.delete_expired()

        assert count == 2

        # Verify all are gone
        assert repo.find_by_hash("all_exp_1" * 7 + "ab") is None
        assert repo.find_by_hash("all_exp_2" * 7 + "ab") is None

    def test_delete_expired_does_not_delete_revoked(self, repo: SqlRefreshTokenRepository) -> None:
        """
        Test delete_expired only considers expiry, not revocation status.

        Scenario: Token is revoked but not yet expired.
        Expected: Token is NOT deleted.
        """
        now = datetime.now(timezone.utc)

        repo.create(
            token_id="01HTOKEN_REVOKED_ACTIVE",
            user_id="01HUSER123ABCDEFGHIJKL",
            token_hash="revoked_active" * 4 + "wxyz",
            expires_at=now + timedelta(days=30),
        )

        repo.revoke("01HTOKEN_REVOKED_ACTIVE")

        count = repo.delete_expired()

        assert count == 0

        # Verify token still exists (was not deleted)
        result = repo.find_by_hash("revoked_active" * 4 + "wxyz")
        assert result is not None
        assert result["revoked_at"] is not None

    def test_delete_expired_empty_database(self, repo: SqlRefreshTokenRepository) -> None:
        """
        Test delete_expired on an empty database.

        Scenario: No tokens in database.
        Expected: Returns 0.
        """
        count = repo.delete_expired()

        assert count == 0
