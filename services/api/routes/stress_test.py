"""
Stress testing API endpoints.

Responsibilities:
- Expose stress test execution endpoints (predefined and custom).
- List available predefined scenarios.
- Delegate all computation to StressTestService.
- Enforce scope-based access control (deployments:read).

Does NOT:
- Contain stress test computation logic (service responsibility).
- Access databases directly (injected via DI).

Dependencies:
- StressTestService (injected per request via FastAPI DI).
- services.api.auth: scope-based access control.
- libs.contracts.stress_test: contracts.

Error conditions:
- 400: Invalid scenario parameters.
- 401: Missing or invalid authentication.
- 403: Insufficient scope.
- 404: No positions or unknown predefined scenario.

Example:
    POST /risk/stress-test {"deployment_id": "01HDEPLOY...", "scenario": "flash_crash_2010"}
    GET /risk/stress-test/scenarios
"""

from __future__ import annotations

from decimal import Decimal
from typing import TYPE_CHECKING

import structlog
from fastapi import APIRouter, Depends, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from libs.contracts.errors import NotFoundError
from libs.contracts.stress_test import ScenarioLibrary, StressScenario
from services.api.auth import AuthenticatedUser, require_scope
from services.api.db import get_db

if TYPE_CHECKING:
    from services.api.services.stress_test_service import StressTestService

router = APIRouter(prefix="/risk/stress-test", tags=["stress-test"])

logger = structlog.get_logger(__name__)


# ---------------------------------------------------------------------------
# Dependency provider
# ---------------------------------------------------------------------------


def get_stress_test_service(db: Session = Depends(get_db)) -> StressTestService:
    """
    Provide the StressTestService wired to real repositories.

    Args:
        db: SQLAlchemy session injected by FastAPI DI.

    Returns:
        StressTestService bound to position repo and risk gate.
    """
    from services.api.repositories.sql_position_repository import (
        SqlPositionRepository,
    )
    from services.api.services.risk_gate_service import RiskGateService
    from services.api.services.stress_test_service import StressTestService

    pos_repo = SqlPositionRepository(db=db)

    # Wire risk gate for halt detection — reuse existing DI pattern
    from services.api.repositories.sql_deployment_repository import (
        SqlDeploymentRepository,
    )
    from services.api.repositories.sql_risk_event_repository import (
        SqlRiskEventRepository,
    )

    deployment_repo = SqlDeploymentRepository(db=db)
    risk_event_repo = SqlRiskEventRepository(db=db)
    risk_gate = RiskGateService(
        deployment_repo=deployment_repo,
        risk_event_repo=risk_event_repo,
    )

    return StressTestService(
        position_repo=pos_repo,
        risk_gate=risk_gate,
    )


# ---------------------------------------------------------------------------
# Request schemas
# ---------------------------------------------------------------------------


class RunPredefinedRequest(BaseModel):
    """Request body for running a predefined stress scenario."""

    deployment_id: str = Field(..., min_length=1, description="Deployment ULID.")
    scenario: str = Field(..., description="Predefined scenario name from ScenarioLibrary.")


class CustomShockItem(BaseModel):
    """A single symbol → shock mapping for custom scenarios."""

    symbol: str = Field(..., min_length=1, description="Symbol or '*' for wildcard.")
    shock_pct: Decimal = Field(..., description="Percentage shock to apply.")


class RunCustomRequest(BaseModel):
    """Request body for running a custom stress scenario."""

    deployment_id: str = Field(..., min_length=1, description="Deployment ULID.")
    name: str = Field(
        default="Custom Scenario", min_length=1, max_length=200, description="Scenario name."
    )
    description: str = Field(default="", description="Scenario description.")
    shocks: list[CustomShockItem] = Field(..., min_length=1, description="Shock definitions.")


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.post(
    "",
    summary="Run a stress test scenario",
    status_code=status.HTTP_200_OK,
)
def run_stress_test(
    request: RunPredefinedRequest,
    user: AuthenticatedUser = Depends(require_scope("deployments:read")),
    service: object = Depends(get_stress_test_service),
) -> JSONResponse:
    """
    Run a predefined stress scenario against a deployment.

    Args:
        request: Request with deployment_id and predefined scenario name.
        user: Authenticated user with deployments:read scope.
        service: StressTestService (injected).

    Returns:
        JSONResponse with stress test result.
    """
    try:
        scenario_name = ScenarioLibrary(request.scenario)
    except ValueError:
        return JSONResponse(
            status_code=status.HTTP_400_BAD_REQUEST,
            content={
                "detail": f"Unknown scenario: {request.scenario}. "
                f"Valid: {[s.value for s in ScenarioLibrary if s != ScenarioLibrary.CUSTOM]}"
            },
        )

    try:
        result = service.run_predefined(  # type: ignore[attr-defined]
            deployment_id=request.deployment_id,
            scenario_name=scenario_name,
        )
    except NotFoundError as e:
        return JSONResponse(
            status_code=status.HTTP_404_NOT_FOUND,
            content={"detail": str(e)},
        )

    return JSONResponse(content=result.model_dump(mode="json"))


@router.post(
    "/custom",
    summary="Run a custom stress scenario",
    status_code=status.HTTP_200_OK,
)
def run_custom_stress_test(
    request: RunCustomRequest,
    user: AuthenticatedUser = Depends(require_scope("deployments:read")),
    service: object = Depends(get_stress_test_service),
) -> JSONResponse:
    """
    Run a custom stress scenario with user-defined shocks.

    Args:
        request: Request with deployment_id and custom shock definitions.
        user: Authenticated user with deployments:read scope.
        service: StressTestService (injected).

    Returns:
        JSONResponse with stress test result.
    """
    shocks: dict[str, Decimal] = {item.symbol: item.shock_pct for item in request.shocks}

    scenario = StressScenario(
        name=request.name,
        description=request.description,
        shocks=shocks,
        is_predefined=False,
    )

    try:
        result = service.run_scenario(  # type: ignore[attr-defined]
            deployment_id=request.deployment_id,
            scenario=scenario,
        )
    except NotFoundError as e:
        return JSONResponse(
            status_code=status.HTTP_404_NOT_FOUND,
            content={"detail": str(e)},
        )

    return JSONResponse(content=result.model_dump(mode="json"))


@router.get(
    "/scenarios",
    summary="List predefined stress scenarios",
    status_code=status.HTTP_200_OK,
)
def list_scenarios(
    user: AuthenticatedUser = Depends(require_scope("deployments:read")),
    service: object = Depends(get_stress_test_service),
) -> JSONResponse:
    """
    List all available predefined stress scenarios.

    Args:
        user: Authenticated user with deployments:read scope.
        service: StressTestService (injected).

    Returns:
        JSONResponse with list of predefined scenarios.
    """
    scenarios = service.list_predefined_scenarios()  # type: ignore[attr-defined]
    return JSONResponse(
        content={
            "scenarios": [s.model_dump(mode="json") for s in scenarios],
            "count": len(scenarios),
        }
    )
