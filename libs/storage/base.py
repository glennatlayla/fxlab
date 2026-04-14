"""
Canonical artifact storage interface for FXLab.

Responsibilities:
- Define the single authoritative abstract base class for all storage backends.
- All concrete implementations (local filesystem, MinIO/S3) must inherit from
  ArtifactStorageBase and implement every abstract method.
- Provide the interface contract tested in unit tests via mocks and the
  LocalArtifactStorage implementation.

Does NOT:
- Perform any I/O itself.
- Know about artifact metadata schemas or Pydantic models.
- Handle authentication, retries, or back-off (that belongs in concrete impls).

Dependencies:
- Standard library only (abc, typing, pathlib).

Replaces:
- libs/storage/artifact_storage.py (sync ABC, not wired to an inheritor)
- libs/storage/interface.py (sync ABC duplicate)
- libs/storage/interfaces/object_storage.py (async ABC — kept for async use cases)

Error conditions:
- Concrete impls MUST raise FileNotFoundError for missing objects in get().
- Concrete impls MUST raise ConnectionError if the backend is unreachable.
- delete() MUST be idempotent — no error for non-existent keys.

Example:
    class LocalArtifactStorage(ArtifactStorageBase):
        def put(self, data, bucket, key, metadata=None, correlation_id=None):
            ...

    storage = LocalArtifactStorage(root="/tmp/fxlab")
    key = storage.put(b"hello", "artifacts", "test.bin")
    data = storage.get("artifacts", "test.bin", correlation_id="corr-123")
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class ArtifactStorageBase(ABC):
    """
    Abstract base class for FXLab artifact storage backends.

    Provides a synchronous interface for put / get / list / delete operations.
    Implementations must be thread-safe and idempotent where noted.

    Concrete implementations:
    - LocalArtifactStorage  — local filesystem, used in tests and local dev
    - MinIOArtifactStorage  — MinIO / S3-compatible, used in staging + prod

    All operations propagate a correlation_id for distributed tracing.
    """

    @abstractmethod
    def initialize(self, correlation_id: str) -> None:
        """
        Initialize the storage backend and create any required buckets/dirs.

        Must be idempotent — safe to call multiple times without side effects.

        Args:
            correlation_id: Request correlation ID for distributed tracing.

        Raises:
            ConnectionError: If the storage backend is unreachable.
            PermissionError: If credentials are insufficient to create buckets.
        """
        ...

    @abstractmethod
    def is_initialized(self) -> bool:
        """
        Return whether initialize() has completed successfully.

        Returns:
            True if the backend is ready to accept operations.
        """
        ...

    @abstractmethod
    def health_check(self, correlation_id: str) -> bool:
        """
        Verify the storage backend is accessible and operational.

        Args:
            correlation_id: Request correlation ID for distributed tracing.

        Returns:
            True if the backend is healthy.

        Raises:
            ConnectionError: If the backend is unreachable.
        """
        ...

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
        Store binary data at the given bucket/key, optionally with metadata.

        Implementations should store correlation_id inside the object metadata
        for end-to-end traceability.

        Args:
            data: Raw bytes to store.
            bucket: Logical bucket name (directory or S3 bucket).
            key: Object key / filename within the bucket.
            metadata: Optional dict of string-serialisable key-value pairs.
            correlation_id: Request correlation ID for distributed tracing.

        Returns:
            The full storage path of the stored object (bucket/key form).

        Raises:
            Exception: If the backend is full or the write otherwise fails.
            ConnectionError: If the backend is unreachable.
        """
        ...

    @abstractmethod
    def get(
        self,
        bucket: str,
        key: str,
        correlation_id: str,
    ) -> bytes:
        """
        Retrieve binary data for the given bucket/key.

        Args:
            bucket: Logical bucket name.
            key: Object key / filename within the bucket.
            correlation_id: Request correlation ID for distributed tracing.

        Returns:
            Raw bytes of the stored object.

        Raises:
            FileNotFoundError: If the object does not exist.
            ConnectionError: If the backend is unreachable.
        """
        ...

    @abstractmethod
    def get_with_metadata(
        self,
        bucket: str,
        key: str,
        correlation_id: str,
    ) -> tuple[bytes, dict[str, Any]]:
        """
        Retrieve binary data and its associated metadata.

        Args:
            bucket: Logical bucket name.
            key: Object key / filename within the bucket.
            correlation_id: Request correlation ID for distributed tracing.

        Returns:
            Tuple of (raw_bytes, metadata_dict).

        Raises:
            FileNotFoundError: If the object does not exist.
            ConnectionError: If the backend is unreachable.
        """
        ...

    @abstractmethod
    def list(
        self,
        bucket: str,
        prefix: str,
        correlation_id: str,
        max_keys: int | None = None,
    ) -> list[str]:
        """
        List object keys in a bucket that match the given prefix.

        Args:
            bucket: Logical bucket name.
            prefix: Key prefix filter (empty string = list all).
            correlation_id: Request correlation ID for distributed tracing.
            max_keys: Optional upper bound on result count.

        Returns:
            List of matching object keys (not full paths).

        Raises:
            ConnectionError: If the backend is unreachable.
        """
        ...

    @abstractmethod
    def delete(
        self,
        bucket: str,
        key: str,
        correlation_id: str,
    ) -> None:
        """
        Delete the object at bucket/key.

        Must be idempotent — deleting a non-existent key must NOT raise.

        Args:
            bucket: Logical bucket name.
            key: Object key / filename within the bucket.
            correlation_id: Request correlation ID for distributed tracing.

        Raises:
            ConnectionError: If the backend is unreachable.
        """
        ...
