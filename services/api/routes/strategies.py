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

from libs.contracts.errors import (
    NotFoundError,
    RowVersionConflictError,
    StrategyArchiveStateError,
    StrategyNameConflictError,
    ValidationError,
)
from libs.contracts.governance import DraftAutosavePayload
from libs.contracts.run_results import (
    DEFAULT_STRATEGY_RUNS_PAGE_SIZE,
    MAX_STRATEGY_RUNS_PAGE_SIZE,
)
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


#: Hard cap on the size of an inbound IR text payload. Mirrors the IR
#: file size we expect on the import path (production IRs run ~5-10 KB;
#: 1 MiB is generous headroom while still preventing accidental abuse
#: via a 100 MB textarea paste).
_MAX_IR_TEXT_BYTES: int = 1_048_576


class ValidateIrRequest(BaseModel):
    """
    Request payload for ``POST /strategies/validate-ir``.

    Carries the raw IR JSON text the operator is drafting in the
    Strategy Studio textarea. Validation runs the same parse + Pydantic
    + reference-resolution pipeline as ``POST /strategies/import-ir``
    but never persists.
    """

    ir_text: str = Field(
        ...,
        min_length=1,
        max_length=_MAX_IR_TEXT_BYTES,
        description=(
            "Raw IR JSON text (1 byte to 1 MiB). The endpoint validates "
            "without persisting; failures are surfaced via the report."
        ),
    )


class CloneStrategyRequest(BaseModel):
    """
    Request payload for ``POST /strategies/{strategy_id}/clone``.

    The frontend pre-fills ``new_name`` with ``"{source.name} (copy)"``;
    the backend re-validates the constraint here so a stale frontend
    cannot bypass it. ``min_length=1`` rejects empty strings (FastAPI
    surfaces a 422); ``max_length=255`` mirrors the ``Strategy.name``
    SQL column limit so an overlong submission is also a 422 rather
    than a SQLAlchemy ``DataError`` at write time.
    """

    new_name: str = Field(
        ...,
        min_length=1,
        max_length=255,
        description="Display name for the clone. 1-255 chars, must be unique.",
    )


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


@router.post(
    "/validate-ir",
    summary="Validate a strategy IR JSON body without persisting (no-save)",
)
async def validate_strategy_ir(
    payload: ValidateIrRequest,
    user: AuthenticatedUser = Depends(require_scope("strategies:write")),
) -> JSONResponse:
    """
    Run the IR import pipeline against ``ir_text`` WITHOUT persisting.

    The request body carries the raw IR JSON text the operator is
    drafting in the Strategy Studio textarea; the response carries a
    :class:`StrategyValidationReport` describing whether the IR would
    pass the import path or not. Both pass and fail share HTTP 200 —
    the request itself succeeded; the IR's validity is the report
    payload. Only auth failures (401/403) and malformed request bodies
    (422) yield non-2xx responses.

    Behaviour contract:

    - Delegates to :meth:`StrategyService.validate_ir` so the
      validate-IR endpoint and the import-IR endpoint apply byte-
      identical pipeline semantics.
    - Persists nothing, regardless of validity.
    - Always returns 200 (or one of 401/403/422); the report carries
      the actual validity flag.
    - Caps the error list at
      :data:`libs.contracts.strategy.MAX_VALIDATION_ISSUES` to bound
      response size; truncation is surfaced as a trailing
      ``code="truncated"`` issue so the operator sees that more
      errors exist beyond what was rendered.

    Auth scope: ``strategies:write`` (matches the sibling
    ``POST /strategies/import-ir`` — the project does not split read /
    write scopes for strategy administration).

    Args:
        payload: ``ValidateIrRequest`` with ``ir_text`` (1 byte to 1
            MiB; validated by Pydantic before the handler runs).
        user: Authenticated user with ``strategies:write`` scope.

    Returns:
        200 ``JSONResponse`` with the
        :class:`StrategyValidationReport` body. The body shape is
        ``{"valid": bool, "parsed_ir": dict|None, "errors": [...],
        "warnings": [...]}``.

    Raises:
        HTTPException 422: If ``ir_text`` is empty or exceeds the cap.

    Example:
        POST /strategies/validate-ir
        {"ir_text": "{...}"}
        → 200 {"valid": true, "parsed_ir": {...}, "errors": [],
                "warnings": []}
        POST /strategies/validate-ir
        {"ir_text": "not json"}
        → 200 {"valid": false, "parsed_ir": null,
                "errors": [{"path": "/", "code": "invalid_json",
                            "message": "..."}], "warnings": []}
    """
    corr_id = correlation_id_var.get("no-corr")
    service = get_strategy_service()

    logger.info(
        "strategies.validate_ir.called",
        text_len=len(payload.ir_text),
        user_id=user.user_id,
        correlation_id=corr_id,
        component="strategies",
        operation="validate_strategy_ir",
    )

    # The service guarantees this never raises — every failure is
    # captured in the report.
    report = service.validate_ir(payload.ir_text)

    logger.info(
        "strategies.validate_ir.completed",
        valid=report.valid,
        error_count=len(report.errors),
        user_id=user.user_id,
        correlation_id=corr_id,
        component="strategies",
        operation="validate_strategy_ir",
    )

    return JSONResponse(content=report.model_dump(mode="json"))


