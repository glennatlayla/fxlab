"""
Unit tests for reconciliation contract schemas.

Covers:
- Enum stability (ReconciliationTrigger, DiscrepancyType).
- Discrepancy model construction, frozen, serialization.
- ReconciliationReport model construction, frozen, defaults, serialization.
- Mock repository behavioural parity.

Dependencies:
- libs.contracts.reconciliation
- libs.contracts.mocks.mock_reconciliation_repository
"""

from __future__ import annotations

from datetime import datetime

import pytest

from libs.contracts.mocks.mock_reconciliation_repository import (
    MockReconciliationRepository,
)
from libs.contracts.reconciliation import (
    Discrepancy,
    DiscrepancyType,
    ReconciliationReport,
    ReconciliationTrigger,
)

# ------------------------------------------------------------------
# ReconciliationTrigger enum
# ------------------------------------------------------------------


class TestReconciliationTrigger:
    """Verify trigger enum members and string values."""

    def test_trigger_members(self) -> None:
        members = {m.value for m in ReconciliationTrigger}
        assert members == {"startup", "reconnect", "scheduled", "manual"}

    def test_trigger_string_identity(self) -> None:
        assert ReconciliationTrigger.STARTUP == "startup"
        assert ReconciliationTrigger.RECONNECT == "reconnect"
        assert ReconciliationTrigger.SCHEDULED == "scheduled"
        assert ReconciliationTrigger.MANUAL == "manual"


# ------------------------------------------------------------------
# DiscrepancyType enum
# ------------------------------------------------------------------


class TestDiscrepancyType:
    """Verify discrepancy type enum has all 7 members."""

    def test_discrepancy_type_members(self) -> None:
        members = {m.value for m in DiscrepancyType}
        assert members == {
            "missing_order",
            "extra_order",
            "quantity_mismatch",
            "price_mismatch",
            "status_mismatch",
            "missing_position",
            "extra_position",
        }

    def test_discrepancy_type_count(self) -> None:
        assert len(DiscrepancyType) == 7


# ------------------------------------------------------------------
# Discrepancy model
# ------------------------------------------------------------------


class TestDiscrepancy:
    """Verify Discrepancy construction, frozen, serialization."""

    def test_construction_minimal(self) -> None:
        d = Discrepancy(
            discrepancy_type=DiscrepancyType.STATUS_MISMATCH,
            entity_type="order",
            entity_id="ord-001",
        )
        assert d.discrepancy_type == DiscrepancyType.STATUS_MISMATCH
        assert d.entity_type == "order"
        assert d.entity_id == "ord-001"
        assert d.symbol is None
        assert d.field is None
        assert d.internal_value is None
        assert d.broker_value is None
        assert d.auto_resolved is False
        assert d.resolution is None

    def test_construction_full(self) -> None:
        d = Discrepancy(
            discrepancy_type=DiscrepancyType.PRICE_MISMATCH,
            entity_type="order",
            entity_id="ord-002",
            symbol="AAPL",
            field="price",
            internal_value="150.00",
            broker_value="150.50",
            auto_resolved=True,
            resolution="Updated internal price",
        )
        assert d.symbol == "AAPL"
        assert d.field == "price"
        assert d.auto_resolved is True
        assert d.resolution == "Updated internal price"

    def test_frozen(self) -> None:
        d = Discrepancy(
            discrepancy_type=DiscrepancyType.MISSING_ORDER,
            entity_type="order",
            entity_id="ord-003",
        )
        with pytest.raises(Exception):
            d.entity_id = "changed"  # type: ignore[misc]

    def test_serialization_roundtrip(self) -> None:
        d = Discrepancy(
            discrepancy_type=DiscrepancyType.QUANTITY_MISMATCH,
            entity_type="order",
            entity_id="ord-004",
            symbol="MSFT",
            field="quantity",
            internal_value="100",
            broker_value="95",
        )
        data = d.model_dump()
        restored = Discrepancy.model_validate(data)
        assert restored == d


# ------------------------------------------------------------------
# ReconciliationReport model
# ------------------------------------------------------------------


