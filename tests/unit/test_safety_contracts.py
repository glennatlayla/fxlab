"""
Unit tests for safety control contract schemas.

Covers:
- Enum stability (KillSwitchScope, HaltTrigger).
- KillSwitchStatus construction, frozen, serialization.
- KillSwitchActivateRequest validation.
- HaltEvent construction, frozen, serialization.
- EmergencyPostureDecision construction, frozen, serialization.

Dependencies:
- libs.contracts.safety
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from libs.contracts.deployment import EmergencyPostureType
from libs.contracts.safety import (
    EmergencyPostureDecision,
    HaltEvent,
    HaltTrigger,
    KillSwitchActivateRequest,
    KillSwitchScope,
    KillSwitchStatus,
)

# ------------------------------------------------------------------
# KillSwitchScope enum
# ------------------------------------------------------------------


class TestKillSwitchScope:
    """Verify kill switch scope enum members."""

    def test_scope_members(self) -> None:
        members = {m.value for m in KillSwitchScope}
        assert members == {"global", "strategy", "symbol"}

    def test_scope_string_identity(self) -> None:
        assert KillSwitchScope.GLOBAL == "global"
        assert KillSwitchScope.STRATEGY == "strategy"
        assert KillSwitchScope.SYMBOL == "symbol"


# ------------------------------------------------------------------
# HaltTrigger enum
# ------------------------------------------------------------------


class TestHaltTrigger:
    """Verify halt trigger enum members."""

    def test_trigger_members(self) -> None:
        members = {m.value for m in HaltTrigger}
        assert members == {"kill_switch", "daily_loss", "regime", "data_state", "manual"}

    def test_trigger_count(self) -> None:
        assert len(HaltTrigger) == 5


# ------------------------------------------------------------------
# KillSwitchStatus
# ------------------------------------------------------------------


class TestKillSwitchStatus:
    """Verify KillSwitchStatus construction and behavior."""

    def test_construction_active(self) -> None:
        now = datetime.now(timezone.utc)
        status = KillSwitchStatus(
            scope=KillSwitchScope.GLOBAL,
            target_id="global",
            is_active=True,
            activated_at=now,
            activated_by="system:risk_gate",
            reason="Emergency halt",
        )
        assert status.is_active is True
        assert status.scope == KillSwitchScope.GLOBAL
        assert status.deactivated_at is None

    def test_construction_inactive(self) -> None:
        status = KillSwitchStatus(
            scope=KillSwitchScope.STRATEGY,
            target_id="01HSTRAT001",
            is_active=False,
        )
        assert status.is_active is False
        assert status.activated_at is None

    def test_frozen(self) -> None:
        status = KillSwitchStatus(
            scope=KillSwitchScope.GLOBAL,
            target_id="global",
            is_active=True,
        )
        with pytest.raises(Exception):
            status.is_active = False  # type: ignore[misc]

    def test_serialization_roundtrip(self) -> None:
        status = KillSwitchStatus(
            scope=KillSwitchScope.SYMBOL,
            target_id="AAPL",
            is_active=True,
            activated_at=datetime.now(timezone.utc),
            activated_by="user:admin",
            reason="Halted for volatility",
        )
        data = status.model_dump()
        restored = KillSwitchStatus.model_validate(data)
        assert restored == status


# ------------------------------------------------------------------
# KillSwitchActivateRequest
# ------------------------------------------------------------------


class TestKillSwitchActivateRequest:
    """Verify activation request validation."""

    def test_valid_request(self) -> None:
        req = KillSwitchActivateRequest(
            scope=KillSwitchScope.GLOBAL,
            target_id="global",
            reason="Daily loss breach",
            activated_by="system:risk_gate",
        )
        assert req.scope == KillSwitchScope.GLOBAL
        assert req.target_id == "global"

    def test_empty_reason_rejected(self) -> None:
        with pytest.raises(Exception):
            KillSwitchActivateRequest(
                scope=KillSwitchScope.GLOBAL,
                target_id="global",
                reason="",
                activated_by="system",
            )

    def test_frozen(self) -> None:
        req = KillSwitchActivateRequest(
            scope=KillSwitchScope.GLOBAL,
            target_id="global",
            reason="Test",
            activated_by="system",
        )
        with pytest.raises(Exception):
            req.reason = "changed"  # type: ignore[misc]


# ------------------------------------------------------------------
# HaltEvent
# ------------------------------------------------------------------


class TestHaltEvent:
    """Verify HaltEvent construction and behavior."""

    def test_construction_defaults(self) -> None:
        event = HaltEvent(
            event_id="01HHALT001",
            scope=KillSwitchScope.GLOBAL,
            target_id="global",
            trigger=HaltTrigger.KILL_SWITCH,
            reason="Emergency halt",
            activated_by="system:risk_gate",
        )
        assert event.event_id == "01HHALT001"
        assert event.confirmed_at is None
        assert event.mtth_ms is None
        assert event.orders_cancelled == 0
        assert event.positions_flattened == 0

    def test_construction_with_mtth(self) -> None:
        now = datetime.now(timezone.utc)
        event = HaltEvent(
            event_id="01HHALT002",
            scope=KillSwitchScope.STRATEGY,
            target_id="01HSTRAT001",
            trigger=HaltTrigger.DAILY_LOSS,
            reason="Daily loss $5000 breached",
            activated_by="system:risk_gate",
            activated_at=now,
            confirmed_at=now,
            mtth_ms=250,
            orders_cancelled=5,
            positions_flattened=2,
        )
        assert event.mtth_ms == 250
        assert event.orders_cancelled == 5

    def test_frozen(self) -> None:
        event = HaltEvent(
            event_id="01HHALT003",
            scope=KillSwitchScope.GLOBAL,
            target_id="global",
            trigger=HaltTrigger.MANUAL,
            reason="Manual halt",
            activated_by="user:admin",
        )
        with pytest.raises(Exception):
            event.mtth_ms = 100  # type: ignore[misc]

    def test_serialization_roundtrip(self) -> None:
        event = HaltEvent(
            event_id="01HHALT004",
            scope=KillSwitchScope.SYMBOL,
            target_id="AAPL",
            trigger=HaltTrigger.DATA_STATE,
            reason="Feed degraded",
            activated_by="system:feed_health",
            mtth_ms=50,
        )
        data = event.model_dump()
        restored = HaltEvent.model_validate(data)
        assert restored.event_id == event.event_id
        assert restored.mtth_ms == 50


# ------------------------------------------------------------------
# EmergencyPostureDecision
# ------------------------------------------------------------------


class TestEmergencyPostureDecision:
    """Verify EmergencyPostureDecision construction and behavior."""

    def test_construction_flatten(self) -> None:
        decision = EmergencyPostureDecision(
            decision_id="01HEPDEC001",
            deployment_id="01HDEPLOY001",
            posture=EmergencyPostureType.flatten_all,
            trigger=HaltTrigger.KILL_SWITCH,
            reason="Global kill switch",
            orders_cancelled=3,
            positions_flattened=2,
            duration_ms=150,
        )
        assert decision.posture == EmergencyPostureType.flatten_all
        assert decision.orders_cancelled == 3
        assert decision.positions_flattened == 2
        assert decision.duration_ms == 150

    def test_construction_hold(self) -> None:
        decision = EmergencyPostureDecision(
            decision_id="01HEPDEC002",
            deployment_id="01HDEPLOY001",
            posture=EmergencyPostureType.hold,
            trigger=HaltTrigger.MANUAL,
        )
        assert decision.orders_cancelled == 0
        assert decision.positions_flattened == 0

    def test_frozen(self) -> None:
        decision = EmergencyPostureDecision(
            decision_id="01HEPDEC003",
            deployment_id="01HDEPLOY001",
            posture=EmergencyPostureType.cancel_open,
            trigger=HaltTrigger.REGIME,
        )
        with pytest.raises(Exception):
            decision.orders_cancelled = 10  # type: ignore[misc]

    def test_serialization_roundtrip(self) -> None:
        decision = EmergencyPostureDecision(
            decision_id="01HEPDEC004",
            deployment_id="01HDEPLOY001",
            posture=EmergencyPostureType.flatten_all,
            trigger=HaltTrigger.DAILY_LOSS,
            orders_cancelled=5,
            positions_flattened=3,
            duration_ms=200,
        )
        data = decision.model_dump()
        restored = EmergencyPostureDecision.model_validate(data)
        assert restored == decision
