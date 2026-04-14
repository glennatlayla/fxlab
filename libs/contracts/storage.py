"""
Storage interface contracts for artifact management.
Defines the protocol for object storage operations.
"""

from datetime import datetime
from typing import Any, Protocol

from pydantic import BaseModel, ConfigDict, Field


class StorageLocation(BaseModel):
    """
    Location descriptor for stored objects (bucket/key pairs).

    Responsibilities:
    - Identify bucket and object key for storage operations.
    - Validate location constraints.

    Example:
        loc = StorageLocation(bucket="artifacts", key="runs/01HQ.../output.parquet")
    """

    bucket: str = Field(..., description="Storage bucket name")
    key: str = Field(..., description="Object key/path within bucket")

    model_config = ConfigDict(frozen=True)


class ObjectMetadata(BaseModel):
    """
    Metadata for stored objects.

    Responsibilities:
    - Track object properties (size, content type, timestamps).
    - Carry application-specific metadata tags.

    Example:
        meta = ObjectMetadata(
            key="runs/01HQ.../output.parquet",
            content_type="application/octet-stream",
            size_bytes=1024,
            created_at=datetime.now(),
        )
    """

    key: str = Field(..., description="Object key/path")
    content_type: str = Field(default="application/octet-stream", description="MIME type")
    size_bytes: int = Field(default=0, description="Object size in bytes", ge=0)
    created_at: datetime | None = Field(default=None, description="Creation timestamp")
    version_id: str | None = Field(
        default=None, description="Version identifier (for versioned stores)"
    )
    tags: dict[str, str] = Field(default_factory=dict, description="Custom metadata tags")

    model_config = ConfigDict(from_attributes=True)


class ArtifactStorage(Protocol):
    """
    Protocol for artifact storage operations.
    Defines contract for object storage (MinIO, S3, etc).
    """

    def initialize(self, correlation_id: str) -> None:
        """
        Initialize storage backend and create required buckets.
        Must be idempotent.

        Args:
            correlation_id: Request correlation ID for tracing
        """
        ...

    def is_initialized(self) -> bool:
        """
        Check if storage backend is initialized.

        Returns:
            True if initialized, False otherwise
        """
        ...

    def health_check(self, correlation_id: str) -> bool:
        """
        Verify storage backend is accessible and healthy.

        Args:
            correlation_id: Request correlation ID for tracing

        Returns:
            True if healthy

        Raises:
            ConnectionError: If storage is unreachable
        """
        ...

    def put(
        self,
        data: bytes,
        bucket: str,
        key: str,
        metadata: dict[str, Any] | None = None,
        correlation_id: str = "",
    ) -> str:
        """
        Store artifact data in object storage.

        Args:
            data: Artifact bytes to store
            bucket: Target bucket name
            key: Object key/path
            metadata: Optional metadata dict
            correlation_id: Request correlation ID for tracing

        Returns:
            Object key of stored artifact

        Raises:
            Exception: If storage quota exceeded or other errors
        """
        ...

    def get(
        self,
        bucket: str,
        key: str,
        correlation_id: str,
    ) -> bytes:
        """
        Retrieve artifact data from object storage.

        Args:
            bucket: Source bucket name
            key: Object key/path
            correlation_id: Request correlation ID for tracing

        Returns:
            Artifact data bytes

        Raises:
            FileNotFoundError: If object not found
        """
        ...

    def get_with_metadata(
        self,
        bucket: str,
        key: str,
        correlation_id: str,
    ) -> tuple[bytes, dict[str, Any]]:
        """
        Retrieve artifact data and metadata from object storage.

        Args:
            bucket: Source bucket name
            key: Object key/path
            correlation_id: Request correlation ID for tracing

        Returns:
            Tuple of (data bytes, metadata dict)

        Raises:
            FileNotFoundError: If object not found
        """
        ...

    def list(
        self,
        bucket: str,
        prefix: str = "",
        max_keys: int | None = None,
        correlation_id: str = "",
    ) -> list[str]:
        """
        List object keys in bucket with optional prefix filter.

        Args:
            bucket: Target bucket name
            prefix: Optional key prefix filter
            max_keys: Optional maximum number of keys to return
            correlation_id: Request correlation ID for tracing

        Returns:
            List of matching object keys
        """
        ...

    def delete(
        self,
        bucket: str,
        key: str,
        correlation_id: str,
    ) -> None:
        """
        Delete artifact from object storage.
        Must be idempotent (no error if object doesn't exist).

        Args:
            bucket: Target bucket name
            key: Object key/path
            correlation_id: Request correlation ID for tracing
        """
        ...
