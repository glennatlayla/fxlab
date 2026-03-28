"""
SQL-backed artifact repository implementation (ISS-011).

Responsibilities:
- Persist and retrieve artifact metadata from the database.
- Implement ArtifactRepositoryInterface using SQLAlchemy ORM.
- Support paginated listing with limit/offset.

Does NOT:
- Handle binary artifact content (that is ArtifactStorageBase's responsibility).
- Perform business logic or filtering beyond query parameters.

Dependencies:
- sqlalchemy.orm.Session: Database session (injected via __init__).
- libs.contracts.models.Artifact: ORM model for artifacts table.
- libs.contracts.artifact: Pydantic contract models.
- libs.contracts.errors.NotFoundError: Raised when record not found.
- structlog: Structured logging.

Error conditions:
- find_by_id: raises NotFoundError when artifact_id has no matching record.
- save: raises ValueError if the Artifact payload is invalid.

Example:
    from services.api.db import SessionLocal
    from services.api.repositories.sql_artifact_repository import SqlArtifactRepository

    db = SessionLocal()
    repo = SqlArtifactRepository(db=db)
    art = repo.find_by_id("01HQZXYZ123456789ABCDEFGHJK")
"""

from __future__ import annotations

from typing import Any

import structlog
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from libs.contracts.artifact import Artifact, ArtifactQuery, ArtifactQueryResponse
from libs.contracts.errors import NotFoundError
from libs.contracts.interfaces.artifact_repository import ArtifactRepositoryInterface
from libs.contracts.models import Artifact as ArtifactModel

logger = structlog.get_logger(__name__)


class SqlArtifactRepository(ArtifactRepositoryInterface):
    """
    SQL-backed implementation of ArtifactRepositoryInterface.

    Responsibilities:
    - Query the artifacts table using SQLAlchemy ORM.
    - Convert ORM models to Pydantic contracts for return values.
    - Raise NotFoundError when artifacts are not found.
    - Support paginated listing via limit/offset.

    Does NOT:
    - Validate Artifact data beyond schema (validation happens in caller).
    - Know about binary artifact storage.
    - Perform business logic or orchestration.

    Dependencies:
    - SQLAlchemy Session (injected): Database connection.

    Error conditions:
    - find_by_id: raises NotFoundError if artifact_id not in database.

    Example:
        repo = SqlArtifactRepository(db=session)
        artifact = repo.find_by_id("01HQZXYZ123456789ABCDEFGHJK")
    """

    def __init__(self, db: Session) -> None:
        """
        Initialize the SQL artifact repository.

        Args:
            db: SQLAlchemy Session instance (injected by FastAPI Depends).

        Example:
            repo = SqlArtifactRepository(db=get_db())
        """
        self.db = db

    def find_by_id(self, artifact_id: str) -> Artifact:
        """
        Retrieve an artifact by its ULID.

        Args:
            artifact_id: 26-character ULID of the artifact.

        Returns:
            Artifact Pydantic model if found.

        Raises:
            NotFoundError: If no artifact with artifact_id exists.

        Example:
            art = repo.find_by_id("01HQZXYZ123456789ABCDEFGHJK")
            assert art.artifact_type is not None
        """
        stmt = select(ArtifactModel).where(ArtifactModel.id == artifact_id)
        orm_artifact = self.db.execute(stmt).scalar_one_or_none()

        if orm_artifact is None:
            logger.warning(
                "artifact.not_found",
                artifact_id=artifact_id,
            )
            raise NotFoundError(f"Artifact {artifact_id!r} not found")

        logger.debug(
            "artifact.found",
            artifact_id=artifact_id,
        )
        return self._orm_to_contract(orm_artifact)

    def list(self, query: ArtifactQuery) -> ArtifactQueryResponse:
        """
        Return a paginated list of artifacts matching the query.

        Args:
            query: ArtifactQuery with limit, offset, and optional filters.

        Returns:
            ArtifactQueryResponse with artifacts, total_count, limit, offset.

        Example:
            resp = repo.list(ArtifactQuery(limit=10, offset=0))
            assert len(resp.artifacts) <= 10
            assert resp.total_count >= 0
        """
        # Build base query
        stmt = select(ArtifactModel)

        # Count total (without limit/offset)
        count_stmt = select(func.count(ArtifactModel.id))
        total_count = self.db.execute(count_stmt).scalar() or 0

        # Apply limit and offset
        stmt = stmt.limit(query.limit).offset(query.offset)

        # Execute and convert
        orm_artifacts = self.db.execute(stmt).scalars().all()
        artifacts = [self._orm_to_contract(art) for art in orm_artifacts]

        logger.debug(
            "artifact.list",
            total_count=total_count,
            returned_count=len(artifacts),
            limit=query.limit,
            offset=query.offset,
        )

        return ArtifactQueryResponse(
            artifacts=artifacts,
            total_count=total_count,
            limit=query.limit,
            offset=query.offset,
        )

    def save(self, artifact: Artifact) -> Artifact:
        """
        Persist an artifact record to the database.

        Args:
            artifact: Fully populated Artifact Pydantic model with id field.

        Returns:
            The saved Artifact (same as input).

        Raises:
            ValueError: If the artifact payload is invalid or violates constraints.

        Example:
            saved = repo.save(Artifact(
                id="01HQ...",
                artifact_type="backtest_result",
                uri="s3://bucket/path",
            ))
            assert saved.id == "01HQ..."
        """
        # Convert contract to ORM
        orm_artifact = ArtifactModel(
            id=artifact.id,
            run_id=artifact.run_id,
            artifact_type=artifact.artifact_type,
            uri=artifact.uri,
            size_bytes=artifact.size_bytes,
            checksum=artifact.checksum,
        )

        try:
            self.db.add(orm_artifact)
            self.db.commit()
            self.db.refresh(orm_artifact)
            logger.info(
                "artifact.saved",
                artifact_id=artifact.id,
            )
        except Exception as exc:
            self.db.rollback()
            logger.error(
                "artifact.save_failed",
                artifact_id=artifact.id,
                error=str(exc),
            )
            raise ValueError(f"Failed to save artifact: {exc}") from exc

        return self._orm_to_contract(orm_artifact)

    # -----------------------------------------------------------------------
    # Private helpers
    # -----------------------------------------------------------------------

    @staticmethod
    def _orm_to_contract(orm_artifact: Any) -> Artifact:
        """
        Convert an ORM Artifact model to a Pydantic Artifact contract.

        Args:
            orm_artifact: SQLAlchemy ORM Artifact instance.

        Returns:
            Artifact Pydantic model.
        """
        return Artifact(
            id=orm_artifact.id,
            run_id=orm_artifact.run_id,
            artifact_type=orm_artifact.artifact_type,
            uri=orm_artifact.uri,
            size_bytes=orm_artifact.size_bytes,
            checksum=orm_artifact.checksum,
            created_at=orm_artifact.created_at,
            updated_at=orm_artifact.updated_at,
        )
