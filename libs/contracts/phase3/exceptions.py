"""
Phase 3 exception contracts.

All Phase 3 services must map internal exceptions to these contract types
before serializing to clients.
"""

from enum import Enum

from pydantic import BaseModel, Field


class ErrorCategory(str, Enum):
    """Top-level error categorization for client handling."""

    VALIDATION = "validation"
    AUTHORIZATION = "authorization"
    NOT_FOUND = "not_found"
    CONFLICT = "conflict"
    RATE_LIMIT = "rate_limit"
    DEPENDENCY = "dependency"
    INTERNAL = "internal"


class ErrorDetail(BaseModel):
    """
    Granular error detail for field-level or sub-component failures.

    Used in validation errors to pinpoint which fields failed and why.
    """

    field: str | None = Field(None, description="Field name or JSON path if applicable")
    message: str = Field(description="Human-readable error message")
    error_code: str | None = Field(
        None, description="Machine-readable error code for programmatic handling"
    )


class ErrorResponse(BaseModel):
    """
    Standard error response envelope for all Phase 3 API errors.

    Clients must handle this structure uniformly across all endpoints.
    """

    category: ErrorCategory = Field(description="Error category for client-side routing")
    message: str = Field(description="Top-level human-readable error message")
    details: list[ErrorDetail] = Field(
        default_factory=list,
        description="Granular error details (e.g., validation failures per field)",
    )
    request_id: str = Field(description="Unique request identifier for log correlation")
    timestamp: str = Field(description="ISO 8601 UTC timestamp of error occurrence")
    retryable: bool = Field(default=False, description="Whether client should retry the request")


class ValidationErrorResponse(ErrorResponse):
    """
    Validation error with field-level details.

    Returned when request payload fails schema validation.
    """

    category: ErrorCategory = Field(default=ErrorCategory.VALIDATION)
    invalid_fields: list[str] = Field(
        default_factory=list, description="List of field names that failed validation"
    )


class AuthorizationErrorResponse(ErrorResponse):
    """
    Authorization error indicating insufficient permissions.

    Client must not retry without acquiring additional privileges.
    """

    category: ErrorCategory = Field(default=ErrorCategory.AUTHORIZATION)
    required_permission: str | None = Field(
        None, description="Permission required to perform the requested action"
    )
    current_role: str | None = Field(None, description="Authenticated user's current role")


class NotFoundErrorResponse(ErrorResponse):
    """
    Resource not found error.

    Indicates requested resource does not exist or is not accessible to the user.
    """

    category: ErrorCategory = Field(default=ErrorCategory.NOT_FOUND)
    resource_type: str | None = Field(
        None, description="Type of resource that was not found (e.g., 'strategy', 'job')"
    )
    resource_id: str | None = Field(
        None, description="Identifier of the resource that was not found"
    )


class ConflictErrorResponse(ErrorResponse):
    """
    Conflict error indicating operation cannot proceed due to state conflict.

    Common cases: optimistic locking failure, duplicate submission, state transition violation.
    """

    category: ErrorCategory = Field(default=ErrorCategory.CONFLICT)
    conflict_type: str | None = Field(
        None, description="Type of conflict (e.g., 'duplicate_name', 'state_transition')"
    )
    conflicting_resource_id: str | None = Field(
        None, description="ID of resource causing the conflict"
    )


class RateLimitErrorResponse(ErrorResponse):
    """
    Rate limit exceeded error.

    Client must back off before retrying.
    """

    category: ErrorCategory = Field(default=ErrorCategory.RATE_LIMIT)
    retry_after_seconds: int = Field(
        description="Number of seconds client must wait before retrying"
    )
    limit: int = Field(description="Rate limit threshold that was exceeded")
    window_seconds: int = Field(description="Time window for the rate limit in seconds")


class DependencyErrorResponse(ErrorResponse):
    """
    Dependency failure error indicating an external service is unavailable.

    Examples: database timeout, Redis connection failure, queue broker unreachable.
    """

    category: ErrorCategory = Field(default=ErrorCategory.DEPENDENCY)
    dependency_name: str = Field(
        description="Name of the failed dependency (e.g., 'postgres', 'redis')"
    )
    retryable: bool = Field(default=True, description="Dependency errors are typically retryable")
