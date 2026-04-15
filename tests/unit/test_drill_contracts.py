"""
Unit tests for drill execution contract schemas.

Covers:
- DrillType enum stability.
- DrillResult construction, frozen, serialization.
- DrillRequirement construction, frozen, serialization.
- LIVE_ELIGIBILITY_REQUIREMENTS completeness.

Dependencies:
- libs.contracts.drill
"""

from __future__ import annotations

from datetime import datetime

import pytest

from libs.contracts.drill import (
    LIVE_ELIGIBILITY_REQUIREMENTS,
    DrillRequirement,
    DrillResult,
    DrillType,
)


class TestDrillType:
    """Verify drill type enum."""

    def test_members(self) -> None:
        members = {m.value for m in DrillType}
        assert members == {"kill_switch", "rollback", "reconnect", "failover"}

    def test_count(self) -> None:
        assert len(DrillType) == 4


class TestDrillResult:
    """Verify DrillResult construction and behavior."""

    def test_construction_minimal(self) -> None:
        r = DrillResult(
            result_id="01HDRILL001",
            deployment_id="01HDEPLOY001",
            drill_type=DrillType.KILL_SWITCH,
            passed=True,
        )
        assert r.result_id == "01HDRILL001"
        assert r.drill_type == DrillType.KILL_SWITCH
        assert r.passed is True
        assert r.mtth_ms is None
        assert r.timeline == []
        assert r.discrepancies == []
        assert r.duration_ms == 0
        assert isinstance(r.executed_at, datetime)

    def test_construction_full(self) -> None:
        r = DrillResult(
            result_id="01HDRILL002",
            deployment_id="01HDEPLOY001",
            drill_type=DrillType.ROLLBACK,
            passed=False,
            mtth_ms=250,
            timeline=["step1", "step2", "failed"],
            discrepancies=["position mismatch"],
            details={"error": "timeout"},
            duration_ms=1500,
        )
        assert r.passed is False
        assert r.mtth_ms == 250
        assert len(r.timeline) == 3
        assert len(r.discrepancies) == 1

    def test_frozen(self) -> None:
        r = DrillResult(
            result_id="01HDRILL003",
            deployment_id="01HDEPLOY001",
            drill_type=DrillType.RECONNECT,
            passed=True,
        )
        with pytest.raises(Exception):
            r.passed = False  # type: ignore[misc]

    def test_serialization_roundtrip(self) -> None:
        r = DrillResult(
            result_id="01HDRILL004",
            deployment_id="01HDEPLOY001",
            drill_type=DrillType.FAILOVER,
            passed=True,
            mtth_ms=100,
            timeline=["disconnect", "reconnect", "reconcile"],
        )
        data = r.model_dump()
        restored = DrillResult.model_validate(data)
        assert restored.result_id == r.result_id
        assert restored.drill_type == r.drill_type
        assert restored.mtth_ms == 100


class TestDrillRequirement:
    """Verify DrillRequirement construction and behavior."""

    def test_construction(self) -> None:
        req = DrillRequirement(
            drill_type=DrillType.KILL_SWITCH,
            description="Kill switch drill",
            required=True,
        )
        assert req.drill_type == DrillType.KILL_SWITCH
        assert req.required is True

    def test_defaults(self) -> None:
        req = DrillRequirement(drill_type=DrillType.ROLLBACK)
        assert req.description == ""
        assert req.required is True

    def test_frozen(self) -> None:
        req = DrillRequirement(drill_type=DrillType.RECONNECT)
        with pytest.raises(Exception):
            req.required = False  # type: ignore[misc]

    def test_serialization_roundtrip(self) -> None:
        req = DrillRequirement(
            drill_type=DrillType.FAILOVER,
            description="Failover test",
        )
        data = req.model_dump()
        restored = DrillRequirement.model_validate(data)
        assert restored.drill_type == req.drill_type


class TestLiveEligibilityRequirements:
    """Verify LIVE_ELIGIBILITY_REQUIREMENTS completeness."""

    def test_covers_all_drill_types(self) -> None:
        """Every drill type must be represented in eligibility requirements."""
        required_types = {r.drill_type for r in LIVE_ELIGIBILITY_REQUIREMENTS}
        all_types = set(DrillType)
        assert required_types == all_types

    def test_all_required(self) -> None:
        """All standard requirements are mandatory."""
        assert all(r.required for r in LIVE_ELIGIBILITY_REQUIREMENTS)

    def test_count(self) -> None:
        assert len(LIVE_ELIGIBILITY_REQUIREMENTS) == 4
