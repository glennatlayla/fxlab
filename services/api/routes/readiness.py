"""
Readiness report endpoints.

GET /runs/{run_id}/readiness - Retrieve readiness report for a run
"""
import structlog
from fastapi import APIRouter, HTTPException, Path
from typing import Annotated

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
    run_id: Annotated[str, Path(description="Run ULID")]
):
    """
    Retrieve readiness report for a specific run.
    
    Returns readiness grade and any blockers preventing promotion.
    """
    logger.info("readiness.get", run_id=run_id)
    
    # Validate ULID format
    if not is_valid_ulid(run_id):
        logger.warning("readiness.invalid_ulid", run_id=run_id)
        raise HTTPException(status_code=422, detail="Invalid ULID format")
    
    # Import here to allow test patching
    from services.api.main import get_readiness_report
    
    report = get_readiness_report(run_id)
    
    if report is None:
        logger.warning("readiness.not_found", run_id=run_id)
        raise HTTPException(status_code=404, detail="Run not found")
    
    logger.info("readiness.retrieved", run_id=run_id, grade=report.get("readiness_grade"))
    return report
