"""
Strategy comparison API routes (Phase 7 — M13).

Responsibilities:
- POST /strategies/compare — Compare and rank strategies.
- GET /strategies/{deployment_id}/metrics — Per-strategy expanded metrics.

Does NOT:
- Implement comparison logic (service responsibility).
- Validate business rules (service responsibility).

Dependencies:
- StrategyComparisonServiceInterface (injected via DI).
- JWT auth with scope enforcement.

Error conditions:
- 400: Validation errors, insufficient data.
- 401: Missing or invalid auth token.
- 403: Insufficient scope.
- 404: Deployment not found.

Example:
    POST /strategies/compare
    {
        "deployment_ids": ["01HDEPLOY...", "01HDEPLOY..."],
        "ranking_criteria": "sharpe_ratio"
    }
"""

from __future__ import annotations

import logging
from datetime import date

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from libs.contracts.errors import NotFoundError, ValidationError
from libs.contracts.strategy_comparison import (
    StrategyComparisonRequest,
    StrategyRankingCriteria,
)
from services.api.auth import require_scope

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Strategy Comparison"])


# ---------------------------------------------------------------------------
# Request / Response schemas (API layer)
# ---------------------------------------------------------------------------


class CompareStrategiesRequest(BaseModel):
    """API request body for comparing strategies."""

    deployment_ids: list[str] = Field(
        ..., min_length=2, max_length=50, description="Deployment IDs to compare."
    )
    date_from: date | None = Field(default=None, description="Period start.")
    date_to: date | None = Field(default=None, description="Period end.")
    ranking_criteria: StrategyRankingCriteria = Field(
        default=StrategyRankingCriteria.SHARPE_RATIO,
        description="Metric to rank by.",
    )


# ---------------------------------------------------------------------------
# Dependency injection
# ---------------------------------------------------------------------------


def get_strategy_comparison_service():
    """
    Build a StrategyComparisonService with real dependencies.

    Wires PnlAttributionService into the comparison service using
    the same DI pattern as other route modules.

    Returns:
        StrategyComparisonService instance.
    """
    from services.api.dependencies import get_db_session
    from services.api.repositories.sql_deployment_repository import (
        SqlDeploymentRepository,
    )
    from services.api.repositories.sql_order_fill_repository import (
        SqlOrderFillRepository,
    )
    from services.api.repositories.sql_order_repository import SqlOrderRepository
    from services.api.repositories.sql_pnl_snapshot_repository import (
        SqlPnlSnapshotRepository,
    )
    from services.api.repositories.sql_position_repository import (
        SqlPositionRepository,
    )
    from services.api.services.pnl_attribution_service import PnlAttributionService
    from services.api.services.strategy_comparison_service import (
        StrategyComparisonService,
    )

    session = get_db_session()
    pnl_service = PnlAttributionService(
        deployment_repo=SqlDeploymentRepository(session=session),
        position_repo=SqlPositionRepository(session=session),
        order_fill_repo=SqlOrderFillRepository(session=session),
        order_repo=SqlOrderRepository(session=session),
        pnl_snapshot_repo=SqlPnlSnapshotRepository(session=session),
    )
    return StrategyComparisonService(pnl_service=pnl_service)


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.post(
    "/strategies/compare",
    response_model=None,
    dependencies=[Depends(require_scope("deployments:read"))],
)
def compare_strategies(
    body: CompareStrategiesRequest,
    service=Depends(get_strategy_comparison_service),
) -> dict:
    """
    Compare and rank multiple strategies.

    Accepts deployment IDs and ranking criteria, returns ranked results
    with full comparison matrix.

    Args:
        body: Comparison request.
        service: Injected comparison service.

    Returns:
        StrategyComparisonResult as dict.

    Raises:
        HTTPException 400: Validation error or insufficient data.
    """
    logger.info(
        "Strategy comparison request received",
        extra={
            "operation": "compare_strategies",
            "component": "strategy_comparison_routes",
            "deployment_count": len(body.deployment_ids),
            "criteria": body.ranking_criteria.value,
        },
    )
    try:
        request = StrategyComparisonRequest(
            deployment_ids=body.deployment_ids,
            date_from=body.date_from,
            date_to=body.date_to,
            ranking_criteria=body.ranking_criteria,
        )
        result = service.compare_strategies(request)
        logger.info(
            "Strategy comparison request completed",
            extra={
                "operation": "compare_strategies",
                "component": "strategy_comparison_routes",
                "result": "success",
                "rankings_count": len(result.rankings),
            },
        )
        return result.model_dump(mode="json")
    except ValidationError as exc:
        logger.warning(
            "Strategy comparison validation failed",
            extra={
                "operation": "compare_strategies",
                "component": "strategy_comparison_routes",
                "result": "failure",
            },
        )
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        logger.error(
            "Strategy comparison failed",
            extra={
                "operation": "compare_strategies",
                "component": "strategy_comparison_routes",
                "result": "failure",
            },
            exc_info=True,
        )
        raise HTTPException(status_code=500, detail="Strategy comparison failed") from exc


@router.get(
    "/strategies/{deployment_id}/metrics",
    response_model=None,
    dependencies=[Depends(require_scope("deployments:read"))],
)
def get_strategy_metrics(
    deployment_id: str,
    service=Depends(get_strategy_comparison_service),
) -> dict:
    """
    Get expanded metrics for a single strategy deployment.

    Args:
        deployment_id: Deployment identifier.
        service: Injected comparison service.

    Returns:
        StrategyMetrics as dict.

    Raises:
        HTTPException 404: Deployment not found.
    """
    logger.info(
        "Strategy metrics request received",
        extra={
            "operation": "get_strategy_metrics",
            "component": "strategy_comparison_routes",
            "deployment_id": deployment_id,
        },
    )
    try:
        metrics = service.get_strategy_metrics(deployment_id)
        logger.info(
            "Strategy metrics request completed",
            extra={
                "operation": "get_strategy_metrics",
                "component": "strategy_comparison_routes",
                "deployment_id": deployment_id,
                "result": "success",
            },
        )
        return metrics.model_dump(mode="json")
    except NotFoundError as exc:
        logger.warning(
            "Strategy metrics not found",
            extra={
                "operation": "get_strategy_metrics",
                "component": "strategy_comparison_routes",
                "deployment_id": deployment_id,
                "result": "failure",
            },
        )
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:
        logger.error(
            "Get strategy metrics failed",
            extra={
                "operation": "get_strategy_metrics",
                "component": "strategy_comparison_routes",
                "deployment_id": deployment_id,
            },
            exc_info=True,
        )
        raise HTTPException(status_code=500, detail="Failed to compute strategy metrics") from exc
