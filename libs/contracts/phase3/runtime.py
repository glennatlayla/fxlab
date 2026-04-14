"""
Phase 3 runtime contracts for Docker Compose orchestration and health checking.

All services in Phase 3 must implement health check endpoints that support
container orchestration readiness and liveness probes.
"""

from datetime import datetime
from enum import Enum
from typing import Literal

from pydantic import BaseModel, Field


class ServiceStatus(str, Enum):
    """Health status enumeration for containerized services."""

    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNHEALTHY = "unhealthy"


class DependencyHealth(BaseModel):
    """Health status of a service dependency."""

    name: str = Field(description="Dependency service name (e.g., 'postgres', 'redis')")
    status: ServiceStatus = Field(description="Current health status of the dependency")
    latency_ms: float | None = Field(None, description="Last measured latency in milliseconds")
    error_message: str | None = Field(None, description="Error detail if unhealthy")


class HealthCheckResponse(BaseModel):
    """
    Standard health check response for all Phase 3 services.

    Consumed by Docker health checks, load balancers, and orchestration tooling.
    """

    service: str = Field(description="Service identifier (e.g., 'api', 'web')")
    status: ServiceStatus = Field(description="Overall service health status")
    timestamp: datetime = Field(description="UTC timestamp of health check execution")
    version: str = Field(description="Service version or build hash")
    dependencies: list[DependencyHealth] = Field(
        default_factory=list, description="Health of external dependencies"
    )
    uptime_seconds: float = Field(description="Service uptime in seconds")


class ReadinessCheckResponse(BaseModel):
    """
    Readiness check response indicating service is ready to accept traffic.

    Differs from liveness in that a service may be alive but not ready
    (e.g., still warming caches, awaiting database migrations).
    """

    ready: bool = Field(description="True if service can accept traffic")
    reason: str | None = Field(None, description="Human-readable reason if not ready")
    checks: dict[str, bool] = Field(description="Map of readiness check names to pass/fail status")


class LivenessCheckResponse(BaseModel):
    """
    Liveness check response indicating service process is alive.

    Used by orchestrators to determine if a container should be restarted.
    """

    alive: bool = Field(description="True if service process is responsive")
    timestamp: datetime = Field(description="UTC timestamp of liveness probe")


class EnvironmentMode(str, Enum):
    """Runtime environment mode."""

    DEVELOPMENT = "development"
    CI = "ci"
    STAGING = "staging"
    PRODUCTION = "production"


class ServiceConfiguration(BaseModel):
    """
    Base service configuration model.

    All Phase 3 services must expose their active configuration for
    debugging and audit purposes.
    """

    environment: EnvironmentMode = Field(description="Active environment mode")
    debug_enabled: bool = Field(description="Whether debug mode is active")
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = Field(
        description="Active logging level"
    )
    cors_origins: list[str] = Field(default_factory=list, description="Allowed CORS origins")


class APIServiceConfiguration(ServiceConfiguration):
    """Configuration specific to the FastAPI service."""

    database_url: str = Field(description="PostgreSQL connection string (credentials redacted)")
    redis_url: str = Field(description="Redis connection string (credentials redacted)")
    max_request_size_mb: int = Field(
        default=10, description="Maximum allowed request body size in MB"
    )
    rate_limit_enabled: bool = Field(default=True, description="Whether rate limiting is active")


class WebServiceConfiguration(ServiceConfiguration):
    """Configuration specific to the web frontend service."""

    api_base_url: str = Field(description="Base URL for backend API calls")
    build_timestamp: datetime | None = Field(
        None, description="UTC timestamp of static asset build"
    )
    enable_hot_reload: bool = Field(
        default=False, description="Whether hot module reloading is enabled"
    )
