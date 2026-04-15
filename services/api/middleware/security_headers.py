"""
Security headers middleware for FXLab API.

Purpose:
    Inject OWASP-recommended security headers into every HTTP response
    to protect against clickjacking, MIME sniffing, XSS, and downgrade
    attacks.

Responsibilities:
    - Add X-Frame-Options: DENY (prevent clickjacking).
    - Add X-Content-Type-Options: nosniff (prevent MIME sniffing).
    - Add X-XSS-Protection: 1; mode=block (legacy XSS filter).
    - Add Referrer-Policy: strict-origin-when-cross-origin, no-referrer.
    - Add Permissions-Policy: deny camera, microphone, geolocation, payment.
    - Optionally add Strict-Transport-Security (HSTS) when enabled.

Does NOT:
    - Manage CORS (that is CORSMiddleware's job).
    - Handle authentication or authorization.
    - Set Content-Security-Policy (requires per-app tuning).

Dependencies:
    - Starlette BaseHTTPMiddleware.

Error conditions:
    - None — middleware is transparent; errors in call_next propagate normally.

Configuration:
    - enable_hsts: Set to True when behind an HTTPS-only reverse proxy.
    - hsts_max_age: HSTS max-age in seconds (default: 31536000 = 1 year).

Example:
    app.add_middleware(SecurityHeadersMiddleware, enable_hsts=True)
"""

from __future__ import annotations

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """
    Injects standard security headers into every response.

    These headers provide baseline protection against common web attacks
    and are required by OWASP guidelines for any internet-facing application.

    Args:
        app: The ASGI application to wrap.
        enable_hsts: Whether to include Strict-Transport-Security header.
            Only enable when ALL traffic is HTTPS (behind TLS-terminating
            reverse proxy). Default: False.
        hsts_max_age: HSTS max-age directive in seconds.
            Default: 31536000 (1 year). Ignored when enable_hsts is False.

    Example:
        app.add_middleware(SecurityHeadersMiddleware, enable_hsts=True)
    """

    def __init__(
        self,
        app: object,
        enable_hsts: bool = False,
        hsts_max_age: int = 31_536_000,
    ) -> None:
        super().__init__(app)  # type: ignore[arg-type]
        self._enable_hsts = enable_hsts
        self._hsts_max_age = hsts_max_age

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        """
        Process request and inject security headers into the response.

        Args:
            request: Incoming HTTP request.
            call_next: Next middleware or route handler.

        Returns:
            Response with security headers added.
        """
        response = await call_next(request)

        # Clickjacking protection — prevents the page from being embedded in iframes
        response.headers["X-Frame-Options"] = "DENY"

        # MIME sniffing prevention — stops browsers from guessing content types
        response.headers["X-Content-Type-Options"] = "nosniff"

        # Legacy XSS filter — tells older browsers to block detected XSS attacks
        response.headers["X-XSS-Protection"] = "1; mode=block"

        # Referrer control — limits information leaked in the Referer header
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin, no-referrer"

        # Permissions policy — restricts browser features the page can use
        response.headers["Permissions-Policy"] = (
            "camera=(), microphone=(), geolocation=(), payment=(), "
            "usb=(), magnetometer=(), gyroscope=(), accelerometer=()"
        )

        # HSTS — forces HTTPS for all future connections (only when enabled)
        if self._enable_hsts:
            response.headers["Strict-Transport-Security"] = (
                f"max-age={self._hsts_max_age}; includeSubDomains"
            )

        return response
