"""Correlation ID contracts for distributed tracing."""

import uuid

from pydantic import BaseModel, Field, field_validator


class CorrelationContext(BaseModel):
    """Correlation tracking context.

    Attributes:
        correlation_id: Unique request/operation identifier.
        parent_id: Parent operation ID if nested.
        service_name: Service that created this context.
    """

    correlation_id: str = Field(
        default_factory=lambda: str(uuid.uuid4()),
        description="Correlation identifier",
    )
    parent_id: str | None = Field(None, description="Parent correlation ID")
    service_name: str = Field(..., description="Service name")

    @field_validator("correlation_id")
    @classmethod
    def validate_correlation_id(cls, v: str) -> str:
        """Ensure correlation ID is not empty."""
        if not v or not v.strip():
            raise ValueError("correlation_id must not be empty")
        return v.strip()

    @field_validator("service_name")
    @classmethod
    def validate_service_name(cls, v: str) -> str:
        """Ensure service name is not empty."""
        if not v or not v.strip():
            raise ValueError("service_name must not be empty")
        return v.strip()
