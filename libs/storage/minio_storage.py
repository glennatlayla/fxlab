"""
MinIO implementation of artifact storage.

Responsibilities:
- Provide a MinIO/S3-compatible implementation of ArtifactStorageBase.
- Translate ArtifactStorageBase's put/get/list/delete operations into MinIO SDK calls.
- Raise FileNotFoundError (not S3Error) for missing objects, so callers remain
  backend-agnostic.
- Raise ConnectionError if the MinIO server is unreachable.

Does NOT:
- Contain business logic.
- Know about artifact metadata schemas or Pydantic models.
- Manage retries (that belongs in the service layer).

Dependencies:
- minio: MinIO Python SDK.
- structlog: structured logging with correlation_id propagation.
- libs.storage.base.ArtifactStorageBase: canonical ABC.

Error conditions:
- get() / get_with_metadata(): raise FileNotFoundError for S3Error("NoSuchKey").
- health_check(): raise ConnectionError if MinIO is unreachable.
- delete(): idempotent — NoSuchKey is silently ignored.

Example:
    storage = MinIOArtifactStorage(
        endpoint="localhost:9000",
        access_key="minioadmin",
        secret_key="minioadmin",
    )
    storage.initialize(correlation_id="corr-123")
    storage.put(b"data", "fxlab-artifacts", "runs/result.json", correlation_id="corr-123")
"""

from __future__ import annotations

import io
from typing import Any

import structlog
from minio import Minio
from minio.error import S3Error

from libs.storage.base import ArtifactStorageBase

logger = structlog.get_logger(__name__)


