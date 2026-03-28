"""Research routes."""
import structlog
from fastapi import APIRouter

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/research", tags=["research"])