@router.get(
    "/{strategy_id}/ir.json",
    summary="Download the canonical Strategy IR JSON for a stored strategy",
)
async def download_strategy_ir_json(
    strategy_id: str = Path(..., description="ULID of the strategy to download"),
    user: AuthenticatedUser = Depends(require_scope("strategies:write")),
) -> Response:
    """
    Stream the canonical IR JSON text for ``strategy_id`` as a download.

    The endpoint surfaces the strategy's persisted ``code`` column
    verbatim — for ``source="ir_upload"`` rows this is the canonical
    IR JSON written by ``create_from_ir`` (sort_keys=True). Legacy
    rows whose ``code`` is blank fall back to a re-serialised parsed
    IR (see :meth:`StrategyService.get_strategy_ir_json`) so the
    download always produces a parseable JSON document.

    Auth scope: ``strategies:write`` (matches every other strategy GET
    in this module — the project does not define a distinct
    ``strategies:read`` scope).

    Args:
        strategy_id: ULID of the strategy whose IR JSON to download.
        user: Authenticated user with ``strategies:write`` scope.

    Returns:
        200 ``Response`` with body=IR JSON text and headers:
        - ``Content-Type: application/json``
        - ``Content-Disposition: attachment;
          filename="{strategy_name}.strategy_ir.json"`` so the
          browser's Save dialog uses the strategy's display name.

    Raises:
        HTTPException 404: If the strategy does not exist.
        HTTPException 422: If the stored IR fails re-validation in the
            fallback path (data integrity breach surfaced explicitly).

    Example:
        GET /strategies/01HSTRAT.../ir.json
        → 200 application/json
            Content-Disposition: attachment;
                filename="FX_DoubleBollinger.strategy_ir.json"
            {... canonical IR body ...}
    """
    corr_id = correlation_id_var.get("no-corr")
    service = get_strategy_service()

    logger.info(
        "strategies.download_ir.called",
        strategy_id=strategy_id,
        user_id=user.user_id,
        correlation_id=corr_id,
        component="strategies",
        operation="download_strategy_ir_json",
    )

    try:
        ir_text = service.get_strategy_ir_json(strategy_id)
    except NotFoundError as exc:
        logger.warning(
            "strategies.download_ir.not_found",
            strategy_id=strategy_id,
            user_id=user.user_id,
            correlation_id=corr_id,
            component="strategies",
            operation="download_strategy_ir_json",
        )
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Strategy {strategy_id} not found",
        ) from exc

    # Pull the strategy name for the filename hint. We deliberately do a
    # second lookup rather than threading the name through
    # get_strategy_ir_json — the service surface stays narrow (one
    # responsibility per method) and the name lookup is a cheap repo
    # hit that already lives behind the same NotFoundError gate above.
    detail = service.get_strategy(strategy_id)
    raw_name = str(detail.get("name") or strategy_id)
    safe_name = _sanitise_filename_token(raw_name)
    filename = f"{safe_name}.strategy_ir.json"

    logger.info(
        "strategies.download_ir.completed",
        strategy_id=strategy_id,
        bytes=len(ir_text),
        user_id=user.user_id,
        correlation_id=corr_id,
        component="strategies",
        operation="download_strategy_ir_json",
    )

    # Return as a Response with explicit Content-Type so the browser's
    # Save dialog respects the application/json mime type even on
    # platforms where the filename suffix alone isn't sufficient.
    return Response(
        content=ir_text,
        media_type="application/json",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
        },
    )


