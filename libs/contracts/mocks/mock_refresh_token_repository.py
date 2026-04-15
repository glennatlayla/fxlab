"""
In-memory mock refresh token repository for unit testing.

Purpose:
    Provide a lightweight, in-memory implementation of
    RefreshTokenRepositoryInterface for use in unit tests without
    database dependencies.

Responsibilities:
    - Store refresh token records in a dict keyed by id.
    - Maintain a secondary index by token_hash for fast lookup.
    - Honour the same interface contract as SqlRefreshTokenRepository.

Does NOT:
    - Persist data between test runs.
    - Enforce database-level constraints (unique, FK).

Dependencies:
    - libs.contracts.interfaces.refresh_token_repository.RefreshTokenRepositoryInterface.
    - libs.contracts.errors: NotFoundError.

Example:
    repo = MockRefreshTokenRepository()
    repo.create(token_id="01...", user_id="01...", token_hash="abc...", expires_at=dt)
    assert repo.count() == 1
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from libs.contracts.errors import NotFoundError
from libs.contracts.interfaces.refresh_token_repository import (
    RefreshTokenRepositoryInterface,
)


class MockRefreshTokenRepository(RefreshTokenRepositoryInterface):
    """
    In-memory implementation of RefreshTokenRepositoryInterface for testing.

    Provides introspection helpers (get_all, count, clear) to simplify
    test assertions.

    Example:
        repo = MockRefreshTokenRepository()
        repo.create(token_id="T1", user_id="U1", token_hash="h1", expires_at=exp)
        assert repo.find_by_hash("h1") is not None
    """

    def __init__(self) -> None:
        self._store: dict[str, dict[str, Any]] = {}
        self._hash_index: dict[str, str] = {}  # token_hash → token_id

    def create(
        self,
        *,
        token_id: str,
        user_id: str,
        token_hash: str,
        expires_at: datetime,
    ) -> dict[str, Any]:
        """Persist a new refresh token record in memory."""
        record = {
            "id": token_id,
            "user_id": user_id,
            "token_hash": token_hash,
            "expires_at": expires_at,
            "revoked_at": None,
            "created_at": datetime.now(timezone.utc),
        }
        self._store[token_id] = record
        self._hash_index[token_hash] = token_id
        return dict(record)

    def find_by_hash(self, token_hash: str) -> dict[str, Any] | None:
        """Look up a refresh token by its SHA-256 hash."""
        token_id = self._hash_index.get(token_hash)
        if token_id is None:
            return None
        record = self._store.get(token_id)
        if record is None:
            return None
        return dict(record)

    def revoke(self, token_id: str) -> None:
        """Mark a single refresh token as revoked."""
        if token_id not in self._store:
            raise NotFoundError(f"Refresh token {token_id} not found")
        self._store[token_id]["revoked_at"] = datetime.now(timezone.utc)

    def revoke_all_for_user(self, user_id: str) -> int:
        """Revoke all active tokens for a user."""
        now = datetime.now(timezone.utc)
        count = 0
        for record in self._store.values():
            if record["user_id"] == user_id and record["revoked_at"] is None:
                record["revoked_at"] = now
                count += 1
        return count

    def delete_expired(self) -> int:
        """Delete all expired tokens."""
        now = datetime.now(timezone.utc)
        expired_ids = [tid for tid, rec in self._store.items() if rec["expires_at"] < now]
        for tid in expired_ids:
            rec = self._store.pop(tid)
            self._hash_index.pop(rec["token_hash"], None)
        return len(expired_ids)

    # --- Introspection helpers for tests ---

    def get_all(self) -> list[dict[str, Any]]:
        """Return all stored token records."""
        return [dict(r) for r in self._store.values()]

    def count(self) -> int:
        """Return the number of stored tokens."""
        return len(self._store)

    def clear(self) -> None:
        """Remove all stored tokens."""
        self._store.clear()
        self._hash_index.clear()
