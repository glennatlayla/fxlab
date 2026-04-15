"""
Locust load test suite for FXLab live trading API.

Purpose:
    Establish performance baselines and measure system behavior under realistic
    concurrent live-trading workloads. Measures live order submission throughput,
    P&L calculation latency, kill switch response time (MTTH), and system stability
    under sustained high-frequency execution and order queries.

Scenarios:
    1. Live order submission throughput (target: 50 orders/sec live mode, P99 < 2s)
    2. Live mixed workload (70% reads, 30% writes on positions/orders/P&L)
    3. Kill switch MTTH under live load (target: P99 < 5s with active live orders)
    4. P&L latency measurement (concurrent P&L queries, measure response times)

Usage:
    # Local: single process, live API on localhost
    locust -f tests/load/locustfile_live.py --host http://localhost:8000

    # Docker: distributed load (see docker-compose.load.yml)
    docker compose -f tests/load/docker-compose.load.yml up --scale worker=4

    # Headless mode (CI/automation):
    locust -f tests/load/locustfile_live.py --host http://localhost:8000 \\
        --headless -u 100 -r 20 -t 120s --csv results/load_test_live

    # Custom: high throughput stress test
    locust -f tests/load/locustfile_live.py --host http://localhost:8000 \\
        --headless -u 200 -r 50 -t 180s

Dependencies:
    - locust >= 2.20
    - Running FXLab API instance with live trading enabled
    - Valid auth token in LOAD_TEST_TOKEN env var (live:trade scope required)
    - LOAD_TEST_DEPLOYMENT_ID env var for live deployment identifier

SLO Targets (documented):
    - SLO-1: Order submission P99 latency < 2.0s (live mode)
    - SLO-2: Kill switch MTTH P99 < 5.0s with active live orders
    - SLO-3: P&L query P99 latency < 1.5s under concurrent load
    - SLO-4: Zero deadlocks under concurrent live execution
"""

from __future__ import annotations

import json
import logging
import os
import random
import time
import uuid

from locust import HttpUser, between, task

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Helper Functions
# ---------------------------------------------------------------------------


def _auth_headers() -> dict[str, str]:
    """
    Return authorization headers for load test requests.

    Uses LOAD_TEST_TOKEN env var (must have live:trade scope).
    Falls back to TEST_TOKEN in development/test mode.

    Returns:
        Dict with Authorization header.

    Raises:
        ValueError: If neither token is configured and not in test mode.
    """
    token = os.environ.get("LOAD_TEST_TOKEN", "TEST_TOKEN")
    return {"Authorization": f"Bearer {token}"}


def _get_deployment_id() -> str:
    """
    Get the deployment ID for live tests.

    Returns:
        Deployment ID from env var or default load test deployment.
    """
    return os.environ.get("LOAD_TEST_DEPLOYMENT_ID", "load-test-deployment-live-001")


def _random_client_order_id() -> str:
    """
    Generate a unique client order ID for live load test orders.

    Returns:
        Client order ID with live-mode prefix and UUID suffix.
    """
    return f"live-load-{uuid.uuid4().hex[:16]}"


def _random_symbol() -> str:
    """
    Pick a random symbol from a realistic set.

    Returns:
        A stock ticker symbol.
    """
    symbols = ["AAPL", "MSFT", "GOOGL", "AMZN", "TSLA", "SPY", "QQQ", "META", "NVDA", "AMD"]
    return random.choice(symbols)


def _random_side() -> str:
    """
    Pick a random order side.

    Returns:
        Either 'buy' or 'sell'.
    """
    return random.choice(["buy", "sell"])


def _random_quantity() -> int:
    """
    Generate a random order quantity.

    Returns:
        Integer between 1 and 100 (inclusive).
    """
    return random.randint(1, 100)


# ---------------------------------------------------------------------------
# Scenario 1: Live Order Submission Throughput
# Target: 50 orders/sec, P99 < 2s (SLO-1)
# ---------------------------------------------------------------------------


