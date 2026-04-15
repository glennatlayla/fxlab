"""
Interface for draft autosave repository operations.

Defines the contract for all draft autosave repository implementations,
including creation, retrieval, deletion, and cleanup operations.

Responsibilities:
- Define the abstract interface that all implementations must follow.
- Document expected behaviour, error conditions, and examples.

Does NOT:
- Implement actual I/O operations (each concrete implementation does).
- Contain business logic.

Example:
    from libs.contracts.interfaces.draft_autosave_repository import (
        DraftAutosaveRepositoryInterface,
    )

    class MyRepository(DraftAutosaveRepositoryInterface):
        def purge_expired(self, max_age_days: int = 30) -> int:
            # Implementation here...
            pass
"""

from abc import ABC, abstractmethod
from typing import Any


class DraftAutosaveRepositoryInterface(ABC):
    """
    Abstract interface for draft autosave repository operations.

    Responsibilities:
    - Persist autosave records (create).
    - Retrieve the latest autosave for a user (get_latest).
    - Delete individual autosave records (delete).
    - Purge autosaves older than a specified age (purge_expired).

    Does NOT:
    - Validate draft content.
    - Contain business logic or orchestration.

    Raises:
    - Various implementation-specific errors (see method docstrings).

    Example:
        repo: DraftAutosaveRepositoryInterface = get_repository()
        record = repo.create(user_id="01H...", draft_payload={...})
        latest = repo.get_latest(user_id="01H...")
        deleted_count = repo.purge_expired(max_age_days=30)
    """

    @abstractmethod
    def create(
        self,
        *,
        user_id: str,
        draft_payload: dict[str, Any],
        form_step: str | None = None,
        session_id: str | None = None,
        client_ts: str | None = None,
        strategy_id: str | None = None,
    ) -> dict[str, Any]:
        """
        Persist a new draft autosave record.

        Args:
            user_id: ULID of the user owning this draft.
            draft_payload: JSON blob of the partial strategy form state.
            form_step: Current form step identifier (e.g. 'parameters').
            session_id: Browser session identifier for recovery correlation.
            client_ts: ISO-8601 client-side timestamp of the autosave event.
            strategy_id: Optional FK to an existing Strategy being edited.

        Returns:
            Dict with autosave_id and saved_at (ISO-8601 string).

        Example:
            record = repo.create(
                user_id="01H...",
                draft_payload={"name": "S1"},
                form_step="parameters",
            )
            # record == {"autosave_id": "01H...", "saved_at": "2026-03-28T..."}
        """

    @abstractmethod
    def get_latest(self, user_id: str) -> dict[str, Any] | None:
        """
        Retrieve the most recent draft autosave for a user.

        Args:
            user_id: ULID of the user whose latest autosave to fetch.

        Returns:
            Dict with full autosave detail, or None if not found.

        Example:
            latest = repo.get_latest(user_id="01H...")
            if latest is None:
                return Response(status_code=204)
        """

    @abstractmethod
    def delete(self, autosave_id: str) -> bool:
        """
        Delete a draft autosave record by primary key.

        Args:
            autosave_id: ULID primary key of the autosave to delete.

        Returns:
            True if the record was found and deleted, False if not found.

        Example:
            deleted = repo.delete(autosave_id="01H...")
            if not deleted:
                raise HTTPException(404, "Autosave not found")
        """

    @abstractmethod
    def purge_expired(self, max_age_days: int = 30) -> int:
        """
        Delete all autosave records older than max_age_days.

        This method is intended for background cleanup jobs that run
        periodically (e.g. daily via Celery) to reclaim storage space.

        Args:
            max_age_days: Number of days; autosaves older than this are deleted.
                         Defaults to 30 days. Computed relative to the current UTC time.

        Returns:
            Count of records deleted (0 if none).

        Example:
            deleted_count = repo.purge_expired(max_age_days=30)
            logger.info(f"Purged {deleted_count} expired autosaves")
        """
