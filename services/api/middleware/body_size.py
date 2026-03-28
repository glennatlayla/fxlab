"""
Request body size limit middleware.

Responsibilities:
- Rejects requests whose body exceeds MAX_REQUEST_BODY_BYTES (default 512 KB).
- Returns 413 Payload Too Large for oversized bodies.
- Excludes: health check paths and OPTIONS requests.

Does NOT:
- Inspect body content.
- Log body payloads.
- Modify the request.

Dependencies:
- Starlette middleware base classes.

Example:
    app.add_middleware(BodySizeLimitMiddleware)
    # Limits requests to 512 KB by default, configurable via MAX_REQUEST_BODY_BYTES env var.
"""

import os

import structlog
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

logger = structlog.get_logger(__name__)

MAX_BYTES_DEFAULT = 512 * 1024  # 512 KB

_EXCLUDED_PATHS = {"/health", "/", "/docs", "/openapi.json", "/redoc"}


class BodySizeLimitMiddleware(BaseHTTPMiddleware):
    """
    Middleware that enforces a maximum request body size.

    Attributes:
        _max_bytes: Maximum allowed body size in bytes.

    Raises:
        413 Payload Too Large if body exceeds the limit.
    """

    def __init__(self, app, max_bytes: int = MAX_BYTES_DEFAULT):
        """
        Initialize the body size limit middleware.

        Args:
            app: The FastAPI application instance.
            max_bytes: Maximum body size in bytes (default: 512 KB).
                      Overridable via MAX_REQUEST_BODY_BYTES environment variable.
        """
        super().__init__(app)
        self._max_bytes = int(os.environ.get("MAX_REQUEST_BODY_BYTES", max_bytes))

    async def dispatch(self, request: Request, call_next):
        """
        Process the request and check body size before passing to handler.

        Args:
            request: The incoming HTTP request.
            call_next: The next middleware or handler in the stack.

        Returns:
            JSONResponse with 413 if body exceeds limit, otherwise the next handler's response.
        """
        # Exclude OPTIONS and health paths from size checking
        if request.method == "OPTIONS" or request.url.path in _EXCLUDED_PATHS:
            return await call_next(request)

        # Check Content-Length header
        content_length = request.headers.get("content-length")
        if content_length and int(content_length) > self._max_bytes:
            logger.warning(
                "body_size_limit.exceeded",
                content_length=int(content_length),
                max_bytes=self._max_bytes,
                path=request.url.path,
                method=request.method,
            )
            return JSONResponse(
                status_code=413,
                content={
                    "detail": f"Request body exceeds maximum size of {self._max_bytes} bytes."
                },
            )

        return await call_next(request)
