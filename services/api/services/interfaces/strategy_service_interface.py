"""
Strategy service interface.

Responsibilities:
- Define the abstract contract for strategy management use cases.
- Support creating, retrieving, listing strategies.
- Support DSL condition validation.

Does NOT:
- Implement business logic (concrete service responsibility).
- Access persistence directly (delegates to repository).

Dependencies:
- None (pure interface).

Example:
    service: StrategyServiceInterface = StrategyService(strategy_repo=repo)
    result = service.create_strategy(
        name="RSI Reversal",
        code="RSI(14) < 30 AND price > SMA(200)",
        created_by="01HUSER001",
    )
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class StrategyServiceInterface(ABC):
    """
    Abstract interface for strategy management.

    Implementations:
    - StrategyService: Production implementation with full validation.
    """

    @abstractmethod
    def create_strategy(
        self,
        *,
        name: str,
        entry_condition: str,
        exit_condition: str,
        description: str | None = None,
        instrument: str | None = None,
        timeframe: str | None = None,
        max_position_size: float | None = None,
        stop_loss_percent: float | None = None,
        take_profit_percent: float | None = None,
        parameters: dict[str, Any] | None = None,
        created_by: str,
    ) -> dict[str, Any]:
        """
        Create a new strategy with validated DSL conditions.

        Args:
            name: Strategy name.
            entry_condition: DSL entry condition expression.
            exit_condition: DSL exit condition expression.
            description: Optional description.
            instrument: Target instrument (e.g. "AAPL", "ES").
            timeframe: Candle timeframe (e.g. "1h", "1d").
            max_position_size: Max position in dollars.
            stop_loss_percent: Stop loss percentage.
            take_profit_percent: Take profit percentage.
            parameters: Optional strategy-specific parameters.
            created_by: ULID of the creating user.

        Returns:
            Dict with strategy record and validation details.

        Raises:
            ValidationError: If DSL conditions are syntactically invalid.
        """

    @abstractmethod
    def create_from_ir(
        self,
        ir_dict: dict[str, Any],
        *,
        created_by: str,
        source: str = "ir_upload",
    ) -> dict[str, Any]:
        """
        Create a strategy from a parsed Strategy IR document.

        Validates the IR via ``StrategyIR.model_validate`` before
        persistence — invalid bodies raise ``ValidationError`` with the
        Pydantic error path so the controller can surface it as 400.

        Args:
            ir_dict: Raw IR body (parsed from the uploaded JSON file).
            created_by: ULID of the importing user.
            source: Provenance flag for the strategy record. Defaults
                to ``"ir_upload"`` (the only valid value for this
                method's call site, but accepted as a parameter so the
                controller can override in future scenarios such as
                automated re-imports).

        Returns:
            Dict with the persisted strategy record (includes ``source``).

        Raises:
            ValidationError: If ``ir_dict`` does not validate against
                the ``StrategyIR`` schema. Message includes every
                Pydantic error path so the caller can locate the
                offending field.
        """

    @abstractmethod
    def clone_strategy(
        self,
        source_id: str,
        *,
        new_name: str,
        requested_by: str,
    ) -> dict[str, Any]:
        """
        Duplicate an existing strategy under a new name (POST /clone).

        The clone is a structural copy of the source's persisted ``code``
        body — the parsed JSON is round-tripped through
        ``json.loads``/``json.dumps`` so the clone never aliases the
        source's in-memory dict. Identity flags that anchor the clone to
        its source are preserved (``source`` provenance,
        ``version``); identity fields that must be unique per row are
        regenerated (``id``, ``created_at``, ``updated_at``,
        ``row_version=1``). Run history, deployments, and approvals are
        deliberately NOT copied — they belong to the source row.

        Args:
            source_id: ULID of the strategy to clone.
            new_name: Display name for the clone. Must be non-empty,
                ≤255 characters (matches the ``Strategy.name`` column),
                and unique (case-insensitive) within the strategies
                catalogue.
            requested_by: ULID of the user performing the clone — recorded
                as the clone's ``created_by`` so audit history attributes
                ownership to the operator who clicked the button rather
                than the source's original author.

        Returns:
            Dict representation of the persisted clone (same shape as
            ``create_strategy``'s ``strategy`` field).

        Raises:
            NotFoundError: If ``source_id`` does not resolve to an
                existing strategy.
            ValidationError: If ``new_name`` is empty, whitespace-only,
                or longer than 255 characters.
            StrategyNameConflictError: If a strategy with ``new_name``
                (case-insensitive) already exists. Maps to HTTP 409 at
                the controller layer.
        """

    @abstractmethod
    def get_strategy(self, strategy_id: str) -> dict[str, Any]:
        """
        Retrieve a strategy by ID.

        Args:
            strategy_id: ULID of the strategy.

        Returns:
            Strategy dict.

        Raises:
            NotFoundError: If strategy does not exist.
        """

    @abstractmethod
    def get_with_parsed_ir(
        self,
        strategy_id: str,
        *,
        correlation_id: str | None = None,
    ) -> dict[str, Any]:
        """
        Retrieve a strategy by ID with parsed IR / draft fields (M2.C4).

        Reads the ``source`` column persisted by :meth:`create_from_ir` and
        :meth:`create_strategy` (migration 0025) and chooses the
        appropriate deserialisation path:

        - ``source == "ir_upload"``: parse ``code`` as JSON, validate via
          :class:`StrategyIR.model_validate`, and surface
          ``StrategyIR.model_dump(mode='json')`` as ``parsed_ir``.
          ``draft_fields`` is ``None``. The original IR JSON round-trips
          deeply (key ordering aside, since ``code`` was canonicalised
          via ``json.dumps(..., sort_keys=True)`` on import).
        - ``source == "draft_form"``: parse ``code`` as JSON and surface
          the dict as ``draft_fields``. ``parsed_ir`` is ``None``.

        The route layer wraps the dict under a top-level ``"strategy"``
        key for the JSON response — this method returns the strategy
        record itself for layering symmetry with the rest of the
        service surface.

        Args:
            strategy_id: ULID of the strategy.
            correlation_id: Optional correlation ID for log propagation.

        Returns:
            Strategy dict including ``source``, ``parsed_ir``, and
            ``draft_fields`` (exactly one of the latter two is
            populated; the other is ``None``).

        Raises:
            NotFoundError: If the strategy does not exist.
            ValidationError: If ``source == "ir_upload"`` but the stored
                ``code`` is no longer valid against the IR schema (would
                indicate a schema-breaking migration without a backfill;
                surfaced explicitly so an operator sees the breach
                rather than a silent 200 with garbage).
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
    ) -> dict[str, Any]:
        """
        List strategies with pagination.

        Args:
            created_by: Filter by creator.
            is_active: Filter by active flag.
            limit: Page size.
            offset: Page offset.
            include_archived: When ``False`` (the default), soft-archived
                rows (``archived_at IS NOT NULL``) are excluded from the
                result set so the operator's default browse view stays
                focused on the active catalogue. When ``True``, archived
                rows are included so the "Show archived" toggle in the
                UI can surface them. The default is ``False`` so existing
                callers that do not pass the kwarg get archive-hidden
                behaviour automatically.

        Returns:
            Dict with strategies list and total count.
        """

    @abstractmethod
    def archive_strategy(
        self,
        strategy_id: str,
        *,
        requested_by: str,
        expected_row_version: int | None = None,
    ) -> dict[str, Any]:
        """
        Soft-archive a strategy by setting ``archived_at`` to now (UTC).

        Behaviour:

        - Resolve the strategy via the repository. Missing → raise
          :class:`NotFoundError` (route maps to 404).
        - If the strategy already has ``archived_at`` set, raise
          :class:`StrategyArchiveStateError` with
          ``current_state="archived"`` (route maps to 409).
        - If ``expected_row_version`` is supplied and does not match
          the persisted ``row_version``, raise
          :class:`RowVersionConflictError` (route maps to 409). When
          ``None``, the archive blindly overwrites — used by the
          single-button UI flow where the operator just clicked Archive
          on a freshly-fetched row.
        - Persist ``archived_at = now`` and bump ``row_version`` via
          the repository's ``set_archived`` operation (single UPDATE).
        - Emit structured ``strategy_archived`` audit log per
          CLAUDE.md §8 with ``correlation_id``, ``strategy_id``, and
          ``requested_by``.

        Args:
            strategy_id: ULID of the strategy to archive.
            requested_by: ULID of the operator clicking Archive —
                recorded in the audit log so attribution survives.
            expected_row_version: Optional optimistic-lock guard. When
                supplied, the repository UPDATE is conditional on the
                row's current ``row_version`` matching this value; on
                mismatch a :class:`RowVersionConflictError` is raised
                without persisting.

        Returns:
            Updated strategy dict (the same shape :meth:`get_strategy`
            returns) — includes ``archived_at`` (non-NULL ISO-8601),
            the bumped ``row_version``, and the unchanged identity
            fields.

        Raises:
            NotFoundError: Strategy does not exist.
            StrategyArchiveStateError: Strategy is already archived.
            RowVersionConflictError: ``expected_row_version`` mismatch.
        """

    @abstractmethod
    def restore_strategy(
        self,
        strategy_id: str,
        *,
        requested_by: str,
        expected_row_version: int | None = None,
    ) -> dict[str, Any]:
        """
        Restore a soft-archived strategy by clearing ``archived_at``.

        Inverse of :meth:`archive_strategy`. The strategy reappears in
        the default browse view immediately after a successful restore.

        Behaviour:

        - Resolve the strategy via the repository. Missing → raise
          :class:`NotFoundError` (route maps to 404).
        - If the strategy's ``archived_at`` is already NULL, raise
          :class:`StrategyArchiveStateError` with
          ``current_state="active"`` (route maps to 409).
        - If ``expected_row_version`` is supplied and does not match
          the persisted ``row_version``, raise
          :class:`RowVersionConflictError` (route maps to 409).
        - Persist ``archived_at = NULL`` and bump ``row_version``.
        - Emit structured ``strategy_restored`` audit log per
          CLAUDE.md §8 with ``correlation_id``, ``strategy_id``, and
          ``requested_by``.

        Args:
            strategy_id: ULID of the strategy to restore.
            requested_by: ULID of the operator clicking Restore.
            expected_row_version: Optional optimistic-lock guard.

        Returns:
            Updated strategy dict — ``archived_at`` is ``None`` and
            ``row_version`` has been bumped.

        Raises:
            NotFoundError: Strategy does not exist.
            StrategyArchiveStateError: Strategy is not archived.
            RowVersionConflictError: ``expected_row_version`` mismatch.
        """

    @abstractmethod
    def list_strategies_page(
        self,
        *,
        page: int,
        page_size: int,
        source_filter: str | None = None,
        name_contains: str | None = None,
        created_by: str | None = None,
        is_active: bool | None = None,
    ) -> Any:
        """
        Paginated browse-page contract for ``GET /strategies`` (M2.D5).

        Returns a :class:`StrategyListPage` value object suitable for
        direct serialisation by the route layer. The caller asserts
        ``page >= 1`` and ``page_size >= 1`` (FastAPI's ``Query`` does
        this in production); the implementation ignores any negative
        offset that would arise from invalid input.

        Args:
            page: 1-based page index.
            page_size: Maximum strategies per page.
            source_filter: Optional provenance filter
                (``"ir_upload"`` | ``"draft_form"``).
            name_contains: Optional case-insensitive substring filter
                applied to ``name``.
            created_by: Optional creator ULID filter.
            is_active: Optional soft-delete flag filter.

        Returns:
            :class:`libs.contracts.strategy.StrategyListPage` value
            object containing the page rows + total_count + total_pages.
        """

    @abstractmethod
    def validate_dsl_expression(self, expression: str) -> dict[str, Any]:
        """
        Validate a DSL condition expression without creating a strategy.

        Args:
            expression: Raw DSL string.

        Returns:
            Dict with is_valid, errors, indicators_used, variables_used.
        """