class TestReconciliationReport:
    """Verify ReconciliationReport construction, defaults, frozen, serialization."""

    def _make_report(self, **overrides: object) -> ReconciliationReport:
        defaults = {
            "report_id": "01HRECON0001",
            "deployment_id": "01HDEPLOY0001",
            "trigger": ReconciliationTrigger.STARTUP,
        }
        defaults.update(overrides)
        return ReconciliationReport(**defaults)  # type: ignore[arg-type]

    def test_construction_defaults(self) -> None:
        r = self._make_report()
        assert r.report_id == "01HRECON0001"
        assert r.deployment_id == "01HDEPLOY0001"
        assert r.trigger == ReconciliationTrigger.STARTUP
        assert r.discrepancies == []
        assert r.resolved_count == 0
        assert r.unresolved_count == 0
        assert r.status == "completed"
        assert r.orders_checked == 0
        assert r.positions_checked == 0
        assert isinstance(r.created_at, datetime)

    def test_construction_with_discrepancies(self) -> None:
        disc = Discrepancy(
            discrepancy_type=DiscrepancyType.STATUS_MISMATCH,
            entity_type="order",
            entity_id="ord-001",
            field="status",
            internal_value="submitted",
            broker_value="filled",
            auto_resolved=True,
            resolution="Updated status",
        )
        r = self._make_report(
            discrepancies=[disc],
            resolved_count=1,
            unresolved_count=0,
            status="completed_with_discrepancies",
            orders_checked=10,
            positions_checked=5,
        )
        assert len(r.discrepancies) == 1
        assert r.resolved_count == 1
        assert r.orders_checked == 10
        assert r.positions_checked == 5

    def test_frozen(self) -> None:
        r = self._make_report()
        with pytest.raises(Exception):
            r.status = "changed"  # type: ignore[misc]

    def test_serialization_roundtrip(self) -> None:
        disc = Discrepancy(
            discrepancy_type=DiscrepancyType.EXTRA_ORDER,
            entity_type="order",
            entity_id="ord-005",
        )
        r = self._make_report(
            discrepancies=[disc],
            resolved_count=0,
            unresolved_count=1,
            status="completed_with_discrepancies",
        )
        data = r.model_dump()
        restored = ReconciliationReport.model_validate(data)
        assert restored.report_id == r.report_id
        assert len(restored.discrepancies) == 1

    def test_json_roundtrip(self) -> None:
        r = self._make_report(orders_checked=5, positions_checked=3)
        json_str = r.model_dump_json()
        restored = ReconciliationReport.model_validate_json(json_str)
        assert restored == r


# ------------------------------------------------------------------
# MockReconciliationRepository
# ------------------------------------------------------------------


class TestMockReconciliationRepository:
    """Verify mock repository implements interface correctly."""

    def _make_report(
        self, report_id: str = "01HRECON0001", deployment_id: str = "01HDEPLOY0001"
    ) -> ReconciliationReport:
        return ReconciliationReport(
            report_id=report_id,
            deployment_id=deployment_id,
            trigger=ReconciliationTrigger.MANUAL,
        )

    def test_save_and_get_by_id(self) -> None:
        repo = MockReconciliationRepository()
        report = self._make_report()
        repo.save(report)
        retrieved = repo.get_by_id("01HRECON0001")
        assert retrieved is not None
        assert retrieved.report_id == "01HRECON0001"

    def test_get_by_id_not_found(self) -> None:
        repo = MockReconciliationRepository()
        assert repo.get_by_id("nonexistent") is None

    def test_list_by_deployment(self) -> None:
        repo = MockReconciliationRepository()
        repo.save(self._make_report("r1", "dep1"))
        repo.save(self._make_report("r2", "dep1"))
        repo.save(self._make_report("r3", "dep2"))
        results = repo.list_by_deployment(deployment_id="dep1")
        assert len(results) == 2
        assert all(r.deployment_id == "dep1" for r in results)

    def test_list_by_deployment_limit(self) -> None:
        repo = MockReconciliationRepository()
        for i in range(5):
            repo.save(self._make_report(f"r{i}", "dep1"))
        results = repo.list_by_deployment(deployment_id="dep1", limit=3)
        assert len(results) == 3

    def test_count_and_clear(self) -> None:
        repo = MockReconciliationRepository()
        assert repo.count() == 0
        repo.save(self._make_report())
        assert repo.count() == 1
        repo.clear()
        assert repo.count() == 0

    def test_get_all(self) -> None:
        repo = MockReconciliationRepository()
        repo.save(self._make_report("r1"))
        repo.save(self._make_report("r2"))
        assert len(repo.get_all()) == 2
