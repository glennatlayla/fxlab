"""
Integration tests for SqlRiskAlertConfigRepository.

Uses in-memory SQLite database to test CRUD operations:
- find_by_deployment_id() retrieves config by ID.
- save() creates new config or updates existing.
- find_all() lists all configurations.
- find_all_enabled() filters for enabled configurations.
- ORM-to-domain conversion via _to_domain().
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from libs.contracts.models import Base, RiskAlertConfigRecord
from libs.contracts.risk_alert import RiskAlertConfig
from services.api.repositories.sql_risk_alert_config_repository import (
    SqlRiskAlertConfigRepository,
)


@pytest.fixture
def in_memory_db() -> Session:
    """
    In-memory SQLite database for risk alert config tests.

    Creates all tables, yields an active session, then cleans up.
    """
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(bind=engine)
    session = SessionLocal()
    yield session
    session.close()
    Base.metadata.drop_all(engine)


@pytest.fixture
def repository(in_memory_db: Session) -> SqlRiskAlertConfigRepository:
    """Provide a SqlRiskAlertConfigRepository bound to the test database."""
    return SqlRiskAlertConfigRepository(db=in_memory_db)


class TestSqlRiskAlertConfigRepositoryFindByDeploymentId:
    """Tests for find_by_deployment_id() method."""

    def test_find_by_deployment_id_returns_config_when_exists(
        self, repository: SqlRiskAlertConfigRepository, in_memory_db: Session
    ) -> None:
        """
        find_by_deployment_id() returns RiskAlertConfig when record exists.

        Scenario:
        - Insert a RiskAlertConfigRecord.
        - Call find_by_deployment_id() with that deployment_id.

        Expected:
        - Returns RiskAlertConfig with matching fields.
        """
        # Create and save a record
        record = RiskAlertConfigRecord(
            deployment_id="01HTEST000000000000000001",
            var_threshold_pct="5.0",
            concentration_threshold_pct="30.0",
            correlation_threshold="0.90",
            lookback_days=60,
            enabled=True,
        )
        in_memory_db.add(record)
        in_memory_db.commit()

        # Retrieve via repository
        config = repository.find_by_deployment_id("01HTEST000000000000000001")

        assert config is not None
        assert config.deployment_id == "01HTEST000000000000000001"
        assert config.var_threshold_pct == Decimal("5.0")
        assert config.concentration_threshold_pct == Decimal("30.0")
        assert config.correlation_threshold == Decimal("0.90")
        assert config.lookback_days == 60
        assert config.enabled is True

    def test_find_by_deployment_id_returns_none_when_not_exists(
        self, repository: SqlRiskAlertConfigRepository
    ) -> None:
        """
        find_by_deployment_id() returns None when record does not exist.

        Scenario:
        - Call find_by_deployment_id() with non-existent deployment_id.

        Expected:
        - Returns None.
        """
        result = repository.find_by_deployment_id("01HNONEXISTENT000000000000")
        assert result is None


class TestSqlRiskAlertConfigRepositorySave:
    """Tests for save() method."""

    def test_save_creates_new_config(
        self, repository: SqlRiskAlertConfigRepository, in_memory_db: Session
    ) -> None:
        """
        save() creates a new config when deployment_id does not exist.

        Scenario:
        - Create a RiskAlertConfig domain object.
        - Call save().

        Expected:
        - Config is persisted to database.
        - Record has correct fields.
        """
        config = RiskAlertConfig(
            deployment_id="01HTEST000000000000000002",
            var_threshold_pct=Decimal("5.0"),
            concentration_threshold_pct=Decimal("30.0"),
            correlation_threshold=Decimal("0.90"),
            lookback_days=60,
            enabled=True,
        )

        saved = repository.save(config)

        assert saved.deployment_id == "01HTEST000000000000000002"
        assert saved.var_threshold_pct == Decimal("5.0")

        # Verify it was persisted
        record = in_memory_db.get(RiskAlertConfigRecord, "01HTEST000000000000000002")
        assert record is not None
        assert record.var_threshold_pct == "5.0"

    def test_save_updates_existing_config(
        self, repository: SqlRiskAlertConfigRepository, in_memory_db: Session
    ) -> None:
        """
        save() updates existing config (upsert semantics).

        Scenario:
        - Create and save initial config.
        - Update threshold values.
        - Call save() again with same deployment_id.

        Expected:
        - Record is updated (not duplicated).
        - New values are persisted.
        """
        deployment_id = "01HTEST000000000000000003"

        # Create and save initial config
        config_v1 = RiskAlertConfig(
            deployment_id=deployment_id,
            var_threshold_pct=Decimal("5.0"),
            concentration_threshold_pct=Decimal("30.0"),
            correlation_threshold=Decimal("0.90"),
            lookback_days=60,
            enabled=True,
        )
        repository.save(config_v1)

        # Update and save again
        config_v2 = RiskAlertConfig(
            deployment_id=deployment_id,
            var_threshold_pct=Decimal("10.0"),  # Changed
            concentration_threshold_pct=Decimal("40.0"),  # Changed
            correlation_threshold=Decimal("0.85"),  # Changed
            lookback_days=90,  # Changed
            enabled=False,  # Changed
        )
        saved_v2 = repository.save(config_v2)

        assert saved_v2.var_threshold_pct == Decimal("10.0")
        assert saved_v2.concentration_threshold_pct == Decimal("40.0")
        assert saved_v2.enabled is False

        # Verify only one record exists
        records = in_memory_db.query(RiskAlertConfigRecord).all()
        assert len(records) == 1
        assert records[0].var_threshold_pct == "10.0"

    def test_save_returns_domain_object(self, repository: SqlRiskAlertConfigRepository) -> None:
        """
        save() returns the saved RiskAlertConfig domain object.

        Scenario:
        - Call save() with a config.

        Expected:
        - Returns RiskAlertConfig (not ORM record).
        """
        config = RiskAlertConfig(
            deployment_id="01HTEST000000000000000004",
            var_threshold_pct=Decimal("7.5"),
            concentration_threshold_pct=Decimal("35.0"),
            correlation_threshold=Decimal("0.95"),
            lookback_days=45,
            enabled=True,
        )

        result = repository.save(config)

        assert isinstance(result, RiskAlertConfig)
        assert result.deployment_id == config.deployment_id
        assert result.var_threshold_pct == config.var_threshold_pct


class TestSqlRiskAlertConfigRepositoryFindAll:
    """Tests for find_all() method."""

    def test_find_all_returns_all_configs_ordered(
        self, repository: SqlRiskAlertConfigRepository, in_memory_db: Session
    ) -> None:
        """
        find_all() returns all configs, ordered by deployment_id.

        Scenario:
        - Save 3 configs with different deployment_ids.
        - Call find_all().

        Expected:
        - Returns list of 3 RiskAlertConfig objects.
        - Ordered by deployment_id (ascending).
        """
        configs = [
            RiskAlertConfig(
                deployment_id="01HTEST000000000000000005",
                var_threshold_pct=Decimal("5.0"),
                concentration_threshold_pct=Decimal("30.0"),
                correlation_threshold=Decimal("0.90"),
                lookback_days=60,
                enabled=True,
            ),
            RiskAlertConfig(
                deployment_id="01HTEST000000000000000003",  # Out of order
                var_threshold_pct=Decimal("6.0"),
                concentration_threshold_pct=Decimal("25.0"),
                correlation_threshold=Decimal("0.85"),
                lookback_days=45,
                enabled=False,
            ),
            RiskAlertConfig(
                deployment_id="01HTEST000000000000000004",  # Out of order
                var_threshold_pct=Decimal("4.0"),
                concentration_threshold_pct=Decimal("35.0"),
                correlation_threshold=Decimal("0.95"),
                lookback_days=75,
                enabled=True,
            ),
        ]

        for config in configs:
            repository.save(config)

        results = repository.find_all()

        assert len(results) == 3
        assert results[0].deployment_id == "01HTEST000000000000000003"
        assert results[1].deployment_id == "01HTEST000000000000000004"
        assert results[2].deployment_id == "01HTEST000000000000000005"

    def test_find_all_returns_empty_list_when_none_exist(
        self, repository: SqlRiskAlertConfigRepository
    ) -> None:
        """
        find_all() returns empty list when no configs exist.

        Scenario:
        - Empty database.
        - Call find_all().

        Expected:
        - Returns empty list.
        """
        results = repository.find_all()
        assert results == []


class TestSqlRiskAlertConfigRepositoryFindAllEnabled:
    """Tests for find_all_enabled() method."""

    def test_find_all_enabled_returns_only_enabled_configs(
        self, repository: SqlRiskAlertConfigRepository
    ) -> None:
        """
        find_all_enabled() returns only configs with enabled=True.

        Scenario:
        - Save 3 configs: 2 enabled, 1 disabled.
        - Call find_all_enabled().

        Expected:
        - Returns list of 2 enabled configs only.
        """
        configs = [
            RiskAlertConfig(
                deployment_id="01HTEST000000000000000006",
                var_threshold_pct=Decimal("5.0"),
                concentration_threshold_pct=Decimal("30.0"),
                correlation_threshold=Decimal("0.90"),
                lookback_days=60,
                enabled=True,
            ),
            RiskAlertConfig(
                deployment_id="01HTEST000000000000000007",
                var_threshold_pct=Decimal("6.0"),
                concentration_threshold_pct=Decimal("25.0"),
                correlation_threshold=Decimal("0.85"),
                lookback_days=45,
                enabled=False,  # Disabled
            ),
            RiskAlertConfig(
                deployment_id="01HTEST000000000000000008",
                var_threshold_pct=Decimal("4.0"),
                concentration_threshold_pct=Decimal("35.0"),
                correlation_threshold=Decimal("0.95"),
                lookback_days=75,
                enabled=True,
            ),
        ]

        for config in configs:
            repository.save(config)

        results = repository.find_all_enabled()

        assert len(results) == 2
        assert all(config.enabled is True for config in results)
        assert results[0].deployment_id == "01HTEST000000000000000006"
        assert results[1].deployment_id == "01HTEST000000000000000008"

    def test_find_all_enabled_returns_empty_when_none_enabled(
        self, repository: SqlRiskAlertConfigRepository
    ) -> None:
        """
        find_all_enabled() returns empty list when no configs are enabled.

        Scenario:
        - Save 2 configs, both disabled.
        - Call find_all_enabled().

        Expected:
        - Returns empty list.
        """
        configs = [
            RiskAlertConfig(
                deployment_id="01HTEST000000000000000009",
                var_threshold_pct=Decimal("5.0"),
                concentration_threshold_pct=Decimal("30.0"),
                correlation_threshold=Decimal("0.90"),
                lookback_days=60,
                enabled=False,
            ),
            RiskAlertConfig(
                deployment_id="01HTEST000000000000000010",
                var_threshold_pct=Decimal("6.0"),
                concentration_threshold_pct=Decimal("25.0"),
                correlation_threshold=Decimal("0.85"),
                lookback_days=45,
                enabled=False,
            ),
        ]

        for config in configs:
            repository.save(config)

        results = repository.find_all_enabled()

        assert results == []


class TestSqlRiskAlertConfigRepositoryToDomain:
    """Tests for _to_domain() conversion method."""

    def test_to_domain_converts_orm_record_correctly(
        self, repository: SqlRiskAlertConfigRepository, in_memory_db: Session
    ) -> None:
        """
        _to_domain() converts ORM record to Pydantic domain object correctly.

        Scenario:
        - Create ORM record with string decimal fields.
        - Call _to_domain().

        Expected:
        - Returns RiskAlertConfig with Decimal fields.
        - All field values match the ORM record.
        """
        record = RiskAlertConfigRecord(
            deployment_id="01HTEST000000000000000011",
            var_threshold_pct="8.5",
            concentration_threshold_pct="32.5",
            correlation_threshold="0.92",
            lookback_days=70,
            enabled=True,
        )

        domain = SqlRiskAlertConfigRepository._to_domain(record)

        assert domain.deployment_id == "01HTEST000000000000000011"
        assert domain.var_threshold_pct == Decimal("8.5")
        assert domain.concentration_threshold_pct == Decimal("32.5")
        assert domain.correlation_threshold == Decimal("0.92")
        assert domain.lookback_days == 70
        assert domain.enabled is True

    def test_to_domain_preserves_decimal_precision(
        self, repository: SqlRiskAlertConfigRepository
    ) -> None:
        """
        _to_domain() preserves decimal precision when converting string fields.

        Scenario:
        - ORM record with precise decimal strings (many decimal places).
        - Call _to_domain().

        Expected:
        - Decimal fields retain full precision.
        """
        record = RiskAlertConfigRecord(
            deployment_id="01HTEST000000000000000012",
            var_threshold_pct="5.12345",
            concentration_threshold_pct="30.99999",
            correlation_threshold="0.950001",
            lookback_days=60,
            enabled=False,
        )

        domain = SqlRiskAlertConfigRepository._to_domain(record)

        assert domain.var_threshold_pct == Decimal("5.12345")
        assert domain.concentration_threshold_pct == Decimal("30.99999")
        assert domain.correlation_threshold == Decimal("0.950001")
