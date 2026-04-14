"""Health check data models."""

from typing import Literal

from libs.contracts.base import FXLabBaseModel


class HealthStatus(FXLabBaseModel):
    """Basic health status response."""

    status: Literal["ok", "degraded", "error"]


class DependencyHealth(FXLabBaseModel):
    """Dependency health status response."""

    database: Literal["ok", "degraded", "error"]
    redis: Literal["ok", "degraded", "error"]
    storage: Literal["ok", "degraded", "error"]


class ReadinessStatus(FXLabBaseModel):
    """Service readiness status response."""

    status: Literal["ready", "not_ready"]


class LivenessStatus(FXLabBaseModel):
    """Service liveness status response."""

    status: Literal["alive", "dead"]
