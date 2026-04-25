"""
ClientSourceMiddleware — extract client source from X-Client-Source header (BE-07).

Purpose:
    Extract the X-Client-Source header from incoming requests and store it in
    request state so downstream handlers can access it when writing audit events.

Responsibilities:
    - Intercept all incoming requests.
    - Extract X-Client-Source header if present.
    - Validate against allowed values: "web-desktop", "web-mobile", "api".
    - Store validated source in request.state.client_source for downstream use.
    - Default to None if header is missing, empty, or invalid.
    - Never reject requests — source extraction is informational only.

Does NOT:
    - Perform business logic.
    - Modify request/response bodies.
    - Log sensitive data.
    - Enforce authentication or authorization.

Dependencies:
    - Starlette middleware base classes.
    - structlog: Structured logging.

Example:
    app.add_middleware(ClientSourceMiddleware)
    # GET /api/test with X-Client-Source: web-desktop
    # -> request.state.client_source == "web-desktop"
    # GET /api/test with X-Client-Source: invalid
    # -> request.state.client_source == None
    # GET /api/test (no header)
    # -> request.state.client_source == None
"""

from __future__ import annotations

import structlog
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

logger = structlog.get_logger(__name__)

# Valid client source values
_VALID_SOURCES = {"web-desktop", "web-mobile", "api"}


class ClientSourceMiddleware(BaseHTTPMiddleware):
    """
    Middleware that extracts client source from X-Client-Source header.

    Behavior:
    - Extracts X-Client-Source header from every request.
    - Validates it against allowed values.
    - Stores result in request.state.client_source (string or None).
    - Does NOT reject requests for invalid/missing headers.
    - All operations are synchronous (no I/O).

    Attributes:
        None (stateless middleware).

    Raises:
        None. Invalid headers are logged but do not raise exceptions.

    Example:
        app.add_middleware(ClientSourceMiddleware)

        @app.post("/api/test")
        async def handler(request: Request):
            source = request.state.client_source
            # source will be "web-desktop", "web-mobile", "api", or None
            return {"source": source}
    """

    async def dispatch(self, request: Request, call_next) -> Response:
        """
        Process the request and extract client source.

        Args:
            request: The incoming HTTP request.
            call_next: The next middleware or handler in the stack.

        Returns:
            The response from the next handler, unmodified.

        Raises:
            None. Invalid sources are logged but do not raise exceptions.
        """
        # Extract X-Client-Source header
        source_header = request.headers.get("X-Client-Source", "").strip()

        # Validate and store in request state
        if source_header and source_header in _VALID_SOURCES:
            request.state.client_source = source_header
            logger.debug(
                "client_source.extracted",
                source=source_header,
                path=request.url.path,
                method=request.method,
                component="client_source_middleware",
            )
        else:
            request.state.client_source = None
            if source_header:
                # Log when header is present but invalid
                logger.debug(
                    "client_source.invalid_or_missing",
                    source_header=source_header,
                    path=request.url.path,
                    method=request.method,
                    component="client_source_middleware",
                )

        # Pass through to next handler (never reject)
        response = await call_next(request)
        return response
