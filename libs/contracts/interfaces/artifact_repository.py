"""
Artifact repository interface (port).

Responsibilities:
- Define the abstract contract for artifact metadata persistence.
- Decouple service-layer code from any specific database or storage mechanism.
- Enable in-memory mock substitution in unit tests.

Does NOT:
- Execute SQL or any I/O.
- Know about binary artifact content (that belongs to ArtifactStorageBase).

Dependencies:
- libs.contracts.artifact (Pydantic models: Artifact, ArtifactQuery,
  ArtifactQueryResponse)

Error conditions:
- find_by_id: raises NotFoundError when artifact_id has no matching record.
- save: raises ValueError if the Artifact payload is structurally invalid.

Example:
    repo: ArtifactRepositoryInterface = MockArtifactRepository()
    art = repo.find_by_id("01HQZXYZ123456789ABCDEFGHJK")
    results = repo.list(ArtifactQuery(limit=20))
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from libs.contracts.artifact import Artifact, ArtifactQuery, ArtifactQueryResponse
from libs.contracts.errors import NotFoundError


class ArtifactRepositoryInterface(ABC):
    """
    Port interface for artifact metadata storage.

    Implementations:
    - MockArtifactRepository  — in-memory, for unit tests
    - SqlArtifactRepository   — SQLAlchemy-backed, for production (future M5+)
    """

    @abstractmethod
    def find_by_id(self, artifact_id: str) -> Artifact:
        """
        Return the artifact with the given ULID.

        Args:
            artifact_id: 26-character ULID of the artifact.

        Returns:
            Artifact Pydantic model if found.

        Raises:
            NotFoundError: If no artifact with artifact_id exists.

        Example:
            art = repo.find_by_id("01HQZXYZ123456789ABCDEFGHJK")
            # art.artifact_type == ArtifactType.BACKTEST_RESULT
        """
        ...

    @abstractmethod
    def list(self, query: ArtifactQuery) -> ArtifactQueryResponse:
        """
        Return a paginated list of artifacts matching the query filters.

        Args:
            query: Filter and pagination parameters.

        Returns:
            ArtifactQueryResponse containing artifacts, total_count, limit,
            and offset fields.

        Example:
            resp = repo.list(ArtifactQuery(limit=10, offset=0))
            # resp.total_count >= 0
            # len(resp.artifacts) <= 10
        """
        ...

    @abstractmethod
    def save(self, artifact: Artifact) -> Artifact:
        """
        Persist a new artifact record and return it.

        Args:
            artifact: Fully populated Artifact Pydantic model.  The caller
                      is responsible for generating the ULID id field.

        Returns:
            The saved Artifact (may include server-side defaults if any).

        Raises:
            ValueError: If the artifact payload is invalid.

        Example:
            saved = repo.save(Artifact(id="01HQ...", artifact_type=..., ...))
            # saved.id == "01HQ..."
        """
        ...
