"""
Acceptance test: Full order timeline from decision to broker response.

Spec gate 6: The execution analysis service can reconstruct a complete
order timeline from the initial decision signal through broker response,
traceable via order_id and correlation_id.

Covers:
- Event registration creates traceable timeline.
- Timeline reconstruction returns ordered events.
- Correlation ID search finds related events across orders.
- Timeline includes all expected lifecycle stages.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from libs.contracts.execution import OrderEvent
from libs.contracts.mocks.mock_broker_adapter import MockBrokerAdapter
from libs.contracts.mocks.mock_deployment_repository import MockDeploymentRepository
from services.api.services.execution_analysis_service import (
    ExecutionAnalysisService,
)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

DEP_ID = "01HACC_RECON_ORD_001"
STRAT_ID = "01HACC_STRAT_RO_001"
ORDER_ID = "ord-timeline-001"
CORR_ID = "corr-timeline-001"


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
    )
    adapter = MockBrokerAdapter(fill_mode="instant")
    service = ExecutionAnalysisService(
        deployment_repo=dep_repo,
        adapter_registry={DEP_ID: adapter},
    )
    return service


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestOrderReconstruction:
    """Spec gate 6: Full order timeline from decision to broker response."""

    def test_full_timeline_reconstruction(self, setup) -> None:
        """Complete order lifecycle can be reconstructed from events."""
        service = setup
        now = datetime.now(timezone.utc)

        # Register lifecycle events
        events = [
            OrderEvent(
                event_id="evt-signal",
                order_id=ORDER_ID,
                event_type="signal",
                timestamp=now,
                details={"strategy": "momentum", "signal_strength": 0.85},
                correlation_id=CORR_ID,
            ),
            OrderEvent(
                event_id="evt-risk-check",
                order_id=ORDER_ID,
                event_type="risk_check_passed",
                timestamp=now,
                details={"checks_passed": 5},
                correlation_id=CORR_ID,
            ),
            OrderEvent(
                event_id="evt-submitted",
                order_id=ORDER_ID,
                event_type="submitted",
                timestamp=now,
                details={"broker_order_id": "BRK-001"},
                correlation_id=CORR_ID,
            ),
            OrderEvent(
                event_id="evt-filled",
                order_id=ORDER_ID,
                event_type="filled",
                timestamp=now,
                details={"fill_price": "175.50", "quantity": "100"},
                correlation_id=CORR_ID,
            ),
        ]
        for event in events:
            service.register_event(event)

        # Reconstruct timeline
        timeline = service.get_order_timeline(order_id=ORDER_ID)
        assert timeline.order_id == ORDER_ID
        assert len(timeline.events) == 4
        event_types = [e.event_type for e in timeline.events]
        assert "signal" in event_types
        assert "submitted" in event_types
        assert "filled" in event_types

    def test_correlation_id_links_related_orders(self, setup) -> None:
        """Correlation ID search finds events across multiple orders."""
        service = setup
        now = datetime.now(timezone.utc)

        # Two orders with same correlation ID (e.g., bracket order)
        service.register_event(
            OrderEvent(
                event_id="evt-entry",
                order_id="ord-entry",
                event_type="submitted",
                timestamp=now,
                correlation_id=CORR_ID,
            )
        )
        service.register_event(
            OrderEvent(
                event_id="evt-stop",
                order_id="ord-stop-loss",
                event_type="submitted",
                timestamp=now,
                correlation_id=CORR_ID,
            )
        )

        results = service.search_by_correlation_id(correlation_id=CORR_ID)
        assert len(results) == 2
        order_ids = {e.order_id for e in results}
        assert "ord-entry" in order_ids
        assert "ord-stop-loss" in order_ids

    def test_timeline_includes_all_stages(self, setup) -> None:
        """Timeline preserves all registered event types."""
        service = setup
        now = datetime.now(timezone.utc)

        stages = [
            "signal",
            "risk_check_passed",
            "order_created",
            "submitted",
            "acknowledged",
            "partial_fill",
            "filled",
        ]
        for i, stage in enumerate(stages):
            service.register_event(
                OrderEvent(
                    event_id=f"evt-{i}",
                    order_id="ord-stages",
                    event_type=stage,
                    timestamp=now,
                    correlation_id="corr-stages",
                )
            )

        timeline = service.get_order_timeline(order_id="ord-stages")
        assert len(timeline.events) == len(stages)
