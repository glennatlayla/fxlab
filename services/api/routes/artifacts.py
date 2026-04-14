"""
Artifact Registry API endpoints.

Responsibilities:
- Expose GET /artifacts for paginated artifact metadata listing.
- Expose GET /artifacts/{artifact_id}/download for streaming artifact content.
- Delegate all data access to ArtifactRepositoryInterface (injected).
- Delegate all binary retrieval to ArtifactStorageBase (injected).
- Return 404 when an artifact or its storage content cannot be located.

Does NOT:
- Contain business logic or filtering logic (delegated to repository).
- Access the database directly.
- Know which storage backend is in use (local vs. MinIO).

Dependencies:
- libs.contracts.interfaces.artifact_repository.ArtifactRepositoryInterface
- libs.storage.base.ArtifactStorageBase
- libs.contracts.artifact (Artifact, ArtifactQuery, ArtifactQueryResponse)
- libs.contracts.errors.NotFoundError

Error conditions:
- GET /artifacts/{artifact_id}/download returns 404 when:
    - artifact_id is not found in the repository.
    - The storage backend cannot locate the file at the registered path.

Example (curl):
    curl http://localhost:8000/artifacts?limit=10
    curl http://localhost:8000/artifacts/01HQAAAA.../download -O
"""

from __future__ import annotations

import os
from typing import Any

import structlog

# ---------------------------------------------------------------------------
# MIME type registry for downloadable artifact formats.
#
# The spec requires "correct Content-Type" for CSV, JSON, and Parquet files.
# application/octet-stream is the safe fallback for unknown extensions.
# ---------------------------------------------------------------------------
_EXTENSION_MEDIA_TYPES: dict[str, str] = {
    ".json": "application/json",
    ".csv": "text/csv",
    ".parquet": "application/vnd.apache.parquet",
    ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    ".txt": "text/plain",
    ".zip": "application/zip",
}

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import JSONResponse, Response
from sqlalchemy.orm import Session

from libs.contracts.artifact import ArtifactQuery, ArtifactQueryResponse, ArtifactType
from libs.contracts.errors import NotFoundError
from libs.contracts.interfaces.artifact_repository import ArtifactRepositoryInterface
from libs.storage.base import ArtifactStorageBase
from services.api.auth import AuthenticatedUser, require_scope
from services.api.db import get_db

logger = structlog.get_logger(__name__)

router = APIRouter(tags=["artifacts"])


# ---------------------------------------------------------------------------
# Dependency providers
#
# These functions are the injection points for tests (via
# app.dependency_overrides) and for production wiring (via lifespan or DI
# container).  Never instantiate the concrete classes inside route handlers.
# ---------------------------------------------------------------------------


def get_artifact_repository(db: Session = Depends(get_db)) -> ArtifactRepositoryInterface:
    """
    Provide the active ArtifactRepositoryInterface implementation.

    Always returns the DB-backed repository bound to the current request's session.

    Args:
        db: SQLAlchemy session injected by FastAPI dependency injection.

    Returns:
        ArtifactRepositoryInterface implementation (SQL-backed).
    """
    from services.api.repositories.sql_artifact_repository import SqlArtifactRepository

    return SqlArtifactRepository(db=db)


