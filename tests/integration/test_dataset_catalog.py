"""
Integration tests for the M4.E3 dataset catalog stack.

Exercises the full slice end-to-end against a real database:

    SqlDatasetRepository
        -> DatasetService
            -> CatalogBackedResolver
                -> DatasetResolverInterface

Plus the bootstrap seed-on-empty path that
``services/api/main._seed_dataset_catalog_if_empty`` runs on first
boot, so we know production wiring populates the catalog from the
documented defaults (the same dataset_refs the M2.C2 in-memory
seeder shipped) and is idempotent on a re-run.

Uses the existing integration_db_session fixture (Postgres if
TEST_DATABASE_URL points at it, SQLite otherwise) with SAVEPOINT
isolation per test.
"""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest
from sqlalchemy.orm import Session

from libs.contracts.models import CandleRecord, ResearchRun, Strategy, User
from libs.strategy_ir.dataset_resolver import CatalogBackedResolver
from libs.strategy_ir.interfaces.dataset_resolver_interface import (
    DatasetResolverInterface,
)
from libs.strategy_ir.interfaces.dataset_service_interface import (
    DatasetNotFoundError,
    ResolvedDataset,
)
from services.api.main import (
    _DATASET_CATALOG_BOOTSTRAP_SEED,
    _seed_dataset_catalog_if_empty,
)
from services.api.repositories.sql_dataset_repository import SqlDatasetRepository
from services.api.services.dataset_service import DatasetService

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


@pytest.fixture()
def repo(integration_db_session: Session) -> SqlDatasetRepository:
    return SqlDatasetRepository(db=integration_db_session)


@pytest.fixture()
def service(repo: SqlDatasetRepository) -> DatasetService:
    return DatasetService(repo=repo)


@pytest.fixture()
def resolver(service: DatasetService) -> DatasetResolverInterface:
    return CatalogBackedResolver(service)


# ---------------------------------------------------------------------------
# End-to-end: register → resolve via the full stack
# ---------------------------------------------------------------------------


class TestEndToEndStack:
    def test_register_then_resolve_returns_resolved_dataset(
        self,
        service: DatasetService,
        resolver: DatasetResolverInterface,
    ) -> None:
        service.register_dataset(
            "fx-eurusd-15m-certified-v3",
            symbols=["EURUSD"],
            timeframe="15m",
            source="oanda",
            version="v3",
        )

        result = resolver.resolve("fx-eurusd-15m-certified-v3")
        assert isinstance(result, ResolvedDataset)
        assert result.dataset_ref == "fx-eurusd-15m-certified-v3"
        assert result.symbols == ["EURUSD"]
        # ULID stored in dataset_id; not the human ref.
        assert result.dataset_id != "fx-eurusd-15m-certified-v3"
        assert len(result.dataset_id) == 26

    def test_resolver_raises_not_found_for_unknown_ref(
        self,
        resolver: DatasetResolverInterface,
    ) -> None:
        with pytest.raises(DatasetNotFoundError):
            resolver.resolve("never-registered")

    def test_register_then_list_known_refs(
        self,
        service: DatasetService,
    ) -> None:
        service.register_dataset(
            "fx-eurusd-15m-certified-v3",
            symbols=["EURUSD"],
            timeframe="15m",
            source="oanda",
            version="v3",
        )
        service.register_dataset(
            "fx-majors-h1-certified-v1",
            symbols=["EURUSD", "GBPUSD"],
            timeframe="1h",
            source="oanda",
            version="v1",
        )
        refs = service.list_known_refs()
        assert refs == [
            "fx-eurusd-15m-certified-v3",
            "fx-majors-h1-certified-v1",
        ]

    def test_register_is_upsert(self, service: DatasetService) -> None:
        service.register_dataset(
            "fx-eurusd-15m-certified-v3",
            symbols=["EURUSD"],
            timeframe="15m",
            source="oanda",
            version="v3",
        )
        first = service.lookup("fx-eurusd-15m-certified-v3")

        # Re-register with new metadata — must UPDATE in place.
        service.register_dataset(
            "fx-eurusd-15m-certified-v3",
            symbols=["EURUSD", "GBPUSD"],
            timeframe="15m",
            source="oanda",
            version="v4",
        )
        second = service.lookup("fx-eurusd-15m-certified-v3")

        assert second.dataset_id == first.dataset_id  # ULID preserved
        assert second.symbols == ["EURUSD", "GBPUSD"]


# ---------------------------------------------------------------------------
# Bootstrap seed-on-empty path (production startup ritual)
# ---------------------------------------------------------------------------


