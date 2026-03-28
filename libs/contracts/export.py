"""
Export job contracts.

Pydantic v2 schemas for asynchronous export jobs.
"""

from datetime import datetime
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


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
    """
    id: str = Field(..., description="ULID")
    export_type: ExportType
    object_id: str
    status: ExportStatus
    artifact_uri: Optional[str] = Field(None, description="Download URI when complete")
    requested_by: str
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True
