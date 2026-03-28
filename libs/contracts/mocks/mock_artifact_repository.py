"""
In-memory mock implementation of ArtifactRepositoryInterface.

Responsibilities:
- Provide a fully functional in-memory artifact repository for unit tests.
- Honour the same interface contract as the production SqlArtifactRepository.
- Expose introspection helpers (all(), count(), clear()) so tests can verify
  side-effects without depending on return values alone.

Does NOT:
- Perform any I/O.
- Validate business rules (that belongs in the service layer).

Dependencies:
- libs.contracts.interfaces.artifact_repository.ArtifactRepositoryInterface
- libs.contracts.artifact (Artifact, ArtifactQuery, ArtifactQueryResponse)
- libs.contracts.errors.NotFoundError

Example:
    repo = MockArtifactRepository()
    art = Artifact(id="01HQAAAAAAAAAAAAAAAAAAAAAA", ...)
    repo.save(art)
    found = repo.find_by_id("01HQAAAAAAAAAAAAAAAAAAAAAA")
    assert found == art
    assert repo.count() == 1
"""

from __future__ import annotations

from libs.contracts.artifact import Artifact, ArtifactQuery, ArtifactQueryResponse
from libs.contracts.errors import NotFoundError
from libs.contracts.interfaces.artifact_repository import ArtifactRepositoryInterface


class MockArtifactRepository(ArtifactRepositoryInterface):
    """
    In-memory artifact repository for unit testing.

    Stores artifacts in a plain dict keyed by ULID id.  All filtering in
    list() is applied in Python rather than SQL.

    Introspection helpers:
    - all()   — return every saved artifact
    - count() — return number of saved artifacts
    - clear() — wipe the store (useful in teardown or between sub-tests)
    """

    def __init__(self) -> None:
        """Initialise with an empty in-memory store."""
        self._store: dict[str, Artifact] = {}

    # ------------------------------------------------------------------
    # ArtifactRepositoryInterface implementation
    # ------------------------------------------------------------------

    def find_by_id(self, artifact_id: str) -> Artifact:
        """
        Return the artifact with the given ULID.

        Args:
            artifact_id: 26-character ULID string.

        Returns:
            Artifact if found.

        Raises:
            NotFoundError: If no artifact with artifact_id is in the store.

        Example:
            art = repo.find_by_id("01HQAAAAAAAAAAAAAAAAAAAAAA")
        """
        if artifact_id not in self._store:
            raise NotFoundError(f"Artifact {artifact_id!r} not found")
        return self._store[artifact_id]

    def list(self, query: ArtifactQuery) -> ArtifactQueryResponse:
        """
        Return a paginated, filtered list of stored artifacts.

        Applies all non-None filters from ArtifactQuery in memory.  This
        mirrors the behaviour expected from a SQL implementation so tests
        remain valid when the real repo is substituted.

        Args:
            query: Filter and pagination parameters.

        Returns:
            ArtifactQueryResponse with matching artifacts and metadata.

        Example:
            resp = repo.list(ArtifactQuery(limit=5))
            assert resp.total_count == len(repo.all())
        """
        artifacts = list(self._store.values())

        # Apply filters
        if query.artifact_types is not None:
            artifacts = [a for a in artifacts if a.artifact_type in query.artifact_types]
        if query.subject_id is not None:
            artifacts = [a for a in artifacts if a.subject_id == query.subject_id]
        if query.created_by is not None:
            artifacts = [a for a in artifacts if a.created_by == query.created_by]
        if query.start_time is not None:
            artifacts = [a for a in artifacts if a.created_at >= query.start_time]
        if query.end_time is not None:
            artifacts = [a for a in artifacts if a.created_at <= query.end_time]

        total_count = len(artifacts)
        page = artifacts[query.offset : query.offset + query.limit]

        return ArtifactQueryResponse(
            artifacts=page,
            total_count=total_count,
            limit=query.limit,
            offset=query.offset,
        )

    def save(self, artifact: Artifact) -> Artifact:
        """
        Persist artifact to the in-memory store.

        Args:
            artifact: Fully populated Artifact model with a valid ULID id.

        Returns:
            The same artifact (pass-through, matches SQL behaviour).

        Raises:
            ValueError: If artifact.id is empty or None.

        Example:
            saved = repo.save(Artifact(id="01HQAAAAAAAAAAAAAAAAAAAAAA", ...))
            assert repo.count() == 1
        """
        if not artifact.id:
            raise ValueError("Artifact.id must be a non-empty ULID string")
        self._store[artifact.id] = artifact
        return artifact

    # ------------------------------------------------------------------
    # Introspection helpers (test-only, not part of the interface)
    # ------------------------------------------------------------------

    def all(self) -> list[Artifact]:
        """
        Return all artifacts in the store.

        Returns:
            List of every saved Artifact, in insertion order (Python 3.7+).
        """
        return list(self._store.values())

    def count(self) -> int:
        """
        Return the number of artifacts in the store.

        Returns:
            Integer count >= 0.
        """
        return len(self._store)

    def clear(self) -> None:
        """
        Remove all artifacts from the store.

        Use in test teardown or when a test needs a fresh state mid-run.
        """
        self._store.clear()
