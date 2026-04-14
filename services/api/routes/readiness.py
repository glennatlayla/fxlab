"""
Readiness report endpoints.

GET /runs/{run_id}/readiness - Retrieve readiness report for a run
"""

from typing import Annotated

import structlog
from fastapi import APIRouter, Depends, HTTPException, Path

from services.api.auth import AuthenticatedUser, get_current_user
from services.api.middleware.correlation import correlation_id_var

logger = structlog.get_logger()

router = APIRouter(tags=["readiness"])


def is_valid_ulid(ulid: str) -> bool:
    """Validate ULID format: 26 characters, Crockford's Base32."""
    if len(ulid) != 26:
        return False
    # Crockford's Base32 alphabet (case-insensitive)
    valid_chars = set("0123456789ABCDEFGHJKMNPQRSTVWXYZ")
    return all(c.upper() in valid_chars for c in ulid)


@router.get("/runs/{run_id}/readiness")
async def get_run_readiness(
    run_id: Annotated[str, Path(description="Run ULID")],
    user: AuthenticatedUser = Depends(get_current_user),
):
    """
    Retrieve readiness report for a specific run.

    Returns readiness grade and any blockers preventing promotion.
    """
    corr_id = correlation_id_var.get("no-corr")
    logger.info("readiness.get", run_id=run_id, correlation_id=corr_id, component="readiness")

    # Validate ULID format
    if not is_valid_ulid(run_id):
        logger.warning(
            "readiness.invalid_ulid", run_id=run_id, correlation_id=corr_id, component="readiness"
        )
        raise HTTPException(status_code=422, detail="Invalid ULID format")

    # Import here to allow test patching
    from services.api.main import get_readiness_report

    report = get_readiness_report(run_id)

    if report is None:
        logger.warning(
            "readiness.not_found", run_id=run_id, correlation_id=corr_id, component="readiness"
        )
        raise HTTPException(status_code=404, detail="Run not found")

    logger.info(
        "readiness.retrieved",
        run_id=run_id,
        grade=report.get("readiness_grade"),
        correlation_id=corr_id,
        component="readiness",
    )
    return report