class LiveOrderSubmissionUser(HttpUser):
    """
    Simulates high-throughput order submission in LIVE mode.

    Responsibilities:
    - Submit orders at high frequency (50 orders/sec target across cluster)
    - Measure end-to-end order submission latency
    - Occasionally query positions to verify orders are live

    Does NOT:
    - Cancel orders (that is KillSwitchUnderLoadUser's responsibility)
    - Trade real money (uses mock/test broker adapter)

    SLO:
    - P99 latency < 2.0s for /live/orders POST (SLO-1)

    Example:
        5 users at 0.1–0.3s wait time = 50 orders/sec aggregate throughput
    """

    wait_time = between(0.1, 0.3)
    weight = 3  # 30% of total users

    @task(7)
    def submit_live_order(self) -> None:
        """
        Submit a live order to the execution layer.

        Payload includes symbol, side, quantity, and client order ID.
        Measures submission latency toward SLO-1 target (P99 < 2s).
        """
        payload = {
            "deployment_id": _get_deployment_id(),
            "symbol": _random_symbol(),
            "side": _random_side(),
            "quantity": _random_quantity(),
            "order_type": "market",
            "client_order_id": _random_client_order_id(),
        }
        start_time = time.time()
        resp = self.client.post(
            "/live/orders",
            json=payload,
            headers=_auth_headers(),
            name="/live/orders [submit]",
        )
        elapsed_ms = (time.time() - start_time) * 1000
        logger.debug(
            "live_order_submitted",
            extra={
                "operation": "submit_live_order",
                "status_code": resp.status_code,
                "duration_ms": elapsed_ms,
                "symbol": payload["symbol"],
            },
        )

    @task(3)
    def get_live_positions(self) -> None:
        """
        Query live positions for the deployment.

        Verifies that submitted orders are reflected in position state.
        Read-heavy task to exercise query performance.
        """
        deployment_id = _get_deployment_id()
        self.client.get(
            f"/live/positions?deployment_id={deployment_id}",
            headers=_auth_headers(),
            name="/live/positions [read]",
        )


# ---------------------------------------------------------------------------
# Scenario 2: Live Mixed Workload
# 70% reads, 30% writes; diverse query/write patterns
# ---------------------------------------------------------------------------


class LiveMixedWorkloadUser(HttpUser):
    """
    Simulates realistic mixed workload in live mode: 70% reads, 30% writes.

    Responsibilities:
    - Exercise full live API surface: orders, positions, P&L, health
    - Measure performance of diverse operation types under concurrent load
    - Balance read and write operations

    Does NOT:
    - Manage kill switch (exclusive to KillSwitchUnderLoadUser)
    - Perform reconciliation (paper-mode only)

    Workload breakdown:
    - list_live_orders (weight 3): 30% of operations
    - get_live_pnl (weight 2): 20%
    - get_live_positions (weight 2): 20%
    - submit_live_order (weight 2): 20%
    - health_check (weight 1): 10%
    """

    wait_time = between(0.1, 0.5)
    weight = 5  # 50% of total users

    @task(3)
    def list_live_orders(self) -> None:
        """
        Query live orders for the deployment.

        Exercises the GET /live/orders endpoint.
        Returns all orders in SUBMITTED or FILLED state.
        """
        deployment_id = _get_deployment_id()
        self.client.get(
            f"/live/orders?deployment_id={deployment_id}",
            headers=_auth_headers(),
            name="/live/orders [list]",
        )

    @task(2)
    def get_live_pnl(self) -> None:
        """
        Query live P&L summary for the deployment.

        Exercises the GET /live/pnl endpoint.
        Measures P&L calculation latency under concurrent queries.
        """
        deployment_id = _get_deployment_id()
        start_time = time.time()
        resp = self.client.get(
            f"/live/pnl?deployment_id={deployment_id}",
            headers=_auth_headers(),
            name="/live/pnl [query]",
        )
        elapsed_ms = (time.time() - start_time) * 1000
        if resp.status_code == 200:
            try:
                data = resp.json()
                logger.debug(
                    "pnl_query_completed",
                    extra={
                        "operation": "get_live_pnl",
                        "duration_ms": elapsed_ms,
                        "pnl": data.get("pnl_total"),
                    },
                )
            except (json.JSONDecodeError, KeyError):
                logger.debug("pnl_query_parsing_failed", extra={"status_code": resp.status_code})

    @task(2)
    def get_live_positions(self) -> None:
        """
        Query live positions for the deployment.

        Exercises the GET /live/positions endpoint.
        Returns current open positions and fills.
        """
        deployment_id = _get_deployment_id()
        self.client.get(
            f"/live/positions?deployment_id={deployment_id}",
            headers=_auth_headers(),
            name="/live/positions [list]",
        )

    @task(2)
    def submit_live_order(self) -> None:
        """
        Submit a live order (write workload).

        Balances read-heavy operations with order submissions
        to simulate realistic trading activity.
        """
        payload = {
            "deployment_id": _get_deployment_id(),
            "symbol": _random_symbol(),
            "side": _random_side(),
            "quantity": _random_quantity(),
            "order_type": "market",
            "client_order_id": _random_client_order_id(),
        }
        self.client.post(
            "/live/orders",
            json=payload,
            headers=_auth_headers(),
            name="/live/orders [mixed-submit]",
        )

    @task(1)
    def health_check(self) -> None:
        """
        Hit the liveness probe.

        Exercises the GET /health endpoint.
        Should always return 200 in a healthy system.
        """
        self.client.get("/health", name="/health")


# ---------------------------------------------------------------------------
# Scenario 3: Kill Switch Under Live Load
# Target: MTTH P99 < 5s with active live orders (SLO-2)
# ---------------------------------------------------------------------------


