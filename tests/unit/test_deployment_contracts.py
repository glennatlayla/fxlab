"""
Unit tests for deployment Pydantic schemas, state machine transitions, and error types.

Covers:
- DeploymentState enum completeness (10 states)
- EmergencyPostureType enum completeness (4 postures)
- DEPLOYMENT_TRANSITIONS map exhaustiveness (every state has an entry)
- is_valid_transition() for all valid and invalid transitions
- Terminal states have no outbound transitions
- DeploymentCreateRequest validation (execution_mode, emergency_posture, custom config)
- RiskLimits defaults and constraints
- DeploymentTransitionRecord immutability
- DeploymentHealthResponse defaults
- StateTransitionError carries current_state and attempted_state
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from libs.contracts.deployment import (
    DEPLOYMENT_TRANSITIONS,
    DeploymentCreateRequest,
    DeploymentHealthResponse,
    DeploymentState,
    DeploymentTransitionRecord,
    EmergencyPostureType,
    RiskLimits,
    is_valid_transition,
)
from libs.contracts.errors import StateTransitionError

# ---------------------------------------------------------------------------
# Enum stability
# ---------------------------------------------------------------------------


class TestDeploymentStateEnum:
    """Verify DeploymentState enum has exactly 10 members matching spec."""

    def test_state_count(self) -> None:
        assert len(DeploymentState) == 10

    def test_expected_states(self) -> None:
        expected = {
            "created",
            "pending_approval",
            "approved",
            "activating",
            "active",
            "frozen",
            "deactivating",
            "deactivated",
            "rolled_back",
            "failed",
        }
        actual = {s.value for s in DeploymentState}
        assert actual == expected

    def test_string_enum(self) -> None:
        """Each member is a string for DB compatibility."""
        for member in DeploymentState:
            assert isinstance(member.value, str)


class TestEmergencyPostureTypeEnum:
    """Verify EmergencyPostureType enum completeness."""

    def test_posture_count(self) -> None:
        assert len(EmergencyPostureType) == 4

    def test_expected_postures(self) -> None:
        expected = {"flatten_all", "cancel_open", "hold", "custom"}
        actual = {p.value for p in EmergencyPostureType}
        assert actual == expected


# ---------------------------------------------------------------------------
# State machine transition map
# ---------------------------------------------------------------------------


class TestDeploymentTransitions:
    """Verify the DEPLOYMENT_TRANSITIONS map is exhaustive and correct."""

    def test_every_state_has_transition_entry(self) -> None:
        """Every DeploymentState must be a key in the transitions map."""
        for state in DeploymentState:
            assert state in DEPLOYMENT_TRANSITIONS, f"Missing transition entry for {state}"

    def test_terminal_states_have_no_outbound(self) -> None:
        terminal = {
            DeploymentState.deactivated,
            DeploymentState.rolled_back,
            DeploymentState.failed,
        }
        for state in terminal:
            assert len(DEPLOYMENT_TRANSITIONS[state]) == 0, f"{state} should be terminal"

    def test_created_transitions(self) -> None:
        assert DEPLOYMENT_TRANSITIONS[DeploymentState.created] == frozenset(
            {DeploymentState.pending_approval, DeploymentState.failed}
        )

    def test_pending_approval_transitions(self) -> None:
        assert DEPLOYMENT_TRANSITIONS[DeploymentState.pending_approval] == frozenset(
            {DeploymentState.approved, DeploymentState.failed}
        )

    def test_approved_transitions(self) -> None:
        assert DEPLOYMENT_TRANSITIONS[DeploymentState.approved] == frozenset(
            {DeploymentState.activating, DeploymentState.failed}
        )

    def test_activating_transitions(self) -> None:
        assert DEPLOYMENT_TRANSITIONS[DeploymentState.activating] == frozenset(
            {DeploymentState.active, DeploymentState.failed}
        )

    def test_active_transitions(self) -> None:
        expected = frozenset(
            {
                DeploymentState.frozen,
                DeploymentState.deactivating,
                DeploymentState.rolled_back,
                DeploymentState.failed,
            }
        )
        assert DEPLOYMENT_TRANSITIONS[DeploymentState.active] == expected

    def test_frozen_transitions(self) -> None:
        expected = frozenset(
            {
                DeploymentState.active,
                DeploymentState.deactivating,
                DeploymentState.rolled_back,
                DeploymentState.failed,
            }
        )
        assert DEPLOYMENT_TRANSITIONS[DeploymentState.frozen] == expected

    def test_deactivating_transitions(self) -> None:
        assert DEPLOYMENT_TRANSITIONS[DeploymentState.deactivating] == frozenset(
            {DeploymentState.deactivated, DeploymentState.failed}
        )


class TestIsValidTransition:
    """Verify is_valid_transition() function."""

    def test_valid_forward_transition(self) -> None:
        assert (
            is_valid_transition(DeploymentState.created, DeploymentState.pending_approval) is True
        )

    def test_valid_freeze(self) -> None:
        assert is_valid_transition(DeploymentState.active, DeploymentState.frozen) is True

    def test_valid_unfreeze(self) -> None:
        assert is_valid_transition(DeploymentState.frozen, DeploymentState.active) is True

    def test_invalid_backward_transition(self) -> None:
        assert is_valid_transition(DeploymentState.active, DeploymentState.created) is False

    def test_invalid_terminal_to_active(self) -> None:
        assert is_valid_transition(DeploymentState.deactivated, DeploymentState.active) is False

    def test_invalid_same_state(self) -> None:
        assert is_valid_transition(DeploymentState.active, DeploymentState.active) is False

    def test_rollback_from_active(self) -> None:
        assert is_valid_transition(DeploymentState.active, DeploymentState.rolled_back) is True

    def test_rollback_from_frozen(self) -> None:
        assert is_valid_transition(DeploymentState.frozen, DeploymentState.rolled_back) is True

    def test_rollback_from_created_invalid(self) -> None:
        assert is_valid_transition(DeploymentState.created, DeploymentState.rolled_back) is False


# ---------------------------------------------------------------------------
# DeploymentCreateRequest validation
# ---------------------------------------------------------------------------


class TestDeploymentCreateRequest:
    """Validate DeploymentCreateRequest Pydantic schema."""

    def test_valid_paper_deployment(self) -> None:
        req = DeploymentCreateRequest(
            strategy_id="01HTESTSTRT000000000000001",
            execution_mode="paper",
            emergency_posture="flatten_all",
        )
        assert req.execution_mode == "paper"
        assert req.emergency_posture == "flatten_all"
        assert req.risk_limits.max_order_rate_per_minute == 60

    def test_valid_live_deployment(self) -> None:
        req = DeploymentCreateRequest(
            strategy_id="01HTESTSTRT000000000000001",
            execution_mode="live",
            emergency_posture="cancel_open",
            risk_limits=RiskLimits(max_position_size="50000", max_daily_loss="10000"),
        )
        assert req.risk_limits.max_position_size == "50000"

    def test_valid_shadow_deployment(self) -> None:
        req = DeploymentCreateRequest(
            strategy_id="01HTESTSTRT000000000000001",
            execution_mode="shadow",
            emergency_posture="hold",
        )
        assert req.execution_mode == "shadow"

    def test_custom_posture_requires_config(self) -> None:
        with pytest.raises(ValidationError, match="custom_posture_config is required"):
            DeploymentCreateRequest(
                strategy_id="01HTESTSTRT000000000000001",
                execution_mode="paper",
                emergency_posture="custom",
            )

    def test_custom_posture_with_config_valid(self) -> None:
        req = DeploymentCreateRequest(
            strategy_id="01HTESTSTRT000000000000001",
            execution_mode="paper",
            emergency_posture="custom",
            custom_posture_config={"action": "hedge_with_puts"},
        )
        assert req.custom_posture_config == {"action": "hedge_with_puts"}

    def test_invalid_execution_mode(self) -> None:
        with pytest.raises(ValidationError, match="execution_mode must be one of"):
            DeploymentCreateRequest(
                strategy_id="01HTESTSTRT000000000000001",
                execution_mode="turbo",
                emergency_posture="flatten_all",
            )

    def test_invalid_emergency_posture(self) -> None:
        with pytest.raises(ValidationError, match="emergency_posture must be one of"):
            DeploymentCreateRequest(
                strategy_id="01HTESTSTRT000000000000001",
                execution_mode="paper",
                emergency_posture="yolo",
            )

    def test_strategy_id_too_short(self) -> None:
        with pytest.raises(ValidationError):
            DeploymentCreateRequest(
                strategy_id="tooshort",
                execution_mode="paper",
                emergency_posture="flatten_all",
            )

    def test_frozen_model(self) -> None:
        req = DeploymentCreateRequest(
            strategy_id="01HTESTSTRT000000000000001",
            execution_mode="paper",
            emergency_posture="flatten_all",
        )
        with pytest.raises(ValidationError):
            req.execution_mode = "live"  # type: ignore[misc]


# ---------------------------------------------------------------------------
# RiskLimits
# ---------------------------------------------------------------------------


class TestRiskLimits:
    """Verify RiskLimits defaults and constraints."""

    def test_defaults(self) -> None:
        limits = RiskLimits()
        assert limits.max_position_size == "0"
        assert limits.max_daily_loss == "0"
        assert limits.max_order_rate_per_minute == 60
        assert limits.max_notional_per_order == "0"

    def test_custom_values(self) -> None:
        limits = RiskLimits(
            max_position_size="100000",
            max_daily_loss="50000",
            max_order_rate_per_minute=120,
            max_notional_per_order="25000",
        )
        assert limits.max_position_size == "100000"
        assert limits.max_order_rate_per_minute == 120

    def test_order_rate_min_bound(self) -> None:
        with pytest.raises(ValidationError):
            RiskLimits(max_order_rate_per_minute=0)

    def test_order_rate_max_bound(self) -> None:
        with pytest.raises(ValidationError):
            RiskLimits(max_order_rate_per_minute=10001)


# ---------------------------------------------------------------------------
# DeploymentTransitionRecord
# ---------------------------------------------------------------------------


class TestDeploymentTransitionRecord:
    """Verify DeploymentTransitionRecord is immutable."""

    def test_create_record(self) -> None:
        record = DeploymentTransitionRecord(
            from_state="approved",
            to_state="activating",
            actor="user:01HUSER...",
            reason="Activation initiated",
            timestamp="2026-04-11T10:00:00Z",
        )
        assert record.from_state == "approved"
        assert record.to_state == "activating"

    def test_frozen(self) -> None:
        record = DeploymentTransitionRecord(
            from_state="active",
            to_state="frozen",
            actor="system",
            reason="Kill switch triggered",
            timestamp="2026-04-11T10:00:00Z",
        )
        with pytest.raises(ValidationError):
            record.reason = "changed"  # type: ignore[misc]


# ---------------------------------------------------------------------------
# DeploymentHealthResponse
# ---------------------------------------------------------------------------


class TestDeploymentHealthResponse:
    """Verify DeploymentHealthResponse defaults."""

    def test_defaults(self) -> None:
        health = DeploymentHealthResponse(
            deployment_id="01HDEPLOY...",
            state="active",
            execution_mode="paper",
            emergency_posture="flatten_all",
        )
        assert health.open_order_count == 0
        assert health.position_count == 0
        assert health.total_unrealized_pnl == "0"
        assert health.adapter_connected is False
        assert health.last_heartbeat_at is None


# ---------------------------------------------------------------------------
# StateTransitionError
# ---------------------------------------------------------------------------


class TestStateTransitionError:
    """Verify StateTransitionError carries state context."""

    def test_error_message(self) -> None:
        err = StateTransitionError(
            "Cannot transition from active to created",
            current_state="active",
            attempted_state="created",
        )
        assert "active" in str(err)
        assert err.current_state == "active"
        assert err.attempted_state == "created"

    def test_inherits_fxlab_error(self) -> None:
        from libs.contracts.errors import FXLabError

        err = StateTransitionError("test")
        assert isinstance(err, FXLabError)