def get_artifact_storage() -> ArtifactStorageBase:
    """
    Provide the active ArtifactStorageBase implementation.

    Reads ARTIFACT_STORAGE_BACKEND from the environment to select the backend:

    - ``"local"`` (default): Uses LocalArtifactStorage with ARTIFACT_STORAGE_ROOT
      (defaults to ``/var/lib/fxlab/artifacts`` in production).
    - ``"minio"``: Uses MinIOArtifactStorage for S3-compatible object storage.
      Requires MINIO_ENDPOINT, MINIO_ACCESS_KEY, MINIO_SECRET_KEY environment
      variables.  Optional MINIO_SECURE (default ``"false"``).

    In tests: overridden via ``app.dependency_overrides[get_artifact_storage]``.

    Returns:
        ArtifactStorageBase implementation.

    Raises:
        ConfigError: If the selected backend requires environment variables
            that are not set (e.g. missing MINIO_ENDPOINT for minio backend).
        ValueError: If the backend string is not a supported value.

    Example:
        # Environment: ARTIFACT_STORAGE_BACKEND=minio MINIO_ENDPOINT=minio:9000 ...
        storage = get_artifact_storage()
        # → MinIOArtifactStorage(endpoint="minio:9000", ...)
    """
    import os

    from libs.contracts.errors import ConfigError

    backend = os.environ.get("ARTIFACT_STORAGE_BACKEND", "local")

    if backend == "local":
        from libs.storage.local_storage import LocalArtifactStorage

        root = os.environ.get("ARTIFACT_STORAGE_ROOT", "/var/lib/fxlab/artifacts")
        return LocalArtifactStorage(root=root)

    if backend == "minio":
        from libs.storage.minio_storage import MinIOArtifactStorage

        # All three connection parameters are mandatory — fail fast with a
        # clear message instead of letting the MinIO SDK surface a cryptic
        # connection error at first use.
        required_vars = ["MINIO_ENDPOINT", "MINIO_ACCESS_KEY", "MINIO_SECRET_KEY"]
        missing = [v for v in required_vars if not os.environ.get(v)]
        if missing:
            raise ConfigError(
                f"MinIO backend requires environment variables: {', '.join(missing)}. "
                "Set them in .env or your deployment manifest."
            )

        secure_raw = os.environ.get("MINIO_SECURE", "false").lower()
        secure = secure_raw in ("true", "1", "yes")

        return MinIOArtifactStorage(
            endpoint=os.environ["MINIO_ENDPOINT"],
            access_key=os.environ["MINIO_ACCESS_KEY"],
            secret_key=os.environ["MINIO_SECRET_KEY"],
            secure=secure,
        )

    raise ValueError(
        f"Unsupported ARTIFACT_STORAGE_BACKEND: '{backend}'. Supported: 'local', 'minio'."
    )


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.get(
    "/artifacts",
    summary="List artifact metadata",
    description=(
        "Return a paginated list of artifact metadata records. "
        "Supports optional filtering by artifact_type and subject_id."
    ),
)
def list_artifacts(
    artifact_type: str | None = Query(
        default=None,
        description="Filter by artifact type (e.g. backtest_result, readiness_report).",
    ),
    subject_id: str | None = Query(
        default=None,
        description="Filter by the ULID of the subject entity (run, candidate, etc.).",
    ),
    limit: int = Query(
        default=100,
        ge=1,
        le=1000,
        description="Maximum number of artifacts to return.",
    ),
    offset: int = Query(
        default=0,
        ge=0,
        description="Pagination offset.",
    ),
    repo: ArtifactRepositoryInterface = Depends(get_artifact_repository),
    correlation_id: str | None = Query(default=None, include_in_schema=False),
    user: AuthenticatedUser = Depends(require_scope("exports:read")),
) -> JSONResponse:
    """
    Return paginated artifact metadata.

    Args:
        artifact_type: Optional type filter string.
        subject_id: Optional subject ULID filter.
        limit: Max results per page (1–1000).
        offset: Pagination offset.
        repo: Injected artifact repository.
        correlation_id: Optional correlation ID for tracing (not in schema).

    Returns:
        JSONResponse containing ArtifactQueryResponse fields: artifacts list
        and pagination metadata.

    Raises:
        HTTPException(422): If limit/offset are out of range.

    Note (LL-007): FastAPI's response_model serialization uses pydantic-core
    under the hood.  In cross-architecture sandboxes the native pydantic-core
    binary may not load, causing the response to serialize as an empty dict.
    We bypass this by calling model_dump() explicitly and returning JSONResponse.
    """
    corr = correlation_id or "no-corr"
    logger.info(
        "artifacts.list.request",
        artifact_type=artifact_type,
        subject_id=subject_id,
        limit=limit,
        offset=offset,
        correlation_id=corr,
        component="artifacts",
    )

    # Resolve artifact_type string to enum (if provided)
    artifact_types = None
    if artifact_type is not None:
        try:
            artifact_types = [ArtifactType(artifact_type)]
        except ValueError:
            logger.warning(
                "artifacts.list.invalid_type",
                artifact_type=artifact_type,
                correlation_id=corr,
                component="artifacts",
            )
            raise HTTPException(
                status_code=422,
                detail=f"Invalid artifact_type: {artifact_type!r}",
            )

    # Build query — use model_construct to avoid pydantic-core stub issues
    # when Optional[str] fields are explicitly set (LL-007).
    # Coerce limit/offset to int explicitly: FastAPI normally does this, but
    # the pydantic-core stub may leave them as strings in some environments.
    query = ArtifactQuery.model_construct(
        artifact_types=artifact_types,
        subject_id=subject_id,
        created_by=None,
        start_time=None,
        end_time=None,
        limit=int(limit),
        offset=int(offset),
    )

    result = repo.list(query)

    logger.info(
        "artifacts.list.response",
        total_count=result.total_count,
        returned=len(result.artifacts),
        correlation_id=corr,
        component="artifacts",
    )

    # Use model_dump() + JSONResponse to bypass pydantic-core stub serialization
    # issues in cross-architecture sandboxes (LL-007).
    return JSONResponse(content=_serialize_query_response(result))


# ---------------------------------------------------------------------------
# Private serialisation helpers
# ---------------------------------------------------------------------------


