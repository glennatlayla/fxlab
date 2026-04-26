"""
Strategy repository interface (port).

Responsibilities:
- Define the abstract contract for strategy CRUD persistence.
- Support creating, retrieving, listing, and deactivating strategies.
- Return dict representations for layer decoupling.

Does NOT:
- Implement storage logic (adapter responsibility).
- Validate DSL syntax (service layer responsibility).
- Contain business logic.

Dependencies:
- None (pure interface).

Error conditions:
- NotFoundError: raised when a specific strategy is not found.

Example:
    repo: StrategyRepositoryInterface = SqlStrategyRepository(db=session)
    strategy = repo.create(
        name="Momentum Crossover",
        code="RSI(14) < 30 AND price > SMA(200)",
        created_by="01HUSER001",
    )
    found = repo.get_by_id("01HSTRAT001")
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime
from typing import Any


class StrategyRepositoryInterface(ABC):
    """
    Abstract interface for strategy persistence.

    All monetary values and identifiers are strings to maintain
    decimal precision safety and layer decoupling.

    Implementations:
    - SqlStrategyRepository: Production SQL-backed persistence.
    - MockStrategyRepository: In-memory fake for unit testing.
    """

    @abstractmethod
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
        Create a new strategy record.

        Args:
            name: Human-readable strategy name.
            code: Strategy source — DSL JSON for the draft-form flow,
                or the full ``strategy_ir.json`` body for IR uploads.
            created_by: ULID of the creating user.
            version: Optional semantic version string.
            source: Provenance flag — ``"draft_form"`` (Strategy Studio
                wizard) or ``"ir_upload"`` (POST /strategies/import-ir).
                Persisted on the strategy record so downstream
                consumers (M2.C4 GET /strategies/{id}) can render the
                correct view. Backed by migration 0025 with a CHECK
                constraint pinning the allowed values.

        Returns:
            Dict with id, name, code, version, created_by, is_active,
            source, created_at, updated_at.
        """

    @abstractmethod
    def get_by_id(self, strategy_id: str) -> dict[str, Any] | None:
        """
        Retrieve a strategy by its ULID.

        Args:
            strategy_id: ULID of the strategy.

        Returns:
            Dict representation of the strategy, or None if not found.
        """

    @abstractmethod
    def list_strategies(
        self,
        *,
        created_by: str | None = None,
        is_active: bool | None = None,
        limit: int = 50,
        offset: int = 0,
        include_archived: bool = False,
    ) -> list[dict[str, Any]]:
        """
        List strategies with optional filtering and pagination.

        Args:
            created_by: Filter by creator ULID.
            is_active: Filter by active status.
            limit: Maximum results to return.
            offset: Number of results to skip.
            include_archived: When ``False`` (the default), rows with
                ``archived_at IS NOT NULL`` are excluded. When ``True``,
                the result set spans both active and archived rows.

        Returns:
            List of strategy dicts ordered by created_at descending.
        """

    @abstractmethod
    def list_with_total(
        self,
        *,
        created_by: str | None = None,
        is_active: bool | None = None,
        source: str | None = None,
        name_contains: str | None = None,
        limit: int = 20,
        offset: int = 0,
        include_archived: bool = False,
    ) -> tuple[list[dict[str, Any]], int]:
        """
        List strategies with filters + pagination and return the total count.

        Powers the M2.D5 ``GET /strategies`` browse page where the UI
        needs ``total_count`` to render pagination controls (Next/Prev,
        "Page X of Y") that the legacy ``list_strategies`` cannot supply
        without a separate count query.

        Args:
            created_by: Filter by creator ULID.
            is_active: Filter by active status.
            source: Filter by provenance — ``"ir_upload"`` or
                ``"draft_form"``. ``None`` means no source filter.
            name_contains: Case-insensitive substring filter on the
                strategy ``name`` column. ``None`` means no name filter.
            limit: Maximum results to return on this page.
            offset: Number of results to skip before the page starts.
            include_archived: When ``False`` (the default), rows with
                ``archived_at IS NOT NULL`` are excluded — the default
                browse view stays focused on the active catalogue.
                When ``True``, the page + total span both archived and
                active rows so the "Show archived" toggle in the UI can
                reveal them.

        Returns:
            ``(strategies, total_count)`` where ``strategies`` is the
            page (length <= ``limit``) ordered by ``created_at``
            descending, and ``total_count`` is the total number of rows
            matching the filters across all pages.
        """

    @abstractmethod
    def set_archived(
        self,
        strategy_id: str,
        *,
        archived_at: datetime | None,
        expected_row_version: int | None = None,
    ) -> dict[str, Any] | None:
        """
        Set or clear ``strategies.archived_at`` for a single row.

        Performs a single conditional UPDATE that bumps ``row_version``
        atomically with the ``archived_at`` write. The
        ``expected_row_version`` guard implements optimistic locking:
        the UPDATE only proceeds if the row's current ``row_version``
        matches; on mismatch the method raises
        :class:`RowVersionConflictError` and persists nothing.

        Args:
            strategy_id: ULID of the strategy to mutate.
            archived_at: New value for the column. ``None`` restores
                the row to the active catalogue; a UTC ``datetime``
                soft-archives it.
            expected_row_version: When supplied, the UPDATE only fires
                if the row's current ``row_version`` equals this value.
                ``None`` skips the check (caller accepts last-writer-
                wins semantics).

        Returns:
            Updated strategy dict, or ``None`` if no row matched
            ``strategy_id``.

        Raises:
            RowVersionConflictError: ``expected_row_version`` did not
                match the persisted value. Carries
                ``actual_row_version`` so the caller can decide whether
                to surface "another user just changed this" or to
                re-read and retry.
        """

    @abstractmethod
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
        Update fields on an existing strategy.

        Uses optimistic locking via row_version. Only non-None fields
        are updated.

        Args:
            strategy_id: ULID of the strategy to update.
            name: New name (optional).
            code: New DSL code (optional).
            version: New version string (optional).
            is_active: New active status (optional).

        Returns:
            Updated strategy dict, or None if not found.
        """

    @abstractmethod
    def deactivate(self, strategy_id: str) -> bool:
        """
        Soft-delete a strategy by setting is_active=False.

        Args:
            strategy_id: ULID of the strategy to deactivate.

        Returns:
            True if found and deactivated, False if not found.
        """
