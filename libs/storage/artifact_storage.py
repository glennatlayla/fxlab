"""
Artifact storage interface for object storage operations.

Provides abstraction over S3-compatible storage (MinIO) for:
- Storing experiment artifacts, datasets, and model outputs
- Retrieving artifacts with metadata
- Listing and discovering artifacts by prefix
- Managing bucket lifecycle

All operations accept correlation_id for distributed tracing.
"""

from abc import ABC, abstractmethod
from typing import Any


class ArtifactStorage(ABC):
    """
    Abstract interface for artifact object storage operations.

    Implementations must handle:
    - Bucket initialization and health checks
    - Object put/get with metadata preservation
    - Prefix-based listing with pagination
    - Idempotent delete operations
    - Correlation ID propagation for observability
    """

    @abstractmethod
    def initialize(self, correlation_id: str) -> None:
        """
        Initialize storage backend and create required buckets.

        Must be idempotent - safe to call multiple times.

        Args:
            correlation_id: Request correlation ID for tracing

        Raises:
            ConnectionError: If storage backend is unreachable
            PermissionError: If insufficient permissions to create buckets
        """
        pass

    @abstractmethod
    def is_initialized(self) -> bool:
        """
        Check if storage has been initialized.

        Returns:
            True if initialize() has completed successfully, False otherwise
        """
        pass

    @abstractmethod
    def health_check(self, correlation_id: str) -> bool:
        """
        Verify storage backend is accessible and healthy.

        Args:
            correlation_id: Request correlation ID for tracing

        Returns:
            True if storage is accessible and operational

        Raises:
            ConnectionError: If storage backend is unreachable
        """
        pass

    @abstractmethod
    def put(
        self,
        data: bytes,
        bucket: str,
        key: str,
        metadata: dict[str, Any] | None = None,
        correlation_id: str | None = None,
    ) -> str:
        """
        Store artifact data with optional metadata.

        For large files (>5MB), should use multipart upload automatically.
        Stores correlation_id in object metadata for tracing.

        Args:
            data: Artifact content as bytes
            bucket: Target bucket name
            key: Object key (path within bucket)
            metadata: Optional custom metadata dict
            correlation_id: Request correlation ID for tracing

        Returns:
            Full object key/path of stored artifact

        Raises:
            Exception: If storage quota exceeded or write fails
            ConnectionError: If storage backend unreachable
        """
        pass

    @abstractmethod
    def get(
        self,
        bucket: str,
        key: str,
        correlation_id: str,
    ) -> bytes:
        """
        Retrieve artifact data by key.

        Args:
            bucket: Source bucket name
            key: Object key to retrieve
            correlation_id: Request correlation ID for tracing

        Returns:
            Artifact content as bytes

        Raises:
            FileNotFoundError: If object does not exist
            ConnectionError: If storage backend unreachable
        """
        pass

    @abstractmethod
    def get_with_metadata(
        self,
        bucket: str,
        key: str,
        correlation_id: str,
    ) -> tuple[bytes, dict[str, Any]]:
        """
        Retrieve artifact data and metadata together.

        Args:
            bucket: Source bucket name
            key: Object key to retrieve
            correlation_id: Request correlation ID for tracing

        Returns:
            Tuple of (data bytes, metadata dict)

        Raises:
            FileNotFoundError: If object does not exist
            ConnectionError: If storage backend unreachable
        """
        pass

    @abstractmethod
    def list(
        self,
        bucket: str,
        prefix: str,
        correlation_id: str,
        max_keys: int | None = None,
    ) -> list[str]:
        """
        List object keys matching prefix.

        Supports pagination via max_keys parameter.

        Args:
            bucket: Bucket to list from
            prefix: Key prefix filter
            correlation_id: Request correlation ID for tracing
            max_keys: Optional maximum number of keys to return

        Returns:
            List of matching object keys

        Raises:
            ConnectionError: If storage backend unreachable
        """
        pass

    @abstractmethod
    def delete(
        self,
        bucket: str,
        key: str,
        correlation_id: str,
    ) -> None:
        """
        Delete artifact by key.

        Must be idempotent - deleting non-existent key is not an error.

        Args:
            bucket: Source bucket name
            key: Object key to delete
            correlation_id: Request correlation ID for tracing

        Raises:
            ConnectionError: If storage backend unreachable
        """
        pass
