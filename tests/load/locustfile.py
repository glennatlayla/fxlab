"""
Locust load test suite for FXLab API.

Purpose:
    Establish performance baselines for the FXLab execution layer under
    realistic concurrent load. Measures order submission throughput, latency
    percentiles, and system behavior under pressure.

Scenarios:
    1. Order submission throughput (target: 100 orders/sec paper mode)
    2. Concurrent reconciliation (target: 10 concurrent, no deadlocks)
    3. Kill switch under load (target: < 5s MTTH with 1000 open orders)
    4. Mixed read/write (70% queries, 30% order submissions)

Usage:
    # Local: single process
    locust -f tests/load/locustfile.py --host http://localhost:8000

    # Docker: distributed mode (see docker-compose.load.yml)
    docker compose -f tests/load/docker-compose.load.yml up --scale worker=4

    # Headless (CI):
    locust -f tests/load/locustfile.py --host http://localhost:8000 \\
        --headless -u 50 -r 10 -t 60s --csv results/load_test

Dependencies:
    - locust >= 2.20
    - Running FXLab API instance
    - Valid auth token (or ENVIRONMENT=test for TEST_TOKEN bypass)

Example:
    # Run with 50 users, ramp 10/sec, for 60 seconds
    locust -f tests/load/locustfile.py --host http://localhost:8000 \\
        --headless -u 50 -r 10 -t 60s
"""

from __future__ import annotations

import os
import random
import uuid

from locust import HttpUser, between, task


def _auth_headers() -> dict[str, str]:
    """
    Return authorization headers for load test requests.

    Uses TEST_TOKEN when ENVIRONMENT=test (development/CI).
    Uses a real JWT when LOAD_TEST_TOKEN env var is set (staging/production).

    Returns:
        Dict with Authorization header.
    """
    token = os.environ.get("LOAD_TEST_TOKEN", "TEST_TOKEN")
    return {"Authorization": f"Bearer {token}"}


def _random_client_order_id() -> str:
    """Generate a unique client order ID for load test orders."""
    return f"load-{uuid.uuid4().hex[:16]}"


def _random_symbol() -> str:
    """Pick a random symbol from a realistic set."""
    symbols = ["AAPL", "MSFT", "GOOGL", "AMZN", "TSLA", "SPY", "QQQ", "META", "NVDA", "AMD"]
    return random.choice(symbols)


# ---------------------------------------------------------------------------
# Scenario 1: Order Submission Throughput
# ---------------------------------------------------------------------------


class OrderSubmissionUser(HttpUser):
    """
    Simulates high-throughput order submission in paper mode.

    Target: 100 orders/sec across all users.
    Each user submits orders with random symbols and sides.
    """

    wait_time = between(0.05, 0.2)
    weight = 3  # 30% of total users

    @task(7)
    def submit_paper_order(self) -> None:
        """Submit a paper order."""
        payload = {
            "deployment_id": "load-test-deployment-001",
            "symbol": _random_symbol(),
            "side": random.choice(["buy", "sell"]),
            "quantity": str(random.randint(1, 100)),
            "order_type": "market",
            "client_order_id": _random_client_order_id(),
        }
        self.client.post(
            "/paper/orders",
            json=payload,
            headers=_auth_headers(),
            name="/paper/orders [submit]",
        )

    @task(3)
    def get_positions(self) -> None:
        """Query paper positions (read workload)."""
        self.client.get(
            "/paper/positions?deployment_id=load-test-deployment-001",
            headers=_auth_headers(),
            name="/paper/positions [read]",
        )


# ---------------------------------------------------------------------------
# Scenario 2: Mixed Read/Write Workload
# ---------------------------------------------------------------------------


class MixedWorkloadUser(HttpUser):
    """
    Simulates realistic mixed workload: 70% reads, 30% writes.

    Exercises the full API surface including health checks, positions,
    orders, and account queries alongside order submissions.
    """

    wait_time = between(0.1, 0.5)
    weight = 5  # 50% of total users

    @task(3)
    def health_check(self) -> None:
        """Hit the liveness probe."""
        self.client.get("/health", name="/health")

    @task(2)
    def readiness_check(self) -> None:
        """Hit the readiness probe."""
        self.client.get("/ready", name="/ready")

    @task(2)
    def get_metrics(self) -> None:
        """Scrape Prometheus metrics."""
        self.client.get("/metrics", name="/metrics")

    @task(1)
    def list_deployments(self) -> None:
        """List active deployments."""
        self.client.get(
            "/deployments/",
            headers=_auth_headers(),
            name="/deployments [list]",
        )

    @task(2)
    def submit_order(self) -> None:
        """Submit a paper order (write workload)."""
        payload = {
            "deployment_id": "load-test-deployment-001",
            "symbol": _random_symbol(),
            "side": random.choice(["buy", "sell"]),
            "quantity": str(random.randint(1, 50)),
            "order_type": "market",
            "client_order_id": _random_client_order_id(),
        }
        self.client.post(
            "/paper/orders",
            json=payload,
            headers=_auth_headers(),
            name="/paper/orders [mixed-submit]",
        )


# ---------------------------------------------------------------------------
# Scenario 3: Reconciliation Under Load
# ---------------------------------------------------------------------------


class ReconciliationUser(HttpUser):
    """
    Simulates concurrent reconciliation runs.

    Target: 10 concurrent reconciliation runs without deadlocks.
    Reconciliation is a heavier operation that reads orders and positions
    from both internal state and broker adapters.
    """

    wait_time = between(1.0, 3.0)
    weight = 1  # 10% of total users

    @task
    def trigger_reconciliation(self) -> None:
        """Trigger a reconciliation run for a deployment."""
        payload = {
            "deployment_id": "load-test-deployment-001",
            "trigger": "manual",
        }
        self.client.post(
            "/reconciliation/run",
            json=payload,
            headers=_auth_headers(),
            name="/reconciliation/run [trigger]",
        )


# ---------------------------------------------------------------------------
# Scenario 4: Kill Switch Stress Test
# ---------------------------------------------------------------------------


class KillSwitchUser(HttpUser):
    """
    Simulates kill switch activation under load.

    Target: < 5s MTTH even when system has many open orders.
    This user periodically activates and deactivates the kill switch
    to measure MTTH under sustained load.

    NOTE: This should be run with a dedicated load test deployment
    that tolerates repeated kill switch cycling.
    """

    wait_time = between(5.0, 15.0)
    weight = 1  # 10% of total users

    @task
    def cycle_kill_switch(self) -> None:
        """Activate then deactivate kill switch."""
        activate_payload = {
            "scope": "deployment",
            "target_id": "load-test-deployment-002",
            "reason": "load test kill switch cycle",
            "activated_by": "load-test-user",
        }
        resp = self.client.post(
            "/kill-switch/activate",
            json=activate_payload,
            headers=_auth_headers(),
            name="/kill-switch/activate",
        )

        if resp.status_code in (200, 201):
            # Deactivate after brief pause
            deactivate_payload = {
                "scope": "deployment",
                "target_id": "load-test-deployment-002",
                "deactivated_by": "load-test-user",
            }
            self.client.post(
                "/kill-switch/deactivate",
                json=deactivate_payload,
                headers=_auth_headers(),
                name="/kill-switch/deactivate",
            )