def _sanitise_filename_token(value: str) -> str:
    """
    Strip path separators and quoting characters from a filename hint.

    Strategy names are operator-supplied free text; the route exposes
    them in the ``Content-Disposition`` header as the filename hint.
    Without sanitisation a name like ``Foo"; rm -rf /; ".json`` could
    inject a header line break or break out of the filename quoting.

    The replacement set is conservative: keep alphanumerics, dots,
    hyphens, underscores, and spaces; replace everything else with an
    underscore. Falls back to ``"strategy"`` when the resulting token
    is empty.

    Args:
        value: Raw strategy name (or any free-text token).

    Returns:
        Sanitised string safe to embed in the ``filename="..."`` header
        value.

    Example:
        >>> _sanitise_filename_token('FX_DoubleBollinger Trend/Zone')
        'FX_DoubleBollinger Trend_Zone'
        >>> _sanitise_filename_token('"; rm -rf')
        '_ rm -rf'
    """
    keep = set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789.-_ ")
    sanitised = "".join(ch if ch in keep else "_" for ch in value).strip()
    return sanitised or "strategy"


@router.post(
    "/{strategy_id}/clone",
    status_code=status.HTTP_201_CREATED,
    summary="Clone an existing strategy under a new name",
)
async def clone_strategy_route(
    payload: CloneStrategyRequest,
    strategy_id: str = Path(..., description="ULID of the source strategy to clone"),
    user: AuthenticatedUser = Depends(require_scope("strategies:write")),
) -> JSONResponse:
    """
    Duplicate the source strategy under ``new_name`` and return the clone.

    Delegates to :meth:`StrategyService.clone_strategy`. The clone:
    - Inherits ``source`` (provenance) and ``version`` from the source.
    - Holds an independent dict graph for ``code`` (re-parsed via
      ``json.loads`` / ``json.dumps``); mutating the clone never
      affects the source's persisted bytes.
    - Is attributed to the requesting operator (``created_by`` =
      ``user.user_id``) so audit history shows who clicked the button.
    - Carries a fresh ULID, fresh timestamps, and ``row_version=1``.
    - Does NOT copy run history, deployments, or approvals.

    Auth scope: ``strategies:write`` (matches every other write route
    in this module — the project does not split read/write scopes for
    strategy administration).

    Args:
        payload: ``CloneStrategyRequest`` with the ``new_name`` field
            (1-255 chars, validated by Pydantic before the handler runs).
        strategy_id: ULID of the source strategy.
        user: Authenticated user with ``strategies:write`` scope.

    Returns:
        201 ``JSONResponse`` with body ``{"strategy": <persisted clone>}``.

    Raises:
        HTTPException 404: If the source ``strategy_id`` does not exist.
        HTTPException 409: If a strategy with ``new_name`` already exists
            (case-insensitive collision).
        HTTPException 422: If ``new_name`` fails the request schema
            (empty / overlong) — surfaced by FastAPI before the handler
            executes.

    Example:
        POST /strategies/01HSRC.../clone
        {"new_name": "RSI Reversal (copy)"}
        → 201 {"strategy": {"id": "01HCLN...", "name": "RSI Reversal (copy)",
                            "source": "draft_form", "row_version": 1, ...}}
    """
    corr_id = correlation_id_var.get("no-corr")
    service = get_strategy_service()

    logger.info(
        "strategies.clone.called",
        source_id=strategy_id,
        new_name=payload.new_name,
        user_id=user.user_id,
        correlation_id=corr_id,
        component="strategies",
        operation="clone_strategy",
    )

    try:
        clone = service.clone_strategy(
            strategy_id,
            new_name=payload.new_name,
            requested_by=user.user_id,
        )
    except NotFoundError as exc:
        logger.warning(
            "strategies.clone.source_not_found",
            source_id=strategy_id,
            user_id=user.user_id,
            correlation_id=corr_id,
            component="strategies",
            operation="clone_strategy",
        )
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Strategy {strategy_id} not found",
        ) from exc
    except StrategyNameConflictError as exc:
        # 409 carries the colliding name in the detail body so the UI
        # can show "A strategy named 'X' already exists." inline without
        # re-deriving the message client-side.
        logger.warning(
            "strategies.clone.name_conflict",
            source_id=strategy_id,
            new_name=payload.new_name,
            user_id=user.user_id,
            correlation_id=corr_id,
            component="strategies",
            operation="clone_strategy",
        )
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(exc),
        ) from exc
    except ValidationError as exc:
        # The request body schema already rejects empty / overlong
        # names with 422. A ValidationError here would indicate a
        # service-layer guard fired (e.g. trimming made the name empty
        # — Pydantic min_length=1 doesn't trim). Surface as 422 so the
        # UI's existing inline-error path renders identically to the
        # body-validation case.
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from exc

    logger.info(
        "strategies.clone.completed",
        source_id=strategy_id,
        new_id=clone["id"],
        new_name=clone["name"],
        user_id=user.user_id,
        correlation_id=corr_id,
        component="strategies",
        operation="clone_strategy",
    )

    return JSONResponse(
        content={"strategy": clone},
        status_code=status.HTTP_201_CREATED,
    )


