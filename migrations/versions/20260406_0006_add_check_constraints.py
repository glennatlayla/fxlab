"""Add CHECK constraints on all enum-like String columns.

Every status, role, environment, and type column previously accepted arbitrary
string values. This migration enforces the valid value sets at the database
level, preventing data corruption from bugs or malicious input.

Constraints added (15 total across 12 tables):
  - users.role: admin, operator, reviewer, viewer
  - strategy_builds.build_status: pending, success, failed
  - candidates.status: draft, submitted, approved, rejected
  - deployments.status: pending, running, completed, failed
  - deployments.environment: research, paper, live
  - runs.status: pending, running, completed, failed, cancelled
  - runs.run_type: backtest, paper, live
  - trials.status: pending, running, completed, failed
  - overrides.status: pending, approved, rejected
  - approval_requests.status: pending, approved, rejected
  - promotion_requests.status: pending, validating, approved, rejected,
                                deploying, completed, failed
  - promotion_requests.target_environment: paper, live
  - feed_health_events.status: healthy, degraded, unhealthy, unknown
  - parity_events.status: unknown, pass, fail, warning
  - certification_events.status: pending, passed, failed, certified,
                                  blocked, expired

Revision ID: 0006
Revises: 0005
Create Date: 2026-04-06 00:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Union

from alembic import op

# revision identifiers
revision: str = "0006"
down_revision: Union[str, None] = "0005"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# ---------------------------------------------------------------------------
# Constraint definitions: (table, constraint_name, check_sql)
# ---------------------------------------------------------------------------

_CONSTRAINTS: list[tuple[str, str, str]] = [
    (
        "users",
        "chk_users_role",
        "role IN ('admin', 'operator', 'reviewer', 'viewer')",
    ),
    (
        "strategy_builds",
        "chk_strategy_builds_build_status",
        "build_status IN ('pending', 'success', 'failed')",
    ),
    (
        "candidates",
        "chk_candidates_status",
        "status IN ('draft', 'submitted', 'approved', 'rejected')",
    ),
    (
        "deployments",
        "chk_deployments_status",
        "status IN ('pending', 'running', 'completed', 'failed')",
    ),
    (
        "deployments",
        "chk_deployments_environment",
        "environment IN ('research', 'paper', 'live')",
    ),
    (
        "runs",
        "chk_runs_status",
        "status IN ('pending', 'running', 'completed', 'failed', 'cancelled')",
    ),
    (
        "runs",
        "chk_runs_run_type",
        "run_type IN ('backtest', 'paper', 'live')",
    ),
    (
        "trials",
        "chk_trials_status",
        "status IN ('pending', 'running', 'completed', 'failed')",
    ),
    (
        "overrides",
        "chk_overrides_status",
        "status IN ('pending', 'approved', 'rejected')",
    ),
    (
        "approval_requests",
        "chk_approval_requests_status",
        "status IN ('pending', 'approved', 'rejected')",
    ),
    (
        "promotion_requests",
        "chk_promotion_requests_status",
        "status IN ('pending', 'validating', 'approved', 'rejected', "
        "'deploying', 'completed', 'failed')",
    ),
    (
        "promotion_requests",
        "chk_promotion_requests_target_environment",
        "target_environment IN ('paper', 'live')",
    ),
    (
        "feed_health_events",
        "chk_feed_health_events_status",
        "status IN ('healthy', 'degraded', 'unhealthy', 'unknown')",
    ),
    (
        "parity_events",
        "chk_parity_events_status",
        "status IN ('unknown', 'pass', 'fail', 'warning')",
    ),
    (
        "certification_events",
        "chk_certification_events_status",
        "status IN ('pending', 'passed', 'failed', 'certified', 'blocked', 'expired')",
    ),
]


def upgrade() -> None:
    """Add CHECK constraints to all enum-like String columns."""
    for table, name, check_sql in _CONSTRAINTS:
        op.create_check_constraint(name, table, check_sql)


def downgrade() -> None:
    """Remove CHECK constraints from all enum-like String columns."""
    for table, name, _check_sql in reversed(_CONSTRAINTS):
        op.drop_constraint(name, table, type_="check")
