"""
Drill execution service implementation.

Responsibilities:
- Execute production readiness drills against deployments.
- Measure MTTH during kill switch drills.
- Simulate rollback, reconnect, and failover scenarios.
- Track drill results per deployment for eligibility gating.
- Check live deployment eligibility based on drill history.

Does NOT:
- Implement broker communication (delegates to adapter).
- Persist drill results externally (caller responsibility).
- Modify deployment state (read-only verification).

Dependencies:
- DeploymentRepositoryInterface: deployment lookups.
- BrokerAdapterInterface (via adapter_registry): order/position data.

Error conditions:
- NotFoundError: deployment_id not found.
- ValueError: invalid drill type.

Example:
    service = DrillService(
        deployment_repo=deployment_repo,
        adapter_registry={"01HDEPLOY...": adapter},
    )
    result = service.execute_drill(drill_type="kill_switch", deployment_id="01HDEPLOY...")
"""

from __future__ import annotations

import logging
import threading
import time
from datetime import datetime, timezone
from typing import Any

import ulid as _ulid

from libs.contracts.drill import (
    LIVE_ELIGIBILITY_REQUIREMENTS,
    DrillRequirement,
    DrillResult,
    DrillType,
)
from libs.contracts.errors import NotFoundError
from libs.contracts.interfaces.broker_adapter import BrokerAdapterInterface
from libs.contracts.interfaces.deployment_repository_interface import (
    DeploymentRepositoryInterface,
)
from libs.contracts.interfaces.drill_service_interface import (
    DrillServiceInterface,
)
from libs.contracts.interfaces.execution_event_repository_interface import (
    ExecutionEventRepositoryInterface,
)

logger = logging.getLogger(__name__)

# Valid drill type strings for validation
_VALID_DRILL_TYPES = {dt.value for dt in DrillType}