# ---------------------------------------------------------------------------
# Soft-archive lifecycle (POST /archive | POST /restore)
# ---------------------------------------------------------------------------


def _emit_archive_lifecycle_audit(
    *,
    event: str,
    strategy_id: str,
    user_id: str,
    correlation_id: str,
    archived_at: str | None,
) -> None:
    """
    Emit the canonical archive/restore audit line per CLAUDE.md §8.

    Centralised so the two route handlers share one structured-log
    contract — the "event" name is bound to the first positional arg
    by structlog, and the kwargs are the indexed fields downstream
    log consumers filter on.

    Args:
        event: ``"strategy_archived"`` or ``"strategy_restored"``.
        strategy_id: ULID of the strategy whose lifecycle changed.
        user_id: ULID of the operator who clicked the button.
        correlation_id: Request correlation id propagated from the
            FastAPI middleware.
        archived_at: New archived_at value after the write (None for
            restore, ISO-8601 string for archive).
    """
    logger.info(
        event,
        strategy_id=strategy_id,
        user_id=user_id,
        archived_at=archived_at,
        correlation_id=correlation_id,
        component="strategies",
        operation=event,
    )


@router.post(
    "/{strategy_id}/archive",
    summary="Soft-archive a strategy (hidden from default list, kept for audit)",
)
async def archive_strategy_route(
    strategy_id: str = Path(..., description="ULID of the strategy to archive"),
    user: AuthenticatedUser = Depends(require_scope("strategies:write")),
) -> JSONResponse:
    """
    Soft-archive a strategy by setting ``archived_at`` to UTC now.

    Delegates to :meth:`StrategyService.archive_strategy`. The archived
    strategy disappears from the default catalogue browse view but its
    history (runs, audit trail, deployments) stays intact. Restoration
    is a single POST to the matching restore endpoint.

    Auth scope: ``strategies:write`` (matches every other write route
    in this module — the project does not split read/write scopes for
    strategy administration).

    Args:
        strategy_id: ULID of the strategy to archive.
        user: Authenticated user with ``strategies:write`` scope.

    Returns:
        200 ``JSONResponse`` with body ``{"strategy": <updated record>}``.
        The updated record carries the new ``archived_at`` timestamp
        (ISO-8601), the bumped ``row_version``, and unchanged identity
        fields.

    Raises:
        HTTPException 404: Strategy does not exist.
        HTTPException 409: Strategy is already archived.

    Example:
        POST /strategies/01HSRC.../archive
        → 200 {"strategy": {"id": "01HSRC...",
                            "archived_at": "2026-04-26T18:53:34+00:00",
                            "row_version": 2, ...}}
    """
    corr_id = correlation_id_var.get("no-corr")
    service = get_strategy_service()

    logger.info(
        "strategies.archive.called",
        strategy_id=strategy_id,
        user_id=user.user_id,
        correlation_id=corr_id,
        component="strategies",
        operation="archive_strategy",
    )

    try:
        updated = service.archive_strategy(strategy_id, requested_by=user.user_id)
    except NotFoundError as exc:
        logger.warning(
            "strategies.archive.not_found",
            strategy_id=strategy_id,
            user_id=user.user_id,
            correlation_id=corr_id,
            component="strategies",
            operation="archive_strategy",
        )
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Strategy {strategy_id} not found",
        ) from exc
    except StrategyArchiveStateError as exc:
        # 409 — the strategy is already archived. The detail body
        # carries the service's message verbatim so the UI can render
        # "already archived" inline without re-deriving copy.
        logger.warning(
            "strategies.archive.already_archived",
            strategy_id=strategy_id,
            user_id=user.user_id,
            correlation_id=corr_id,
            component="strategies",
            operation="archive_strategy",
        )
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(exc),
        ) from exc
    except RowVersionConflictError as exc:
        # 409 — concurrent writer mutated the row between read + write.
        # Per CLAUDE.md §9 we do not retry this — the operator's view
        # is stale and they need to refresh before deciding what to do.
        logger.warning(
            "strategies.archive.row_version_conflict",
            strategy_id=strategy_id,
            user_id=user.user_id,
            correlation_id=corr_id,
            actual_row_version=exc.actual_row_version,
            expected_row_version=exc.expected_row_version,
            component="strategies",
            operation="archive_strategy",
        )
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(exc),
        ) from exc

    _emit_archive_lifecycle_audit(
        event="strategy_archived",
        strategy_id=strategy_id,
        user_id=user.user_id,
        correlation_id=corr_id,
        archived_at=updated.get("archived_at"),
    )

    return JSONResponse(content={"strategy": updated})


