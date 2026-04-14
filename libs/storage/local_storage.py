"""
Local filesystem implementation of ArtifactStorageBase.

Responsibilities:
- Provide a fully functional artifact storage backend backed by the local
  filesystem, suitable for local development and unit/integration tests.
- Implement every method of ArtifactStorageBase.
- Store object metadata as a JSON sidecar file alongside each artifact.
- Treat each bucket as a subdirectory within the configured root.

Does NOT:
- Enforce access control or authentication.
- Handle distributed concurrency (single-process, single-threaded use only).
- Perform network I/O.

Dependencies:
- libs.storage.base.ArtifactStorageBase
- Python standard library: pathlib, json, shutil, structlog

Error conditions:
- get() raises FileNotFoundError when the object does not exist.
- get() raises ConnectionError when the root directory is not accessible.
- delete() is idempotent: deleting a non-existent key is a no-op.

Example:
    storage = LocalArtifactStorage(root=Path("/tmp/fxlab-dev"))
    storage.initialize(correlation_id="corr-001")
    key = storage.put(b"hello", "fxlab-artifacts", "runs/test.bin",
                      metadata={"type": "result"}, correlation_id="corr-001")
    data = storage.get("fxlab-artifacts", "test.bin", correlation_id="corr-001")
    assert data == b"hello"
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import structlog

from libs.storage.base import ArtifactStorageBase

logger = structlog.get_logger(__name__)

_META_SUFFIX = ".meta.json"


class LocalArtifactStorage(ArtifactStorageBase):
    """
    Filesystem-backed artifact storage for local development and testing.

    Layout on disk:
        <root>/
          <bucket>/
            <key>               ← raw bytes
            <key>.meta.json     ← JSON object metadata sidecar

    Buckets are created as subdirectories during put() if they do not already
    exist.  The root is created during initialize().

    Responsibilities:
    - Store/retrieve/list/delete binary artifacts on the local filesystem.
    - Persist per-object metadata in JSON sidecar files.
    - Propagate correlation IDs in metadata sidecars for tracing.

    Does NOT:
    - Enforce quotas.
    - Handle network connectivity.
    - Support concurrent write access from multiple processes.
    """

    def __init__(self, root: Path | str) -> None:
        """
        Initialise the storage backend.

        Args:
            root: Absolute path to the root storage directory.  Subdirectories
                  for each bucket will be created beneath this path.
        """
        self._root = Path(root)
        self._initialized = False

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def initialize(self, correlation_id: str) -> None:
        """
        Create the root directory (and any missing parents).

        Idempotent: safe to call multiple times.

        Args:
            correlation_id: Request correlation ID for tracing.

        Raises:
            ConnectionError: If the root directory cannot be created (e.g.
                             permission denied).
        """
        logger.info(
            "local_storage.initialize",
            root=str(self._root),
            correlation_id=correlation_id,
        )
        try:
            self._root.mkdir(parents=True, exist_ok=True)
            self._initialized = True
            logger.info(
                "local_storage.initialize.success",
                root=str(self._root),
                correlation_id=correlation_id,
            )
        except OSError as exc:
            logger.error(
                "local_storage.initialize.failed",
                root=str(self._root),
                correlation_id=correlation_id,
                error=str(exc),
            )
            raise ConnectionError(f"Cannot create storage root {self._root}: {exc}") from exc

    def is_initialized(self) -> bool:
        """
        Return whether initialize() has been called and the root exists.

        Returns:
            True if the root directory exists and initialize() completed.
        """
        return self._initialized and self._root.exists()

    def health_check(self, correlation_id: str) -> bool:
        """
        Confirm the root directory is accessible.

        Args:
            correlation_id: Request correlation ID for tracing.

        Returns:
            True if the root directory exists and is readable.

        Raises:
            ConnectionError: If the root does not exist or is inaccessible.
        """
        logger.debug(
            "local_storage.health_check",
            root=str(self._root),
            correlation_id=correlation_id,
        )
        if not self._root.exists():
            raise ConnectionError(f"Storage root {self._root} does not exist")
        return True

    # ------------------------------------------------------------------
    # Core I/O
    # ------------------------------------------------------------------

    def put(
        self,
        data: bytes,
        bucket: str,
        key: str,
        metadata: dict[str, Any] | None = None,
        correlation_id: str | None = None,
    ) -> str:
        """
        Write bytes to <root>/<bucket>/<key> and store metadata sidecar.

        Creates the bucket subdirectory and any intermediate directories if
        they do not already exist.

        Args:
            data: Raw bytes to write.
            bucket: Logical bucket name (becomes a subdirectory under root).
            key: Object key (relative path within the bucket).
            metadata: Optional key-value pairs to persist alongside the data.
            correlation_id: Correlation ID stored in the sidecar for tracing.

        Returns:
            Canonical storage path in bucket/key format.

        Raises:
            OSError: If the file cannot be written (wrapped as Exception).
        """
        corr = correlation_id or ""
        logger.debug(
            "local_storage.put",
            bucket=bucket,
            key=key,
            size=len(data),
            correlation_id=corr,
        )

        object_path = self._object_path(bucket, key)
        object_path.parent.mkdir(parents=True, exist_ok=True)

        object_path.write_bytes(data)

        # Write metadata sidecar
        sidecar: dict[str, Any] = dict(metadata) if metadata else {}
        sidecar["_correlation_id"] = corr
        meta_path = self._meta_path(bucket, key)
        meta_path.write_text(json.dumps(sidecar, default=str), encoding="utf-8")

        storage_path = f"{bucket}/{key}"
        logger.debug(
            "local_storage.put.success",
            storage_path=storage_path,
            correlation_id=corr,
        )
        return storage_path

    def get(
        self,
        bucket: str,
        key: str,
        correlation_id: str,
    ) -> bytes:
        """
        Read and return the raw bytes for <bucket>/<key>.

        Args:
            bucket: Logical bucket name.
            key: Object key within the bucket.
            correlation_id: Correlation ID for tracing.

        Returns:
            Raw bytes of the stored object.

        Raises:
            FileNotFoundError: If the object does not exist.
        """
        logger.debug(
            "local_storage.get",
            bucket=bucket,
            key=key,
            correlation_id=correlation_id,
        )
        object_path = self._object_path(bucket, key)
        if not object_path.exists():
            logger.warning(
                "local_storage.get.not_found",
                bucket=bucket,
                key=key,
                correlation_id=correlation_id,
            )
            raise FileNotFoundError(f"Object not found: {bucket}/{key}")

        data = object_path.read_bytes()
        logger.debug(
            "local_storage.get.success",
            bucket=bucket,
            key=key,
            size=len(data),
            correlation_id=correlation_id,
        )
        return data

    def get_with_metadata(
        self,
        bucket: str,
        key: str,
        correlation_id: str,
    ) -> tuple[bytes, dict[str, Any]]:
        """
        Read raw bytes and metadata sidecar for <bucket>/<key>.

        Args:
            bucket: Logical bucket name.
            key: Object key within the bucket.
            correlation_id: Correlation ID for tracing.

        Returns:
            Tuple of (raw_bytes, metadata_dict).  metadata_dict is empty if
            no sidecar file exists.

        Raises:
            FileNotFoundError: If the object data file does not exist.
        """
        data = self.get(bucket, key, correlation_id)

        meta_path = self._meta_path(bucket, key)
        meta: dict[str, Any] = {}
        if meta_path.exists():
            try:
                meta = json.loads(meta_path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                # Sidecar is corrupt or unreadable; return empty metadata
                logger.warning(
                    "local_storage.get_with_metadata.sidecar_unreadable",
                    bucket=bucket,
                    key=key,
                    correlation_id=correlation_id,
                )

        return data, meta

    def list(
        self,
        bucket: str,
        prefix: str,
        correlation_id: str,
        max_keys: int | None = None,
    ) -> list[str]:
        """
        Return object keys in <bucket> whose key matches the given prefix.

        Sidecar files (.meta.json) are excluded from the results.

        Args:
            bucket: Logical bucket name.
            prefix: Key prefix filter.  Empty string matches all keys.
            correlation_id: Correlation ID for tracing.
            max_keys: Optional upper bound on result count.

        Returns:
            List of matching object keys relative to the bucket directory.
            Returns empty list if the bucket does not exist.
        """
        logger.debug(
            "local_storage.list",
            bucket=bucket,
            prefix=prefix,
            max_keys=max_keys,
            correlation_id=correlation_id,
        )
        bucket_dir = self._root / bucket
        if not bucket_dir.exists():
            return []

        keys: list[str] = []
        for path in sorted(bucket_dir.rglob("*")):
            if not path.is_file():
                continue
            if path.name.endswith(_META_SUFFIX):
                continue  # skip sidecar files
            # Compute key relative to bucket dir
            relative_key = str(path.relative_to(bucket_dir))
            if relative_key.startswith(prefix):
                keys.append(relative_key)
                if max_keys is not None and len(keys) >= max_keys:
                    break

        logger.debug(
            "local_storage.list.success",
            bucket=bucket,
            count=len(keys),
            correlation_id=correlation_id,
        )
        return keys

    def delete(
        self,
        bucket: str,
        key: str,
        correlation_id: str,
    ) -> None:
        """
        Delete the object at <bucket>/<key> and its metadata sidecar.

        Idempotent: calling delete on a non-existent key is a no-op.

        Args:
            bucket: Logical bucket name.
            key: Object key within the bucket.
            correlation_id: Correlation ID for tracing.
        """
        logger.debug(
            "local_storage.delete",
            bucket=bucket,
            key=key,
            correlation_id=correlation_id,
        )
        object_path = self._object_path(bucket, key)
        meta_path = self._meta_path(bucket, key)

        if object_path.exists():
            object_path.unlink()
            logger.debug(
                "local_storage.delete.success",
                bucket=bucket,
                key=key,
                correlation_id=correlation_id,
            )
        else:
            logger.debug(
                "local_storage.delete.already_gone",
                bucket=bucket,
                key=key,
                correlation_id=correlation_id,
            )

        # Clean up sidecar regardless
        if meta_path.exists():
            meta_path.unlink()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _object_path(self, bucket: str, key: str) -> Path:
        """
        Return the absolute filesystem path for the object data file.

        Args:
            bucket: Logical bucket name.
            key: Object key (may contain path separators for nested keys).

        Returns:
            Absolute Path to the data file.
        """
        return self._root / bucket / key

    def _meta_path(self, bucket: str, key: str) -> Path:
        """
        Return the absolute filesystem path for the metadata sidecar file.

        Args:
            bucket: Logical bucket name.
            key: Object key.

        Returns:
            Absolute Path to the <key>.meta.json sidecar file.
        """
        return self._root / bucket / (key + _META_SUFFIX)
