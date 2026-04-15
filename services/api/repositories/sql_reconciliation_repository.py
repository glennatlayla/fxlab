"""
SQL repository for reconciliation report persistence.

Responsibilities:
- Persist reconciliation reports via SQLAlchemy.
- Map between Pydantic ReconciliationReport and ORM ReconciliationReport models.
- Support querying by deployment with most-recent-first ordering.

Does NOT:
- Execute reconciliation logic (service layer responsibility).
- Resolve discrepancies.
- Contain business logic.

Dependencies:
- SQLAlchemy Session (injected).
- libs.contracts.models.ReconciliationReport ORM model (aliased as ReconORM).
- libs.contracts.reconciliation: ReconciliationReport Pydantic model.
- libs.contracts.reconciliation: Discrepancy, ReconciliationTrigger.

Example:
    db = next(get_db())
    repo = SqlReconciliationRepository(db=db)
    report = ReconciliationReport(report_id="01HRECON...", ...)
    repo.save(report)
    reports = repo.list_by_deployment(deployment_id="01HDEPLOY...")
"""

from __future__ import annotations

from typing import Any

import structlog
from sqlalchemy.orm import Session

from libs.contracts.interfaces.reconciliation_repository_interface import (
    ReconciliationRepositoryInterface,
)
from libs.contracts.models import (
    ReconciliationReport as ReconORM,
)
from libs.contracts.reconciliation import (
    Discrepancy,
    ReconciliationReport,
    ReconciliationTrigger,
)

logger = structlog.get_logger(__name__)


def _pydantic_to_orm(report: ReconciliationReport) -> ReconORM:
    """
    Convert a Pydantic ReconciliationReport to its ORM counterpart.

    Discrepancies are serialised to a JSON-compatible list of dicts.
    The Pydantic status field is mapped to the ORM status with appropriate
    constraint-compatible values.

    Args:
        report: Pydantic ReconciliationReport instance.

    Returns:
        ORM ReconciliationReport ready for persistence.
    """
    # Map Pydantic status to ORM CHECK constraint values.
    # Pydantic uses "completed", "completed_with_discrepancies", "failed".
    # ORM CHECK allows "running", "completed", "failed".
    orm_status = report.status
    if orm_status == "completed_with_discrepancies":
        orm_status = "completed"

    # Serialise discrepancies to JSON-compatible list of dicts.
    discrepancies_json = [d.model_dump() for d in report.discrepancies]

    return ReconORM(
        id=report.report_id,
        deployment_id=report.deployment_id,
        trigger=report.trigger.value,
        started_at=report.created_at,
        status=orm_status,
        discrepancies=discrepancies_json,
        resolved_count=report.resolved_count,
        unresolved_count=report.unresolved_count,
    )


def _orm_to_pydantic(record: ReconORM) -> ReconciliationReport:
    """
    Convert an ORM ReconciliationReport to its Pydantic counterpart.

    Discrepancies are deserialised from JSON dicts back to Pydantic
    Discrepancy instances.

    Args:
        record: ORM ReconciliationReport instance.

    Returns:
        Pydantic ReconciliationReport.
    """
    discrepancies = [Discrepancy(**d) for d in (record.discrepancies or [])]

    # Determine Pydantic status from ORM status and discrepancy count.
    status = record.status
    if status == "completed" and record.unresolved_count > 0:
        status = "completed_with_discrepancies"

    return ReconciliationReport(
        report_id=record.id,
        deployment_id=record.deployment_id,
        trigger=ReconciliationTrigger(record.trigger),
        discrepancies=discrepancies,
        resolved_count=record.resolved_count,
        unresolved_count=record.unresolved_count,
        status=status,
        created_at=record.started_at,
    )


class SqlReconciliationRepository(ReconciliationRepositoryInterface):
    """
    SQL implementation of ReconciliationRepositoryInterface.

    Responsibilities:
    - Persist reconciliation reports with discrepancy JSON serialisation.
    - Retrieve by ID and by deployment.
    - Map between Pydantic and ORM models at the boundary.

    Does NOT:
    - Execute reconciliation logic.
    - Generate report IDs (caller provides via report_id field).

    Dependencies:
    - db: SQLAlchemy Session, injected by the caller.

    Example:
        repo = SqlReconciliationRepository(db=session)
        repo.save(report)
        retrieved = repo.get_by_id("01HRECON...")
    """

    def __init__(self, db: Any) -> None:
        """
        Initialise with an active SQLAlchemy session.

        Args:
            db: SQLAlchemy Session for database operations.
        """
        self._db: Session = db

    def save(self, report: ReconciliationReport) -> None:
        """
        Persist a reconciliation report.

        Converts the Pydantic model to its ORM counterpart and flushes
        to the database within the current transaction.

        Args:
            report: Pydantic ReconciliationReport to persist.
        """
        orm_record = _pydantic_to_orm(report)
        self._db.add(orm_record)
        self._db.flush()

        logger.info(
            "reconciliation_report.saved",
            operation="reconciliation_report_save",
            component="SqlReconciliationRepository",
            report_id=report.report_id,
            deployment_id=report.deployment_id,
            trigger=report.trigger.value,
        )

    def get_by_id(self, report_id: str) -> ReconciliationReport | None:
        """
        Get a reconciliation report by its primary key.

        Args:
            report_id: ULID of the report.

        Returns:
            Pydantic ReconciliationReport, or None if not found.
        """
        record = self._db.get(ReconORM, report_id)
        if record is None:
            return None
        return _orm_to_pydantic(record)

    def list_by_deployment(
        self,
        *,
        deployment_id: str,
        limit: int = 20,
    ) -> list[ReconciliationReport]:
        """
        List reconciliation reports for a deployment, most recent first.

        Args:
            deployment_id: Deployment ULID.
            limit: Maximum number of reports to return.

        Returns:
            List of Pydantic ReconciliationReport objects.
        """
        records = (
            self._db.query(ReconORM)
            .filter(ReconORM.deployment_id == deployment_id)
            .order_by(ReconORM.started_at.desc())
            .limit(limit)
            .all()
        )
        return [_orm_to_pydantic(r) for r in records]
