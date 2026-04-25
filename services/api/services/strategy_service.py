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
from typing import Any

import structlog
from pydantic import ValidationError as PydanticValidationError

from libs.contracts.errors import NotFoundError, ValidationError
from libs.contracts.interfaces.strategy_repository_interface import (
    StrategyRepositoryInterface,
)
from libs.contracts.strategy_ir import StrategyIR
from services.api.services.dsl_validator import (
    DslValidationResult,
    validate_dsl,
)
from services.api.services.interfaces.strategy_service_interface import (
    StrategyServiceInterface,
)

logger = structlog.get_logger(__name__)


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

        # Schema validation. Pydantic produces a structured error list
        # with dotted paths into the document — we surface that path
        # verbatim so M2.C1 acceptance "400 with the validation error
        # path in the response body" is satisfied without bespoke
        # reformatting at the controller layer.
        try:
            ir_model = StrategyIR.model_validate(ir_dict)
        except PydanticValidationError as exc:
            errors = exc.errors()
            paths = [
                "{path}: {msg}".format(
                    path=".".join(str(p) for p in err.get("loc", ())) or "<root>",
                    msg=err.get("msg", "validation failed"),
                )
                for err in errors
            ]
            raise ValidationError("; ".join(paths)) from exc

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
    ) -> dict[str, Any]:
        """
        List strategies with optional filtering and pagination.

        Args:
            created_by: Filter by creator ULID.
            is_active: Filter by active flag.
            limit: Page size.
            offset: Page offset.

        Returns:
            Dict with strategies list and pagination metadata.
        """
        strategies = self._strategy_repo.list_strategies(
            created_by=created_by,
            is_active=is_active,
            limit=limit,
            offset=offset,
        )

        logger.debug(
            "strategy.list.completed",
            count=len(strategies),
            component="StrategyService",
            operation="list_strategies",
        )

        return {
            "strategies": strategies,
            "limit": limit,
            "offset": offset,
            "count": len(strategies),
        }

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
