"""Initial schema — Phase 3 all tables.

Creates all tables defined in libs.contracts.models as of M0–M13:
users, strategies, strategy_builds, candidates, deployments, runs, trials,
artifacts, audit_events, feeds, feed_health_events, parity_events, overrides,
approval_requests, draft_autosaves, override_requests, override_watermarks,
chart_cache_entries.

Revision ID: 0001
Revises:
Create Date: 2026-03-28 12:00:00.000000
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers
revision: str = "0001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Create all Phase 3 tables."""

    # ------------------------------------------------------------------
    # users
    # ------------------------------------------------------------------
    op.create_table(
        "users",
        sa.Column("id", sa.String(26), primary_key=True, nullable=False),
        sa.Column("email", sa.String(255), nullable=False, unique=True),
        sa.Column("hashed_password", sa.String(255), nullable=False),
        sa.Column("role", sa.String(50), nullable=False),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime, nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime, nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_users_email", "users", ["email"])

    # ------------------------------------------------------------------
    # strategies
    # ------------------------------------------------------------------
    op.create_table(
        "strategies",
        sa.Column("id", sa.String(26), primary_key=True, nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("code", sa.Text, nullable=False),
        sa.Column("version", sa.String(50), nullable=True),
        sa.Column("created_by", sa.String(26), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime, nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime, nullable=False, server_default=sa.func.now()),
    )

    # ------------------------------------------------------------------
    # strategy_builds
    # ------------------------------------------------------------------
    op.create_table(
        "strategy_builds",
        sa.Column("id", sa.String(26), primary_key=True, nullable=False),
        sa.Column("strategy_id", sa.String(26), sa.ForeignKey("strategies.id"), nullable=False),
        sa.Column("artifact_uri", sa.String(512), nullable=True),
        sa.Column("source_hash", sa.String(64), nullable=True),
        sa.Column("build_status", sa.String(50), nullable=False, server_default="pending"),
        sa.Column("created_at", sa.DateTime, nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime, nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_strategy_builds_strategy_id", "strategy_builds", ["strategy_id"])

    # ------------------------------------------------------------------
    # candidates
    # ------------------------------------------------------------------
    op.create_table(
        "candidates",
        sa.Column("id", sa.String(26), primary_key=True, nullable=False),
        sa.Column("strategy_id", sa.String(26), sa.ForeignKey("strategies.id"), nullable=False),
        sa.Column("status", sa.String(50), nullable=False, server_default="draft"),
        sa.Column("submitted_by", sa.String(26), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("created_at", sa.DateTime, nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime, nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_candidates_strategy_id", "candidates", ["strategy_id"])

    # ------------------------------------------------------------------
    # deployments
    # ------------------------------------------------------------------
    op.create_table(
        "deployments",
        sa.Column("id", sa.String(26), primary_key=True, nullable=False),
        sa.Column("strategy_id", sa.String(26), sa.ForeignKey("strategies.id"), nullable=False),
        sa.Column("environment", sa.String(50), nullable=False),
        sa.Column("status", sa.String(50), nullable=False, server_default="pending"),
        sa.Column("deployed_by", sa.String(26), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("created_at", sa.DateTime, nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime, nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_deployments_strategy_id", "deployments", ["strategy_id"])

    # ------------------------------------------------------------------
    # runs
    # ------------------------------------------------------------------
    op.create_table(
        "runs",
        sa.Column("id", sa.String(26), primary_key=True, nullable=False),
        sa.Column("strategy_id", sa.String(26), sa.ForeignKey("strategies.id"), nullable=True),
        sa.Column("run_type", sa.String(50), nullable=False, server_default="backtest"),
        sa.Column("status", sa.String(50), nullable=False, server_default="pending"),
        sa.Column("started_at", sa.DateTime, nullable=True),
        sa.Column("completed_at", sa.DateTime, nullable=True),
        sa.Column("created_at", sa.DateTime, nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime, nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_runs_strategy_id", "runs", ["strategy_id"])

    # ------------------------------------------------------------------
    # trials
    # ------------------------------------------------------------------
    op.create_table(
        "trials",
        sa.Column("id", sa.String(26), primary_key=True, nullable=False),
        sa.Column("run_id", sa.String(26), sa.ForeignKey("runs.id"), nullable=False),
        sa.Column("trial_index", sa.Integer, nullable=False, server_default="0"),
        sa.Column("status", sa.String(50), nullable=False, server_default="pending"),
        sa.Column("metrics", sa.JSON, nullable=True),
        sa.Column("created_at", sa.DateTime, nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime, nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_trials_run_id", "trials", ["run_id"])

    # ------------------------------------------------------------------
    # artifacts
    # ------------------------------------------------------------------
    op.create_table(
        "artifacts",
        sa.Column("id", sa.String(26), primary_key=True, nullable=False),
        sa.Column("run_id", sa.String(26), sa.ForeignKey("runs.id"), nullable=True),
        sa.Column("artifact_type", sa.String(100), nullable=False),
        sa.Column("uri", sa.String(512), nullable=False),
        sa.Column("size_bytes", sa.Integer, nullable=True),
        sa.Column("checksum", sa.String(64), nullable=True),
        sa.Column("created_at", sa.DateTime, nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime, nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_artifacts_run_id", "artifacts", ["run_id"])

    # ------------------------------------------------------------------
    # audit_events  (append-only; no updated_at)
    # ------------------------------------------------------------------
    op.create_table(
        "audit_events",
        sa.Column("id", sa.String(26), primary_key=True, nullable=False),
        sa.Column("actor", sa.String(255), nullable=False),
        sa.Column("action", sa.String(255), nullable=False),
        sa.Column("object_id", sa.String(26), nullable=False),
        sa.Column("object_type", sa.String(100), nullable=False),
        sa.Column("metadata", sa.JSON, nullable=False, server_default="{}"),
        sa.Column("created_at", sa.DateTime, nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_audit_events_object_id", "audit_events", ["object_id"])
    op.create_index("ix_audit_events_created_at", "audit_events", ["created_at"])

    # ------------------------------------------------------------------
    # feeds
    # ------------------------------------------------------------------
    op.create_table(
        "feeds",
        sa.Column("id", sa.String(26), primary_key=True, nullable=False),
        sa.Column("name", sa.String(255), nullable=False, unique=True),
        sa.Column("feed_type", sa.String(100), nullable=False),
        sa.Column("source", sa.String(255), nullable=True),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime, nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime, nullable=False, server_default=sa.func.now()),
    )

    # ------------------------------------------------------------------
    # feed_health_events
    # ------------------------------------------------------------------
    op.create_table(
        "feed_health_events",
        sa.Column("id", sa.String(26), primary_key=True, nullable=False),
        sa.Column("feed_id", sa.String(26), sa.ForeignKey("feeds.id"), nullable=False),
        sa.Column("status", sa.String(50), nullable=False),
        sa.Column("checked_at", sa.DateTime, nullable=False, server_default=sa.func.now()),
        sa.Column("details", sa.JSON, nullable=True),
    )
    op.create_index("ix_feed_health_events_feed_id", "feed_health_events", ["feed_id"])

    # ------------------------------------------------------------------
    # parity_events
    # ------------------------------------------------------------------
    op.create_table(
        "parity_events",
        sa.Column("id", sa.String(26), primary_key=True, nullable=False),
        sa.Column("feed_id", sa.String(26), sa.ForeignKey("feeds.id"), nullable=True),
        sa.Column("reference_feed_id", sa.String(26), sa.ForeignKey("feeds.id"), nullable=True),
        sa.Column("parity_score", sa.String(20), nullable=True),
        sa.Column("status", sa.String(50), nullable=False, server_default="unknown"),
        sa.Column("checked_at", sa.DateTime, nullable=False, server_default=sa.func.now()),
        sa.Column("details", sa.JSON, nullable=True),
    )
    op.create_index("ix_parity_events_feed_id", "parity_events", ["feed_id"])

    # ------------------------------------------------------------------
    # overrides
    # ------------------------------------------------------------------
    op.create_table(
        "overrides",
        sa.Column("id", sa.String(26), primary_key=True, nullable=False),
        sa.Column("target_id", sa.String(26), nullable=False),
        sa.Column("target_type", sa.String(100), nullable=False),
        sa.Column("override_type", sa.String(100), nullable=False),
        sa.Column("governance_gate", sa.String(100), nullable=True),
        sa.Column("rationale", sa.Text, nullable=True),
        sa.Column("evidence_link", sa.String(512), nullable=True),
        sa.Column("submitter_id", sa.String(26), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("status", sa.String(50), nullable=False, server_default="pending"),
        sa.Column("reviewer_id", sa.String(26), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("decision_rationale", sa.Text, nullable=True),
        sa.Column("decided_at", sa.DateTime, nullable=True),
        sa.Column("original_state", sa.JSON, nullable=True),
        sa.Column("new_state", sa.JSON, nullable=True),
        sa.Column("applied_by", sa.String(26), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime, nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime, nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_overrides_target_id", "overrides", ["target_id"])

    # ------------------------------------------------------------------
    # override_watermarks
    # ------------------------------------------------------------------
    op.create_table(
        "override_watermarks",
        sa.Column("id", sa.String(26), primary_key=True, nullable=False),
        sa.Column("override_id", sa.String(26), sa.ForeignKey("overrides.id"), nullable=False),
        sa.Column("target_id", sa.String(26), nullable=False),
        sa.Column("target_type", sa.String(100), nullable=False),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime, nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_override_watermarks_target_id", "override_watermarks", ["target_id"])
    op.create_index("ix_override_watermarks_override_id", "override_watermarks", ["override_id"])

    # ------------------------------------------------------------------
    # approval_requests
    # ------------------------------------------------------------------
    op.create_table(
        "approval_requests",
        sa.Column("id", sa.String(26), primary_key=True, nullable=False),
        sa.Column("candidate_id", sa.String(26), sa.ForeignKey("candidates.id"), nullable=True),
        sa.Column("requested_by", sa.String(26), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("status", sa.String(50), nullable=False, server_default="pending"),
        sa.Column("reviewer_id", sa.String(26), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("decision_reason", sa.Text, nullable=True),
        sa.Column("decided_at", sa.DateTime, nullable=True),
        sa.Column("created_at", sa.DateTime, nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime, nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_approval_requests_candidate_id", "approval_requests", ["candidate_id"])

    # ------------------------------------------------------------------
    # draft_autosaves  (M13 spec)
    # form_step, session_id, client_ts capture the UI recovery context
    # needed for the DraftRecoveryBanner (frontend calls POST every 30 s).
    # ------------------------------------------------------------------
    op.create_table(
        "draft_autosaves",
        sa.Column("id", sa.String(26), primary_key=True, nullable=False),
        sa.Column("user_id", sa.String(26), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("strategy_id", sa.String(26), sa.ForeignKey("strategies.id"), nullable=True),
        sa.Column("draft_payload", sa.JSON, nullable=False, server_default="{}"),
        sa.Column("form_step", sa.String(100), nullable=True),
        sa.Column("session_id", sa.String(255), nullable=True),
        sa.Column("client_ts", sa.String(50), nullable=True),
        sa.Column("created_at", sa.DateTime, nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime, nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_draft_autosaves_user_id", "draft_autosaves", ["user_id"])
    op.create_index("ix_draft_autosaves_created_at", "draft_autosaves", ["created_at"])

    # ------------------------------------------------------------------
    # chart_cache_entries  (M24 spec — write-through cache)
    # ------------------------------------------------------------------
    op.create_table(
        "chart_cache_entries",
        sa.Column("id", sa.String(26), primary_key=True, nullable=False),
        sa.Column("run_id", sa.String(26), sa.ForeignKey("runs.id"), nullable=False, unique=True),
        sa.Column("equity_points", sa.JSON, nullable=True),
        sa.Column("drawdown_points", sa.JSON, nullable=True),
        sa.Column("sampling_applied", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column("raw_equity_point_count", sa.Integer, nullable=True),
        sa.Column("is_partial", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column("created_at", sa.DateTime, nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime, nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_chart_cache_entries_run_id", "chart_cache_entries", ["run_id"])

    # ------------------------------------------------------------------
    # certification_events
    # ------------------------------------------------------------------
    op.create_table(
        "certification_events",
        sa.Column("id", sa.String(26), primary_key=True, nullable=False),
        sa.Column("feed_id", sa.String(26), sa.ForeignKey("feeds.id"), nullable=True),
        sa.Column("run_id", sa.String(26), sa.ForeignKey("runs.id"), nullable=True),
        sa.Column("certification_type", sa.String(100), nullable=False),
        sa.Column("status", sa.String(50), nullable=False, server_default="pending"),
        sa.Column("blocked", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column("details", sa.JSON, nullable=True),
        sa.Column("certified_at", sa.DateTime, nullable=True),
        sa.Column("created_at", sa.DateTime, nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime, nullable=False, server_default=sa.func.now()),
    )

    # ------------------------------------------------------------------
    # symbol_lineage_entries
    # ------------------------------------------------------------------
    op.create_table(
        "symbol_lineage_entries",
        sa.Column("id", sa.String(26), primary_key=True, nullable=False),
        sa.Column("symbol", sa.String(50), nullable=False),
        sa.Column("feed_id", sa.String(26), sa.ForeignKey("feeds.id"), nullable=True),
        sa.Column("run_id", sa.String(26), sa.ForeignKey("runs.id"), nullable=True),
        sa.Column("lineage_type", sa.String(100), nullable=True),
        sa.Column("details", sa.JSON, nullable=True),
        sa.Column("created_at", sa.DateTime, nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_symbol_lineage_symbol", "symbol_lineage_entries", ["symbol"])

    # ------------------------------------------------------------------
    # promotion_requests
    # ------------------------------------------------------------------
    op.create_table(
        "promotion_requests",
        sa.Column("id", sa.String(26), primary_key=True, nullable=False),
        sa.Column("candidate_id", sa.String(26), sa.ForeignKey("candidates.id"), nullable=True),
        sa.Column("requester_id", sa.String(26), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("target_environment", sa.String(50), nullable=False),
        sa.Column("status", sa.String(50), nullable=False, server_default="pending"),
        sa.Column("rationale", sa.Text, nullable=True),
        sa.Column("evidence_link", sa.String(512), nullable=True),
        sa.Column("reviewer_id", sa.String(26), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("decision_rationale", sa.Text, nullable=True),
        sa.Column("decided_at", sa.DateTime, nullable=True),
        sa.Column("created_at", sa.DateTime, nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime, nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_promotion_requests_candidate_id", "promotion_requests", ["candidate_id"])


def downgrade() -> None:
    """Drop all Phase 3 tables in reverse dependency order."""
    op.drop_table("promotion_requests")
    op.drop_table("symbol_lineage_entries")
    op.drop_table("certification_events")
    op.drop_table("chart_cache_entries")
    op.drop_table("draft_autosaves")
    op.drop_table("approval_requests")
    op.drop_table("override_watermarks")
    op.drop_table("overrides")
    op.drop_table("parity_events")
    op.drop_table("feed_health_events")
    op.drop_table("feeds")
    op.drop_table("audit_events")
    op.drop_table("artifacts")
    op.drop_table("trials")
    op.drop_table("runs")
    op.drop_table("deployments")
    op.drop_table("candidates")
    op.drop_table("strategy_builds")
    op.drop_table("strategies")
    op.drop_table("users")