class MinIOArtifactStorage(ArtifactStorageBase):
    """
    MinIO-backed implementation of ArtifactStorageBase.

    Responsibilities:
    - Wrap MinIO SDK calls behind the ArtifactStorageBase interface.
    - Normalise MinIO S3Errors into FileNotFoundError / ConnectionError.
    - Propagate correlation_id into MinIO object metadata for traceability.

    Does NOT:
    - Contain business logic.
    - Know about Pydantic models or artifact registry schemas.

    Dependencies:
    - Minio (injected via constructor endpoint/credentials).
    - structlog (logger).

    Raises:
    - FileNotFoundError: When a requested object does not exist.
    - ConnectionError: When MinIO is unreachable (health_check / initialize).
    - Exception: On unrecoverable write errors (quota, permission, etc.).

    Example:
        storage = MinIOArtifactStorage("localhost:9000", "key", "secret")
        storage.initialize(correlation_id="corr-1")
        storage.put(b"hello", "fxlab-artifacts", "test.bin", correlation_id="corr-1")
    """

    def __init__(
        self,
        endpoint: str,
        access_key: str,
        secret_key: str,
        secure: bool = False,
    ):
        """
        Initialize MinIO client.

        Args:
            endpoint: MinIO server endpoint (host:port)
            access_key: MinIO access key
            secret_key: MinIO secret key
            secure: Whether to use HTTPS
        """
        self.client = Minio(
            endpoint=endpoint,
            access_key=access_key,
            secret_key=secret_key,
            secure=secure,
        )
        self._initialized = False
        self._required_buckets = ["fxlab-artifacts"]

    def initialize(self, correlation_id: str) -> None:
        """
        Initialize storage backend and create required buckets.
        Idempotent - safe to call multiple times.

        Args:
            correlation_id: Request correlation ID for tracing
        """
        logger.info(
            "artifact_storage.initialize",
            correlation_id=correlation_id,
            buckets=self._required_buckets,
        )

        for bucket in self._required_buckets:
            try:
                if not self.client.bucket_exists(bucket):
                    self.client.make_bucket(bucket)
                    logger.info(
                        "artifact_storage.bucket_created",
                        correlation_id=correlation_id,
                        bucket=bucket,
                    )
            except S3Error as e:
                logger.error(
                    "artifact_storage.bucket_creation_failed",
                    correlation_id=correlation_id,
                    bucket=bucket,
                    error=str(e),
                )
                raise

        self._initialized = True
        logger.info(
            "artifact_storage.initialized",
            correlation_id=correlation_id,
        )

    def is_initialized(self) -> bool:
        """
        Check if storage backend is initialized.

        Returns:
            True if initialized, False otherwise
        """
        return self._initialized

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
        logger.info(
            "artifact_storage.health_check",
            correlation_id=correlation_id,
        )

        try:
            # Try to list buckets as health check
            list(self.client.list_buckets())
            logger.info(
                "artifact_storage.health_check_passed",
                correlation_id=correlation_id,
            )
            return True
        except Exception as e:
            logger.error(
                "artifact_storage.health_check_failed",
                correlation_id=correlation_id,
                error=str(e),
            )
            raise ConnectionError(f"Storage unreachable: {e}")

    def put(
        self,
        data: bytes,
        bucket: str,
        key: str,
        metadata: dict[str, Any] | None = None,
        correlation_id: str | None = None,
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
        logger.info(
            "artifact_storage.put",
            correlation_id=correlation_id,
            bucket=bucket,
            key=key,
            size=len(data),
        )

        try:
            # Prepare metadata — correlation_id stored for end-to-end traceability
            corr = correlation_id or ""
            meta = metadata.copy() if metadata else {}
            if corr:
                meta["correlation_id"] = corr

            # MinIO requires all metadata values to be strings
            str_metadata = {k: str(v) for k, v in meta.items()}

            data_stream = io.BytesIO(data)
            self.client.put_object(
                bucket_name=bucket,
                object_name=key,
                data=data_stream,
                length=len(data),
                metadata=str_metadata,  # type: ignore[arg-type]
            )

            object_key = f"artifacts/{key}" if not key.startswith("artifacts/") else key

            logger.info(
                "artifact_storage.put_success",
                correlation_id=correlation_id,
                bucket=bucket,
                key=object_key,
            )

            return object_key

        except S3Error as e:
            if "quota" in str(e).lower() or "storage" in str(e).lower():
                logger.error(
                    "artifact_storage.quota_exceeded",
                    correlation_id=correlation_id,
                    error=str(e),
                )
                raise Exception("Storage quota exceeded")
            logger.error(
                "artifact_storage.put_failed",
                correlation_id=correlation_id,
                error=str(e),
            )
            raise

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
        logger.info(
            "artifact_storage.get",
            correlation_id=correlation_id,
            bucket=bucket,
            key=key,
        )

        try:
            response = self.client.get_object(bucket, key)
            data = response.read()
            response.close()
            response.release_conn()

            logger.info(
                "artifact_storage.get_success",
                correlation_id=correlation_id,
                bucket=bucket,
                key=key,
                size=len(data),
            )

            return data

        except S3Error as e:
            if e.code == "NoSuchKey":
                logger.error(
                    "artifact_storage.not_found",
                    correlation_id=correlation_id,
                    bucket=bucket,
                    key=key,
                )
                raise FileNotFoundError(f"Object not found: {bucket}/{key}")
            logger.error(
                "artifact_storage.get_failed",
                correlation_id=correlation_id,
                error=str(e),
            )
            raise

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
        logger.info(
            "artifact_storage.get_with_metadata",
            correlation_id=correlation_id,
            bucket=bucket,
            key=key,
        )

        try:
            # Get object with stat
            response = self.client.get_object(bucket, key)
            data = response.read()
            response.close()
            response.release_conn()

            # Get metadata via stat_object
            stat = self.client.stat_object(bucket, key)
            metadata = dict(stat.metadata) if stat.metadata else {}

            logger.info(
                "artifact_storage.get_with_metadata_success",
                correlation_id=correlation_id,
                bucket=bucket,
                key=key,
                size=len(data),
            )

            return data, metadata  # type: ignore[return-value]

        except S3Error as e:
            if e.code == "NoSuchKey":
                logger.error(
                    "artifact_storage.not_found",
                    correlation_id=correlation_id,
                    bucket=bucket,
                    key=key,
                )
                raise FileNotFoundError(f"Object not found: {bucket}/{key}")
            logger.error(
                "artifact_storage.get_with_metadata_failed",
                correlation_id=correlation_id,
                error=str(e),
            )
            raise

    def list(
        self,
        bucket: str,
        prefix: str,
        correlation_id: str,
        max_keys: int | None = None,
    ) -> list[str]:
        """
        List object keys in bucket with optional prefix filter.

        Args:
            bucket: Target bucket name.
            prefix: Key prefix filter (empty string = list all keys).
            correlation_id: Request correlation ID for tracing.
            max_keys: Optional upper bound on result count.

        Returns:
            List of matching object keys.

        Raises:
            ConnectionError: If MinIO is unreachable.
        """
        logger.info(
            "artifact_storage.list",
            correlation_id=correlation_id,
            bucket=bucket,
            prefix=prefix,
            max_keys=max_keys,
        )

        try:
            objects = self.client.list_objects(
                bucket,
                prefix=prefix,
                recursive=True,
            )

            keys = []
            for obj in objects:
                keys.append(obj.object_name)
                if max_keys and len(keys) >= max_keys:
                    break

            logger.info(
                "artifact_storage.list_success",
                correlation_id=correlation_id,
                bucket=bucket,
                count=len(keys),
            )

            return keys

        except S3Error as e:
            logger.error(
                "artifact_storage.list_failed",
                correlation_id=correlation_id,
                error=str(e),
            )
            raise

    def delete(
        self,
        bucket: str,
        key: str,
        correlation_id: str,
    ) -> None:
        """
        Delete artifact from object storage.
        Idempotent - no error if object doesn't exist.

        Args:
            bucket: Target bucket name
            key: Object key/path
            correlation_id: Request correlation ID for tracing
        """
        logger.info(
            "artifact_storage.delete",
            correlation_id=correlation_id,
            bucket=bucket,
            key=key,
        )

        try:
            self.client.remove_object(bucket, key)
            logger.info(
                "artifact_storage.delete_success",
                correlation_id=correlation_id,
                bucket=bucket,
                key=key,
            )

        except S3Error as e:
            # NoSuchKey is ok - idempotent delete
            if e.code == "NoSuchKey":
                logger.info(
                    "artifact_storage.delete_already_gone",
                    correlation_id=correlation_id,
                    bucket=bucket,
                    key=key,
                )
                return

            logger.error(
                "artifact_storage.delete_failed",
                correlation_id=correlation_id,
                error=str(e),
            )
            raise
