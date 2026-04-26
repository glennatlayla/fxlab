"""
SQL-backed research run repository.

Purpose:
    Persist and query research run records in PostgreSQL/SQLite via
    SQLAlchemy, implementing ResearchRunRepositoryInterface.

Responsibilities:
    - Create research run records with serialised JSON config.
    - Retrieve by ID with deserialisation of config and result JSON.
    - Update status with transition validation and timestamp tracking.
    - Attach results (serialised as JSON).
    - List runs by strategy or user with pagination.
    - Count runs by status.

Does NOT:
    - Execute research engines (service layer responsibility).
    - Call session.commit() — uses flush() for request-scoped transactions.
    - Contain business logic.

Dependencies:
    - SQLAlchemy Session (injected).
    - libs.contracts.models.ResearchRun ORM model.
    - libs.contracts.interfaces.research_run_repository.ResearchRunRepositoryInterface.

Error conditions:
    - update_status: NotFoundError if run_id missing, InvalidStatusTransitionError
      if transition is illegal.
    - save_result: NotFoundError if run_id missing.

Example:
    repo = SqlResearchRunRepository(db=session)
    repo.create(record)
    run = repo.get_by_id("01HRUN...")
"""

from __future__ import annotations

from datetime import datetime, timezone

import structlog
from sqlalchemy import func
from sqlalchemy.orm import Session

from libs.contracts.errors import NotFoundError
from libs.contracts.interfaces.research_run_repository import (
    ResearchRunRepositoryInterface,
)
from libs.contracts.models import ResearchRun
from libs.contracts.research_run import (
    InvalidStatusTransitionError,
    ResearchRunConfig,
    ResearchRunRecord,
    ResearchRunResult,
    ResearchRunStatus,
    validate_status_transition,
)

logger = structlog.get_logger(__name__)


