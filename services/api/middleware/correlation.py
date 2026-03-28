"""
Correlation ID middleware.

Responsibilities:
- Read X-Correlation-ID from incoming request header.
- Generate a UUID4 if not present.
- Attach the ID to every response header.
- Store in a ContextVar for use by structured loggers in all layers.

Does NOT:
- Validate the correlation ID format.
- Modify request/response bodies.

Dependencies:
- uuid for UUID4 generation.
- contextvars for propagating ID through async contexts.
- Starlette middleware.

Example:
    Client sends:
        GET / HTTP/1.1
        X-Correlation-ID: abc-123-def

    API responds:
        200 OK
        X-Correlation-ID: abc-123-def
        (all logs in this request context include correlation_id="abc-123-def")

    If client does not send X-Correlation-ID:
        API generates UUID4 and returns it.
"""

import uuid
from contextvars import ContextVar

import structlog
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request

logger = structlog.get_logger(__name__)

# ContextVar accessible from any log call within the same async context.
# All loggers configured with structlog can read this variable.
correlation_id_var: ContextVar[str] = ContextVar("correlation_id", default="no-corr")


class CorrelationIDMiddleware(BaseHTTPMiddleware):
    """
    Middleware that propagates correlation ID through request/response and context.

    Reads X-Correlation-ID from request header. If not present, generates a UUID4.
    Stores it in a ContextVar so all downstream code (loggers, services, repositories)
    can access it without passing it as a parameter.
    """

    async def dispatch(self, request: Request, call_next):
        """
        Extract or generate correlation ID, set context variable, and propagate to response.

        Args:
            request: The incoming HTTP request.
            call_next: The next middleware or handler in the stack.

        Returns:
            The response from the next handler with X-Correlation-ID header added.
        """
        # Read correlation ID from request header; generate UUID4 if not present
        corr_id = request.headers.get("X-Correlation-ID") or str(uuid.uuid4())

        # Set the context variable so all downstream code (loggers, services) can read it
        token = correlation_id_var.set(corr_id)

        logger.info(
            "correlation_id.request_received",
            correlation_id=corr_id,
            path=request.url.path,
            method=request.method,
        )

        try:
            # Process the request through the next middleware/handler
            response = await call_next(request)

            # Attach correlation ID to response header
            response.headers["X-Correlation-ID"] = corr_id

            logger.info(
                "correlation_id.response_sent",
                correlation_id=corr_id,
                status_code=response.status_code,
            )

            return response
        finally:
            # Reset the context variable to prevent leakage between requests
            correlation_id_var.reset(token)