@router.post(
    "/{strategy_id}/restore",
    summary="Restore a soft-archived strategy back to the active catalogue",
)
async def restore_strategy_route(
    strategy_id: str = Path(..., description="ULID of the strategy to restore"),
    user: AuthenticatedUser = Depends(require_scope("strategies:write")),
) -> JSONResponse:
    """
    Restore a soft-archived strategy by clearing ``archived_at``.

    Inverse of the archive endpoint. The strategy reappears in the
    default catalogue immediately after a successful restore.

    Auth scope: ``strategies:write`` (matches every other write route
    in this module).

    Args:
        strategy_id: ULID of the strategy to restore.
        user: Authenticated user with ``strategies:write`` scope.

    Returns:
        200 ``JSONResponse`` with body ``{"strategy": <updated record>}``.
        The updated record carries ``archived_at: null`` and a bumped
        ``row_version``.

    Raises:
        HTTPException 404: Strategy does not exist.
        HTTPException 409: Strategy is not currently archived.

    Example:
        POST /strategies/01HSRC.../restore
        → 200 {"strategy": {"id": "01HSRC...",
                            "archived_at": null,
                            "row_version": 3, ...}}
    """
    corr_id = correlation_id_var.get("no-corr")
    service = get_strategy_service()

    logger.info(
        "strategies.restore.called",
        strategy_id=strategy_id,
        user_id=user.user_id,
        correlation_id=corr_id,
        component="strategies",
        operation="restore_strategy",
    )

    try:
        updated = service.restore_strategy(strategy_id, requested_by=user.user_id)
    except NotFoundError as exc:
        logger.warning(
            "strategies.restore.not_found",
            strategy_id=strategy_id,
            user_id=user.user_id,
            correlation_id=corr_id,
            component="strategies",
            operation="restore_strategy",
        )
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Strategy {strategy_id} not found",
        ) from exc
    except StrategyArchiveStateError as exc:
        logger.warning(
            "strategies.restore.not_archived",
            strategy_id=strategy_id,
            user_id=user.user_id,
            correlation_id=corr_id,
            component="strategies",
            operation="restore_strategy",
        )
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(exc),
        ) from exc
    except RowVersionConflictError as exc:
        logger.warning(
            "strategies.restore.row_version_conflict",
            strategy_id=strategy_id,
            user_id=user.user_id,
            correlation_id=corr_id,
            actual_row_version=exc.actual_row_version,
            expected_row_version=exc.expected_row_version,
            component="strategies",
            operation="restore_strategy",
        )
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(exc),
        ) from exc

    _emit_archive_lifecycle_audit(
        event="strategy_restored",
        strategy_id=strategy_id,
        user_id=user.user_id,
        correlation_id=corr_id,
        archived_at=updated.get("archived_at"),
    )

    return JSONResponse(content={"strategy": updated})