def _serialize_artifact(artifact: Any) -> dict[str, Any]:
    """
    Serialise a single Artifact Pydantic model to a JSON-safe dict.

    Uses model_dump() explicitly rather than relying on FastAPI's response_model
    serialisation, which fails when pydantic-core native binary is unavailable
    (LL-007).

    Args:
        artifact: Artifact Pydantic model instance.

    Returns:
        Dict with ISO-8601 datetime strings and enum values as strings.
    """
    raw = artifact.model_dump()
    # Convert datetime objects to ISO strings for JSON serialisation
    if "created_at" in raw and hasattr(raw["created_at"], "isoformat"):
        raw["created_at"] = raw["created_at"].isoformat()
    # Convert enum values to their string value
    if "artifact_type" in raw and hasattr(raw["artifact_type"], "value"):
        raw["artifact_type"] = raw["artifact_type"].value
    return raw


def _serialize_query_response(response: ArtifactQueryResponse) -> dict[str, Any]:
    """
    Serialise an ArtifactQueryResponse to a JSON-safe dict.

    Args:
        response: ArtifactQueryResponse Pydantic model.

    Returns:
        Dict suitable for JSONResponse content.
    """
    return {
        "artifacts": [_serialize_artifact(a) for a in response.artifacts],
        "total_count": response.total_count,
        "limit": response.limit,
        "offset": response.offset,
    }


@router.get(
    "/artifacts/{artifact_id}/download",
    summary="Download artifact content",
    description=(
        "Stream the binary content of an artifact identified by its ULID. "
        "Sets Content-Disposition: attachment with the original filename."
    ),
    responses={
        200: {"content": {"application/octet-stream": {}}},
        404: {"description": "Artifact not found or storage content missing"},
    },
)
def download_artifact(
    artifact_id: str,
    repo: ArtifactRepositoryInterface = Depends(get_artifact_repository),
    storage: ArtifactStorageBase = Depends(get_artifact_storage),
    correlation_id: str | None = Query(default=None, include_in_schema=False),
    user: AuthenticatedUser = Depends(require_scope("exports:read")),
) -> Response:
    """
    Stream artifact binary content.

    Resolves the artifact's storage_path from the repository, splits it into
    bucket and key, retrieves the bytes from the storage backend, and returns
    them as an application/octet-stream response with Content-Disposition set.

    Args:
        artifact_id: 26-character ULID of the artifact.
        repo: Injected artifact repository.
        storage: Injected storage backend.
        correlation_id: Optional correlation ID for tracing.

    Returns:
        Response with binary content, correct Content-Type for the file
        extension, and Content-Disposition header set to attachment.

    Raises:
        HTTPException(404): If the artifact_id is not in the registry or
                            the storage backend cannot find the file.
        HTTPException(500): If the registered storage_path is malformed
                            (missing the required bucket/key separator).

    Example:
        # storage_path "fxlab-artifacts/runs/result.json"
        # → bucket="fxlab-artifacts", key="runs/result.json"
        # → Content-Type: application/json
        # → Content-Disposition: attachment; filename="result.json"
    """
    corr = correlation_id or "no-corr"
    logger.info(
        "artifacts.download.request",
        artifact_id=artifact_id,
        correlation_id=corr,
        component="artifacts",
    )

    # 1. Resolve artifact metadata from registry
    try:
        artifact = repo.find_by_id(artifact_id)
    except NotFoundError:
        logger.warning(
            "artifacts.download.not_found",
            artifact_id=artifact_id,
            correlation_id=corr,
            component="artifacts",
        )
        raise HTTPException(
            status_code=404,
            detail=f"Artifact {artifact_id!r} not found",
        )

    # 2. Parse storage_path into bucket + key
    #    Expected format: "<bucket>/<key>" where key may contain slashes.
    storage_path = artifact.storage_path
    if "/" not in storage_path:
        logger.error(
            "artifacts.download.malformed_storage_path",
            artifact_id=artifact_id,
            storage_path=storage_path,
            correlation_id=corr,
            component="artifacts",
        )
        raise HTTPException(
            status_code=500,
            detail=f"Artifact {artifact_id!r} has a malformed storage_path",
        )

    bucket, key = storage_path.split("/", 1)

    # 3. Retrieve binary content from storage backend
    try:
        data = storage.get(
            bucket=bucket,
            key=key,
            correlation_id=corr,
        )
    except FileNotFoundError:
        logger.error(
            "artifacts.download.storage_not_found",
            artifact_id=artifact_id,
            storage_path=storage_path,
            correlation_id=corr,
            component="artifacts",
        )
        raise HTTPException(
            status_code=404,
            detail=f"Artifact content not found at storage path {storage_path!r}",
        )

    # 4. Derive filename and Content-Type from the key's last path component.
    #    Fall back to artifact_id if the key has no basename (edge case).
    filename = os.path.basename(key) or artifact_id
    _, ext = os.path.splitext(filename)
    media_type = _EXTENSION_MEDIA_TYPES.get(ext.lower(), "application/octet-stream")

    logger.info(
        "artifacts.download.response",
        artifact_id=artifact_id,
        size=len(data),
        filename=filename,
        media_type=media_type,
        correlation_id=corr,
        component="artifacts",
    )

    return Response(
        content=data,
        media_type=media_type,
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
        },
    )