class TestBootstrapSeed:
    def test_seed_populates_empty_catalog_with_production_refs(
        self,
        service: DatasetService,
        integration_db_session: Session,
    ) -> None:
        assert service.list_known_refs() == []

        _seed_dataset_catalog_if_empty(service, integration_db_session)

        refs = service.list_known_refs()
        # Every dataset_ref in the bootstrap table must end up in the
        # catalog after the seed runs against an empty table.
        expected = sorted({entry["dataset_ref"] for entry in _DATASET_CATALOG_BOOTSTRAP_SEED})
        assert refs == expected

    def test_seed_is_noop_when_catalog_already_populated(
        self,
        service: DatasetService,
        integration_db_session: Session,
    ) -> None:
        service.register_dataset(
            "operator-only-ref",
            symbols=["EURUSD"],
            timeframe="15m",
            source="manual",
            version="v1",
        )

        _seed_dataset_catalog_if_empty(service, integration_db_session)

        # The seed must not have added the bootstrap entries — only
        # the operator-registered ref survives.
        assert service.list_known_refs() == ["operator-only-ref"]

    def test_seed_is_idempotent_across_repeated_runs(
        self,
        service: DatasetService,
        integration_db_session: Session,
    ) -> None:
        _seed_dataset_catalog_if_empty(service, integration_db_session)
        first_refs = service.list_known_refs()

        # Calling a second time must not double-insert.
        _seed_dataset_catalog_if_empty(service, integration_db_session)
        second_refs = service.list_known_refs()

        assert first_refs == second_refs

    def test_seed_resolves_via_catalog_backed_resolver(
        self,
        service: DatasetService,
        integration_db_session: Session,
        resolver: DatasetResolverInterface,
    ) -> None:
        _seed_dataset_catalog_if_empty(service, integration_db_session)

        # Sanity: every seeded ref resolves cleanly through the
        # narrow resolver port that the route layer depends on.
        for entry in _DATASET_CATALOG_BOOTSTRAP_SEED:
            resolved = resolver.resolve(entry["dataset_ref"])
            assert resolved.dataset_ref == entry["dataset_ref"]
            assert resolved.symbols == list(entry["symbols"])

    def test_bootstrap_table_includes_known_production_refs(self) -> None:
        """The seed table must always carry the canonical production
        refs the M2.C2 in-memory seeder shipped, so behaviour is
        unchanged from the operator's perspective on first boot."""
        refs = {entry["dataset_ref"] for entry in _DATASET_CATALOG_BOOTSTRAP_SEED}
        # Spot-check the four canonical certified refs the M2.C2
        # seeder declared for production experiment plans.
        for required in (
            "fx-eurusd-15m-certified-v3",
            "fx-majors-h1-certified-v1",
            "fx-majors-d1-certified-v1",
            "fx-majors-1h-certified-v3",
            "fx-majors-4h-certified-v3",
        ):
            assert required in refs, f"missing seed entry: {required}"


# ---------------------------------------------------------------------------
# Certification round-trip
# ---------------------------------------------------------------------------


class TestCertification:
    def test_default_uncertified_after_register(
        self,
        service: DatasetService,
    ) -> None:
        service.register_dataset(
            "fx-eurusd-15m-certified-v3",
            symbols=["EURUSD"],
            timeframe="15m",
            source="oanda",
            version="v3",
        )
        assert service.is_certified("fx-eurusd-15m-certified-v3") is False

    def test_unknown_ref_is_not_certified(self, service: DatasetService) -> None:
        assert service.is_certified("never-registered") is False


# ---------------------------------------------------------------------------
# get_detail / detail-page projections — end to end
# ---------------------------------------------------------------------------


class TestGetDetailEndToEnd:
    def test_unknown_ref_raises_not_found(
        self,
        service: DatasetService,
    ) -> None:
        with pytest.raises(DatasetNotFoundError):
            service.get_detail("never-registered")

    def test_returns_inventory_strategies_and_runs(
        self,
        service: DatasetService,
        integration_db_session: Session,
    ) -> None:
        # Catalog row.
        service.register_dataset(
            "fx-eurusd-15m-it",
            symbols=["EURUSD"],
            timeframe="15m",
            source="oanda",
            version="v1",
        )

        # Bar fixtures.
        base = datetime(2026, 4, 1, 0, 0, 0)
        for n in range(3):
            integration_db_session.add(
                CandleRecord(
                    symbol="EURUSD",
                    interval="15m",
                    timestamp=base + timedelta(minutes=15 * n),
                    open="1.0",
                    high="1.0",
                    low="1.0",
                    close="1.0",
                    volume=1,
                )
            )

        # User + strategy + run referencing the dataset.
        user = User(
            id="01HXSER000000000000000T001",
            email="it@fxlab.test",
            hashed_password="x",
            role="admin",
            is_active=True,
        )
        integration_db_session.add(user)
        integration_db_session.flush()

        strategy = Strategy(
            id="01HSTRAT0000000000000T0001",
            name="Integration Strategy",
            code="def signals(): pass",
            version="v1",
            created_by="01HXSER000000000000000T001",
            is_active=True,
            source="draft_form",
        )
        integration_db_session.add(strategy)
        integration_db_session.flush()

        run = ResearchRun(
            id="01HRXN000000000000000T0001",
            run_type="backtest",
            strategy_id="01HSTRAT0000000000000T0001",
            status="completed",
            config_json={
                "run_type": "backtest",
                "strategy_id": "01HSTRAT0000000000000T0001",
                "data_selection": {"dataset_ref": "fx-eurusd-15m-it"},
            },
            result_json=None,
            created_by="01HXSER000000000000000T001",
            created_at=base,
            updated_at=base,
            started_at=None,
            completed_at=base + timedelta(hours=2),
        )
        integration_db_session.add(run)
        integration_db_session.flush()

        detail = service.get_detail("fx-eurusd-15m-it")

        assert detail.dataset_ref == "fx-eurusd-15m-it"
        assert detail.symbols == ["EURUSD"]
        assert detail.timeframe == "15m"

        assert len(detail.bar_inventory) == 1
        only = detail.bar_inventory[0]
        assert only.symbol == "EURUSD"
        assert only.row_count == 3

        assert len(detail.strategies_using) == 1
        assert detail.strategies_using[0].strategy_id == "01HSTRAT0000000000000T0001"
        assert detail.strategies_using[0].name == "Integration Strategy"

        assert len(detail.recent_runs) == 1
        assert detail.recent_runs[0].run_id == "01HRXN000000000000000T0001"
        assert detail.recent_runs[0].status == "completed"
