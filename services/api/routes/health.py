"""
Health check route for API service.

Responsibilities:
- Probe database connectivity on every health check request.
- Return 200 OK when database is reachable.
- Return 503 Service Unavailable when database is unreachable.
- Do NOT raise exceptions; catch DB errors and return graceful status.

Does NOT:
- Contain business logic.
- Log database credentials.

Dependencies:
- check_db_connection (imported dynamically to avoid circular imports at test time).

Example:
    GET /health when DB is up:
        200 OK
        {"status": "ok", "components": {"database": "ok"}}

    GET /health when DB is down:
        503 Service Unavailable
        {"status": "degraded", "components": {"database": "error"}}
"""
import structlog
from fastapi import APIRouter, Response

logger = structlog.get_logger(__name__)

router = APIRouter()


@router.get("/health")
async def health_check() -> Response:
    """
    Health check endpoint with database probe.

    Calls check_db_connection() to verify the database is reachable.
    If the database is unreachable, returns 503 (degraded) instead of 500 (error).

    Returns:
        Response with status 200 and {"status": "ok", "components": {"database": "ok"}}
        if database is reachable, or status 503 and degraded status if not.

    Raises:
        Nothing — all exceptions are caught and converted to 503 responses.
    """
    import json
    logger.info("health_check_requested")

    # Import here to avoid circular imports at module load time
    from services.api.db import check_db_connection

    try:
        db_ok = check_db_connection()
        if db_ok:
            logger.info("health_check.db_ok")
            return Response(
                content=json.dumps({
                    "status": "ok",
                    "components": {"database": "ok"},
                }),
                status_code=200,
                media_type="application/json",
            )
        else:
            logger.warning("health_check.db_unreachable")
            return Response(
                content=json.dumps({
                    "status": "degraded",
                    "components": {"database": "error"},
                }),
                status_code=503,
                media_type="application/json",
            )
    except Exception as exc:
        logger.warning("health_check.db_check_failed", error=str(exc), exc_info=True)
        return Response(
            content=json.dumps({
                "status": "degraded",
                "components": {"database": "error"},
            }),
            status_code=503,
            media_type="application/json",
        )
