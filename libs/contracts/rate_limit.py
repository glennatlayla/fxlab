"""
Rate limit error response contracts and exceptions.

Responsibilities:
- Define Pydantic models for rate limit error responses.
- Provide structured rate limit exception for service layer.
- Enable consistent error handling across mobile mutation endpoints.

Does NOT:
- Contain business logic.
- Handle HTTP status codes (controller layer maps these).

Example:
    from libs.contracts.rate_limit import RateLimitExceededError
    from libs.contracts.rate_limit import RateLimitErrorResponse

    try:
        check_rate_limit(...)
    except RateLimitExceededError as e:
        return JSONResponse(
            status_code=429,
            content=RateLimitErrorResponse(
                detail=e.detail,
                retry_after=e.retry_after_seconds,
            ).model_dump(),
            headers={"Retry-After": str(e.retry_after_seconds)},
        )
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from libs.contracts.errors import FXLabError


class RateLimitExceededError(FXLabError):
    """
    Raised when a rate limit is exceeded.

    The service layer or dependency raises this when a request exceeds
    the configured limit for its endpoint and time window.

    Attributes:
        detail: Human-readable error message.
        retry_after_seconds: Seconds until the client can retry.
        scope: Rate limit scope (e.g. "run_submission", "risk_setting").
        limit: Maximum requests allowed.
        window_seconds: Time window for the limit.
    """

    def __init__(
        self,
        detail: str = "Rate limit exceeded. Please slow down.",
        *,
        retry_after_seconds: int = 60,
        scope: str = "",
        limit: int = 0,
        window_seconds: int = 0,
    ) -> None:
        """
        Initialize a rate limit exceeded error.

        Args:
            detail: Error message shown to client.
            retry_after_seconds: Seconds to wait before retrying.
            scope: Rate limit scope identifier.
            limit: Max requests for this scope/window.
            window_seconds: Window size in seconds.
        """
        super().__init__(detail)
        self.detail = detail
        self.retry_after_seconds = retry_after_seconds
        self.scope = scope
        self.limit = limit
        self.window_seconds = window_seconds


class RateLimitErrorResponse(BaseModel):
    """
    HTTP response payload when rate limit is exceeded (429).

    This is the contract returned to clients when they exceed the configured
    rate limit. Always returned with HTTP 429 and Retry-After header.

    Attributes:
        detail: Human-readable error message.
        retry_after: Seconds until client may retry (matches HTTP Retry-After).
        error_code: Machine-readable error code for client handling.
    """

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "detail": "Rate limit exceeded. Please slow down.",
                "retry_after": 45,
                "error_code": "RATE_LIMIT_EXCEEDED",
            }
        }
    )

    detail: str = Field(
        default="Rate limit exceeded. Please slow down.",
        description="Human-readable error message.",
    )
    retry_after: int = Field(
        default=60,
        ge=1,
        description="Seconds to wait before retrying. Matches Retry-After header.",
    )
    error_code: str = Field(
        default="RATE_LIMIT_EXCEEDED",
        description="Machine-readable error code for client-side handling.",
    )


class RateLimitConfig(BaseModel):
    """
    Configuration for a rate limit scope.

    Used internally by the rate limit dependency to define per-endpoint limits.

    Attributes:
        scope: Unique scope identifier (e.g. "run_submission").
        max_requests: Maximum requests allowed within the window.
        window_seconds: Time window in seconds.
        description: Human-readable description for logging.
    """

    scope: str = Field(description="Unique rate limit scope identifier.")
    max_requests: int = Field(ge=1, description="Max requests per window.")
    window_seconds: int = Field(ge=1, description="Window duration in seconds.")
    description: str = Field(default="", description="Human-readable description for logging.")


class RateLimitStatus(BaseModel):
    """
    Current rate limit status for a scope and user.

    Used for informational purposes (e.g., to return via headers or in
    response payloads if the client requests status).

    Attributes:
        limit: Maximum requests for this scope/window.
        remaining: Requests remaining before hitting limit.
        reset_at: Unix timestamp when the window resets.
        scope: The rate limit scope.
    """

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "limit": 5,
                "remaining": 2,
                "reset_at": 1681234560,
                "scope": "run_submission",
            }
        }
    )

    limit: int = Field(description="Max requests per window.")
    remaining: int = Field(ge=0, description="Requests remaining this window.")
    reset_at: int = Field(description="Unix timestamp when window resets.")
    scope: str = Field(description="Rate limit scope identifier.")
