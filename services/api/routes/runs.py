"""
Routes for /runs endpoints.
Thin handlers - no business logic.
"""
from fastapi import APIRouter, HTTPException, Path
from typing import Any
import structlog
import re

logger = structlog.get_logger()

router = APIRouter(prefix="/runs", tags=["runs"])

# ULID format: 26 alphanumeric characters (Crockford's Base32)
ULID_PATTERN = re.compile(r'^[0-9A-HJKMNP-TV-Z]{26}$', re.IGNORECASE)


def is_valid_ulid(value: str) -> bool:
    """Validate ULID format."""
    return bool(ULID_PATTERN.match(value))


@router.get("/{run_id}/results")
async def get_run_results_endpoint(
    run_id: str = Path(..., description="Run ULID")
) -> dict[str, Any]:
    """
    Retrieve results for a completed run.
    
    Returns:
        Run results with metrics and artifacts
        
    Raises:
        HTTPException: 400 for invalid ULID format, 404 if run not found
    """
    logger.info("get_run_results.entry", run_id=run_id)
    
    # Validate ULID format
    if not is_valid_ulid(run_id):
        logger.warning("get_run_results.invalid_ulid", run_id=run_id)
        raise HTTPException(status_code=422, detail="Invalid ULID format")
    
    # Import here to allow mocking in tests
    from services.api.main import get_run_results

    # Retrieve results — surface service errors as 500
    try:
        results = get_run_results(run_id)
    except Exception as exc:
        logger.error("get_run_results.error", run_id=run_id, error=str(exc), exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error")

    if results is None:
        logger.warning("get_run_results.not_found", run_id=run_id)
        raise HTTPException(status_code=404, detail="Run not found")

    logger.info("get_run_results.success", run_id=run_id)
    return results
