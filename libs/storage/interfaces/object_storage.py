"""Object storage abstraction for artifacts and binary data."""

from abc import ABC, abstractmethod
from typing import AsyncIterator, BinaryIO

from libs.contracts.storage import ObjectMetadata, StorageLocation


class ObjectStorage(ABC):
    """Abstract interface for artifact and object storage operations.
    
    Supports versioned, immutable storage with metadata and lineage tracking.
    """

    @abstractmethod
    async def put_object(
        self,
        location: StorageLocation,
        data: bytes | BinaryIO,
        metadata: ObjectMetadata,
    ) -> str:
        """Store an object with metadata.
        
        Args:
            location: Target storage location (bucket/key).
            data: Binary data or file-like object to store.
            metadata: Object metadata including content type and custom tags.
            
        Returns:
            Object version identifier or ETag.
            
        Raises:
            StorageError: If write fails or location is invalid.
        """
        ...

    @abstractmethod
    async def get_object(
        self,
        location: StorageLocation,
        version_id: str | None = None,
    ) -> tuple[bytes, ObjectMetadata]:
        """Retrieve an object and its metadata.
        
        Args:
            location: Storage location to retrieve from.
            version_id: Optional specific version to retrieve.
            
        Returns:
            Tuple of (object_data, metadata).
            
        Raises:
            ObjectNotFoundError: If object does not exist.
            StorageError: If read fails.
        """
        ...

    @abstractmethod
    async def delete_object(
        self,
        location: StorageLocation,
        version_id: str | None = None,
    ) -> None:
        """Delete an object or specific version.
        
        Args:
            location: Storage location to delete.
            version_id: Optional specific version to delete.
            
        Raises:
            ObjectNotFoundError: If object does not exist.
            StorageError: If deletion fails.
        """
        ...

    @abstractmethod
    async def list_objects(
        self,
        prefix: str,
        max_keys: int = 1000,
    ) -> AsyncIterator[ObjectMetadata]:
        """List objects matching a prefix.
        
        Args:
            prefix: Key prefix to filter objects.
            max_keys: Maximum number of results per page.
            
        Yields:
            ObjectMetadata for each matching object.
        """
        ...

    @abstractmethod
    async def object_exists(
        self,
        location: StorageLocation,
        version_id: str | None = None,
    ) -> bool:
        """Check if an object exists without retrieving it.
        
        Args:
            location: Storage location to check.
            version_id: Optional specific version to check.
            
        Returns:
            True if object exists.
        """
        ...
