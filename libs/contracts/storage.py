"""
Storage interface contracts for artifact management.
Defines the protocol for object storage operations.
"""

from typing import Protocol, Optional, Dict, Any, List


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
        metadata: Optional[Dict[str, Any]] = None,
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
    ) -> tuple[bytes, Dict[str, Any]]:
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
        max_keys: Optional[int] = None,
        correlation_id: str = "",
    ) -> List[str]:
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