@router.get("/{strategy_id}", summary="Get strategy by ID")
async def get_strategy(
    strategy_id: str = Path(..., description="Strategy ULID"),
    user: AuthenticatedUser = Depends(require_scope("strategies:write")),
) -> JSONResponse:
    """
    Retrieve a strategy by its ULID with parsed IR + draft view (M2.C4).

    Returns the strategy record alongside either ``parsed_ir`` (when
    ``source=="ir_upload"``) or ``draft_fields`` (when
    ``source=="draft_form"``). The ``source`` field tells the frontend
    which view to render.

    For source=ir_upload the returned ``parsed_ir`` round-trips deeply
    against the original IR JSON uploaded via
    ``POST /strategies/import-ir`` — this is the M2.C4 acceptance gate.

    Auth scope: ``strategies:write`` (matches every other strategy GET
    in this module — there is no ``strategies:read`` scope in the
    project's ROLE_SCOPES vocabulary).

    Args:
        strategy_id: ULID of the strategy.
        user: Authenticated user with ``strategies:write`` scope.

    Returns:
        200 JSONResponse with body ``{"strategy": {...}}``. The
        strategy record contains the persistence columns (id, name,
        code, version, source, created_by, is_active, row_version,
        created_at, updated_at) plus ``parsed_ir`` and
        ``draft_fields`` (exactly one populated, the other ``None``).

    Raises:
        HTTPException 404: If the strategy does not exist.
        HTTPException 422: If the stored IR fails schema validation
            (data integrity breach surfaced explicitly so an operator
            sees it rather than a silent 200 with garbage).
    """
    corr_id = correlation_id_var.get("no-corr")
    service = get_strategy_service()

    logger.info(
        "strategies.get.called",
        strategy_id=strategy_id,
        user_id=user.user_id,
        correlation_id=corr_id,
        component="strategies",
        operation="get_strategy",
    )

    try:
        strategy = service.get_with_parsed_ir(strategy_id, correlation_id=corr_id)
    except NotFoundError as exc:
        logger.warning(
            "strategies.get.not_found",
            strategy_id=strategy_id,
            correlation_id=corr_id,
            component="strategies",
            operation="get_strategy",
        )
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Strategy {strategy_id} not found",
        ) from exc
    except ValidationError as exc:
        # Stored IR failed re-validation — schema drift without a
        # backfill. Surface as 422 so the caller knows the data is
        # actually present but unrenderable.
        logger.error(
            "strategies.get.ir_invalid",
            strategy_id=strategy_id,
            correlation_id=corr_id,
            component="strategies",
            operation="get_strategy",
        )
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from exc

    logger.info(
        "strategies.get.completed",
        strategy_id=strategy_id,
        source=strategy.get("source"),
        correlation_id=corr_id,
        component="strategies",
        operation="get_strategy",
    )

    return JSONResponse(content={"strategy": strategy})


