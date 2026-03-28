"""
Export endpoints (Phase 3 stub).
"""
import structlog
from fastapi import APIRouter

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/exports", tags=["exports"])


# Phase 3 endpoints will be implemented later
# This is a minimal stub to satisfy importability tests
