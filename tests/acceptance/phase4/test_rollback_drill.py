"""
Acceptance test: Rollback drill executed and documented.

Spec gate 8: Rollback drills can be executed against deployments,
produce documented results, and gate live deployment eligibility.

Covers:
- Rollback drill can be executed against an active deployment.
- Drill result is recorded and retrievable.
- All 4 drill types can be executed.
- Live eligibility requires all drills to pass.
- Drill history provides audit trail.
"""

from __future__ import annotations

import pytest

from libs.contracts.drill import DrillType
from libs.contracts.mocks.mock_broker_adapter import MockBrokerAdapter
from libs.contracts.mocks.mock_deployment_repository import MockDeploymentRepository
from services.api.services.drill_service import DrillService

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

DEP_ID = "01HACC_ROLLBACK_001"
STRAT_ID = "01HACC_STRAT_RB_001"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def setup():
    dep_repo = MockDeploymentRepository()
    dep_repo.seed(
        deployment_id=DEP_ID,
        strategy_id=STRAT_ID,
        state="active",
        execution_mode="paper",
        emergency_posture="flatten_all",
    )
    adapter = MockBrokerAdapter(fill_mode="instant")
    service = DrillService(
        deployment_repo=dep_repo,
        adapter_registry={DEP_ID: adapter},
    )
    return service


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestRollbackDrill:
    """Spec gate 8: Rollback drill executed and documented."""

    def test_rollback_drill_executes(self, setup) -> None:
        """Rollback drill can be executed on an active deployment."""
        service = setup
        result = service.execute_drill(
            drill_type="rollback",
            deployment_id=DEP_ID,
        )
        assert result.drill_type == DrillType.ROLLBACK
        assert result.passed is True
        assert result.deployment_id == DEP_ID
        assert len(result.timeline) >= 1

    def test_drill_result_retrievable(self, setup) -> None:
        """Drill results are recorded and retrievable via history."""
        service = setup
        result = service.execute_drill(
            drill_type="rollback",
            deployment_id=DEP_ID,
        )

        history = service.get_drill_history(deployment_id=DEP_ID)
        assert len(history) == 1
        assert history[0].result_id == result.result_id

    def test_all_four_drill_types_executable(self, setup) -> None:
        """All 4 required drill types can be executed."""
        service = setup
        results = {}
        for drill_type in ["kill_switch", "rollback", "reconnect", "failover"]:
            result = service.execute_drill(
                drill_type=drill_type,
                deployment_id=DEP_ID,
            )
            results[drill_type] = result
            assert result.passed is True, f"Drill {drill_type} should pass"

        assert len(results) == 4

    def test_live_eligibility_after_all_drills(self, setup) -> None:
        """Live eligibility is granted after all 4 drills pass."""
        service = setup

        # Before drills: not eligible
        eligible, missing = service.check_live_eligibility(
            deployment_id=DEP_ID,
        )
        assert eligible is False
        assert len(missing) == 4

        # Run all drills
        for drill_type in ["kill_switch", "rollback", "reconnect", "failover"]:
            service.execute_drill(
                drill_type=drill_type,
                deployment_id=DEP_ID,
            )

        # After drills: eligible
        eligible, missing = service.check_live_eligibility(
            deployment_id=DEP_ID,
        )
        assert eligible is True
        assert len(missing) == 0

    def test_drill_audit_trail(self, setup) -> None:
        """Drill history provides complete audit trail."""
        service = setup
        for drill_type in ["kill_switch", "rollback", "reconnect", "failover"]:
            service.execute_drill(
                drill_type=drill_type,
                deployment_id=DEP_ID,
            )

        history = service.get_drill_history(deployment_id=DEP_ID)
        assert len(history) == 4

        # Verify all types are represented
        types = {r.drill_type for r in history}
        assert types == {
            DrillType.KILL_SWITCH,
            DrillType.ROLLBACK,
            DrillType.RECONNECT,
            DrillType.FAILOVER,
        }

        # Verify all have timestamps and IDs
        for result in history:
            assert result.result_id is not None
            assert result.executed_at is not None
            assert result.passed is True