@router.get("/", summary="List strategies (browse page, M2.D5)")
async def list_strategies(
    page: int | None = Query(
        None,
        ge=1,
        description=(
            "1-based page index. When supplied, the response uses the M2.D5 paginated "
            "envelope: {strategies, page, page_size, total_count, total_pages, count}."
        ),
    ),
    page_size: int = Query(
        20,
        ge=1,
        le=200,
        description="Page size (1-200, default 20). Used when ``page`` is supplied.",
    ),
    source: str | None = Query(
        None,
        pattern=r"^(ir_upload|draft_form)$",
        description="Filter by provenance — 'ir_upload' or 'draft_form'.",
    ),
    name_contains: str | None = Query(
        None,
        max_length=255,
        description="Case-insensitive substring filter on the strategy name.",
    ),
    created_by: str | None = Query(None, description="Filter by creator ULID"),
    is_active: bool | None = Query(None, description="Filter by active status"),
    include_archived: bool = Query(
        False,
        description=(
            "When true, include soft-archived strategies (archived_at IS NOT NULL) "
            "in the response. Defaults to false so the operator's default browse "
            "view stays focused on the active catalogue."
        ),
    ),
    limit: int = Query(
        50, ge=1, le=200, description="Legacy page size (used when ``page`` omitted)"
    ),
    offset: int = Query(0, ge=0, description="Legacy page offset (used when ``page`` omitted)"),
    user: AuthenticatedUser = Depends(require_scope("strategies:write")),
) -> JSONResponse:
    """
    List strategies with optional filtering, pagination, and search.

    Powers the M2.D5 ``/strategies`` browse page in the frontend. The
    endpoint supports two pagination shapes for backward compatibility:

    - **New (M2.D5):** caller supplies ``?page=1&page_size=20`` and gets
      back ``{strategies: [...], page, page_size, total_count,
      total_pages, count}`` where ``count`` is the size of the current
      page (kept for older callers) and ``total_count`` is the size of
      the entire filtered set.
    - **Legacy:** caller omits ``page`` and uses ``?limit=&offset=``.
      Response shape stays at ``{strategies, limit, offset, count}``.

    The new shape adds two filters that the legacy shape did not
    expose:

    - ``source=ir_upload|draft_form`` — provenance discriminator.
    - ``name_contains=...`` — case-insensitive substring search on
      ``Strategy.name``.

    Both filters compose with ``created_by`` and ``is_active`` so the
    UI can offer a "my drafts" or "active IR uploads" view from the
    same endpoint.

    Auth scope: ``strategies:write`` (matches every other strategy
    endpoint in this module — there is no ``strategies:read`` scope in
    the project's ROLE_SCOPES vocabulary).

    Args:
        page: 1-based page index. Triggers the new envelope when set.
        page_size: Strategies per page (1-200, default 20).
        source: Optional provenance filter.
        name_contains: Optional case-insensitive name substring filter.
        created_by: Optional creator ULID filter.
        is_active: Optional active-flag filter.
        limit: Legacy page size (only used when ``page`` is omitted).
        offset: Legacy page offset (only used when ``page`` is omitted).
        user: Authenticated user with strategies:write scope.

    Returns:
        200 JSONResponse. Body shape depends on whether ``page`` was
        supplied (see above).

    Example:
        GET /strategies/?page=1&page_size=20&source=ir_upload
        → 200 {"strategies": [...], "page": 1, "page_size": 20,
                "total_count": 5, "total_pages": 1, "count": 5}
    """
    corr_id = correlation_id_var.get("no-corr")
    service = get_strategy_service()

    if page is not None:
        # New M2.D5 paginated envelope. The service hands back a
        # validated StrategyListPage; we serialise via model_dump and
        # add a ``count`` alias so the legacy assertion shape (count =
        # rows on this page) keeps working for any caller that only
        # checks page-level size.
        page_obj = service.list_strategies_page(
            page=page,
            page_size=page_size,
            source_filter=source,
            name_contains=name_contains,
            created_by=created_by,
            is_active=is_active,
            include_archived=include_archived,
        )
        body = page_obj.model_dump(mode="json")
        body["count"] = len(body["strategies"])

        # Audit log per CLAUDE.md §8 — operators expect a per-request
        # line so they can see who browsed which slice of the catalogue.
        # ``strategy_list_browsed`` is the literal event name; structlog
        # binds the first positional arg as the ``event`` key.
        logger.info(
            "strategy_list_browsed",
            page=page,
            page_size=page_size,
            source_filter=source,
            name_contains=name_contains,
            include_archived=include_archived,
            returned=body["count"],
            total_count=body["total_count"],
            user_id=user.user_id,
            correlation_id=corr_id,
            component="strategies",
            operation="list_strategies",
        )

        return JSONResponse(content=body)

    # Legacy shape. Preserve byte-for-byte response for older callers
    # (the M2.C tests and any internal scripts assume this shape).
    result = service.list_strategies(
        created_by=created_by,
        is_active=is_active,
        limit=limit,
        offset=offset,
        include_archived=include_archived,
    )

    logger.debug(
        "strategies.list.completed",
        count=result["count"],
        correlation_id=corr_id,
        component="strategies",
        operation="list_strategies_legacy",
    )

    return JSONResponse(content=result)


# ---------------------------------------------------------------------------
# Strategy run history (powers the StrategyDetail page's recent-runs section)
# ---------------------------------------------------------------------------


