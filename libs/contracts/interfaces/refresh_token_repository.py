"""
RefreshTokenRepositoryInterface — port for OIDC refresh token storage.

Purpose:
    Define the contract that all refresh token repository implementations
    must honour, enabling the auth service to depend on an abstraction
    rather than a concrete database adapter.

Responsibilities:
    - create() → persist a new hashed refresh token.
    - find_by_hash() → look up a token record by its SHA-256 hash.
    - revoke() → mark a single token as revoked.
    - revoke_all_for_user() → revoke all tokens for a given user.
    - delete_expired() → purge tokens past their expiry (housekeeping).

Does NOT:
    - Hash tokens (callers must provide pre-hashed values).
    - Validate business rules (service layer responsibility).
    - Create or sign JWTs.

Dependencies:
    - libs.contracts.errors: NotFoundError.
    - libs.contracts.models: RefreshToken ORM model (for SQL impl).

Error conditions:
    - find_by_hash returns None when no matching token exists.
    - revoke raises NotFoundError when token_id does not exist.

Example:
    class SqlRefreshTokenRepository(RefreshTokenRepositoryInterface):
        def create(self, ...) -> dict: ...
        def find_by_hash(self, token_hash) -> dict | None: ...
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime
from typing import Any


class RefreshTokenRepositoryInterface(ABC):
    """
    Abstract port for refresh token data access.

    Implementations:
    - MockRefreshTokenRepository — in-memory, for unit tests
    - SqlRefreshTokenRepository  — SQLAlchemy-backed, for production
    """

    @abstractmethod
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
            Dict with at least id, user_id, token_hash, expires_at, created_at.
        """
        ...

    @abstractmethod
    def find_by_hash(self, token_hash: str) -> dict[str, Any] | None:
        """
        Look up a refresh token by its SHA-256 hash.

        Args:
            token_hash: SHA-256 hex digest to search for.

        Returns:
            Dict with token details, or None if no matching token exists.
        """
        ...

    @abstractmethod
    def revoke(self, token_id: str) -> None:
        """
        Mark a single refresh token as revoked.

        Args:
            token_id: ULID primary key of the token to revoke.

        Raises:
            NotFoundError: If token_id does not exist.
        """
        ...

    @abstractmethod
    def revoke_all_for_user(self, user_id: str) -> int:
        """
        Revoke all active refresh tokens for a given user.

        Args:
            user_id: ULID of the user whose tokens to revoke.

        Returns:
            Number of tokens revoked.
        """
        ...

    @abstractmethod
    def delete_expired(self) -> int:
        """
        Delete all refresh tokens that have passed their expires_at time.

        Returns:
            Number of tokens deleted.
        """
        ...
