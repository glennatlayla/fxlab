"""
Governance Routes Stub

Placeholder for governance approval and override endpoints.
"""
from fastapi import APIRouter
import structlog

logger = structlog.get_logger(__name__)

router = APIRouter()


@router.get("/")
async def list_governance_items():
    """List governance items endpoint stub."""
    logger.info("list_governance_items", event="List governance items called")
    return {"success": True, "data": []}
