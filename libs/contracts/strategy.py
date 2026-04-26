"""
Strategy draft and build contracts.

Pydantic v2 schemas for strategy lifecycle.
"""

from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class StrategyDraftCreate(BaseModel):
    """
    Request payload to create a new strategy draft.
    """

    name: str = Field(..., min_length=1, max_length=255, description="Draft strategy name")
    description: str | None = Field(None, description="Strategy description")
    parameters: dict[str, Any] = Field(
        default_factory=dict,
        description="Strategy parameters (validation TBD)",
    )


class StrategyDraftUpdate(BaseModel):
    """
    Request payload to update an existing strategy draft.
    """

    name: str | None = Field(None, min_length=1, max_length=255)
    description: str | None = None
    parameters: dict[str, Any] | None = None


class StrategyDraftResponse(BaseModel):
    """
    Response schema for strategy draft.
    """

    id: str = Field(..., description="ULID")
    user_id: str
    name: str
    description: str | None
    parameters: dict[str, Any]
    is_submitted: bool
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class StrategyBuildResponse(BaseModel):
    """
    Response schema for compiled strategy build.

    Phase 1/2 contract. Phase 3 consumes but does not mutate.
    Includes override_watermark per spec §8.2 for governance visibility.
    """

    id: str = Field(..., description="ULID")
    name: str
    version: str
    artifact_uri: str
    source_hash: str
    created_by: str
    created_at: datetime
    updated_at: datetime
    override_watermark: dict[str, Any] | None = Field(
        None,
        description="Override watermark metadata for active overrides (spec §8.2)",
    )

    model_config = ConfigDict(from_attributes=True)


# ---------------------------------------------------------------------------
# M2 additions — compiler interface contracts
# ---------------------------------------------------------------------------


class StrategyDefinition(BaseModel):
    """
    Input specification for a strategy to be compiled.

    Used as the input contract for the StrategyCompilerInterface.
    """

    id: str = Field(..., description="ULID of the strategy draft")
    name: str = Field(..., description="Human-readable strategy name")
    parameters: dict[str, Any] = Field(
        default_factory=dict,
        description="Strategy parameters",
    )
    version: str | None = Field(None, description="Optional version tag")
    created_by: str | None = Field(None, description="ULID of the owning user")


class CompiledStrategy(BaseModel):
    """
    Output of a successful strategy compilation step.

    Returned by StrategyCompilerInterface.compile().
    """

    id: str = Field(..., description="ULID of the compiled strategy artefact")
    strategy_id: str = Field(..., description="ULID of the source StrategyDefinition")
    artifact_uri: str = Field(..., description="Storage URI of the compiled artefact")
    source_hash: str = Field(..., description="SHA-256 of the source definition")
    version: str = Field(..., description="SemVer build tag")
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


# ---------------------------------------------------------------------------
# M2.D5 — Strategy list / browse page (paginated catalogue endpoint)
# ---------------------------------------------------------------------------

#: Hard cap on ``page_size`` for the strategies list endpoint. Matches the
#: M2.C-style envelope adopted by the other list endpoints (audit, exports,
#: trade blotter) where 200 is the largest single page the UI ever needs
#: while remaining cheap to serialise.
MAX_STRATEGY_LIST_PAGE_SIZE: int = 200

#: Default page size for the list endpoint when the caller does not specify
#: one. Mirrors the existing ``GET /strategies/`` ``limit=50`` default so
#: callers using the legacy ``limit=`` query parameter see identical
#: behaviour.
DEFAULT_STRATEGY_LIST_PAGE_SIZE: int = 20


class StrategyListItem(BaseModel):
    """
    A single row in the paginated strategies list.

    Pinned to the columns the M2.D5 ``/strategies`` browse page renders:
    identity, provenance (``source``), version, ownership, and audit
    columns. Heavy fields like ``code`` are deliberately omitted — the
    caller fetches the full :class:`StrategyDetail` only when an
    individual row is opened.

    Attributes:
        id: Strategy ULID.
        name: Display name.
        source: Provenance flag — ``"ir_upload"`` or ``"draft_form"``.
        version: SemVer-style version string.
        created_by: ULID of the creating user.
        created_at: ISO-8601 timestamp of creation.
        is_active: Soft-delete flag (``True`` for visible strategies).

    Example:
        item = StrategyListItem(
            id="01HZ...",
            name="FX_DoubleBollinger_TrendZone",
            source="ir_upload",
            version="0.1.0",
            created_by="01HUSER...",
            created_at="2026-04-25T12:00:00+00:00",
            is_active=True,
        )
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str = Field(..., min_length=1, description="Strategy ULID.")
    name: str = Field(..., min_length=1, description="Display name.")
    source: str = Field(
        ...,
        pattern=r"^(ir_upload|draft_form)$",
        description="Provenance flag — pinned by chk_strategies_source.",
    )
    version: str = Field(..., min_length=1, description="SemVer-style version.")
    created_by: str = Field(..., min_length=1, description="Creator ULID.")
    created_at: str = Field(..., min_length=1, description="ISO-8601 creation timestamp.")
    is_active: bool = Field(..., description="Soft-delete flag.")


class StrategyListPage(BaseModel):
    """
    Response body for ``GET /strategies`` (M2.D5).

    Pagination contract mirrors the trade blotter endpoint:
        - ``page`` is 1-based.
        - ``page_size`` defaults to
          :data:`DEFAULT_STRATEGY_LIST_PAGE_SIZE` (20) and is capped at
          :data:`MAX_STRATEGY_LIST_PAGE_SIZE` (200); above the cap the
          route returns HTTP 422 (FastAPI's ``le`` validator).
        - Strategies are ordered by ``created_at`` descending so the most
          recently imported row appears first.
        - Pages beyond the last populated page return an empty
          ``strategies`` list with ``total_count`` and ``total_pages``
          unchanged so the UI can detect the end of the dataset and
          disable the "Next" button.

    Attributes:
        strategies: The strategies on this page (may be empty).
        page: 1-based page index requested.
        page_size: Maximum strategies per page for this request.
        total_count: Total strategies matching the filters.
        total_pages: Ceiling of ``total_count / page_size`` (0 if no rows).

    Example:
        page = StrategyListPage(
            strategies=[item],
            page=1,
            page_size=20,
            total_count=37,
            total_pages=2,
        )
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    strategies: list[StrategyListItem] = Field(default_factory=list)
    page: int = Field(..., ge=1, description="1-based page index.")
    page_size: int = Field(
        ...,
        ge=1,
        le=MAX_STRATEGY_LIST_PAGE_SIZE,
        description="Strategies per page.",
    )
    total_count: int = Field(..., ge=0, description="Total matching strategies.")
    total_pages: int = Field(..., ge=0, description="Total pages at this page_size.")