class SqlResearchRunRepository(ResearchRunRepositoryInterface):
    """
    SQL-backed implementation of ResearchRunRepositoryInterface.

    Stores research run configuration and results as JSON columns.
    Status transitions are validated before persistence.

    Attributes:
        _db: SQLAlchemy session for database operations.

    Example:
        repo = SqlResearchRunRepository(db=session)
        repo.create(record)
    """

    def __init__(self, db: Session) -> None:
        self._db = db

    # ------------------------------------------------------------------
    # Serialisation helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _record_to_orm(record: ResearchRunRecord) -> ResearchRun:
        """
        Convert a domain record to an ORM instance.

        Args:
            record: The domain ResearchRunRecord.

        Returns:
            A ResearchRun ORM instance ready for persistence.
        """
        config_dict = record.config.model_dump(mode="json")
        result_dict = record.result.model_dump(mode="json") if record.result else None
        summary = (
            record.result.summary_metrics
            if record.result and record.result.summary_metrics
            else None
        )

        return ResearchRun(
            id=record.id,
            run_type=record.config.run_type.value,
            strategy_id=record.config.strategy_id,
            status=record.status.value,
            config_json=config_dict,
            result_json=result_dict,
            error_message=record.error_message,
            summary_metrics=summary,
            created_by=record.created_by,
            created_at=record.created_at,
            updated_at=record.updated_at,
            started_at=record.started_at,
            completed_at=record.completed_at,
        )

    @staticmethod
    def _orm_to_record(orm: ResearchRun) -> ResearchRunRecord:
        """
        Convert an ORM instance to a domain record.

        Args:
            orm: The ResearchRun ORM instance.

        Returns:
            A ResearchRunRecord domain object.
        """
        config = ResearchRunConfig.model_validate(orm.config_json)
        result = ResearchRunResult.model_validate(orm.result_json) if orm.result_json else None

        return ResearchRunRecord(
            id=orm.id,
            config=config,
            status=ResearchRunStatus(orm.status),
            result=result,
            error_message=orm.error_message,
            created_by=orm.created_by,
            created_at=orm.created_at,
            updated_at=orm.updated_at,
            started_at=orm.started_at,
            completed_at=orm.completed_at,
        )

    # ------------------------------------------------------------------
    # Interface methods
    # ------------------------------------------------------------------

    def create(self, record: ResearchRunRecord) -> ResearchRunRecord:
        """
        Persist a new research run record.

        Args:
            record: The domain record to persist.

        Returns:
            The persisted record.

        Raises:
            ValueError: If a record with the same id already exists.
        """
        existing = self._db.get(ResearchRun, record.id)
        if existing is not None:
            raise ValueError(f"Research run {record.id} already exists")

        orm = self._record_to_orm(record)
        self._db.add(orm)
        self._db.flush()

        logger.debug(
            "research_run.created",
            run_id=record.id,
            run_type=record.config.run_type.value,
            strategy_id=record.config.strategy_id,
            component="sql_research_run_repository",
        )

        return self._orm_to_record(orm)

    def get_by_id(self, run_id: str) -> ResearchRunRecord | None:
        """
        Retrieve a research run by ID.

        Args:
            run_id: The ULID to look up.

        Returns:
            The record if found, None otherwise.
        """
        orm = self._db.get(ResearchRun, run_id)
        if orm is None:
            return None
        return self._orm_to_record(orm)

    def update_status(
        self,
        run_id: str,
        new_status: ResearchRunStatus,
        *,
        error_message: str | None = None,
    ) -> ResearchRunRecord:
        """
        Transition a run to a new status with validation.

        Args:
            run_id: The ULID of the run.
            new_status: Target status.
            error_message: Optional error for FAILED transitions.

        Returns:
            The updated record.

        Raises:
            NotFoundError: If the run does not exist.
            InvalidStatusTransitionError: If the transition is invalid.
        """
        orm = self._db.get(ResearchRun, run_id)
        if orm is None:
            raise NotFoundError(f"Research run {run_id} not found")

        current = ResearchRunStatus(orm.status)
        if not validate_status_transition(current, new_status):
            raise InvalidStatusTransitionError(current, new_status)

        now = datetime.now(timezone.utc)
        orm.status = new_status.value
        orm.updated_at = now

        if new_status == ResearchRunStatus.RUNNING:
            orm.started_at = now
        elif new_status in (
            ResearchRunStatus.COMPLETED,
            ResearchRunStatus.FAILED,
            ResearchRunStatus.CANCELLED,
        ):
            orm.completed_at = now

        if error_message is not None:
            orm.error_message = error_message

        self._db.flush()

        logger.info(
            "research_run.status_updated",
            run_id=run_id,
            old_status=current.value,
            new_status=new_status.value,
            component="sql_research_run_repository",
        )

        return self._orm_to_record(orm)

    def save_result(self, run_id: str, result: ResearchRunResult) -> ResearchRunRecord:
        """
        Attach an engine result to a run.

        Args:
            run_id: The ULID of the run.
            result: The engine result to persist.

        Returns:
            The updated record.

        Raises:
            NotFoundError: If the run does not exist.
        """
        orm = self._db.get(ResearchRun, run_id)
        if orm is None:
            raise NotFoundError(f"Research run {run_id} not found")

        orm.result_json = result.model_dump(mode="json")
        orm.summary_metrics = result.summary_metrics
        orm.updated_at = datetime.now(timezone.utc)
        self._db.flush()

        logger.debug(
            "research_run.result_saved",
            run_id=run_id,
            component="sql_research_run_repository",
        )

        return self._orm_to_record(orm)

    def list_by_strategy(
        self,
        strategy_id: str,
        *,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[ResearchRunRecord], int]:
        """
        List runs for a strategy with pagination.

        Args:
            strategy_id: Filter by strategy ULID.
            limit: Max records.
            offset: Pagination offset.

        Returns:
            Tuple of (records, total_count).
        """
        query = self._db.query(ResearchRun).filter(ResearchRun.strategy_id == strategy_id)
        total = query.count()
        orms = query.order_by(ResearchRun.created_at.desc()).offset(offset).limit(limit).all()
        records = [self._orm_to_record(o) for o in orms]
        return records, total

    def list_by_user(
        self,
        user_id: str,
        *,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[ResearchRunRecord], int]:
        """
        List runs for a user with pagination.

        Args:
            user_id: Filter by user ULID.
            limit: Max records.
            offset: Pagination offset.

        Returns:
            Tuple of (records, total_count).
        """
        query = self._db.query(ResearchRun).filter(ResearchRun.created_by == user_id)
        total = query.count()
        orms = query.order_by(ResearchRun.created_at.desc()).offset(offset).limit(limit).all()
        records = [self._orm_to_record(o) for o in orms]
        return records, total

    def list_by_strategy_id(
        self,
        *,
        strategy_id: str,
        page: int,
        page_size: int,
    ) -> tuple[list[ResearchRunRecord], int]:
        """
        Page runs for a strategy and return the matching total count.

        Mirrors :meth:`SqlStrategyRepository.list_with_total` (M2.D5 commit
        740e33e): two queries hit the database — one ``count(*)`` over the
        filtered set, one bounded ``select`` for the page itself. Sharing
        the filter chain keeps ``total_count`` perfectly consistent with
        the page rows so the UI's "Page X of Y" never disagrees with the
        rendered table on re-render.

        Args:
            strategy_id: Filter by strategy ULID.
            page: 1-based page index. Values < 1 are clamped to 1 so the
                method is safe under direct unit-test calls.
            page_size: Maximum runs per page. Must be >= 1.

        Returns:
            Tuple of ``(records, total_count)`` — the page rows ordered
            by ``created_at`` descending and the total count of rows
            matching the strategy filter.

        Raises:
            ValueError: If ``page_size`` < 1.
        """
        if page_size < 1:
            raise ValueError("page_size must be >= 1")
        safe_page = page if page >= 1 else 1
        offset = (safe_page - 1) * page_size

        base = self._db.query(ResearchRun).filter(ResearchRun.strategy_id == strategy_id)
        total_count = base.count()
        orms = base.order_by(ResearchRun.created_at.desc()).offset(offset).limit(page_size).all()
        records = [self._orm_to_record(o) for o in orms]
        return records, total_count

    def count_by_status(self, status: ResearchRunStatus | None = None) -> int:
        """
        Count runs, optionally filtered by status.

        Args:
            status: If provided, count only matching.

        Returns:
            The count.
        """
        query = self._db.query(func.count(ResearchRun.id))
        if status is not None:
            query = query.filter(ResearchRun.status == status.value)
        result = query.scalar()
        return result or 0
