"""
Artifact storage interface contract.
Defines the abstraction for object storage operations (MinIO, S3, etc.).
"""

from abc import ABC, abstractmethod
from typing import Optional, List, Tuple, Dict, Any


class ArtifactStorage(ABC):
    """
    Abstract interface for artifact storage operations.
    
    Implementations must support:
    - Bucket initialization and health checks
    - Object put/get/delete operations
    - Metadata storage and retrieval
    - Prefix-based listing with pagination
    - Correlation ID tracking for observability
    """

    @abstractmethod
    def initialize(self, correlation_id: str) -> None:
        """
        Initialize storage backend and create required buckets.
        Must be idempotent - safe to call multiple times.
        
        Args:
            correlation_id: Correlation ID for tracing
            
        Raises:
            ConnectionError: If storage backend is unreachable
        """
        pass

    @abstractmethod
    def is_initialized(self) -> bool:
        """
        Check if storage has been initialized.
        
        Returns:
            True if initialized, False otherwise
        """
        pass

    @abstractmethod
    def health_check(self, correlation_id: str) -> bool:
        """
        Verify storage backend is accessible and healthy.
        
        Args:
            correlation_id: Correlation ID for tracing
            
        Returns:
            True if healthy
            
        Raises:
            ConnectionError: If storage is unreachable
        """
        pass

    @abstractmethod
    def put(
        self,
        data: bytes,
        bucket: str,
        key: str,
        metadata: Optional[Dict[str, Any]] = None,
        correlation_id: Optional[str] = None,
    ) -> str:
        """
        Store artifact data in object storage.
        
        Args:
            data: Binary data to store
            bucket: Target bucket name
            key: Object key/path
            metadata: Optional metadata to attach
            correlation_id: Correlation ID for tracing
            
        Returns:
            Full object key of stored artifact
            
        Raises:
            Exception: If storage quota exceeded or upload fails
        """
        pass

    @abstractmethod
    def get(
        self,
        bucket: str,
        key: str,
        correlation_id: Optional[str] = None,
    ) -> bytes:
        """
        Retrieve artifact data from object storage.
        
        Args:
            bucket: Source bucket name
            key: Object key/path
            correlation_id: Correlation ID for tracing
            
        Returns:
            Binary artifact data
            
        Raises:
            FileNotFoundError: If object does not exist
        """
        pass

    @abstractmethod
    def get_with_metadata(
        self,
        bucket: str,
        key: str,
        correlation_id: Optional[str] = None,
    ) -> Tuple[bytes, Dict[str, Any]]:
        """
        Retrieve artifact data and metadata from object storage.
        
        Args:
            bucket: Source bucket name
            key: Object key/path
            correlation_id: Correlation ID for tracing
            
        Returns:
            Tuple of (binary data, metadata dict)
            
        Raises:
            FileNotFoundError: If object does not exist
        """
        pass

    @abstractmethod
    def list(
        self,
        bucket: str,
        prefix: Optional[str] = None,
        max_keys: Optional[int] = None,
        correlation_id: Optional[str] = None,
    ) -> List[str]:
        """
        List objects in bucket matching prefix.
        
        Args:
            bucket: Source bucket name
            prefix: Optional key prefix filter
            max_keys: Maximum number of keys to return
            correlation_id: Correlation ID for tracing
            
        Returns:
            List of object keys
        """
        pass

    @abstractmethod
    def delete(
        self,
        bucket: str,
        key: str,
        correlation_id: Optional[str] = None,
    ) -> None:
        """
        Delete artifact from object storage.
        Must be idempotent - safe to call on non-existent objects.
        
        Args:
            bucket: Source bucket name
            key: Object key/path
            correlation_id: Correlation ID for tracing
        """
        pass
