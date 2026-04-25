"""
SQL repository for governance override requests.

Responsibilities:
- Persist override requests to the overrides table via SQLAlchemy.
- Look up overrides by primary key.
- Generate ULID-shaped primary keys for new records.

Does NOT:
- Enforce separation-of-duties (service layer responsibility).
- Contain business logic or approval logic.
- Emit audit events (audit_service responsibility).

Dependencies:
- SQLAlchemy Session (injected via get_db).
- libs.contracts.models.Override ORM model.

Error conditions:
- NotFoundError: raised by get_by_id when the override_id does not exist.

Example:
    db = next(get_db())
    repo = SqlOverrideRepository(db=db)
    record = repo.create(
        object_id="01H...",
        object_type="candidate",
        override_type="grade_override",
        original_state={"grade": "C"},
        new_state={"grade": "B"},
        evidence_link="https://jira.example.com/browse/FX-123",
        rationale="Backtest justifies grade uplift.",
        submitter_id="01H...",
    )
    detail = repo.get_by_id(record["override_id"])
"""

from __future__ import annotations

from typing import Any

import structlog

from libs.contracts.interfaces.override_repository import OverrideRepositoryInterface
from libs.contracts.models import Override

logger = structlog.get_logger(__name__)


def _generate_ulid() -> str:
    """
    Generate a cryptographically random, time-ordered ULID for new records.

    Uses python-ulid which is thread-safe and produces spec-compliant
    26-character Crockford base32 ULIDs with millisecond-precision
    timestamps and 80 bits of cryptographic randomness.

    Returns:
        26-character ULID string (Crockford base32).
    """
    import ulid as _ulid

    return str(_ulid.ULID())


class SqlOverrideRepository(OverrideRepositoryInterface):
    """
    SQLAlchemy-backed repository for governance override requests.

    Responsibilities:
    - Insert new Override rows on create().
    - Retrieve Override rows by primary key on get_by_id().

    Does NOT:
    - Contain business logic.
    - Enforce separation-of-duties.

    Dependencies:
        db: SQLAlchemy Session, injected by the caller via get_db().

    Example:
        repo = SqlOverrideRepository(db=session)
        record = repo.create(object_id="01H...", ...)
    """

    def __init__(self, db: Any) -> None:
        """
        Initialise with an active SQLAlchemy session.

        Args:
            db: An open SQLAlchemy Session from get_db().
        """
        self._db = db

    def create(
        self,
        *,
        object_id: str,
        object_type: str,
        override_type: str,
        original_state: dict[str, Any] | None,
        new_state: dict[str, Any] | None,
        evidence_link: str,
        rationale: str,
        submitter_id: str,
    ) -> dict[str, Any]:
        """
        Persist a new governance override request.

        Args:
            object_id: ULID of the target entity being overridden.
            object_type: Entity type classifier (candidate, deployment).
            override_type: Override category (e.g. grade_override).
            original_state: JSON snapshot of entity state before the override.
            new_state: JSON snapshot of proposed entity state after the override.
            evidence_link: Absolute HTTP/HTTPS URI to supporting evidence.
            rationale: Submitter's free-text justification (≥20 chars).
            submitter_id: ULID of the requesting operator.

        Returns:
            Dict with override_id and status='pending'.

        Example:
            record = repo.create(
                object_id="01H...", object_type="candidate",
                override_type="grade_override",
                original_state={"grade": "C"}, new_state={"grade": "B"},
                evidence_link="https://jira.example.com/browse/FX-123",
                rationale="3-year backtest justifies grade B uplift.",
                submitter_id="01H...",
            )
            # record == {"override_id": "01H...", "status": "pending"}
        """
        override_id = _generate_ulid()

        row = Override(
            id=override_id,
            target_id=object_id,
            target_type=object_type,
            override_type=override_type,
            original_state=original_state,
            new_state=new_state,
            evidence_link=evidence_link,
            rationale=rationale,
            submitter_id=submitter_id,
            status="pending",
            is_active=True,
        )

        self._db.add(row)
        self._db.flush()  # Emit SQL but keep transaction open for atomicity.
        self._db.refresh(row)

        logger.debug(
            "override.sql.created",
            override_id=override_id,
            object_type=object_type,
            override_type=override_type,
        )

        return {"override_id": override_id, "status": "pending"}

    def get_by_id(self, override_id: str) -> dict[str, Any] | None:
        """
        Retrieve a governance override request by primary key.

        Args:
            override_id: ULID primary key of the override record.

        Returns:
            Dict with full override detail, or None if not found.

        Example:
            detail = repo.get_by_id("01HOVERRIDE...")
            if detail is None:
                raise HTTPException(404, ...)
        """
        row: Override | None = self._db.get(Override, override_id)
        if row is None:
            return None

        return {
            "override_id": row.id,
            "id": row.id,
            "object_id": row.target_id,
            "object_type": row.target_type,
            "override_type": row.override_type,
            "original_state": row.original_state,
            "new_state": row.new_state,
            "evidence_link": row.evidence_link,
            "rationale": row.rationale,
            "submitter_id": row.submitter_id,
            "status": row.status,
            "reviewed_by": row.reviewer_id,
            "reviewed_at": row.decided_at.isoformat() if row.decided_at else None,
            "created_at": row.created_at.isoformat() if row.created_at else None,
            "updated_at": row.updated_at.isoformat() if row.updated_at else None,
        }

    def update_decision(
        self,
        *,
        override_id: str,
        reviewer_id: str,
        status: str,
        decision_rationale: str,
    ) -> dict[str, Any]:
        """
        Record a reviewer's decision (approve/reject) on an override.

        Args:
            override_id: ULID of the override being decided.
            reviewer_id: ULID of the reviewer making the decision.
            status: New status — must be 'approved' or 'rejected'.
            decision_rationale: Reviewer's justification for the decision.

        Returns:
            Dict with updated override detail.

        Raises:
            NotFoundError: If override_id does not exist.

        Example:
            result = repo.update_decision(
                override_id="01HOVERRIDE...",
                reviewer_id="01HREVIEWER...",
                status="approved",
                decision_rationale="Evidence is sound.",
            )
        """
        from datetime import datetime, timezone

        from libs.contracts.errors import NotFoundError

        row: Override | None = self._db.get(Override, override_id)
        if row is None:
            raise NotFoundError(f"Override {override_id!r} not found")

        now = datetime.now(tz=timezone.utc)
        row.status = status
        row.reviewer_id = reviewer_id
        row.decision_rationale = decision_rationale
        row.decided_at = now
        row.updated_at = now  # type: ignore[assignment]

        self._db.flush()

        logger.debug(
            "override.sql.decision_recorded",
            override_id=override_id,
            reviewer_id=reviewer_id,
            status=status,
        )

        return self.get_by_id(override_id) or {}
