"""
Export job contracts.

Pydantic v2 schemas for asynchronous export jobs.
"""

from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class ExportType(str, Enum):
    """Export data type."""

    TRADES = "trades"
    RUNS = "runs"
    ARTIFACTS = "artifacts"


class ExportStatus(str, Enum):
    """Export job status."""

    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETE = "complete"
    FAILED = "failed"


class ExportJobCreate(BaseModel):
    """
    Request payload to create an export job.
    """

    export_type: ExportType
    object_id: str = Field(..., description="ULID of run, candidate, or artifact")


class ExportJobResponse(BaseModel):
    """
    Response schema for export job.

    Exports are zip bundles: data.csv, metadata.json, README.txt.
    Includes override_watermark per spec §8.2 for governance visibility.
    """

    id: str = Field(..., description="ULID")
    export_type: ExportType
    object_id: str
    status: ExportStatus
    artifact_uri: str | None = Field(None, description="Download URI when complete")
    requested_by: str
    error_message: str | None = Field(None, description="Error description if failed")
    created_at: datetime
    updated_at: datetime
    override_watermark: dict[str, Any] | None = Field(
        None,
        description="Override watermark metadata for active overrides (spec §8.2)",
    )

    model_config = ConfigDict(from_attributes=True)