@router.get(
    "/{strategy_id}/runs",
    summary="List recent runs for a strategy (paginated, newest first)",
)
async def list_strategy_runs(
    strategy_id: str = Path(..., description="Strategy ULID"),
    page: int = Query(1, ge=1, description="1-based page index."),
    page_size: int = Query(
        DEFAULT_STRATEGY_RUNS_PAGE_SIZE,
        ge=1,
        le=MAX_STRATEGY_RUNS_PAGE_SIZE,
        description=(
            "Runs per page "
            f"(default {DEFAULT_STRATEGY_RUNS_PAGE_SIZE}, "
            f"max {MAX_STRATEGY_RUNS_PAGE_SIZE})."
        ),
    ),
    user: AuthenticatedUser = Depends(require_scope("strategies:write")),
) -> JSONResponse:
    """
    Return paginated run history for a given strategy.

    Powers the "Recent runs" section on the StrategyDetail page. Runs
    are ordered by ``created_at`` descending so the most recent submission
    appears first. Each row carries the run id (used as the
    ``/runs/{id}/results`` navigation target), the lifecycle status, the
    started/completed timestamps, and the compact summary metrics
    (``total_return_pct``, ``sharpe_ratio``, ``win_rate``, ``trade_count``)
    surfaced on the table row.

    Auth scope: ``strategies:write`` (matches every other strategy
    endpoint in this module — the project's ROLE_SCOPES vocabulary
    does not define a distinct ``strategies:read`` scope).

    Args:
        strategy_id: ULID of the strategy whose run history to fetch.
        page: 1-based page index (default 1).
        page_size: Runs per page (1-200, default 20).
        user: Authenticated user with ``strategies:write`` scope.

    Returns:
        200 JSONResponse. Body shape:
        ``{runs: [{id, status, started_at, completed_at, summary_metrics:
        {total_return_pct, sharpe_ratio, win_rate, trade_count}}, ...],
        page, page_size, total_count, total_pages}``.

        Pages beyond the last populated page return an empty ``runs``
        list with ``total_count`` and ``total_pages`` unchanged so the
        UI can disable the "Next" button.

    Raises:
        HTTPException 422: If ``page`` < 1 or ``page_size`` outside
            [1, 200] (FastAPI's ``ge`` / ``le`` validators).
        HTTPException 503: If the research-run service is not configured
            (raised by :func:`_get_research_run_service`).

    Example:
        GET /strategies/01HSTRAT0000000000000001/runs?page=1&page_size=20
        → 200 {"runs": [{"id": "01HRUN...", "status": "completed",
                        "started_at": "...", "completed_at": "...",
                        "summary_metrics": {...}}, ...],
                "page": 1, "page_size": 20,
                "total_count": 5, "total_pages": 1}
    """
    corr_id = correlation_id_var.get("no-corr")
    service = _get_research_run_service()

    page_obj = service.list_runs_for_strategy(
        strategy_id,
        page=page,
        page_size=page_size,
    )
    body = page_obj.model_dump(mode="json")

    # Audit log per CLAUDE.md §8 — operators expect a per-request line
    # so they can see who browsed which strategy's run history.
    # ``strategy_runs_browsed`` is the literal event name; structlog
    # binds the first positional arg as the ``event`` key.
    logger.info(
        "strategy_runs_browsed",
        strategy_id=strategy_id,
        page=page,
        page_size=page_size,
        returned=len(body["runs"]),
        total_count=body["total_count"],
        user_id=user.user_id,
        correlation_id=corr_id,
        component="strategies",
        operation="list_strategy_runs",
    )

    return JSONResponse(content=body)


def _get_research_run_service() -> Any:
    """
    Resolve the registered :class:`ResearchRunService` for the runs route.

    The strategy router does not own the research-run service DI — the
    runs router does (see :func:`services.api.routes.runs.set_research_run_service`).
    We re-use that registration so this endpoint stays consistent with
    the rest of the run history surface, and so the application bootstrap
    in ``services/api/main.py`` does not have to wire the service twice.

    Returns:
        The registered :class:`ResearchRunService` instance.

    Raises:
        HTTPException 503: If no service has been registered.
    """
    # Local import keeps the dependency cycle explicit and avoids
    # importing the runs router at module import time.
    from services.api.routes.runs import _research_run_service

    if _research_run_service is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Research run service not configured.",
        )
    return _research_run_service


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
