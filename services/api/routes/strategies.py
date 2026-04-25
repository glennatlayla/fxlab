"""
Strategy Routes.

Responsibilities:
- Strategy CRUD endpoints (POST create, GET by id, GET list).
- DSL condition validation endpoint (POST /validate-dsl).
- Draft autosave endpoints (POST, GET /latest, DELETE /{id}).

Does NOT:
- Contain business logic or DSL parsing (service layer responsibility).
- Access the database directly (routed through repository/service layer).

Dependencies:
- StrategyService: Business logic for strategy management.
- SqlDraftAutosaveRepository: Draft autosave persistence.
- structlog for structured logging.

Error conditions:
- 201 Created: strategy successfully created.
- 200 OK: strategy retrieved or validation result.
- 422 Unprocessable Entity: DSL validation failure or missing fields.
- 404 Not Found: strategy or autosave not found.
- 204 No Content: no autosave found for user_id (GET /latest).

Example:
    POST /strategies
    {"name": "RSI Reversal", "entry_condition": "RSI(14) < 30", ...}
    → 201 {"strategy": {...}, "entry_validation": {...}}

    POST /strategies/validate-dsl
    {"expression": "RSI(14) < 30 AND price > SMA(200)"}
    → 200 {"is_valid": true, "errors": [], ...}
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from services.api.repositories.sql_draft_autosave_repository import (
        SqlDraftAutosaveRepository,
    )

import structlog
from fastapi import APIRouter, Depends, File, HTTPException, Path, Query, UploadFile, status
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from libs.contracts.errors import NotFoundError, ValidationError
from libs.contracts.governance import DraftAutosavePayload
from services.api.auth import AuthenticatedUser, require_scope
from services.api.db import get_db
from services.api.middleware.correlation import correlation_id_var

logger = structlog.get_logger(__name__)

router = APIRouter()


# ---------------------------------------------------------------------------
# Request/response models for strategy endpoints
# ---------------------------------------------------------------------------


class CreateStrategyRequest(BaseModel):
    """
    Request payload for POST /strategies.

    Contains all fields from the Strategy Studio wizard form.
    """

    name: str = Field(..., min_length=1, max_length=255, description="Strategy name")
    entry_condition: str = Field(..., min_length=1, description="DSL entry condition")
    exit_condition: str = Field(..., min_length=1, description="DSL exit condition")
    description: str | None = Field(None, description="Strategy description")
    instrument: str | None = Field(None, description="Target instrument (e.g. AAPL)")
    timeframe: str | None = Field(None, description="Candle timeframe (e.g. 1h, 1d)")
    max_position_size: float | None = Field(None, ge=0, description="Max position in dollars")
    stop_loss_percent: float | None = Field(None, ge=0, le=100, description="Stop loss %")
    take_profit_percent: float | None = Field(None, ge=0, le=100, description="Take profit %")
    parameters: dict[str, Any] | None = Field(None, description="Custom parameters")


class ValidateDslRequest(BaseModel):
    """Request payload for POST /strategies/validate-dsl."""

    expression: str = Field(..., description="DSL expression to validate")


# ---------------------------------------------------------------------------
# Module-level DI for StrategyService
# ---------------------------------------------------------------------------

_strategy_service = None


def set_strategy_service(service: Any) -> None:
    """
    Register the StrategyService instance for route injection.

    Called during application bootstrap or in test setup.

    Args:
        service: StrategyServiceInterface implementation.
    """
    global _strategy_service
    _strategy_service = service


def get_strategy_service() -> Any:
    """
    Retrieve the registered StrategyService.

    Returns:
        The registered StrategyServiceInterface implementation.

    Raises:
        RuntimeError: If no service has been registered.
    """
    if _strategy_service is None:
        raise RuntimeError("StrategyService not configured. Call set_strategy_service() first.")
    return _strategy_service


# ---------------------------------------------------------------------------
# Dependency provider for draft autosave (SQL-backed)
# ---------------------------------------------------------------------------


def get_draft_autosave_repository(
    db: Session = Depends(get_db),
) -> SqlDraftAutosaveRepository:
    """
    Provide a request-scoped DraftAutosave repository.

    Always returns the SQL-backed implementation bound to the current
    request's DB session. In tests, get_db() yields a SQLite session
    (configured in db.py) so the SQL repos work identically.

    Args:
        db: SQLAlchemy session injected by FastAPI dependency injection.

    Returns:
        DraftAutosaveRepositoryInterface implementation bound to the request's session.
    """
    from services.api.repositories.sql_draft_autosave_repository import (
        SqlDraftAutosaveRepository,
    )

    return SqlDraftAutosaveRepository(db=db)


# ---------------------------------------------------------------------------
# Strategy CRUD endpoints (M10)
# ---------------------------------------------------------------------------


@router.post(
    "/",
    status_code=status.HTTP_201_CREATED,
    summary="Create a new strategy",
)
async def create_strategy(
    payload: CreateStrategyRequest,
    user: AuthenticatedUser = Depends(require_scope("strategies:write")),
) -> JSONResponse:
    """
    Create a new strategy with validated DSL conditions.

    Validates both entry and exit conditions using the DSL parser.
    Returns 201 with the persisted strategy and validation metadata.

    Args:
        payload: CreateStrategyRequest with name, conditions, and risk params.
        user: Authenticated user with strategies:write scope.

    Returns:
        201 JSONResponse with strategy record and validation details.

    Raises:
        HTTPException 422: If DSL conditions are syntactically invalid.

    Example:
        POST /strategies
        {"name": "RSI Reversal", "entry_condition": "RSI(14) < 30", ...}
        → 201 {"strategy": {...}, "entry_validation": {...}}
    """
    corr_id = correlation_id_var.get("no-corr")
    service = get_strategy_service()

    logger.info(
        "strategies.create.called",
        name=payload.name,
        user_id=user.user_id,
        correlation_id=corr_id,
        component="strategies",
    )

    try:
        result = service.create_strategy(
            name=payload.name,
            entry_condition=payload.entry_condition,
            exit_condition=payload.exit_condition,
            description=payload.description,
            instrument=payload.instrument,
            timeframe=payload.timeframe,
            max_position_size=payload.max_position_size,
            stop_loss_percent=payload.stop_loss_percent,
            take_profit_percent=payload.take_profit_percent,
            parameters=payload.parameters,
            created_by=user.user_id,
        )
    except ValidationError as e:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(e),
        ) from e

    logger.info(
        "strategies.create.completed",
        strategy_id=result["strategy"]["id"],
        correlation_id=corr_id,
        component="strategies",
    )

    return JSONResponse(content=result, status_code=status.HTTP_201_CREATED)


@router.post(
    "/import-ir",
    status_code=status.HTTP_201_CREATED,
    summary="Import a strategy from a strategy_ir.json file (M2.C1)",
)
async def import_strategy_ir(
    file: UploadFile = File(..., description="strategy_ir.json file"),
    user: AuthenticatedUser = Depends(require_scope("strategies:write")),
) -> JSONResponse:
    """
    Import a strategy from a multipart-uploaded ``strategy_ir.json`` body.

    Validates the body via :class:`StrategyIR` (the M1.A1 schema). On
    success persists via ``StrategyService.create_from_ir`` with
    ``source="ir_upload"`` and emits an audit log line per CLAUDE.md
    §8 in the form ``event=strategy_imported strategy_id=...
    source=ir_upload``.

    Args:
        file: Multipart-uploaded JSON file containing a strategy IR.
        user: Authenticated user with ``strategies:write`` scope
            (matches the Tranche L scope vocabulary, identical to the
            existing ``POST /strategies/`` route).

    Returns:
        201 JSONResponse with ``{"strategy": <persisted record>}``.
        The strategy record contains the new ``strategy_id`` (alias
        ``id``), ``name``, ``version``, ``source="ir_upload"``,
        ``created_by``, timestamps, and the canonical IR body in
        ``code``.

    Raises:
        HTTPException 400: If the upload is not valid JSON, or if the
            parsed body fails ``StrategyIR`` validation. The response
            body's ``detail`` carries every Pydantic error path so the
            caller can locate the offending field.

    Example:
        POST /strategies/import-ir  (multipart/form-data)
            file=@FX_DoubleBollinger_TrendZone.strategy_ir.json
        → 201 {"strategy": {"id": "01H...", "name": "FX_Double...",
                            "source": "ir_upload", ...}}
    """
    corr_id = correlation_id_var.get("no-corr")
    service = get_strategy_service()

    logger.info(
        "strategies.import_ir.called",
        filename=file.filename,
        user_id=user.user_id,
        correlation_id=corr_id,
        component="strategies",
        operation="import_strategy_ir",
    )

    # 1) Read the upload. python-multipart streams the body into memory
    #    (acceptable here — IR files are O(10 KB), not video uploads).
    raw = await file.read()

    # 2) Parse JSON. Malformed JSON is a 400 with an explicit message —
    #    we never want a JSONDecodeError to escape to the global 500
    #    handler when the cause is a clearly-attributable client error.
    try:
        ir_dict = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        logger.warning(
            "strategies.import_ir.invalid_json",
            filename=file.filename,
            error=str(exc),
            correlation_id=corr_id,
            component="strategies",
        )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Uploaded file is not valid JSON: {exc}",
        ) from exc

    # 3) Schema-validate + persist. ValidationError carries the
    #    Pydantic error path (e.g. ``metadata.strategy_name: field
    #    required``) so 400 detail satisfies the M2.C1 acceptance
    #    criterion verbatim.
    try:
        strategy = service.create_from_ir(ir_dict, created_by=user.user_id)
    except ValidationError as exc:
        logger.warning(
            "strategies.import_ir.validation_failed",
            filename=file.filename,
            error=str(exc),
            correlation_id=corr_id,
            component="strategies",
        )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc

    # 4) Audit log per CLAUDE.md §8. Structured fields are mandatory
    #    and the workplan pins the literal field shape:
    #    "event=strategy_imported strategy_id=... source=ir_upload".
    #    structlog binds the first positional arg to the ``event`` key,
    #    so we use the literal event name here and surface ``source``
    #    as a separate structured field.
    logger.info(
        "strategy_imported",
        strategy_id=strategy["id"],
        source="ir_upload",
        user_id=user.user_id,
        correlation_id=corr_id,
        component="strategies",
        operation="import_strategy_ir",
    )

    return JSONResponse(
        content={"strategy": strategy},
        status_code=status.HTTP_201_CREATED,
    )


@router.get("/{strategy_id}", summary="Get strategy by ID")
async def get_strategy(
    strategy_id: str = Path(..., description="Strategy ULID"),
    user: AuthenticatedUser = Depends(require_scope("strategies:write")),
) -> JSONResponse:
    """
    Retrieve a strategy by its ULID, including parsed code fields.

    Args:
        strategy_id: ULID of the strategy.
        user: Authenticated user with strategies:write scope.

    Returns:
        200 JSONResponse with strategy record and parsed code.

    Raises:
        HTTPException 404: If strategy does not exist.
    """
    corr_id = correlation_id_var.get("no-corr")
    service = get_strategy_service()

    try:
        result = service.get_strategy(strategy_id)
    except NotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Strategy {strategy_id} not found",
        ) from exc

    logger.debug(
        "strategies.get.completed",
        strategy_id=strategy_id,
        correlation_id=corr_id,
        component="strategies",
    )

    return JSONResponse(content=result)


@router.get("/", summary="List strategies")
async def list_strategies(
    created_by: str | None = Query(None, description="Filter by creator ULID"),
    is_active: bool | None = Query(None, description="Filter by active status"),
    limit: int = Query(50, ge=1, le=200, description="Page size"),
    offset: int = Query(0, ge=0, description="Page offset"),
    user: AuthenticatedUser = Depends(require_scope("strategies:write")),
) -> JSONResponse:
    """
    List strategies with optional filtering and pagination.

    Args:
        created_by: Optional filter by creator ULID.
        is_active: Optional filter by active status.
        limit: Maximum results per page (1-200, default 50).
        offset: Number of results to skip.
        user: Authenticated user with strategies:write scope.

    Returns:
        200 JSONResponse with strategies list and count.
    """
    corr_id = correlation_id_var.get("no-corr")
    service = get_strategy_service()

    result = service.list_strategies(
        created_by=created_by,
        is_active=is_active,
        limit=limit,
        offset=offset,
    )

    logger.debug(
        "strategies.list.completed",
        count=result["count"],
        correlation_id=corr_id,
        component="strategies",
    )

    return JSONResponse(content=result)


@router.post("/validate-dsl", summary="Validate DSL expression")
async def validate_dsl(
    payload: ValidateDslRequest,
    user: AuthenticatedUser = Depends(require_scope("strategies:write")),
) -> JSONResponse:
    """
    Validate a DSL condition expression without creating a strategy.

    Used by the frontend DslEditor for live validation as the user types.
    Does not persist anything — purely syntactic analysis.

    Args:
        payload: ValidateDslRequest with the DSL expression to validate.
        user: Authenticated user with strategies:write scope.

    Returns:
        200 JSONResponse with is_valid, errors, indicators_used, variables_used.

    Example:
        POST /strategies/validate-dsl
        {"expression": "RSI(14) < 30 AND price > SMA(200)"}
        → 200 {"is_valid": true, "errors": [], "indicators_used": ["RSI", "SMA"], ...}
    """
    corr_id = correlation_id_var.get("no-corr")
    service = get_strategy_service()

    result = service.validate_dsl_expression(payload.expression)

    logger.debug(
        "strategies.validate_dsl.completed",
        is_valid=result["is_valid"],
        correlation_id=corr_id,
        component="strategies",
    )

    return JSONResponse(content=result)


# ---------------------------------------------------------------------------
# Draft autosave endpoints (M13 gap G-10 — spec Section 7.5 / 8.8)
# ---------------------------------------------------------------------------


@router.post(
    "/draft/autosave",
    summary="Save a draft strategy autosave",
)
async def post_draft_autosave(
    payload: DraftAutosavePayload,
    user: AuthenticatedUser = Depends(require_scope("strategies:write")),
    repo: Any = Depends(get_draft_autosave_repository),
) -> dict:
    """
    Persist a draft strategy autosave for the given user.

    The frontend calls this endpoint every 30 seconds and on every field blur.
    The draft_payload may be incomplete — partial validation only, not full
    StrategyDraftInput validation.

    Autosaves older than 30 days are purged from the server (enforced by a
    background cleanup job, not here).

    Args:
        payload: DraftAutosavePayload containing user_id, draft_payload,
                 form_step, client_ts, and session_id.
        user: Authenticated user (required).
        repo: Injected DraftAutosaveRepositoryInterface.

    Returns:
        Dict with autosave_id and saved_at timestamp (ISO-8601).

    Raises:
        HTTPException 422: If required fields are missing.

    Example:
        POST /strategies/draft/autosave
        {"user_id": "01H...", "draft_payload": {"name": "S1"}, ...}
        → 200 {"autosave_id": "01H...", "saved_at": "2026-03-28T11:00:01Z"}
    """
    corr_id = correlation_id_var.get("no-corr")
    result = repo.create(
        user_id=payload.user_id,
        draft_payload=payload.draft_payload,
        form_step=payload.form_step,
        session_id=payload.session_id,
        client_ts=payload.client_ts,
    )

    logger.info(
        "draft.autosave.saved",
        autosave_id=result["autosave_id"],
        user_id=payload.user_id,
        form_step=payload.form_step,
        correlation_id=corr_id,
        component="strategies",
    )

    return result


@router.get(
    "/draft/autosave/latest",
    summary="Retrieve the latest draft autosave for a user",
)
async def get_latest_draft_autosave(
    user_id: str | None = Query(
        None,
        description="ULID of the user whose latest autosave to fetch",
    ),
    user: AuthenticatedUser = Depends(require_scope("strategies:write")),
    repo: Any = Depends(get_draft_autosave_repository),
) -> Any:
    """
    Return the most recent autosave for the given user, or 204 if none exists.

    Called on login to offer the DraftRecoveryBanner. Autosaves older than
    30 days are excluded (enforced by SQL query in production; mock returns
    whatever is in memory).

    Args:
        user_id: Query parameter — ULID of the user.
        user: Authenticated user (required).
        repo: Injected DraftAutosaveRepositoryInterface.

    Returns:
        200 with the most recent autosave record if found.
        204 No Content if no autosave exists for the user.

    Raises:
        HTTPException 422: If user_id query param is missing.

    Example:
        GET /strategies/draft/autosave/latest?user_id=01H...
        → 200 {"autosave_id": "01H...", "draft_payload": {...}, ...}
    """
    corr_id = correlation_id_var.get("no-corr")
    # Manual validation — pydantic Query(...) 422 enforcement is broken in this env.
    if not user_id:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="user_id query parameter is required",
        )

    latest = repo.get_latest(user_id=user_id)

    if latest is None:
        logger.debug(
            "draft.autosave.latest.none",
            user_id=user_id,
            correlation_id=corr_id,
            component="strategies",
        )
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    logger.debug(
        "draft.autosave.latest.found",
        user_id=user_id,
        autosave_id=latest["autosave_id"],
        correlation_id=corr_id,
        component="strategies",
    )
    return latest


@router.delete(
    "/draft/autosave/{autosave_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
    response_model=None,
    summary="Discard a draft autosave",
)
async def delete_draft_autosave(
    autosave_id: str = Path(..., description="Autosave ULID to discard"),
    user: AuthenticatedUser = Depends(require_scope("strategies:write")),
    repo: Any = Depends(get_draft_autosave_repository),
) -> None:
    """
    Explicitly discard a draft autosave record.

    Called when the user selects 'Start Fresh' from the DraftRecoveryBanner.

    Args:
        autosave_id: ULID of the autosave record to delete.
        user: Authenticated user (required).
        repo: Injected DraftAutosaveRepositoryInterface.

    Returns:
        204 No Content on success.

    Raises:
        HTTPException 404: If autosave_id is not found.

    Example:
        DELETE /strategies/draft/autosave/01H...
        → 204 No Content
    """
    corr_id = correlation_id_var.get("no-corr")
    deleted = repo.delete(autosave_id=autosave_id)

    if not deleted:
        logger.warning(
            "draft.autosave.delete.not_found",
            autosave_id=autosave_id,
            correlation_id=corr_id,
            component="strategies",
        )
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Autosave '{autosave_id}' not found.",
        )

    logger.info(
        "draft.autosave.deleted",
        autosave_id=autosave_id,
        correlation_id=corr_id,
        component="strategies",
    )
    # FastAPI returns 204 with no body when the function returns None
    # and status_code=204 is set on the decorator.
