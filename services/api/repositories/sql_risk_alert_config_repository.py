"""
SQL repository for risk alert configuration persistence (Phase 7 — M11).

Responsibilities:
- Read and write RiskAlertConfigRecord to the database.
- Convert between ORM records and Pydantic domain objects.
- Upsert by deployment_id (merge semantics).

Does NOT:
- Evaluate alerts (service responsibility).
- Dispatch notifications (IncidentManager responsibility).
- Contain business logic.

Dependencies:
- SQLAlchemy Session (injected).
- libs.contracts.models.RiskAlertConfigRecord: ORM model.
- libs.contracts.risk_alert.RiskAlertConfig: domain contract.

Error conditions:
- sqlalchemy.exc.OperationalError: database connectivity issues.

Example:
    repo = SqlRiskAlertConfigRepository(db_session)
    config = repo.find_by_deployment_id("01HTESTDEPLOY000000000000")
"""

from __future__ import annotations

import logging
from decimal import Decimal

from sqlalchemy.orm import Session

from libs.contracts.interfaces.risk_alert_config_repository import (
    RiskAlertConfigRepositoryInterface,
)
from libs.contracts.models import RiskAlertConfigRecord
from libs.contracts.risk_alert import RiskAlertConfig

logger = logging.getLogger(__name__)


class SqlRiskAlertConfigRepository(RiskAlertConfigRepositoryInterface):
    """
    SQL-backed repository for risk alert configurations.

    Responsibilities:
    - CRUD operations for RiskAlertConfigRecord.
    - Convert between ORM and Pydantic domain objects.

    Does NOT:
    - Evaluate or dispatch alerts.

    Dependencies:
    - SQLAlchemy Session (injected via constructor).

    Example:
        repo = SqlRiskAlertConfigRepository(db)
        config = repo.find_by_deployment_id("01H...")
    """

    def __init__(self, db: Session) -> None:
        """
        Initialize with a SQLAlchemy session.

        Args:
            db: SQLAlchemy session for database operations.
        """
        self._db = db

    def find_by_deployment_id(self, deployment_id: str) -> RiskAlertConfig | None:
        """
        Find alert config for a deployment.

        Args:
            deployment_id: Target deployment.

        Returns:
            RiskAlertConfig if found, None otherwise.
        """
        record = self._db.get(RiskAlertConfigRecord, deployment_id)
        if record is None:
            return None
        return self._to_domain(record)

    def save(self, config: RiskAlertConfig) -> RiskAlertConfig:
        """
        Create or update an alert configuration (upsert).

        Args:
            config: Alert configuration to persist.

        Returns:
            The saved RiskAlertConfig.
        """
        record = self._db.get(RiskAlertConfigRecord, config.deployment_id)
        if record is None:
            record = RiskAlertConfigRecord(
                deployment_id=config.deployment_id,
            )
            self._db.add(record)

        record.var_threshold_pct = str(config.var_threshold_pct)
        record.concentration_threshold_pct = str(config.concentration_threshold_pct)
        record.correlation_threshold = str(config.correlation_threshold)
        record.lookback_days = config.lookback_days
        record.enabled = config.enabled

        self._db.flush()

        logger.info(
            "Risk alert config saved",
            extra={
                "operation": "save",
                "component": "SqlRiskAlertConfigRepository",
                "deployment_id": config.deployment_id,
                "enabled": config.enabled,
            },
        )

        return self._to_domain(record)

    def find_all(self) -> list[RiskAlertConfig]:
        """
        List all alert configurations.

        Returns:
            List of all persisted RiskAlertConfig entries.
        """
        records = (
            self._db.query(RiskAlertConfigRecord)
            .order_by(RiskAlertConfigRecord.deployment_id)
            .all()
        )
        return [self._to_domain(r) for r in records]

    def find_all_enabled(self) -> list[RiskAlertConfig]:
        """
        List all enabled alert configurations.

        Returns:
            List of enabled RiskAlertConfig entries.
        """
        records = (
            self._db.query(RiskAlertConfigRecord)
            .filter(RiskAlertConfigRecord.enabled.is_(True))
            .order_by(RiskAlertConfigRecord.deployment_id)
            .all()
        )
        return [self._to_domain(r) for r in records]

    @staticmethod
    def _to_domain(record: RiskAlertConfigRecord) -> RiskAlertConfig:
        """
        Convert ORM record to Pydantic domain object.

        Args:
            record: ORM RiskAlertConfigRecord.

        Returns:
            RiskAlertConfig domain object.
        """
        return RiskAlertConfig(
            deployment_id=record.deployment_id,
            var_threshold_pct=Decimal(record.var_threshold_pct),
            concentration_threshold_pct=Decimal(record.concentration_threshold_pct),
            correlation_threshold=Decimal(record.correlation_threshold),
            lookback_days=record.lookback_days,
            enabled=record.enabled,
        )
