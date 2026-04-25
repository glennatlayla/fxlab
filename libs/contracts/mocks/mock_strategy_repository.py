"""
In-memory mock strategy repository for unit testing.

Responsibilities:
- Implement StrategyRepositoryInterface with dict-backed storage.
- Provide introspection helpers (get_all, count, clear) for test assertions.
- Generate ULID-format IDs for new records.

Does NOT:
- Persist data across process restarts.
- Enforce referential integrity (no FK checks).

Dependencies:
- None (pure in-memory implementation).

Example:
    repo = MockStrategyRepository()
    strategy = repo.create(name="Test", code="RSI(14) < 30", created_by="01HUSER001")
    assert repo.count() == 1
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from ulid import ULID

from libs.contracts.interfaces.strategy_repository_interface import (
    StrategyRepositoryInterface,
)


class MockStrategyRepository(StrategyRepositoryInterface):
    """
    In-memory strategy repository for unit testing.

    Responsibilities:
    - CRUD operations on an in-memory dict store.
    - Introspection methods for test assertions.

    Does NOT:
    - Persist state durably (by design — test scope only).
    - Validate foreign keys or enforce referential integrity.

    Example:
        repo = MockStrategyRepository()
        s = repo.create(name="Test", code="RSI(14) < 30", created_by="u1")
        assert repo.get_by_id(s["id"]) is not None
    """

    def __init__(self) -> None:
        self._store: dict[str, dict[str, Any]] = {}

    def create(
        self,
        *,
        name: str,
        code: str,
        created_by: str,
        version: str | None = None,
        source: str = "draft_form",
    ) -> dict[str, Any]:
        """
        Create a strategy in the in-memory store.

        Args:
            name: Strategy name.
            code: Strategy source code or IR JSON body.
            created_by: Creator ULID.
            version: Optional version string.
            source: Provenance flag (``"draft_form"`` | ``"ir_upload"``).
                Mirrors the SQL repo's ``chk_strategies_source`` CHECK
                constraint (migration 0025).

        Returns:
            Dict with all strategy fields, including ``source``.

        Raises:
            ValueError: If ``source`` is not one of the allowed values.
                Mirrors the SQL CHECK constraint at the mock layer so
                bad callers fail loudly in unit tests too.
        """
        if source not in ("draft_form", "ir_upload"):
            raise ValueError(f"Invalid source {source!r}: expected 'draft_form' or 'ir_upload'")
        now = datetime.now(timezone.utc)
        strategy_id = str(ULID())
        record: dict[str, Any] = {
            "id": strategy_id,
            "name": name,
            "code": code,
            "version": version or "0.1.0",
            "created_by": created_by,
            "is_active": True,
            "row_version": 1,
            "source": source,
            "created_at": now.isoformat(),
            "updated_at": now.isoformat(),
        }
        self._store[strategy_id] = record
        return dict(record)

    def get_by_id(self, strategy_id: str) -> dict[str, Any] | None:
        """
        Retrieve strategy by ID from in-memory store.

        Args:
            strategy_id: ULID.

        Returns:
            Strategy dict or None.
        """
        record = self._store.get(strategy_id)
        return dict(record) if record else None

    def list_strategies(
        self,
        *,
        created_by: str | None = None,
        is_active: bool | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        """
        List strategies with optional filtering and pagination.

        Args:
            created_by: Filter by creator ULID.
            is_active: Filter by active status.
            limit: Maximum results.
            offset: Pagination offset.

        Returns:
            List of strategy dicts, most recent first.
        """
        results = list(self._store.values())

        if created_by is not None:
            results = [r for r in results if r["created_by"] == created_by]
        if is_active is not None:
            results = [r for r in results if r["is_active"] == is_active]

        # Sort by created_at descending
        results.sort(key=lambda r: r["created_at"], reverse=True)
        return [dict(r) for r in results[offset : offset + limit]]

    def update(
        self,
        strategy_id: str,
        *,
        name: str | None = None,
        code: str | None = None,
        version: str | None = None,
        is_active: bool | None = None,
    ) -> dict[str, Any] | None:
        """
        Update strategy fields in the in-memory store.

        Args:
            strategy_id: ULID.
            name: New name (optional).
            code: New code (optional).
            version: New version (optional).
            is_active: New active flag (optional).

        Returns:
            Updated strategy dict or None if not found.
        """
        record = self._store.get(strategy_id)
        if record is None:
            return None

        if name is not None:
            record["name"] = name
        if code is not None:
            record["code"] = code
        if version is not None:
            record["version"] = version
        if is_active is not None:
            record["is_active"] = is_active

        record["row_version"] = record["row_version"] + 1
        record["updated_at"] = datetime.now(timezone.utc).isoformat()
        return dict(record)

    def deactivate(self, strategy_id: str) -> bool:
        """
        Soft-delete by setting is_active=False.

        Args:
            strategy_id: ULID.

        Returns:
            True if found and deactivated, False otherwise.
        """
        record = self._store.get(strategy_id)
        if record is None:
            return False

        record["is_active"] = False
        record["row_version"] = record["row_version"] + 1
        record["updated_at"] = datetime.now(timezone.utc).isoformat()
        return True

    # ------------------------------------------------------------------
    # Introspection helpers for tests
    # ------------------------------------------------------------------

    def get_all(self) -> list[dict[str, Any]]:
        """Return all strategies in the store."""
        return [dict(r) for r in self._store.values()]

    def count(self) -> int:
        """Return the number of strategies in the store."""
        return len(self._store)

    def clear(self) -> None:
        """Remove all strategies from the store."""
        self._store.clear()