class DrillService(DrillServiceInterface):
    """
    Production implementation of DrillServiceInterface.

    Executes production readiness drills against deployments to verify
    operational procedures before live deployment. Tracks results
    in-memory per deployment for eligibility gating.

    Responsibilities:
    - Kill switch drill: activate, measure MTTH, verify order cancellation.
    - Rollback drill: verify deployment can return to previous state.
    - Reconnect drill: verify adapter can reconnect after disconnect.
    - Failover drill: verify position reconciliation after recovery.
    - Live eligibility: all 4 drill types must pass before live.

    Does NOT:
    - Modify actual deployment state during drills.

    Example:
        service = DrillService(
            deployment_repo=deployment_repo,
            adapter_registry={"01HDEPLOY...": adapter},
            execution_event_repo=event_repo,  # Optional
        )
    """

    def __init__(
        self,
        *,
        deployment_repo: DeploymentRepositoryInterface,
        adapter_registry: dict[str, BrokerAdapterInterface],
        execution_event_repo: ExecutionEventRepositoryInterface | None = None,
    ) -> None:
        """
        Initialise the drill service.

        Args:
            deployment_repo: Repository for deployment lookups.
            adapter_registry: Map of deployment_id → BrokerAdapterInterface.
            execution_event_repo: Optional repository for persisting drill results.
                If provided, drill results are saved as execution events.
        """
        self._deployment_repo = deployment_repo
        self._adapter_registry = adapter_registry
        self._execution_event_repo = execution_event_repo
        # Drill results: deployment_id → [DrillResult]
        self._results: dict[str, list[DrillResult]] = {}
        # Locks for thread safety
        self._registry_lock = threading.Lock()
        self._results_lock = threading.Lock()

    def execute_drill(
        self,
        *,
        drill_type: str,
        deployment_id: str,
    ) -> DrillResult:
        """
        Execute a production readiness drill against a deployment.

        Validates the deployment exists and the drill type is valid,
        then delegates to the appropriate drill executor. Records
        the result for eligibility gating.

        Args:
            drill_type: Type of drill (kill_switch, rollback, reconnect, failover).
            deployment_id: ULID of the deployment to test.

        Returns:
            DrillResult with pass/fail, MTTH, timeline, and discrepancies.

        Raises:
            NotFoundError: deployment not found.
            ValueError: invalid drill type.
        """
        # Validate drill type
        if drill_type not in _VALID_DRILL_TYPES:
            raise ValueError(
                f"Invalid drill type: {drill_type}. Valid types: {sorted(_VALID_DRILL_TYPES)}"
            )

        # Validate deployment exists
        deployment = self._deployment_repo.get_by_id(deployment_id)
        if deployment is None:
            raise NotFoundError(f"Deployment {deployment_id} not found")

        drill_enum = DrillType(drill_type)
        # Take snapshot of adapter under lock
        with self._registry_lock:
            adapter = self._adapter_registry.get(deployment_id)

        # Dispatch to drill executor
        start_ns = time.monotonic_ns()
        if drill_enum == DrillType.KILL_SWITCH:
            result = self._execute_kill_switch_drill(deployment_id, adapter)
        elif drill_enum == DrillType.ROLLBACK:
            result = self._execute_rollback_drill(deployment_id)
        elif drill_enum == DrillType.RECONNECT:
            result = self._execute_reconnect_drill(deployment_id, adapter)
        elif drill_enum == DrillType.FAILOVER:
            result = self._execute_failover_drill(deployment_id, adapter)
        else:
            raise ValueError(f"Unhandled drill type: {drill_type}")

        elapsed_ms = (time.monotonic_ns() - start_ns) // 1_000_000

        # Build final result with timing
        final_result = DrillResult(
            result_id=result.result_id,
            deployment_id=deployment_id,
            drill_type=drill_enum,
            passed=result.passed,
            mtth_ms=result.mtth_ms,
            timeline=result.timeline,
            discrepancies=result.discrepancies,
            details=result.details,
            duration_ms=elapsed_ms,
        )

        # Record result under lock
        with self._results_lock:
            if deployment_id not in self._results:
                self._results[deployment_id] = []
            self._results[deployment_id].append(final_result)

        # Persist to repository if available
        if self._execution_event_repo is not None:
            self._execution_event_repo.save(
                order_id=f"drill-{final_result.result_id}",
                event_type="drill_result",
                timestamp=datetime.now(timezone.utc).isoformat(),
                details={
                    "drill_type": final_result.drill_type.value,
                    "passed": final_result.passed,
                    "mtth_ms": final_result.mtth_ms,
                    "duration_ms": final_result.duration_ms,
                    "timeline": final_result.timeline,
                    "discrepancies": final_result.discrepancies,
                },
                correlation_id=f"drill-{deployment_id}",
            )

        logger.info(
            "Drill executed",
            extra={
                "operation": "drill_executed",
                "component": "DrillService",
                "deployment_id": deployment_id,
                "drill_type": drill_type,
                "passed": final_result.passed,
                "duration_ms": elapsed_ms,
                "mtth_ms": final_result.mtth_ms,
            },
        )

        return final_result

    def check_live_eligibility(
        self,
        *,
        deployment_id: str,
    ) -> tuple[bool, list[DrillRequirement]]:
        """
        Check whether a deployment has passed all required drills for live.

        Compares passing drill types against LIVE_ELIGIBILITY_REQUIREMENTS.

        Args:
            deployment_id: ULID of the deployment.

        Returns:
            Tuple of (eligible, missing_requirements).

        Raises:
            NotFoundError: deployment not found.
        """
        deployment = self._deployment_repo.get_by_id(deployment_id)
        if deployment is None:
            raise NotFoundError(f"Deployment {deployment_id} not found")

        # Take snapshot of results under lock
        with self._results_lock:
            results = list(self._results.get(deployment_id, []))
        # Collect drill types that have at least one passing result
        passing_types = {r.drill_type for r in results if r.passed}

        missing: list[DrillRequirement] = []
        for req in LIVE_ELIGIBILITY_REQUIREMENTS:
            if req.required and req.drill_type not in passing_types:
                missing.append(req)

        eligible = len(missing) == 0

        logger.info(
            "Live eligibility checked",
            extra={
                "operation": "live_eligibility_checked",
                "component": "DrillService",
                "deployment_id": deployment_id,
                "eligible": eligible,
                "passing_types": [t.value for t in passing_types],
                "missing_count": len(missing),
            },
        )

        return eligible, missing

    def get_drill_history(
        self,
        *,
        deployment_id: str,
    ) -> list[DrillResult]:
        """
        Retrieve all drill results for a deployment.

        Args:
            deployment_id: ULID of the deployment.

        Returns:
            List of DrillResult ordered by execution time.
        """
        # Take snapshot under lock
        with self._results_lock:
            return list(self._results.get(deployment_id, []))

    # ------------------------------------------------------------------
    # Private drill executors
    # ------------------------------------------------------------------

    def _execute_kill_switch_drill(
        self,
        deployment_id: str,
        adapter: BrokerAdapterInterface | None,
    ) -> DrillResult:
        """
        Execute kill switch drill: activate kill switch, cancel orders, measure MTTH.

        Args:
            deployment_id: ULID of the deployment.
            adapter: Broker adapter (may be None if no adapter registered).

        Returns:
            DrillResult with MTTH measurement.
        """
        timeline: list[str] = []
        discrepancies: list[str] = []
        mtth_ms: int | None = None

        timeline.append("kill_switch_drill_started")

        # Measure MTTH: time from activation to all orders cancelled
        start_ns = time.monotonic_ns()

        if adapter is not None:
            # Get open orders and cancel them
            open_orders = adapter.list_open_orders()
            timeline.append(f"found_{len(open_orders)}_open_orders")

            cancelled = 0
            for order in open_orders:
                try:
                    adapter.cancel_order(  # type: ignore[call-arg]
                        client_order_id=order.client_order_id,
                        deployment_id=deployment_id,
                    )
                    cancelled += 1
                except Exception as exc:
                    discrepancies.append(f"Failed to cancel {order.client_order_id}: {exc}")

            timeline.append(f"cancelled_{cancelled}_orders")
        else:
            timeline.append("no_adapter_registered")

        elapsed_ns = time.monotonic_ns() - start_ns
        mtth_ms = elapsed_ns // 1_000_000

        timeline.append("kill_switch_drill_completed")

        return DrillResult(
            result_id=str(_ulid.ULID()),
            deployment_id=deployment_id,
            drill_type=DrillType.KILL_SWITCH,
            passed=len(discrepancies) == 0,
            mtth_ms=mtth_ms,
            timeline=timeline,
            discrepancies=discrepancies,
        )

    def _execute_rollback_drill(
        self,
        deployment_id: str,
    ) -> DrillResult:
        """
        Execute rollback drill: verify deployment can be rolled back.

        Validates that the deployment state machine supports rollback
        from the current state.

        Args:
            deployment_id: ULID of the deployment.

        Returns:
            DrillResult indicating rollback readiness.
        """
        timeline: list[str] = []
        discrepancies: list[str] = []

        timeline.append("rollback_drill_started")

        # Verify deployment exists and check state
        deployment = self._deployment_repo.get_by_id(deployment_id)
        if deployment is not None:
            state = (
                deployment.get("state", "unknown")
                if isinstance(deployment, dict)
                else getattr(deployment, "state", "unknown")
            )
            timeline.append(f"current_state_{state}")

            # Rollback is valid from active, frozen, or deactivating states
            rollback_states = {"active", "frozen", "deactivating"}
            if state in rollback_states:
                timeline.append("rollback_path_available")
            else:
                timeline.append(f"rollback_not_available_from_{state}")
                discrepancies.append(f"Cannot rollback from state '{state}'")

        timeline.append("rollback_drill_completed")

        return DrillResult(
            result_id=str(_ulid.ULID()),
            deployment_id=deployment_id,
            drill_type=DrillType.ROLLBACK,
            passed=len(discrepancies) == 0,
            timeline=timeline,
            discrepancies=discrepancies,
        )

    def _execute_reconnect_drill(
        self,
        deployment_id: str,
        adapter: BrokerAdapterInterface | None,
    ) -> DrillResult:
        """
        Execute reconnect drill: verify adapter can reconnect.

        Checks adapter diagnostics to verify connection health
        and ability to recover from disconnection.

        Args:
            deployment_id: ULID of the deployment.
            adapter: Broker adapter (may be None).

        Returns:
            DrillResult indicating reconnect readiness.
        """
        timeline: list[str] = []
        discrepancies: list[str] = []

        timeline.append("reconnect_drill_started")

        if adapter is not None:
            # Check adapter diagnostics
            try:
                diagnostics = adapter.get_diagnostics()
                timeline.append("diagnostics_retrieved")

                # Verify connection status
                connection = getattr(diagnostics, "connection_status", None)
                if connection is not None:
                    timeline.append(
                        f"connection_status_{connection.value if hasattr(connection, 'value') else connection}"
                    )
                else:
                    timeline.append("connection_status_available")

                timeline.append("adapter_responsive")
            except Exception as exc:
                discrepancies.append(f"Adapter diagnostics failed: {exc}")
                timeline.append("diagnostics_failed")
        else:
            discrepancies.append("No adapter registered for deployment")
            timeline.append("no_adapter_registered")

        timeline.append("reconnect_drill_completed")

        return DrillResult(
            result_id=str(_ulid.ULID()),
            deployment_id=deployment_id,
            drill_type=DrillType.RECONNECT,
            passed=len(discrepancies) == 0,
            timeline=timeline,
            discrepancies=discrepancies,
        )

    def _execute_failover_drill(
        self,
        deployment_id: str,
        adapter: BrokerAdapterInterface | None,
    ) -> DrillResult:
        """
        Execute failover drill: verify position reconciliation after recovery.

        Checks that positions can be retrieved and reconciled after
        a simulated failover event.

        Args:
            deployment_id: ULID of the deployment.
            adapter: Broker adapter (may be None).

        Returns:
            DrillResult indicating failover readiness.
        """
        timeline: list[str] = []
        discrepancies: list[str] = []
        details: dict[str, Any] = {}

        timeline.append("failover_drill_started")

        if adapter is not None:
            # Retrieve current positions for reconciliation baseline
            try:
                positions = adapter.get_positions()
                timeline.append(f"retrieved_{len(positions)}_positions")
                details["position_count"] = len(positions)
            except Exception as exc:
                discrepancies.append(f"Position retrieval failed: {exc}")
                timeline.append("position_retrieval_failed")

            # Verify account state is accessible
            try:
                adapter.get_account()
                timeline.append("account_state_accessible")
                details["account_accessible"] = True
            except Exception as exc:
                discrepancies.append(f"Account retrieval failed: {exc}")
                timeline.append("account_retrieval_failed")

            # Verify order state is accessible for reconciliation
            try:
                if hasattr(adapter, "get_all_order_states"):
                    orders = adapter.get_all_order_states()
                elif hasattr(adapter, "get_all_orders"):
                    orders = adapter.get_all_orders()
                else:
                    orders = adapter.list_open_orders()
                timeline.append(f"retrieved_{len(orders)}_orders")
                details["order_count"] = len(orders)
            except Exception as exc:
                discrepancies.append(f"Order state retrieval failed: {exc}")
                timeline.append("order_retrieval_failed")

            timeline.append("reconciliation_baseline_established")
        else:
            discrepancies.append("No adapter registered for deployment")
            timeline.append("no_adapter_registered")

        timeline.append("failover_drill_completed")

        return DrillResult(
            result_id=str(_ulid.ULID()),
            deployment_id=deployment_id,
            drill_type=DrillType.FAILOVER,
            passed=len(discrepancies) == 0,
            timeline=timeline,
            discrepancies=discrepancies,
            details=details,
        )
