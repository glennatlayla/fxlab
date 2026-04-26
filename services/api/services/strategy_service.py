"""
Strategy management service.

Responsibilities:
- Orchestrate strategy creation with DSL validation.
- Persist strategies via the repository interface.
- Format strategy data including parsed DSL metadata.
- Provide live DSL validation for frontend editors.

Does NOT:
- Access the database directly (delegates to StrategyRepositoryInterface).
- Execute or backtest strategies (runtime engine responsibility).
- Handle HTTP or message formatting (controller responsibility).

Dependencies:
- StrategyRepositoryInterface (injected): Strategy persistence.
- dsl_validator: DSL tokenizer/parser for condition validation.

Error conditions:
- ValidationError: DSL condition syntax is invalid.
- NotFoundError: Requested strategy does not exist.

Example:
    service = StrategyService(strategy_repo=repo)
    result = service.create_strategy(
        name="RSI Reversal",
        entry_condition="RSI(14) < 30 AND price > SMA(200)",
        exit_condition="RSI(14) > 70 OR price < SMA(200)",
        created_by="01HUSER001",
    )
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

import structlog
from pydantic import ValidationError as PydanticValidationError

from libs.contracts.errors import (
    NotFoundError,
    StrategyArchiveStateError,
    StrategyNameConflictError,
    ValidationError,
)
from libs.contracts.interfaces.strategy_repository_interface import (
    StrategyRepositoryInterface,
)
from libs.contracts.strategy import (
    MAX_VALIDATION_ISSUES,
    StrategyListItem,
    StrategyListPage,
    StrategyValidationReport,
    ValidationIssue,
)
from libs.contracts.strategy_ir import StrategyIR
from libs.strategy_ir.reference_resolver import (
    IRReferenceError,
    ReferenceResolver,
)
from services.api.services.dsl_validator import (
    DslValidationResult,
    validate_dsl,
)
from services.api.services.interfaces.strategy_service_interface import (
    StrategyServiceInterface,
)

logger = structlog.get_logger(__name__)


#: Hard cap on ``Strategy.name`` enforced by the SQL column type
#: (``String(255)``). Mirrored at the service layer so the clone path
#: can fail fast with a typed :class:`ValidationError` instead of
#: surfacing a SQLAlchemy ``DataError`` for the same condition. Kept in
#: sync manually with :class:`libs.contracts.models.Strategy.name`.
_STRATEGY_NAME_MAX_LEN: int = 255


def _build_strategy_code(
    entry_condition: str,
    exit_condition: str,
    description: str | None = None,
    instrument: str | None = None,
    timeframe: str | None = None,
    max_position_size: float | None = None,
    stop_loss_percent: float | None = None,
    take_profit_percent: float | None = None,
    parameters: dict[str, Any] | None = None,
) -> str:
    """
    Assemble a strategy code JSON document from individual fields.

    The strategy code is stored as a structured JSON string in the
    database. This format preserves all form fields and allows the
    strategy compiler to extract individual components.

    Args:
        entry_condition: DSL entry condition expression.
        exit_condition: DSL exit condition expression.
        description: Optional strategy description.
        instrument: Target instrument symbol.
        timeframe: Candle timeframe.
        max_position_size: Max position in dollars.
        stop_loss_percent: Stop loss percentage.
        take_profit_percent: Take profit percentage.
        parameters: Strategy-specific parameter overrides.

    Returns:
        JSON string encoding all strategy fields.
    """
    code_doc: dict[str, Any] = {
        "entry_condition": entry_condition,
        "exit_condition": exit_condition,
    }
    if description:
        code_doc["description"] = description
    if instrument:
        code_doc["instrument"] = instrument
    if timeframe:
        code_doc["timeframe"] = timeframe
    if max_position_size is not None:
        code_doc["max_position_size"] = max_position_size
    if stop_loss_percent is not None:
        code_doc["stop_loss_percent"] = stop_loss_percent
    if take_profit_percent is not None:
        code_doc["take_profit_percent"] = take_profit_percent
    if parameters:
        code_doc["parameters"] = parameters

    return json.dumps(code_doc, sort_keys=True)


def _pydantic_loc_to_pointer(loc: tuple[Any, ...]) -> str:
    """
    Convert a Pydantic ``error['loc']`` tuple into an RFC 6901 JSON pointer.

    Pydantic locates errors as a tuple of mixed strings (object keys)
    and ints (list indices), e.g. ``("metadata", "strategy_name")`` or
    ``("indicators", 3, "length")``. The validate-IR contract surfaces
    paths as JSON pointers (``"/metadata/strategy_name"``,
    ``"/indicators/3/length"``) so the frontend's error renderer can
    use a single path-formatting routine across every call site.

    Args:
        loc: Pydantic error ``loc`` tuple.

    Returns:
        ``"/"`` for an empty tuple, otherwise a slash-joined pointer
        with each segment escaped per RFC 6901 (``~`` → ``~0``,
        ``/`` → ``~1``).

    Example:
        >>> _pydantic_loc_to_pointer(("metadata", "strategy_name"))
        '/metadata/strategy_name'
        >>> _pydantic_loc_to_pointer(("indicators", 3, "length"))
        '/indicators/3/length'
        >>> _pydantic_loc_to_pointer(())
        '/'
    """
    if not loc:
        return "/"
    parts: list[str] = []
    for segment in loc:
        token = str(segment)
        # RFC 6901 escape: ``~`` first, then ``/`` — ordering matters.
        token = token.replace("~", "~0").replace("/", "~1")
        parts.append(token)
    return "/" + "/".join(parts)


def _resolver_location_to_pointer(location: str) -> str:
    """
    Convert a :class:`ReferenceResolver` dotted location into a JSON pointer.

    The resolver emits locations like
    ``entry_logic.long.conditions[0].lhs`` and
    ``indicators[3].mean_source``; the validate-IR contract pins paths
    to JSON pointer form so the frontend's error renderer is uniform.
    Bracket indices and dotted segments are both flattened into pointer
    segments.

    Args:
        location: Resolver location hint.

    Returns:
        A leading-slash JSON pointer. ``"/"`` when the location is
        blank.

    Example:
        >>> _resolver_location_to_pointer("entry_logic.long.conditions[0].lhs")
        '/entry_logic/long/conditions/0/lhs'
        >>> _resolver_location_to_pointer("indicators[3].mean_source")
        '/indicators/3/mean_source'
    """
    if not location:
        return "/"
    # Replace [N] with .N, then split on '.', drop empties so consecutive
    # separators don't yield blank segments.
    normalised = location.replace("[", ".").replace("]", "")
    parts = [seg for seg in normalised.split(".") if seg]
    if not parts:
        return "/"
    escaped = [seg.replace("~", "~0").replace("/", "~1") for seg in parts]
    return "/" + "/".join(escaped)


def _parse_and_validate_ir(
    ir_text_or_dict: str | dict[str, Any],
) -> tuple[dict[str, Any] | None, StrategyIR | None, list[ValidationIssue]]:
    """
    Run the canonical IR pipeline: JSON parse → Pydantic → reference resolution.

    Shared between :meth:`StrategyService.create_from_ir` (which raises
    on the first failing stage so the import endpoint can return 400)
    and :meth:`StrategyService.validate_ir` (which collects every issue
    and returns a non-raising report).

    The pipeline runs each stage in order; if a stage fails, downstream
    stages are skipped because they would only produce derivative
    errors:

    1. JSON parse — failure produces a single
       ``code="invalid_json"`` issue at path ``/`` and short-circuits.
    2. Pydantic schema validation — failure produces one
       ``code="schema_violation"`` issue per Pydantic error.
    3. Reference resolution (`ReferenceResolver`) — failure produces
       a single ``code="undefined_reference"`` issue (the resolver
       raises on the first dangling reference; collecting all of
       them would require a deeper rewrite of that library).

    Args:
        ir_text_or_dict: Raw IR text (validate path) or a pre-parsed
            dict (import path that already parsed via UploadFile).

    Returns:
        ``(parsed_dict, strategy_ir, issues)``. On success
        ``strategy_ir`` is the validated model and ``issues`` is empty.
        On any failure ``strategy_ir`` is ``None`` and ``issues``
        contains at least one row. ``parsed_dict`` is ``None`` only
        when JSON parsing itself failed.

    Raises:
        Nothing — every failure is captured in the ``issues`` list.
    """
    issues: list[ValidationIssue] = []

    # ---- Stage 1: JSON parse (only when input is text). ----
    parsed_dict: dict[str, Any] | None
    if isinstance(ir_text_or_dict, str):
        if not ir_text_or_dict.strip():
            issues.append(
                ValidationIssue(
                    path="/",
                    code="invalid_json",
                    message="IR text is empty.",
                )
            )
            return None, None, issues
        try:
            parsed = json.loads(ir_text_or_dict)
        except json.JSONDecodeError as exc:
            issues.append(
                ValidationIssue(
                    path="/",
                    code="invalid_json",
                    message=f"IR is not valid JSON: {exc.msg} (line {exc.lineno}, col {exc.colno})",
                )
            )
            return None, None, issues
        if not isinstance(parsed, dict):
            issues.append(
                ValidationIssue(
                    path="/",
                    code="invalid_json",
                    message=(f"IR root must be a JSON object, got {type(parsed).__name__}."),
                )
            )
            return None, None, issues
        parsed_dict = parsed
    else:
        parsed_dict = ir_text_or_dict

    # ---- Stage 2: Pydantic schema validation. ----
    try:
        ir_model = StrategyIR.model_validate(parsed_dict)
    except PydanticValidationError as exc:
        for err in exc.errors():
            issues.append(
                ValidationIssue(
                    path=_pydantic_loc_to_pointer(tuple(err.get("loc", ()))),
                    code="schema_violation",
                    message=str(err.get("msg", "validation failed")),
                )
            )
        # Schema failures short-circuit reference resolution because the
        # resolver assumes a well-typed StrategyIR — running it on a
        # half-built dict would just produce confusing AttributeErrors.
        return parsed_dict, None, issues

    # ---- Stage 3: Reference resolution. ----
    try:
        ReferenceResolver(ir_model).resolve()
    except IRReferenceError as exc:
        # The resolver raises on the first dangling identifier. Its
        # message format is
        # ``"unresolved identifier 'X' at <location>; ..."`` — extract
        # the location hint when present so the issue's path field is
        # useful for the operator.
        message = str(exc)
        path = "/"
        if " at " in message:
            tail = message.split(" at ", 1)[1]
            location_hint = tail.split(";", 1)[0].strip()
            if location_hint:
                path = _resolver_location_to_pointer(location_hint)
        issues.append(
            ValidationIssue(
                path=path,
                code="undefined_reference",
                message=message,
            )
        )
        return parsed_dict, None, issues

    return parsed_dict, ir_model, issues


def _format_validation_result(result: DslValidationResult) -> dict[str, Any]:
    """
    Convert a DslValidationResult to a serialisable dict.

    Args:
        result: Parsed validation result from the DSL validator.

    Returns:
        Dict with is_valid, errors (list of dicts), indicators_used, variables_used.
    """
    return {
        "is_valid": result.is_valid,
        "errors": [
            {
                "message": e.message,
                "line": e.line,
                "column": e.column,
                "suggestion": e.suggestion,
            }
            for e in result.errors
        ],
        "indicators_used": sorted(result.indicators_used),
        "variables_used": sorted(result.variables_used),
    }


class StrategyService(StrategyServiceInterface):
    """
    Production strategy management service.

    Responsibilities:
    - Validate entry and exit DSL conditions before persisting.
    - Assemble strategy code documents and persist via repository.
    - Retrieve and list strategies with optional filtering.
    - Provide standalone DSL validation for live editor feedback.

    Does NOT:
    - Execute strategies or run backtests.
    - Handle HTTP routing or response formatting.

    Dependencies:
    - StrategyRepositoryInterface (injected).

    Example:
        service = StrategyService(strategy_repo=repo)
        result = service.create_strategy(
            name="RSI Reversal",
            entry_condition="RSI(14) < 30",
            exit_condition="RSI(14) > 70",
            created_by="01HUSER001",
        )
    """

    def __init__(self, *, strategy_repo: StrategyRepositoryInterface) -> None:
        self._strategy_repo = strategy_repo

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

        Validates both entry and exit conditions using the DSL parser.
        If either condition is invalid, raises ValidationError with
        detailed error positions and suggestions.

        Args:
            name: Strategy name (1-255 chars).
            entry_condition: DSL entry condition expression.
            exit_condition: DSL exit condition expression.
            description: Optional human-readable description.
            instrument: Target instrument (e.g. "AAPL").
            timeframe: Candle timeframe (e.g. "1h", "1d").
            max_position_size: Maximum position size in dollars.
            stop_loss_percent: Stop loss as percentage.
            take_profit_percent: Take profit as percentage.
            parameters: Optional custom parameter dict.
            created_by: ULID of the creating user.

        Returns:
            Dict with: strategy (persisted record), entry_validation,
            exit_validation, indicators_used, variables_used.

        Raises:
            ValidationError: If name is empty or DSL conditions are invalid.
        """
        logger.info(
            "strategy.create.started",
            name=name,
            created_by=created_by,
            component="StrategyService",
            operation="create_strategy",
        )

        # Validate name
        if not name or not name.strip():
            raise ValidationError("Strategy name is required")

        # Validate DSL conditions
        entry_result = validate_dsl(entry_condition)
        exit_result = validate_dsl(exit_condition)

        errors: list[str] = []
        if not entry_result.is_valid:
            for e in entry_result.errors:
                errors.append(f"Entry condition: {e.message} (line {e.line}, col {e.column})")
        if not exit_result.is_valid:
            for e in exit_result.errors:
                errors.append(f"Exit condition: {e.message} (line {e.line}, col {e.column})")

        if errors:
            raise ValidationError("; ".join(errors))

        # Assemble strategy code document
        code = _build_strategy_code(
            entry_condition=entry_condition,
            exit_condition=exit_condition,
            description=description,
            instrument=instrument,
            timeframe=timeframe,
            max_position_size=max_position_size,
            stop_loss_percent=stop_loss_percent,
            take_profit_percent=take_profit_percent,
            parameters=parameters,
        )

        # Persist to database
        strategy = self._strategy_repo.create(
            name=name.strip(),
            code=code,
            created_by=created_by,
        )

        # Collect all indicators and variables across both conditions
        all_indicators = entry_result.indicators_used | exit_result.indicators_used
        all_variables = entry_result.variables_used | exit_result.variables_used

        logger.info(
            "strategy.create.completed",
            strategy_id=strategy["id"],
            name=name,
            indicators=sorted(all_indicators),
            component="StrategyService",
            operation="create_strategy",
        )

        return {
            "strategy": strategy,
            "entry_validation": _format_validation_result(entry_result),
            "exit_validation": _format_validation_result(exit_result),
            "indicators_used": sorted(all_indicators),
            "variables_used": sorted(all_variables),
        }

    def create_from_ir(
        self,
        ir_dict: dict[str, Any],
        *,
        created_by: str,
        source: str = "ir_upload",
    ) -> dict[str, Any]:
        """
        Create a strategy from a parsed Strategy IR document (M2.C1).

        Validates the body against :class:`StrategyIR` before
        persisting. The full IR JSON is stored in the ``code`` column
        verbatim (canonical, sort-keys-stable) so the M2.C4 parsed-IR
        round-trip endpoint can deep-equal it without reformatting.

        Args:
            ir_dict: Raw IR body parsed from the uploaded JSON file.
            created_by: ULID of the importing user.
            source: Provenance flag (default ``"ir_upload"``).

        Returns:
            Dict with the persisted strategy record (includes
            ``source`` and the canonical IR JSON in ``code``).

        Raises:
            ValidationError: If the IR fails Pydantic validation.
                Message preserves every error's dotted path (e.g.
                ``metadata.strategy_name: field required``) so the
                controller can return it as the 400 body without
                further reshaping.

        Example:
            >>> import json
            >>> with open("FX_DoubleBollinger_TrendZone.strategy_ir.json") as fh:
            ...     ir = json.load(fh)
            >>> result = service.create_from_ir(ir, created_by="01HUSER001")
            >>> result["source"]
            'ir_upload'
        """
        logger.info(
            "strategy.create_from_ir.started",
            created_by=created_by,
            source=source,
            component="StrategyService",
            operation="create_from_ir",
        )

        # Run the canonical IR pipeline (parse + Pydantic + reference
        # resolution). Shared with ``validate_ir`` so the validate-IR
        # endpoint and the import-IR endpoint apply byte-identical
        # semantics — operators never see "valid in the validate panel
        # but rejected by import" inconsistencies.
        #
        # M2.C1 acceptance is "400 with the validation error path in
        # the response body". The helper produces JSON-pointer paths
        # (e.g. ``/metadata/strategy_name``) so the controller surfaces
        # them verbatim. Concatenating into a single ValidationError
        # message preserves the existing 400 body shape that
        # downstream tests pin against.
        _parsed, ir_model, issues = _parse_and_validate_ir(ir_dict)
        if ir_model is None:
            raise ValidationError("; ".join(f"{issue.path}: {issue.message}" for issue in issues))

        # Canonicalise the IR body before persistence. Sorting keys
        # gives M2.C4's deep-equal round-trip a stable representation
        # regardless of the upload's original key ordering.
        canonical_code = json.dumps(ir_dict, sort_keys=True)

        strategy = self._strategy_repo.create(
            name=ir_model.metadata.strategy_name,
            code=canonical_code,
            created_by=created_by,
            version=ir_model.metadata.strategy_version,
            source=source,
        )

        logger.info(
            "strategy.create_from_ir.completed",
            strategy_id=strategy["id"],
            name=ir_model.metadata.strategy_name,
            source=source,
            component="StrategyService",
            operation="create_from_ir",
        )

        return strategy

    def clone_strategy(
        self,
        source_id: str,
        *,
        new_name: str,
        requested_by: str,
    ) -> dict[str, Any]:
        """
        Duplicate an existing strategy under ``new_name`` (POST /clone).

        Behaviour:

        1. Resolve the source via :class:`StrategyRepositoryInterface`.
           Missing source → :class:`NotFoundError` (route maps to 404).
        2. Validate ``new_name``: non-empty after trimming, and at most
           :data:`_STRATEGY_NAME_MAX_LEN` characters (mirrors the
           ``Strategy.name`` SQL column limit).
        3. Enforce uniqueness against the existing catalogue using a
           case-insensitive substring lookup that we then exact-match
           on (the ``Strategy.name`` column does not carry a UNIQUE DB
           constraint, so the check lives at the service layer). On
           collision raise :class:`StrategyNameConflictError` (route
           maps to 409).
        4. Re-parse the source's persisted ``code`` JSON via
           ``json.loads`` then re-serialise via
           ``json.dumps(sort_keys=True)`` so the clone holds a brand-
           new dict graph, not an aliased reference. This satisfies
           the brief's "structural copy not an aliased reference"
           requirement and matches :meth:`create_from_ir`'s canonical
           encoding so future round-trip / diff tooling sees stable
           bytes.
        5. Persist via ``repo.create`` with ``source`` + ``version``
           inherited from the source row, ``created_by=requested_by``,
           and a fresh ULID generated by the repository (``row_version``
           defaults to ``1`` per the ORM column default).
        6. Emit ``strategy_cloned`` audit log per CLAUDE.md §8 with
           ``source_id``, ``new_id``, ``new_name``, ``requested_by``.

        Deliberately NOT copied: timestamps, ``row_version``, run
        history, deployments, approvals — those belong to the source
        row's identity.

        Args:
            source_id: ULID of the strategy to clone.
            new_name: Display name for the clone.
            requested_by: ULID of the user performing the clone.

        Returns:
            Dict representation of the persisted clone (same shape the
            repository returns for a fresh ``create``).

        Raises:
            NotFoundError: If ``source_id`` does not resolve.
            ValidationError: If ``new_name`` is empty / whitespace-only
                or exceeds the column length cap.
            StrategyNameConflictError: If ``new_name`` collides
                (case-insensitive) with an existing strategy.

        Example:
            clone = service.clone_strategy(
                "01HSRC...",
                new_name="RSI Reversal (copy)",
                requested_by="01HOPER...",
            )
            # clone["id"] != "01HSRC..."
            # clone["name"] == "RSI Reversal (copy)"
            # clone["row_version"] == 1
        """
        logger.info(
            "strategy.clone.started",
            source_id=source_id,
            new_name=new_name,
            requested_by=requested_by,
            component="StrategyService",
            operation="clone_strategy",
        )

        # 1) Resolve source.
        source = self._strategy_repo.get_by_id(source_id)
        if source is None:
            logger.warning(
                "strategy.clone.source_not_found",
                source_id=source_id,
                requested_by=requested_by,
                component="StrategyService",
                operation="clone_strategy",
            )
            raise NotFoundError(f"Strategy {source_id} not found")

        # 2) Validate new_name. Trimming first so a name that is purely
        # whitespace ("   ") fails the non-empty gate just like "".
        trimmed = (new_name or "").strip()
        if not trimmed:
            raise ValidationError("Strategy name is required")
        if len(trimmed) > _STRATEGY_NAME_MAX_LEN:
            raise ValidationError(
                f"Strategy name exceeds the {_STRATEGY_NAME_MAX_LEN}-character limit"
            )

        # 3) Enforce uniqueness at the service layer (case-insensitive).
        # ``list_with_total`` filters by ``name_contains`` (substring,
        # case-insensitive) — we then exact-match on the lowered name to
        # weed out partial overlaps (e.g. "RSI" should not collide with
        # "RSI Reversal"). Limit is the column cap so any colliding row
        # in the result set is visible without paging.
        existing_rows, _ = self._strategy_repo.list_with_total(
            name_contains=trimmed,
            limit=_STRATEGY_NAME_MAX_LEN,
            offset=0,
        )
        target_lower = trimmed.lower()
        for row in existing_rows:
            if str(row.get("name", "")).strip().lower() == target_lower:
                logger.warning(
                    "strategy.clone.name_conflict",
                    source_id=source_id,
                    new_name=trimmed,
                    requested_by=requested_by,
                    conflicting_id=row.get("id"),
                    component="StrategyService",
                    operation="clone_strategy",
                )
                raise StrategyNameConflictError(
                    f"A strategy named {trimmed!r} already exists",
                    name=trimmed,
                )

        # 4) Re-parse the source's code so the clone holds an independent
        # dict graph. If the source's code is non-JSON (legacy rows that
        # pre-date canonicalisation) fall back to passing the bytes
        # through verbatim — the persisted bytes still survive the round
        # trip, just without the structural-copy guarantee. We log this
        # so operators see when the fallback fires.
        raw_code = source.get("code") or ""
        try:
            parsed = json.loads(raw_code)
            cloned_code = json.dumps(parsed, sort_keys=True)
        except (json.JSONDecodeError, TypeError):
            logger.warning(
                "strategy.clone.code_not_json_passthrough",
                source_id=source_id,
                requested_by=requested_by,
                component="StrategyService",
                operation="clone_strategy",
            )
            cloned_code = raw_code

        # 5) Persist via repo. ``source`` and ``version`` mirror the
        # source row so the clone reads as the same flavour of strategy
        # in downstream views; ``created_by`` is the requester so audit
        # trails attribute ownership to whoever clicked the button.
        new_row = self._strategy_repo.create(
            name=trimmed,
            code=cloned_code,
            created_by=requested_by,
            version=source.get("version") or "0.1.0",
            source=source.get("source") or "draft_form",
        )

        # 6) Audit log per CLAUDE.md §8. Event name pinned to
        # ``strategy_cloned`` so log consumers can filter on it without
        # parsing free-form messages.
        logger.info(
            "strategy_cloned",
            source_id=source_id,
            new_id=new_row["id"],
            new_name=trimmed,
            requested_by=requested_by,
            component="StrategyService",
            operation="clone_strategy",
        )

        return new_row

    def get_strategy(self, strategy_id: str) -> dict[str, Any]:
        """
        Retrieve a strategy by ID.

        Parses the stored code JSON to extract individual fields.

        Args:
            strategy_id: ULID of the strategy.

        Returns:
            Strategy dict with parsed code fields.

        Raises:
            NotFoundError: If strategy does not exist.
        """
        strategy = self._strategy_repo.get_by_id(strategy_id)
        if strategy is None:
            raise NotFoundError(f"Strategy {strategy_id} not found")

        # Parse the code JSON to expose individual fields
        try:
            code_doc = json.loads(strategy["code"])
        except (json.JSONDecodeError, TypeError):
            code_doc = {"raw": strategy["code"]}

        return {
            **strategy,
            "parsed_code": code_doc,
        }

    def get_with_parsed_ir(
        self,
        strategy_id: str,
        *,
        correlation_id: str | None = None,
    ) -> dict[str, Any]:
        """
        Retrieve a strategy by ID with parsed IR + draft view (M2.C4).

        Branches on the ``source`` column persisted by ``create_from_ir``
        (migration 0025) so the frontend can render either the IR-detail
        view (source=ir_upload) or the legacy draft-form view
        (source=draft_form) from a single endpoint.

        For ``source="ir_upload"``: deserialise the canonical IR JSON
        stored in ``code`` and validate via :class:`StrategyIR`. The
        validated model is dumped via ``model_dump(mode='json')`` so it
        round-trips deeply against the original upload (M2.C4 acceptance
        criterion: "5 imported repo strategies each round-trip through
        this endpoint with deep-equal IR bodies").

        For ``source="draft_form"``: parse ``code`` as JSON and surface
        it as ``draft_fields`` for the legacy draft view. ``parsed_ir``
        is ``None``.

        Args:
            strategy_id: ULID of the strategy.
            correlation_id: Optional correlation ID for structured log
                propagation across layers.

        Returns:
            Strategy dict including ``source``, ``parsed_ir``, and
            ``draft_fields`` (exactly one of the latter two is
            populated).

        Raises:
            NotFoundError: If the strategy does not exist.
            ValidationError: If the stored IR fails ``StrategyIR``
                validation (indicates schema drift without backfill).
        """
        logger.info(
            "strategy.get_with_parsed_ir.started",
            strategy_id=strategy_id,
            correlation_id=correlation_id,
            component="StrategyService",
            operation="get_with_parsed_ir",
        )

        strategy = self._strategy_repo.get_by_id(strategy_id)
        if strategy is None:
            logger.warning(
                "strategy.get_with_parsed_ir.not_found",
                strategy_id=strategy_id,
                correlation_id=correlation_id,
                component="StrategyService",
                operation="get_with_parsed_ir",
            )
            raise NotFoundError(f"Strategy {strategy_id} not found")

        # Default to draft_form for legacy rows that pre-date migration
        # 0025 (the column has a NOT NULL default, but mocks/tests can
        # still hand back records lacking it — guard explicitly).
        source = strategy.get("source") or "draft_form"

        parsed_ir: dict[str, Any] | None = None
        draft_fields: dict[str, Any] | None = None

        if source == "ir_upload":
            # The ``code`` column for IR uploads is the canonical IR JSON
            # written verbatim by ``create_from_ir`` (sort_keys=True).
            # Re-validate to catch schema drift, then dump back to JSON-
            # compatible primitives so the response is deep-equal to the
            # original upload.
            try:
                ir_dict = json.loads(strategy["code"])
            except (json.JSONDecodeError, TypeError) as exc:
                # A non-JSON code body for an ir_upload row is a data
                # integrity violation, not a client error — log loudly
                # and surface as ValidationError so the controller can
                # decide how to render it (we don't 500 silently).
                logger.error(
                    "strategy.get_with_parsed_ir.code_not_json",
                    strategy_id=strategy_id,
                    correlation_id=correlation_id,
                    component="StrategyService",
                    operation="get_with_parsed_ir",
                    exc_info=True,
                )
                raise ValidationError(
                    f"Strategy {strategy_id} has source=ir_upload but stored "
                    f"code is not valid JSON: {exc}"
                ) from exc

            # Re-validate the stored IR against the schema as a data
            # integrity check (catches schema drift from a migration that
            # wasn't backfilled). We do NOT use the validated model's
            # ``model_dump`` for the response — Pydantic injects ``None``
            # for every unset optional field, which would break the M2.C4
            # acceptance ("5 imported repo strategies each round-trip
            # through this endpoint with deep-equal IR bodies") because
            # the production IRs deliberately omit those keys. Instead
            # we return the original parsed dict verbatim — the same
            # bytes that ``create_from_ir`` persisted in canonical form.
            try:
                StrategyIR.model_validate(ir_dict)
            except PydanticValidationError as exc:
                logger.error(
                    "strategy.get_with_parsed_ir.ir_validation_failed",
                    strategy_id=strategy_id,
                    correlation_id=correlation_id,
                    component="StrategyService",
                    operation="get_with_parsed_ir",
                    exc_info=True,
                )
                paths = [
                    "{path}: {msg}".format(
                        path=".".join(str(p) for p in err.get("loc", ())) or "<root>",
                        msg=err.get("msg", "validation failed"),
                    )
                    for err in exc.errors()
                ]
                raise ValidationError(
                    f"Strategy {strategy_id} stored IR fails schema validation: " + "; ".join(paths)
                ) from exc

            parsed_ir = ir_dict
        else:
            # Legacy draft-form path: surface whatever JSON the existing
            # strategy stored. If parsing fails fall back to a raw
            # passthrough so the frontend can still render something.
            try:
                draft_fields = json.loads(strategy["code"])
            except (json.JSONDecodeError, TypeError):
                draft_fields = {"raw": strategy["code"]}

        result = {
            **strategy,
            "source": source,
            "parsed_ir": parsed_ir,
            "draft_fields": draft_fields,
        }

        logger.info(
            "strategy.get_with_parsed_ir.completed",
            strategy_id=strategy_id,
            source=source,
            correlation_id=correlation_id,
            component="StrategyService",
            operation="get_with_parsed_ir",
        )

        return result

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
        List strategies with optional filtering and pagination.

        Args:
            created_by: Filter by creator ULID.
            is_active: Filter by active flag.
            limit: Page size.
            offset: Page offset.
            include_archived: When ``False`` (default), soft-archived
                strategies (``archived_at IS NOT NULL``) are excluded
                from the response. Existing callers that do not pass
                this kwarg keep getting archive-hidden behaviour.

        Returns:
            Dict with strategies list and pagination metadata.
        """
        strategies = self._strategy_repo.list_strategies(
            created_by=created_by,
            is_active=is_active,
            limit=limit,
            offset=offset,
            include_archived=include_archived,
        )

        logger.debug(
            "strategy.list.completed",
            count=len(strategies),
            include_archived=include_archived,
            component="StrategyService",
            operation="list_strategies",
        )

        return {
            "strategies": strategies,
            "limit": limit,
            "offset": offset,
            "count": len(strategies),
        }

    def list_strategies_page(
        self,
        *,
        page: int,
        page_size: int,
        source_filter: str | None = None,
        name_contains: str | None = None,
        created_by: str | None = None,
        is_active: bool | None = None,
        include_archived: bool = False,
    ) -> StrategyListPage:
        """
        Return one page of the strategies catalogue (M2.D5).

        Wraps :meth:`StrategyRepositoryInterface.list_with_total` and
        projects the persistence-layer dicts into the typed
        :class:`StrategyListItem` rows the route serialises. Strategy
        rows persisted before the ``source`` column existed default to
        ``"draft_form"`` so the response always satisfies the
        ``StrategyListItem.source`` regex.

        Args:
            page: 1-based page index (validated by the route layer).
            page_size: Strategies per page (capped by the route layer).
            source_filter: ``"ir_upload"`` | ``"draft_form"`` | None.
            name_contains: Case-insensitive substring filter on ``name``.
            created_by: Optional creator ULID filter.
            is_active: Optional active-flag filter.
            include_archived: When ``False`` (default), archived rows
                are excluded from both the page and the total count.

        Returns:
            :class:`StrategyListPage` value object — already validated
            against the response schema, ready to ``model_dump`` for
            JSON output.
        """
        # Translate page/page_size into limit/offset for the repository
        # (the repo speaks the lower-level vocabulary so other callers
        # like the legacy ``GET /strategies/?limit=&offset=`` still work).
        offset = max(0, (page - 1) * page_size)
        rows, total_count = self._strategy_repo.list_with_total(
            created_by=created_by,
            is_active=is_active,
            source=source_filter,
            name_contains=name_contains,
            limit=page_size,
            offset=offset,
            include_archived=include_archived,
        )

        items: list[StrategyListItem] = []
        for row in rows:
            # Defensive defaults so a legacy row that pre-dates migration
            # 0025 still satisfies the response schema. Never silently
            # drop a row — operators need to see everything in the table.
            source = row.get("source") or "draft_form"
            archived_at_raw = row.get("archived_at")
            items.append(
                StrategyListItem(
                    id=str(row["id"]),
                    name=str(row["name"]),
                    source=source,
                    version=str(row.get("version") or "0.1.0"),
                    created_by=str(row["created_by"]),
                    created_at=str(row["created_at"]),
                    is_active=bool(row.get("is_active", True)),
                    archived_at=str(archived_at_raw) if archived_at_raw is not None else None,
                )
            )

        # ceil(total_count / page_size) without importing math.
        total_pages = (total_count + page_size - 1) // page_size if page_size > 0 else 0

        result = StrategyListPage(
            strategies=items,
            page=page,
            page_size=page_size,
            total_count=total_count,
            total_pages=total_pages,
        )

        logger.debug(
            "strategy.list_page.completed",
            page=page,
            page_size=page_size,
            returned=len(items),
            total_count=total_count,
            source_filter=source_filter,
            name_contains=name_contains,
            component="StrategyService",
            operation="list_strategies_page",
        )

        return result

    def archive_strategy(
        self,
        strategy_id: str,
        *,
        requested_by: str,
        expected_row_version: int | None = None,
    ) -> dict[str, Any]:
        """
        Soft-archive a strategy by setting ``archived_at`` to UTC now.

        See :meth:`StrategyServiceInterface.archive_strategy` for the
        full contract; behaviour summary below mirrors the interface
        docstring so on-call operators can read this method in
        isolation.

        Behaviour:

        1. Resolve the source strategy via the repository. Missing →
           :class:`NotFoundError` (route maps to 404).
        2. If ``archived_at`` is already non-NULL → raise
           :class:`StrategyArchiveStateError` with
           ``current_state="archived"`` (route maps to 409).
        3. Persist via ``set_archived(archived_at=now,
           expected_row_version=...)``. Optimistic-lock mismatches
           raise :class:`RowVersionConflictError` from the repository
           layer; we let it propagate so the route maps to 409.
        4. Emit ``strategy_archived`` audit log line.

        Args:
            strategy_id: ULID of the strategy to archive.
            requested_by: ULID of the operator clicking Archive.
            expected_row_version: Optional optimistic-lock guard
                forwarded to the repository.

        Returns:
            Updated strategy dict with ``archived_at`` populated and
            ``row_version`` bumped.

        Raises:
            NotFoundError: Strategy does not exist.
            StrategyArchiveStateError: Strategy is already archived.
            RowVersionConflictError: ``expected_row_version`` mismatch
                (propagated from the repository).
        """
        logger.info(
            "strategy.archive.started",
            strategy_id=strategy_id,
            requested_by=requested_by,
            expected_row_version=expected_row_version,
            component="StrategyService",
            operation="archive_strategy",
        )

        existing = self._strategy_repo.get_by_id(strategy_id)
        if existing is None:
            logger.warning(
                "strategy.archive.not_found",
                strategy_id=strategy_id,
                requested_by=requested_by,
                component="StrategyService",
                operation="archive_strategy",
            )
            raise NotFoundError(f"Strategy {strategy_id} not found")

        if existing.get("archived_at") is not None:
            logger.warning(
                "strategy.archive.already_archived",
                strategy_id=strategy_id,
                requested_by=requested_by,
                component="StrategyService",
                operation="archive_strategy",
            )
            raise StrategyArchiveStateError(
                f"Strategy {strategy_id} is already archived",
                strategy_id=strategy_id,
                current_state="archived",
            )

        now = datetime.now(timezone.utc)
        # set_archived raises RowVersionConflictError on mismatch — we
        # let it propagate so the route layer can map it to 409 without
        # the service swallowing the lock failure.
        updated = self._strategy_repo.set_archived(
            strategy_id,
            archived_at=now,
            expected_row_version=expected_row_version,
        )

        # set_archived returns None only when the row vanished between
        # the get_by_id above and this UPDATE. Treat as NotFound — the
        # operator's view is stale and they need to refresh.
        if updated is None:
            logger.warning(
                "strategy.archive.disappeared",
                strategy_id=strategy_id,
                requested_by=requested_by,
                component="StrategyService",
                operation="archive_strategy",
            )
            raise NotFoundError(f"Strategy {strategy_id} not found")

        logger.info(
            "strategy_archived",
            strategy_id=strategy_id,
            requested_by=requested_by,
            archived_at=updated.get("archived_at"),
            row_version=updated.get("row_version"),
            component="StrategyService",
            operation="archive_strategy",
        )

        return updated

    def restore_strategy(
        self,
        strategy_id: str,
        *,
        requested_by: str,
        expected_row_version: int | None = None,
    ) -> dict[str, Any]:
        """
        Restore a soft-archived strategy by clearing ``archived_at``.

        Inverse of :meth:`archive_strategy`. See the interface docstring
        for the full contract.

        Behaviour:

        1. Resolve the source strategy. Missing → :class:`NotFoundError`.
        2. If ``archived_at`` is already NULL → raise
           :class:`StrategyArchiveStateError` with
           ``current_state="active"``.
        3. Persist via ``set_archived(archived_at=None, ...)``.
        4. Emit ``strategy_restored`` audit log line.

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
        logger.info(
            "strategy.restore.started",
            strategy_id=strategy_id,
            requested_by=requested_by,
            expected_row_version=expected_row_version,
            component="StrategyService",
            operation="restore_strategy",
        )

        existing = self._strategy_repo.get_by_id(strategy_id)
        if existing is None:
            logger.warning(
                "strategy.restore.not_found",
                strategy_id=strategy_id,
                requested_by=requested_by,
                component="StrategyService",
                operation="restore_strategy",
            )
            raise NotFoundError(f"Strategy {strategy_id} not found")

        if existing.get("archived_at") is None:
            logger.warning(
                "strategy.restore.not_archived",
                strategy_id=strategy_id,
                requested_by=requested_by,
                component="StrategyService",
                operation="restore_strategy",
            )
            raise StrategyArchiveStateError(
                f"Strategy {strategy_id} is not archived",
                strategy_id=strategy_id,
                current_state="active",
            )

        updated = self._strategy_repo.set_archived(
            strategy_id,
            archived_at=None,
            expected_row_version=expected_row_version,
        )

        if updated is None:
            logger.warning(
                "strategy.restore.disappeared",
                strategy_id=strategy_id,
                requested_by=requested_by,
                component="StrategyService",
                operation="restore_strategy",
            )
            raise NotFoundError(f"Strategy {strategy_id} not found")

        logger.info(
            "strategy_restored",
            strategy_id=strategy_id,
            requested_by=requested_by,
            row_version=updated.get("row_version"),
            component="StrategyService",
            operation="restore_strategy",
        )

        return updated

    def validate_dsl_expression(self, expression: str) -> dict[str, Any]:
        """
        Validate a DSL expression without creating a strategy.

        Used by the frontend DslEditor for live validation as the
        user types.

        Args:
            expression: Raw DSL condition string.

        Returns:
            Dict with is_valid, errors, indicators_used, variables_used.

        Example:
            result = service.validate_dsl_expression("RSI(14) < 30")
            assert result["is_valid"] is True
        """
        result = validate_dsl(expression)
        return _format_validation_result(result)

    def validate_ir(self, ir_text: str) -> StrategyValidationReport:
        """
        Run the IR import pipeline against ``ir_text`` WITHOUT persisting.

        See :meth:`StrategyServiceInterface.validate_ir` for the full
        contract. This implementation:

        - Delegates to :func:`_parse_and_validate_ir` so the validate
          path and the import path apply byte-identical semantics.
        - Catches every exception (including unexpected ones) and
          maps them to typed :class:`ValidationIssue` rows so the
          method NEVER raises. A leaked exception here would surface
          as a 500 in the route layer, which the operator-facing
          contract explicitly forbids (the request itself succeeded;
          only the IR's validity is in question).
        - Caps the issue list at :data:`MAX_VALIDATION_ISSUES` to
          bound the response payload. When truncation fires, the
          final :class:`ValidationIssue` carries
          ``code="truncated"`` so the operator sees that more
          errors exist beyond what was rendered.
        - Persists nothing — the repository is never touched.

        Args:
            ir_text: Raw IR JSON text from the operator's textarea.

        Returns:
            :class:`StrategyValidationReport` with ``valid`` flag,
            ``parsed_ir`` (on success), and ``errors`` / ``warnings``
            lists.
        """
        logger.info(
            "strategy.validate_ir.started",
            text_len=len(ir_text or ""),
            component="StrategyService",
            operation="validate_ir",
        )

        try:
            parsed_dict, ir_model, issues = _parse_and_validate_ir(ir_text)
        except Exception as exc:  # pragma: no cover — defensive guard
            # The helper is supposed to capture every failure mode in
            # the issues list. If something slips through (e.g. a future
            # refactor of the resolver leaks a non-IRReferenceError),
            # surface it as an unexpected_error issue rather than a 500
            # so the operator's UX is "validation failed, here is why"
            # not "the server crashed".
            logger.error(
                "strategy.validate_ir.unexpected_error",
                error=str(exc),
                component="StrategyService",
                operation="validate_ir",
                exc_info=True,
            )
            return StrategyValidationReport(
                valid=False,
                parsed_ir=None,
                errors=[
                    ValidationIssue(
                        path="/",
                        code="unexpected_error",
                        message=f"Validator raised {type(exc).__name__}: {exc}",
                    )
                ],
                warnings=[],
            )

        # Cap the error list at MAX_VALIDATION_ISSUES. We keep the cap
        # one short and append a synthetic "truncated" issue so the
        # operator sees that more errors exist — surfacing only the
        # head silently would mislead them about the IR's true state.
        capped_errors: list[ValidationIssue]
        if len(issues) > MAX_VALIDATION_ISSUES:
            capped_errors = list(issues[: MAX_VALIDATION_ISSUES - 1])
            extra = len(issues) - len(capped_errors)
            capped_errors.append(
                ValidationIssue(
                    path="/",
                    code="truncated",
                    message=(
                        f"Showing {len(capped_errors)} of {len(issues)} errors; "
                        f"{extra} additional issue(s) were truncated."
                    ),
                )
            )
        else:
            capped_errors = list(issues)

        is_valid = ir_model is not None and not capped_errors

        report = StrategyValidationReport(
            valid=is_valid,
            parsed_ir=parsed_dict if is_valid else None,
            errors=capped_errors,
            warnings=[],
        )

        logger.info(
            "strategy.validate_ir.completed",
            valid=is_valid,
            error_count=len(capped_errors),
            component="StrategyService",
            operation="validate_ir",
        )
        return report

    def get_strategy_ir_json(self, strategy_id: str) -> str:
        """
        Return the canonical IR JSON text for a stored strategy.

        See :meth:`StrategyServiceInterface.get_strategy_ir_json` for
        the full contract. Behaviour:

        1. Resolve the strategy via the repository. Missing →
           :class:`NotFoundError` (route maps to 404).
        2. Return the persisted ``code`` text verbatim when present.
           For ``source="ir_upload"`` rows this is the canonical IR
           JSON written by ``create_from_ir`` (sort_keys=True).
        3. Fallback for legacy / hand-inserted rows whose ``code`` is
           missing or empty: re-serialise from the parsed payload via
           ``json.dumps(..., indent=2, sort_keys=True)`` so the
           download still yields a parseable JSON document.

        Args:
            strategy_id: ULID of the strategy.

        Returns:
            JSON-encoded IR text suitable for browser download.

        Raises:
            NotFoundError: If the strategy does not exist.
        """
        logger.info(
            "strategy.get_strategy_ir_json.started",
            strategy_id=strategy_id,
            component="StrategyService",
            operation="get_strategy_ir_json",
        )

        strategy = self._strategy_repo.get_by_id(strategy_id)
        if strategy is None:
            logger.warning(
                "strategy.get_strategy_ir_json.not_found",
                strategy_id=strategy_id,
                component="StrategyService",
                operation="get_strategy_ir_json",
            )
            raise NotFoundError(f"Strategy {strategy_id} not found")

        raw_code = strategy.get("code")
        if isinstance(raw_code, str) and raw_code.strip():
            logger.info(
                "strategy.get_strategy_ir_json.completed",
                strategy_id=strategy_id,
                bytes=len(raw_code),
                fallback=False,
                component="StrategyService",
                operation="get_strategy_ir_json",
            )
            return raw_code

        # Fallback path — code missing/blank. Recover the IR by
        # parsing whatever we have and pretty-printing it. This is
        # the documented behaviour for legacy rows; we log it so an
        # operator notices when the fallback fires.
        logger.warning(
            "strategy.get_strategy_ir_json.code_blank_using_fallback",
            strategy_id=strategy_id,
            component="StrategyService",
            operation="get_strategy_ir_json",
        )

        # Try to recover via the parsed-IR view path for source=ir_upload
        # rows. For draft_form rows there is no parsed_ir; we surface
        # whatever the row's code field can be coerced into.
        source = strategy.get("source") or "draft_form"
        if source == "ir_upload":
            try:
                detail = self.get_with_parsed_ir(strategy_id)
                parsed_ir = detail.get("parsed_ir")
                if isinstance(parsed_ir, dict):
                    return json.dumps(parsed_ir, indent=2, sort_keys=True)
            except (NotFoundError, ValidationError):
                # If the round-trip itself fails, surface an empty
                # JSON object rather than raising — the download is
                # informational, not a contract endpoint that
                # callers depend on for state.
                pass

        # Absolute last resort: an empty JSON object so the download
        # always produces a parseable file. Keeps the contract
        # ("returns IR JSON text") truthful even on degraded inputs.
        return "{}"
