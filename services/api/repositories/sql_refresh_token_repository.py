"""
SQL-backed refresh token repository for OIDC token endpoint.

Purpose:
    Persist and query refresh token hashes in PostgreSQL/SQLite via
    SQLAlchemy, implementing RefreshTokenRepositoryInterface.

Responsibilities:
    - CRUD operations on the refresh_tokens table.
    - Revoke individual tokens or all tokens for a user.
    - Purge expired tokens for housekeeping.

Does NOT:
    - Hash tokens (callers provide pre-hashed values).
    - Enforce business rules (service layer responsibility).
    - Call session.commit() — uses flush() for request-scoped transactions.

Dependencies:
    - SQLAlchemy Session (injected).
    - libs.contracts.models.RefreshToken ORM model.
    - libs.contracts.interfaces.refresh_token_repository.RefreshTokenRepositoryInterface.

Error conditions:
    - revoke() raises NotFoundError when token_id does not exist.

Example:
    repo = SqlRefreshTokenRepository(db=session)
    repo.create(token_id="01...", user_id="01...", token_hash="abc...", expires_at=dt)
    record = repo.find_by_hash("abc...")
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import structlog
from sqlalchemy.orm import Session

from libs.contracts.errors import NotFoundError
from libs.contracts.interfaces.refresh_token_repository import (
    RefreshTokenRepositoryInterface,
)
from libs.contracts.models import RefreshToken

logger = structlog.get_logger(__name__)


class SqlRefreshTokenRepository(RefreshTokenRepositoryInterface):
    """
    SQLAlchemy implementation of RefreshTokenRepositoryInterface.

    Responsibilities:
    - Map between ORM RefreshToken rows and plain dicts.
    - Use session.flush() (not commit) for request-scoped transaction.

    Does NOT:
    - Contain business logic or hashing logic.

    Dependencies:
    - SQLAlchemy Session (injected via constructor).

    Example:
        repo = SqlRefreshTokenRepository(db=session)
        repo.create(token_id=ulid, user_id=uid, token_hash=h, expires_at=exp)
    """

    def __init__(self, db: Session) -> None:
        self._db = db

    @staticmethod
    def _to_dict(row: RefreshToken) -> dict[str, Any]:
        """Convert ORM row to plain dict."""
        return {
            "id": row.id,
            "user_id": row.user_id,
            "token_hash": row.token_hash,
            "expires_at": row.expires_at,
            "revoked_at": row.revoked_at,
            "created_at": row.created_at,
        }

    def create(
        self,
        *,
        token_id: str,
        user_id: str,
        token_hash: str,
        expires_at: datetime,
    ) -> dict[str, Any]:
        """
        Persist a new refresh token record.

        Args:
            token_id: ULID primary key for the token record.
            user_id: ULID of the user who owns this token.
            token_hash: SHA-256 hex digest of the plaintext refresh token.
            expires_at: Absolute UTC expiry timestamp.

        Returns:
            Dict with id, user_id, token_hash, expires_at, created_at.

        Example:
            result = repo.create(
                token_id="01ABC...", user_id="01DEF...",
                token_hash="deadbeef...", expires_at=datetime(2026, 4, 9)
            )
        """
        row = RefreshToken(
            id=token_id,
            user_id=user_id,
            token_hash=token_hash,
            expires_at=expires_at,
        )
        self._db.add(row)
        self._db.flush()
        logger.debug(
            "refresh_token.created",
            token_id=token_id,
            user_id=user_id,
            component="SqlRefreshTokenRepository",
        )
        return self._to_dict(row)

    def find_by_hash(self, token_hash: str) -> dict[str, Any] | None:
        """
        Look up a refresh token by its SHA-256 hash.

        Args:
            token_hash: SHA-256 hex digest to search for.

        Returns:
            Dict with token details, or None if not found.

        Example:
            record = repo.find_by_hash("deadbeef...")
        """
        row = self._db.query(RefreshToken).filter(RefreshToken.token_hash == token_hash).first()
        if row is None:
            return None
        return self._to_dict(row)

    def revoke(self, token_id: str) -> None:
        """
        Mark a single refresh token as revoked.

        Args:
            token_id: ULID primary key of the token to revoke.

        Raises:
            NotFoundError: If token_id does not exist.

        Example:
            repo.revoke("01ABC...")
        """
        row = self._db.query(RefreshToken).filter(RefreshToken.id == token_id).first()
        if row is None:
            raise NotFoundError(f"Refresh token {token_id} not found")
        row.revoked_at = datetime.now(timezone.utc)
        self._db.flush()
        logger.debug(
            "refresh_token.revoked",
            token_id=token_id,
            component="SqlRefreshTokenRepository",
        )

    def revoke_all_for_user(self, user_id: str) -> int:
        """
        Revoke all active (non-revoked) refresh tokens for a user.

        Args:
            user_id: ULID of the user whose tokens to revoke.

        Returns:
            Number of tokens revoked.

        Example:
            count = repo.revoke_all_for_user("01DEF...")
        """
        now = datetime.now(timezone.utc)
        count = (
            self._db.query(RefreshToken)
            .filter(
                RefreshToken.user_id == user_id,
                RefreshToken.revoked_at.is_(None),
            )
            .update({"revoked_at": now})
        )
        self._db.flush()
        logger.debug(
            "refresh_token.revoked_all",
            user_id=user_id,
            count=count,
            component="SqlRefreshTokenRepository",
        )
        return count

    def delete_expired(self) -> int:
        """
        Delete all refresh tokens that have passed their expires_at time.

        Returns:
            Number of tokens deleted.

        Example:
            purged = repo.delete_expired()
        """
        now = datetime.now(timezone.utc)
        count = self._db.query(RefreshToken).filter(RefreshToken.expires_at < now).delete()
        self._db.flush()
        logger.debug(
            "refresh_token.expired_purged",
            count=count,
            component="SqlRefreshTokenRepository",
        )
        return count
