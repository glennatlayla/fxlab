"""
FastAPI dependency injection providers.

Provides request-scoped services and authentication.
"""
import structlog
from fastapi import Header, HTTPException, status
from typing import Annotated

logger = structlog.get_logger()


async def get_current_user(
    x_user_id: Annotated[str | None, Header()] = None
) -> str:
    """
    Extract current user from request headers.
    
    In production, this would validate JWT tokens.
    For testing, we accept X-User-ID header.
    """
    if not x_user_id:
        logger.warning("authentication_missing")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required"
        )
    
    logger.debug("user_authenticated", user_id=x_user_id)
    return x_user_id
