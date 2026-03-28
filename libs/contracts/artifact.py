"""
Artifact registry contracts.

These models represent artifact metadata and retrieval requests.
"""

from datetime import datetime
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


class ArtifactType(str, Enum):
    """Artifact type enumeration."""

    COMPILED_STRATEGY = "compiled_strategy"
    BACKTEST_RESULT = "backtest_result"
    OPTIMIZATION_RESULT = "optimization_result"
    HOLDOUT_RESULT = "holdout_result"
    READINESS_REPORT = "readiness_report"
    EXPORT_BUNDLE = "export_bundle"


class Artifact(BaseModel):
    """
    Artifact metadata entity.

    Represents a registered artifact in the artifact registry.
    """

    id: str = Field(..., description="Artifact ULID")
    artifact_type: ArtifactType = Field(..., description="Artifact type")
    subject_id: str = Field(..., description="Subject entity ULID (run_id, candidate_id, etc.)")
    storage_path: str = Field(..., description="Storage path (S3 key, filesystem path)")
    size_bytes: int = Field(..., description="Artifact size in bytes", ge=0)
    created_at: datetime = Field(..., description="Creation timestamp")
    created_by: str = Field(..., description="User ULID who created the artifact")
    metadata: dict[str, str] = Field(
        default_factory=dict, description="Additional artifact metadata"
    )


class ArtifactQuery(BaseModel):
    """
    Artifact query request.

    Submitted from the artifact browser UI to filter and retrieve artifacts.
    """

    artifact_types: Optional[list[ArtifactType]] = Field(
        default=None, description="Filter by artifact types"
    )
    subject_id: Optional[str] = Field(
        default=None, description="Filter by subject entity ULID"
    )
    created_by: Optional[str] = Field(
        default=None, description="Filter by creator user ULID"
    )
    start_time: Optional[datetime] = Field(
        default=None, description="Filter by creation start timestamp (inclusive)"
    )
    end_time: Optional[datetime] = Field(
        default=None, description="Filter by creation end timestamp (inclusive)"
    )
    limit: int = Field(default=100, description="Maximum number of artifacts to return", ge=1, le=1000)
    offset: int = Field(default=0, description="Pagination offset", ge=0)


class ArtifactQueryResponse(BaseModel):
    """
    Artifact query response.

    Contains paginated artifact metadata entries.
    """

    artifacts: list[Artifact] = Field(..., description="Artifact metadata entries")
    total_count: int = Field(..., description="Total matching artifacts", ge=0)
    limit: int = Field(..., description="Applied limit", ge=1)
    offset: int = Field(..., description="Applied offset", ge=0)