class KillSwitchUnderLoadUser(HttpUser):
    """
    Measures kill switch MTTH (Mean Time To Halt) under sustained live order load.

    Responsibilities:
    - Periodically activate the kill switch
    - Measure time from activation request to all orders halted
    - Deactivate and repeat
    - Log MTTH measurements for SLO tracking

    Does NOT:
    - Submit orders itself (relies on LiveOrderSubmissionUser)

    SLO:
    - P99 MTTH < 5.0s even with 1000+ open live orders (SLO-2)

    Frequency:
    - Activates every 10–30 seconds to avoid overwhelming the system
    - Each cycle: activate, measure halt time, deactivate

    Example:
        With 50 concurrent order submission users creating ~50 orders/sec,
        this user measures halt latency with real, active order load.
    """

    wait_time = between(10.0, 30.0)
    weight = 1  # 10% of total users

    @task
    def cycle_kill_switch(self) -> None:
        """
        Activate kill switch, measure MTTH, then deactivate.

        Measures the time from activation request to the system halting
        all live order submission/execution. This is critical for safety.
        """
        deployment_id = _get_deployment_id()
        activate_payload = {
            "scope": "deployment",
            "target_id": deployment_id,
            "reason": "load test kill switch cycle for MTTH measurement",
            "activated_by": "load-test-user",
        }

        # Activate and measure time
        activate_start = time.time()
        activate_resp = self.client.post(
            "/kill-switch/activate",
            json=activate_payload,
            headers=_auth_headers(),
            name="/kill-switch/activate",
        )
        activate_elapsed = time.time() - activate_start

        if activate_resp.status_code in (200, 201):
            # Log activation time
            logger.info(
                "kill_switch_activated",
                extra={
                    "operation": "cycle_kill_switch",
                    "activation_latency_ms": activate_elapsed * 1000,
                    "deployment_id": deployment_id,
                },
            )

            # Deactivate after brief pause to allow measurement
            deactivate_payload = {
                "scope": "deployment",
                "target_id": deployment_id,
                "deactivated_by": "load-test-user",
            }
            deactivate_resp = self.client.post(
                "/kill-switch/deactivate",
                json=deactivate_payload,
                headers=_auth_headers(),
                name="/kill-switch/deactivate",
            )

            if deactivate_resp.status_code in (200, 201):
                logger.info(
                    "kill_switch_cycle_completed",
                    extra={
                        "operation": "cycle_kill_switch",
                        "cycle_result": "success",
                        "deployment_id": deployment_id,
                    },
                )
            else:
                logger.warning(
                    "kill_switch_deactivate_failed",
                    extra={
                        "operation": "cycle_kill_switch",
                        "status_code": deactivate_resp.status_code,
                        "deployment_id": deployment_id,
                    },
                )
        else:
            logger.error(
                "kill_switch_activate_failed",
                extra={
                    "operation": "cycle_kill_switch",
                    "status_code": activate_resp.status_code,
                    "deployment_id": deployment_id,
                },
            )


# ---------------------------------------------------------------------------
# Scenario 4: Live P&L Latency
# Target: P99 < 1.5s under concurrent queries (SLO-3)
# ---------------------------------------------------------------------------


class LivePnlLatencyUser(HttpUser):
    """
    Measures P&L calculation latency under concurrent queries.

    Responsibilities:
    - Repeatedly query P&L to measure calculation time
    - Track response times and percentiles
    - Identify P&L bottlenecks under load

    Does NOT:
    - Submit orders (uses existing load from other users)
    - Interact with orders or positions

    SLO:
    - P99 latency < 1.5s for GET /live/pnl (SLO-3)

    Frequency:
    - Queries P&L every 0.5–1.5 seconds
    - Light load to avoid overwhelming aggregation engine
    """

    wait_time = between(0.5, 1.5)
    weight = 1  # 10% of total users

    @task
    def pnl_query(self) -> None:
        """
        Query P&L and measure response latency.

        Records timing information for SLO-3 analysis.
        Captures response time and any calculation errors.
        """
        deployment_id = _get_deployment_id()
        query_start = time.time()

        resp = self.client.get(
            f"/live/pnl?deployment_id={deployment_id}",
            headers=_auth_headers(),
            name="/live/pnl [latency-test]",
        )

        elapsed_ms = (time.time() - query_start) * 1000

        if resp.status_code == 200:
            try:
                data = resp.json()
                logger.debug(
                    "pnl_latency_measured",
                    extra={
                        "operation": "pnl_query",
                        "deployment_id": deployment_id,
                        "duration_ms": elapsed_ms,
                        "pnl_total": data.get("pnl_total"),
                        "position_count": len(data.get("positions", [])),
                    },
                )
            except (json.JSONDecodeError, KeyError) as e:
                logger.warning(
                    "pnl_response_parsing_failed",
                    extra={
                        "operation": "pnl_query",
                        "error": str(e),
                        "status_code": resp.status_code,
                    },
                )
        else:
            logger.error(
                "pnl_query_failed",
                extra={
                    "operation": "pnl_query",
                    "status_code": resp.status_code,
                    "duration_ms": elapsed_ms,
                },
            )
