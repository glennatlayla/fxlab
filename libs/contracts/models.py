"""
SQLAlchemy ORM models for FXLab Phase 3.

Responsibilities:
- Define all database table mappings using SQLAlchemy declarative base.
- Provide Base for use in Alembic migrations and test fixtures.
- Each model maps to one database table (SRP).

Does NOT:
- Contain business logic.
- Perform I/O or queries.

Dependencies:
- SQLAlchemy ORM

Example:
    from libs.contracts.models import Base, Strategy, AuditEvent
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    Column,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import DeclarativeBase, relationship, validates

# ---------------------------------------------------------------------------
# Declarative base
# ---------------------------------------------------------------------------


class Base(DeclarativeBase):
    """
    Declarative base class for all ORM models.

    All models inherit from this base, which provides the metadata registry
    used by Alembic migrations and test fixture setup.

    Note:
        __allow_unmapped__ = True permits legacy Column() declarations
        alongside SQLAlchemy 2.0's DeclarativeBase without requiring
        Mapped[] type annotations on every column attribute.
    """

    __allow_unmapped__ = True


# ---------------------------------------------------------------------------
# Helper mixin: ULID primary key + timestamps
# ---------------------------------------------------------------------------


class TimestampMixin:
    """
    Mixin providing created_at and updated_at timestamp columns.

    Responsibilities:
    - Auto-populate created_at on INSERT.
    - Auto-update updated_at on UPDATE.

    Does NOT:
    - Handle business logic or validation.

    Note:
        __allow_unmapped__ = True is required for SQLAlchemy 2.0 compatibility
        when using Column() declarations without Mapped[] annotations.
    """

    __allow_unmapped__ = True

    created_at = Column(
        DateTime,
        nullable=False,
        default=datetime.utcnow,
        server_default=func.now(),
    )
    updated_at = Column(
        DateTime,
        nullable=False,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
        server_default=func.now(),
    )


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------


class User(TimestampMixin, Base):
    """
    User accounts for authentication and authorisation.

    Attributes:
        id: ULID primary key (26-char string).
        email: Unique user email address.
        hashed_password: BCrypt-hashed password.
        role: User role — one of: admin, operator, researcher, viewer.
        is_active: Whether the account is enabled.
    """

    __tablename__ = "users"
    __table_args__ = (
        CheckConstraint(
            "role IN ('admin', 'operator', 'reviewer', 'viewer')",
            name="chk_users_role",
        ),
    )

    id: Any = Column(String(26), primary_key=True, nullable=False)
    email: Any = Column(String(255), nullable=False, unique=True, index=True)
    hashed_password: Any = Column(String(255), nullable=False)
    role: Any = Column(String(50), nullable=False)
    is_active: Any = Column(Boolean, nullable=False, default=True)


class Strategy(TimestampMixin, Base):
    """
    Registered trading strategy definition.

    Attributes:
        id: ULID primary key.
        name: Human-readable strategy name.
        code: Strategy source code.
        version: Semantic version string.
        created_by: ULID of the user who created this strategy.
        is_active: Whether this strategy is currently active.
    """

    __tablename__ = "strategies"

    id: Any = Column(String(26), primary_key=True, nullable=False)
    name: Any = Column(String(255), nullable=False)
    code: Any = Column(Text, nullable=False)
    version: Any = Column(String(50), nullable=True)
    created_by: Any = Column(
        String(26), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    is_active: Any = Column(Boolean, nullable=False, default=True)
    # Optimistic locking: incremented on every UPDATE to detect concurrent writes.
    row_version: Any = Column(Integer, nullable=False, default=1, server_default="1")

    builds: Any = relationship("StrategyBuild", back_populates="strategy")

    @validates("id")
    def validate_ulid_id(self, key: str, value: str) -> str:
        """
        Validate that the primary key is a well-formed ULID.

        A ULID is exactly 26 characters of Crockford Base32 (uppercase).
        Characters I, L, O, U are excluded from the alphabet.

        Args:
            key: Column name (always "id").
            value: Proposed ID value.

        Returns:
            The validated ULID string.

        Raises:
            ValueError: If value is not a valid ULID (wrong length or chars).
        """
        _ULID_ALPHABET = set("0123456789ABCDEFGHJKMNPQRSTVWXYZ")
        if not value or len(value) != 26:
            raise ValueError(
                f"Invalid ULID for {key!r}: expected 26 chars, got {len(value) if value else 0}"
            )
        invalid_chars = set(value.upper()) - _ULID_ALPHABET
        if invalid_chars:
            raise ValueError(f"Invalid ULID for {key!r}: disallowed characters {invalid_chars!r}")
        return value


class StrategyBuild(TimestampMixin, Base):
    """
    Compiled artifact of a strategy at a given version.

    Attributes:
        id: ULID primary key.
        strategy_id: FK to Strategy.
        artifact_uri: URI where the compiled artifact is stored.
        source_hash: SHA-256 hash of strategy source at build time.
        build_status: one of: pending, success, failed.
    """

    __tablename__ = "strategy_builds"
    __table_args__ = (
        CheckConstraint(
            "build_status IN ('pending', 'success', 'failed')",
            name="chk_strategy_builds_build_status",
        ),
    )

    id: Any = Column(String(26), primary_key=True, nullable=False)
    strategy_id: Any = Column(
        String(26), ForeignKey("strategies.id", ondelete="CASCADE"), nullable=False, index=True
    )
    artifact_uri: Any = Column(String(512), nullable=True)
    source_hash: Any = Column(String(64), nullable=True)
    build_status: Any = Column(String(50), nullable=False, default="pending")

    strategy: Any = relationship("Strategy", back_populates="builds")


class Candidate(TimestampMixin, Base):
    """
    A strategy candidate submitted for evaluation.

    Attributes:
        id: ULID primary key.
        strategy_id: FK to Strategy.
        status: Lifecycle status (draft, submitted, approved, rejected).
        submitted_by: ULID of submitting user.
    """

    __tablename__ = "candidates"
    __table_args__ = (
        CheckConstraint(
            "status IN ('draft', 'submitted', 'approved', 'rejected')",
            name="chk_candidates_status",
        ),
    )

    id: Any = Column(String(26), primary_key=True, nullable=False)
    strategy_id: Any = Column(
        String(26), ForeignKey("strategies.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    status: Any = Column(String(50), nullable=False, default="draft")
    submitted_by: Any = Column(
        String(26), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )


class Deployment(TimestampMixin, Base):
    """
    A strategy deployment to a target environment with state machine lifecycle.

    Phase 4 extended this model with state machine fields for execution control:
    state, execution_mode, emergency_posture, risk_limits, custom_posture_config.
    The original 'status' and 'environment' columns are retained for backward
    compatibility with Phase 1-3 code that references them.

    Attributes:
        id: ULID primary key.
        strategy_id: FK to Strategy.
        environment: Target environment (research, paper, live) — Phase 1-3 field.
        status: Legacy deployment status (pending, running, completed, failed).
        state: Phase 4 state machine state (created → ... → deactivated).
        execution_mode: Execution mode (shadow, paper, live).
        emergency_posture: Declared emergency posture (flatten_all, cancel_open, hold, custom).
        risk_limits: JSON risk limits configuration.
        custom_posture_config: JSON custom posture configuration (nullable).
        deployed_by: ULID of deploying user.

    Does NOT:
    - Enforce state transitions (service layer responsibility).
    - Contain business logic.

    Example:
        deployment = Deployment(
            id="01HDEPLOY...",
            strategy_id="01HSTRAT...",
            environment="paper",
            status="pending",
            state="created",
            execution_mode="paper",
            emergency_posture="flatten_all",
            deployed_by="01HUSER...",
        )
    """

    __tablename__ = "deployments"
    __table_args__ = (
        CheckConstraint(
            "status IN ('pending', 'running', 'completed', 'failed')",
            name="chk_deployments_status",
        ),
        CheckConstraint(
            "environment IN ('research', 'paper', 'live')",
            name="chk_deployments_environment",
        ),
        CheckConstraint(
            "state IN ('created', 'pending_approval', 'approved', 'activating', "
            "'active', 'frozen', 'deactivating', 'deactivated', 'rolled_back', 'failed')",
            name="chk_deployments_state",
        ),
        CheckConstraint(
            "execution_mode IN ('shadow', 'paper', 'live')",
            name="chk_deployments_execution_mode",
        ),
        CheckConstraint(
            "emergency_posture IN ('flatten_all', 'cancel_open', 'hold', 'custom', '')",
            name="chk_deployments_emergency_posture",
        ),
    )

    id: Any = Column(String(26), primary_key=True, nullable=False)
    strategy_id: Any = Column(
        String(26), ForeignKey("strategies.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    environment: Any = Column(String(50), nullable=False)
    status: Any = Column(String(50), nullable=False, default="pending")
    # Phase 4 state machine columns
    state: Any = Column(String(30), nullable=False, server_default="created", index=True)
    execution_mode: Any = Column(String(10), nullable=False, server_default="paper")
    emergency_posture: Any = Column(String(20), nullable=False, server_default="")
    risk_limits: Any = Column(JSON, nullable=False, server_default="{}")
    custom_posture_config: Any = Column(JSON, nullable=True)
    deployed_by: Any = Column(
        String(26), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )


class DeploymentTransition(TimestampMixin, Base):
    """
    Append-only audit trail for deployment state transitions.

    Each row records a single state transition with who initiated it,
    why, and a correlation_id for distributed tracing.

    Attributes:
        id: ULID primary key.
        deployment_id: FK to Deployment (CASCADE — if deployment is
            somehow removed, transitions go with it).
        from_state: State before the transition.
        to_state: State after the transition.
        actor: Identity string (e.g. 'user:<ulid>' or 'system').
        reason: Human-readable reason for the transition.
        correlation_id: Distributed tracing ID.
        transitioned_at: Timestamp of the transition.

    Does NOT:
    - Enforce transition validity (service layer responsibility).

    Example:
        transition = DeploymentTransition(
            id="01HTRANS...",
            deployment_id="01HDEPLOY...",
            from_state="approved",
            to_state="activating",
            actor="user:01HUSER...",
            reason="Activation initiated",
            correlation_id="corr-001",
        )
    """

    __tablename__ = "deployment_transitions"

    id: Any = Column(String(26), primary_key=True, nullable=False)
    deployment_id: Any = Column(
        String(26),
        ForeignKey("deployments.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    from_state: Any = Column(String(30), nullable=False)
    to_state: Any = Column(String(30), nullable=False)
    actor: Any = Column(String(255), nullable=False)
    reason: Any = Column(Text, nullable=False)
    correlation_id: Any = Column(String(255), nullable=False, index=True)
    transitioned_at: Any = Column(DateTime, nullable=False, server_default=func.now())


class Run(TimestampMixin, Base):
    """
    A single execution run of a strategy.

    Attributes:
        id: ULID primary key.
        strategy_id: FK to Strategy.
        run_type: Type of run (backtest, paper, live).
        status: Run lifecycle status.
        started_at: When the run began executing.
        completed_at: When the run finished (nullable until complete).
    """

    __tablename__ = "runs"
    __table_args__ = (
        CheckConstraint(
            "status IN ('pending', 'running', 'completed', 'failed', 'cancelled')",
            name="chk_runs_status",
        ),
        CheckConstraint(
            "run_type IN ('backtest', 'paper', 'live')",
            name="chk_runs_run_type",
        ),
    )

    id: Any = Column(String(26), primary_key=True, nullable=False)
    strategy_id: Any = Column(
        String(26), ForeignKey("strategies.id", ondelete="RESTRICT"), nullable=True, index=True
    )
    run_type: Any = Column(String(50), nullable=False, default="backtest")
    status: Any = Column(String(50), nullable=False, default="pending")
    started_at: Any = Column(DateTime, nullable=True)
    completed_at: Any = Column(DateTime, nullable=True)
    # Optimistic locking: incremented on every UPDATE to detect concurrent writes.
    row_version: Any = Column(Integer, nullable=False, default=1, server_default="1")

    trials: Any = relationship("Trial", back_populates="run")


class Trial(TimestampMixin, Base):
    """
    A single parameter-set trial within a run.

    Attributes:
        id: ULID primary key.
        run_id: FK to Run.
        trial_index: Zero-based trial index within the run.
        status: Trial status.
        metrics: JSON blob of performance metrics.
    """

    __tablename__ = "trials"
    __table_args__ = (
        CheckConstraint(
            "status IN ('pending', 'running', 'completed', 'failed')",
            name="chk_trials_status",
        ),
    )

    id: Any = Column(String(26), primary_key=True, nullable=False)
    run_id: Any = Column(
        String(26), ForeignKey("runs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    trial_index: Any = Column(Integer, nullable=False, default=0)
    status: Any = Column(String(50), nullable=False, default="pending")
    metrics: Any = Column(JSON, nullable=True)

    run: Any = relationship("Run", back_populates="trials")


class Artifact(TimestampMixin, Base):
    """
    A file artifact produced by a run or build.

    Attributes:
        id: ULID primary key.
        run_id: FK to Run (nullable — some artifacts come from builds).
        artifact_type: Type classifier (model, report, chart, etc.).
        uri: Storage URI.
        size_bytes: File size in bytes.
        checksum: SHA-256 checksum.
    """

    __tablename__ = "artifacts"

    id: Any = Column(String(26), primary_key=True, nullable=False)
    run_id: Any = Column(
        String(26), ForeignKey("runs.id", ondelete="CASCADE"), nullable=True, index=True
    )
    artifact_type: Any = Column(String(100), nullable=False)
    uri: Any = Column(String(512), nullable=False)
    size_bytes: Any = Column(Integer, nullable=True)
    checksum: Any = Column(String(64), nullable=True)


class AuditEvent(Base):
    """
    Immutable audit ledger entry.

    Responsibilities:
    - Record every mutation in the system with actor, action, and context.
    - Provide an append-only compliance trail.

    Does NOT:
    - Support UPDATE or DELETE operations.
    - Contain business logic.

    Attributes:
        id: ULID primary key.
        actor: Identity string (e.g. "user:<ulid>", "system:scheduler").
        action: Action verb (e.g. "strategy.created", "run.started").
        object_id: ULID of the affected entity.
        object_type: Entity type name (e.g. "strategy", "run").
        metadata: Arbitrary JSON context for the event.
        created_at: Event timestamp (no updated_at — events are immutable).
    """

    __tablename__ = "audit_events"

    id: Any = Column(String(26), primary_key=True, nullable=False)
    actor: Any = Column(String(255), nullable=False, index=True)
    action: Any = Column(String(255), nullable=False, index=True)
    object_id: Any = Column(String(26), nullable=False, index=True)
    object_type: Any = Column(String(100), nullable=False)
    source: Any = Column(String(32), nullable=True)
    # SQLAlchemy reserves 'metadata' at the class level; use 'event_metadata'
    # as the Python attribute name while mapping to the 'metadata' DB column.
    event_metadata: Any = Column("metadata", JSON, nullable=False, default=dict)
    created_at: Any = Column(
        DateTime,
        nullable=False,
        default=datetime.utcnow,
        server_default=func.now(),
    )


class Feed(TimestampMixin, Base):
    """
    Data feed registration entry.

    Attributes:
        id: ULID primary key.
        name: Unique feed name.
        feed_type: Feed type classifier (e.g. price, fundamental).
        source: Data source identifier.
        is_active: Whether this feed is currently enabled.
    """

    __tablename__ = "feeds"

    id: Any = Column(String(26), primary_key=True, nullable=False)
    name: Any = Column(String(255), nullable=False, unique=True)
    feed_type: Any = Column(String(100), nullable=False, index=True)
    source: Any = Column(String(255), nullable=True)
    is_active: Any = Column(Boolean, nullable=False, default=True)

    health_events: Any = relationship("FeedHealthEvent", back_populates="feed")


class FeedHealthEvent(Base):
    """
    A health check result for a feed.

    Attributes:
        id: ULID primary key.
        feed_id: FK to Feed.
        status: Health status (healthy, degraded, failed).
        checked_at: When the check was performed.
        details: JSON blob with check details.
    """

    __tablename__ = "feed_health_events"
    __table_args__ = (
        CheckConstraint(
            "status IN ('healthy', 'degraded', 'unhealthy', 'unknown')",
            name="chk_feed_health_events_status",
        ),
    )

    id: Any = Column(String(26), primary_key=True, nullable=False)
    feed_id: Any = Column(
        String(26), ForeignKey("feeds.id", ondelete="CASCADE"), nullable=False, index=True
    )
    status: Any = Column(String(50), nullable=False)
    checked_at: Any = Column(DateTime, nullable=False, default=datetime.utcnow)
    details: Any = Column(JSON, nullable=True)

    feed: Any = relationship("Feed", back_populates="health_events")


class ParityEvent(Base):
    """
    A parity check result comparing two data sources.

    Attributes:
        id: ULID primary key.
        feed_id: FK to Feed (primary feed being checked).
        reference_feed_id: FK to the reference Feed.
        parity_score: Numeric parity score (0.0–1.0).
        status: Parity status (pass, fail, warning).
        checked_at: When the parity check ran.
        details: JSON context.
    """

    __tablename__ = "parity_events"
    __table_args__ = (
        CheckConstraint(
            "status IN ('unknown', 'pass', 'fail', 'warning')",
            name="chk_parity_events_status",
        ),
    )

    id: Any = Column(String(26), primary_key=True, nullable=False)
    feed_id: Any = Column(
        String(26), ForeignKey("feeds.id", ondelete="RESTRICT"), nullable=True, index=True
    )
    reference_feed_id: Any = Column(
        String(26), ForeignKey("feeds.id", ondelete="RESTRICT"), nullable=True
    )
    parity_score: Any = Column(String(20), nullable=True)  # stored as string for precision
    status: Any = Column(String(50), nullable=False, default="unknown")
    checked_at: Any = Column(DateTime, nullable=False, default=datetime.utcnow)
    details: Any = Column(JSON, nullable=True)


class Override(TimestampMixin, Base):
    """
    A governance override request for a system decision.

    Responsibilities:
    - Persist override submission, review decision, and current status.
    - Link the override to the target entity and the submitter/reviewer.

    Does NOT:
    - Enforce separation-of-duties (service layer responsibility).
    - Trigger audit events directly.

    Attributes:
        id: ULID primary key.
        target_id: ULID of the entity being overridden.
        target_type: Entity type (candidate, deployment, etc.).
        override_type: Category of override (e.g. grade_override).
        governance_gate: Optional gate classifier (e.g. pre-deployment).
        rationale: Free-text justification provided by submitter (≥20 chars).
        evidence_link: Absolute HTTP/HTTPS URI referencing review evidence.
        submitter_id: ULID of the user requesting the override.
        status: Lifecycle status (pending, approved, rejected).
        reviewer_id: ULID of the reviewing operator (nullable until decided).
        decision_rationale: Free-text rationale for the review decision.
        decided_at: Timestamp of the review decision.
        applied_by: ULID of the operator who applied the override (post-approval).
        is_active: Whether this override is currently in effect.
    """

    __tablename__ = "overrides"
    __table_args__ = (
        CheckConstraint(
            "status IN ('pending', 'approved', 'rejected')",
            name="chk_overrides_status",
        ),
    )

    id: Any = Column(String(26), primary_key=True, nullable=False)
    target_id: Any = Column(String(26), nullable=False, index=True)
    target_type: Any = Column(String(100), nullable=False)
    override_type: Any = Column(String(100), nullable=False)
    governance_gate: Any = Column(String(100), nullable=True)
    rationale: Any = Column(Text, nullable=True)
    evidence_link: Any = Column(String(512), nullable=True)
    submitter_id: Any = Column(
        String(26), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    status: Any = Column(String(50), nullable=False, default="pending")
    reviewer_id: Any = Column(
        String(26), ForeignKey("users.id", ondelete="RESTRICT"), nullable=True
    )
    decision_rationale: Any = Column(Text, nullable=True)
    decided_at: Any = Column(DateTime, nullable=True)
    # JSON snapshots of the entity state before and after the override.
    # Required for compliance: reviewers must see what changed.
    original_state: Any = Column(JSON, nullable=True)
    new_state: Any = Column(JSON, nullable=True)
    applied_by: Any = Column(String(26), ForeignKey("users.id", ondelete="RESTRICT"), nullable=True)
    is_active: Any = Column(Boolean, nullable=False, default=True)
    # Optimistic locking: incremented on every UPDATE to detect concurrent writes.
    row_version: Any = Column(Integer, nullable=False, default=1, server_default="1")

    watermarks: Any = relationship("OverrideWatermark", back_populates="override")


class ApprovalRequest(TimestampMixin, Base):
    """
    A request for human approval of a promotion or deployment.

    Attributes:
        id: ULID primary key.
        candidate_id: FK to Candidate being considered.
        requested_by: ULID of the requesting user.
        status: Approval status (pending, approved, rejected).
        reviewer_id: ULID of the reviewer (nullable until reviewed).
        decision_reason: Free-text rationale for the decision.
        decided_at: When the decision was made.
    """

    __tablename__ = "approval_requests"
    __table_args__ = (
        CheckConstraint(
            "status IN ('pending', 'approved', 'rejected')",
            name="chk_approval_requests_status",
        ),
    )

    id: Any = Column(String(26), primary_key=True, nullable=False)
    candidate_id: Any = Column(
        String(26), ForeignKey("candidates.id", ondelete="RESTRICT"), nullable=True, index=True
    )
    requested_by: Any = Column(
        String(26), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    status: Any = Column(String(50), nullable=False, default="pending")
    reviewer_id: Any = Column(
        String(26), ForeignKey("users.id", ondelete="RESTRICT"), nullable=True, index=True
    )
    decision_reason: Any = Column(Text, nullable=True)
    decided_at: Any = Column(DateTime, nullable=True)


class OverrideWatermark(Base):
    """
    Tracks the 'high-water mark' of an active override against a target entity.

    Responsibilities:
    - Record which override currently governs a given target.
    - Enable efficient lookup of active overrides by target.

    Does NOT:
    - Contain business logic or approval logic.
    - Support UPDATE — rows are inserted or deleted, never mutated.

    Attributes:
        id: ULID primary key.
        override_id: FK to the Override that produced this watermark.
        target_id: ULID of the governed entity.
        target_type: Entity type (candidate, deployment, etc.).
        is_active: Whether this watermark is currently in effect.
        created_at: Row insertion timestamp.
    """

    __tablename__ = "override_watermarks"

    __allow_unmapped__ = True

    id: Any = Column(String(26), primary_key=True, nullable=False)
    override_id: Any = Column(
        String(26), ForeignKey("overrides.id", ondelete="CASCADE"), nullable=False, index=True
    )
    target_id: Any = Column(String(26), nullable=False, index=True)
    target_type: Any = Column(String(100), nullable=False)
    is_active: Any = Column(Boolean, nullable=False, default=True)
    created_at: Any = Column(
        DateTime,
        nullable=False,
        default=datetime.utcnow,
        server_default=func.now(),
    )

    override: Any = relationship("Override", back_populates="watermarks")


class DraftAutosave(TimestampMixin, Base):
    """
    A persisted draft autosave for a strategy being composed by an operator.

    Responsibilities:
    - Persist partial strategy drafts between browser sessions.
    - Enable DraftRecoveryBanner to offer recovery of incomplete drafts on login.

    Does NOT:
    - Validate draft content (partial drafts may be incomplete).
    - Enforce strategy submission logic.

    Attributes:
        id: ULID primary key.
        user_id: FK to User who owns this draft.
        strategy_id: FK to Strategy (nullable — may not exist yet).
        draft_payload: JSON blob containing the partial draft form state.
        created_at: Row insertion timestamp.
        updated_at: Last modification timestamp (updated on each autosave).

    Example:
        autosave = DraftAutosave(
            id="01H...",
            user_id="01H...",
            draft_payload={"name": "MyStrategy", "lookback": 30},
        )
    """

    __tablename__ = "draft_autosaves"

    id: Any = Column(String(26), primary_key=True, nullable=False)
    user_id: Any = Column(
        String(26), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    strategy_id: Any = Column(
        String(26), ForeignKey("strategies.id", ondelete="RESTRICT"), nullable=True, index=True
    )
    draft_payload: Any = Column(JSON, nullable=False, default=dict)
    # UI recovery context — captured on every autosave for DraftRecoveryBanner.
    form_step: Any = Column(String(100), nullable=True)
    session_id: Any = Column(String(255), nullable=True)
    client_ts: Any = Column(String(50), nullable=True)


class ChartCache(Base):
    """
    Generic chart cache with TTL-based eviction (M14-T9 Gap 4).

    Responsibilities:
    - Cache computed chart data (equity, drawdown, etc.) for any run/chart type.
    - Support TTL-based eviration: expired entries are treated as cache misses.
    - Track creation time and expiration time for lifecycle management.

    Does NOT:
    - Compute chart data (handled by services).
    - Perform business logic.

    Attributes:
        cache_key: Composite key: "{run_id}:{chart_type}" (PK).
        run_id: Run ULID for which chart was computed.
        chart_type: Chart type (equity_curve, drawdown, etc).
        data: Serialized chart data (JSON — typically points, metadata, etc).
        created_at: Cache entry creation timestamp (auto-populated).
        expires_at: When this cache entry expires and should be treated as a miss.
            Set to now + TTL on every update.

    Example:
        cache = ChartCache(
            cache_key="run_123:equity_curve",
            run_id="run_123",
            chart_type="equity_curve",
            data={"points": [...], "sampling_applied": true, ...},
            created_at=datetime.now(timezone.utc),
            expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
        )
    """

    __tablename__ = "chart_cache"

    cache_key: Any = Column(String(255), primary_key=True, nullable=False, index=True)
    run_id: Any = Column(String(26), nullable=False, index=True)
    chart_type: Any = Column(String(100), nullable=False, index=True)
    data: Any = Column(JSON, nullable=False)
    created_at: Any = Column(
        DateTime,
        nullable=False,
        default=datetime.utcnow,
        server_default=func.now(),
    )
    expires_at: Any = Column(DateTime, nullable=False, index=True)


class ChartCacheEntry(TimestampMixin, Base):
    """
    Write-through cache of pre-computed equity and drawdown chart data for a run.

    Responsibilities:
    - Cache expensive chart computation results to serve the UI without recomputation.
    - Track whether data was downsampled and whether the run is still in progress.

    Does NOT:
    - Perform chart computation.
    - Contain business logic.

    Attributes:
        id: ULID primary key.
        run_id: FK to Run (unique — one cache entry per run).
        equity_points: JSON array of {ts, value} equity curve data points.
        drawdown_points: JSON array of {ts, value} drawdown data points.
        sampling_applied: True if the raw point count exceeded the UI threshold
            and the series was downsampled.
        raw_equity_point_count: Original point count before sampling (nullable).
        is_partial: True if the run is still in progress and data is incomplete.
        created_at: Cache population timestamp.
        updated_at: Last cache refresh timestamp.
    """

    __tablename__ = "chart_cache_entries"

    id: Any = Column(String(26), primary_key=True, nullable=False)
    run_id: Any = Column(
        String(26),
        ForeignKey("runs.id", ondelete="RESTRICT"),
        nullable=False,
        unique=True,
        index=True,
    )
    equity_points: Any = Column(JSON, nullable=True)
    drawdown_points: Any = Column(JSON, nullable=True)
    sampling_applied: Any = Column(Boolean, nullable=False, default=False)
    raw_equity_point_count: Any = Column(Integer, nullable=True)
    is_partial: Any = Column(Boolean, nullable=False, default=False)


class CertificationEvent(TimestampMixin, Base):
    """
    A certification check result for a feed or run.

    Responsibilities:
    - Record certification gate outcomes (pass/fail/pending) for compliance auditing.
    - Expose blocked status for downstream gate enforcement.

    Does NOT:
    - Execute certification checks.
    - Contain business logic.

    Attributes:
        id: ULID primary key.
        feed_id: FK to Feed being certified (nullable — may certify a run instead).
        run_id: FK to Run being certified (nullable — may certify a feed instead).
        certification_type: Gate classifier (e.g. data_quality, backtest_coverage).
        status: Certification status (pending, passed, failed).
        blocked: True if this event blocks downstream operations.
        details: JSON blob with certification check details.
        certified_at: When the certification decision was made (nullable until decided).
        created_at: Row insertion timestamp.
        updated_at: Last status update timestamp.
    """

    __tablename__ = "certification_events"
    __table_args__ = (
        CheckConstraint(
            "status IN ('pending', 'passed', 'failed', 'certified', 'blocked', 'expired')",
            name="chk_certification_events_status",
        ),
    )

    id: Any = Column(String(26), primary_key=True, nullable=False)
    feed_id: Any = Column(
        String(26), ForeignKey("feeds.id", ondelete="RESTRICT"), nullable=True, index=True
    )
    run_id: Any = Column(
        String(26), ForeignKey("runs.id", ondelete="RESTRICT"), nullable=True, index=True
    )
    certification_type: Any = Column(String(100), nullable=False, index=True)
    status: Any = Column(String(50), nullable=False, default="pending")
    blocked: Any = Column(Boolean, nullable=False, default=False)
    details: Any = Column(JSON, nullable=True)
    certified_at: Any = Column(DateTime, nullable=True)


class RefreshToken(Base):
    """
    Server-side refresh token for OIDC-compatible token endpoint.

    Refresh tokens are long-lived (default 7 days) and stored server-side
    as SHA-256 hashes. They support single-token revocation (logout) and
    bulk revocation per user (force logout / security incident).

    Responsibilities:
    - Store hashed refresh tokens with expiry and revocation timestamps.
    - Support lookup by token_hash for validation during refresh grant.
    - Support bulk deletion/revocation by user_id.

    Does NOT:
    - Store plaintext tokens (only SHA-256 hashes).
    - Contain token creation or signing logic.
    - Enforce business rules (that is the service layer's job).

    Attributes:
        id: ULID primary key (26-char string).
        user_id: FK to the user who owns this refresh token.
        token_hash: SHA-256 hex digest of the plaintext refresh token.
        expires_at: Absolute UTC expiry timestamp.
        revoked_at: UTC timestamp when revoked (None if active).
        created_at: Row insertion timestamp.
    """

    __tablename__ = "refresh_tokens"

    __allow_unmapped__ = True

    id: Any = Column(String(26), primary_key=True, nullable=False)
    user_id: Any = Column(
        String(26), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    token_hash: Any = Column(String(64), nullable=False, unique=True, index=True)
    expires_at: Any = Column(DateTime, nullable=False)
    revoked_at: Any = Column(DateTime, nullable=True)
    created_at: Any = Column(
        DateTime,
        nullable=False,
        default=datetime.utcnow,
        server_default=func.now(),
    )


class RevokedToken(Base):
    """
    Token revocation blacklist for JWT tokens (HS256 and Keycloak RS256).

    Tracks revoked JWT tokens by their JTI (JWT ID) claim. When a user logs out
    or a token is compromised, the token's JTI is added to this blacklist.
    The TokenBlacklistService checks this table during token validation.

    Responsibilities:
    - Store revoked token JTIs with expiry and revocation timestamps.
    - Support lookup by JTI for validation during token processing.
    - Support cleanup of expired entries (purge_expired operation).

    Does NOT:
    - Contain token creation or signing logic.
    - Enforce revocation business rules (that is the service layer's job).

    Attributes:
        jti: JWT ID claim value (UUID string, primary key).
        revoked_at: UTC timestamp when the token was revoked.
        expires_at: Absolute UTC expiry timestamp of the original token.
        reason: Free-text reason for revocation (e.g. "logout", "compromised").
    """

    __tablename__ = "revoked_tokens"

    __allow_unmapped__ = True

    jti: Any = Column(String(36), primary_key=True, nullable=False)
    revoked_at: Any = Column(
        DateTime,
        nullable=False,
        default=datetime.utcnow,
        server_default=func.now(),
    )
    expires_at: Any = Column(DateTime, nullable=False)
    reason: Any = Column(String(255), nullable=True)


class SymbolLineageEntry(Base):
    """
    A lineage record tracking the provenance of a trading symbol through feeds and runs.

    Responsibilities:
    - Record where a symbol's data originated (feed, run, transformation).
    - Support compliance auditing of data provenance.

    Does NOT:
    - Contain business logic or data transformation logic.
    - Support UPDATE — lineage entries are append-only.

    Attributes:
        id: ULID primary key.
        symbol: Ticker symbol string (e.g. "AAPL", "ES=F").
        feed_id: FK to Feed that sourced this symbol (nullable).
        run_id: FK to Run that consumed this symbol (nullable).
        lineage_type: Classifier (e.g. raw_ingest, transformed, backfilled).
        details: JSON blob with provenance details.
        created_at: Row insertion timestamp (immutable).
    """

    __tablename__ = "symbol_lineage_entries"

    __allow_unmapped__ = True

    id: Any = Column(String(26), primary_key=True, nullable=False)
    symbol: Any = Column(String(50), nullable=False, index=True)
    feed_id: Any = Column(
        String(26), ForeignKey("feeds.id", ondelete="RESTRICT"), nullable=True, index=True
    )
    run_id: Any = Column(
        String(26), ForeignKey("runs.id", ondelete="RESTRICT"), nullable=True, index=True
    )
    lineage_type: Any = Column(String(100), nullable=True)
    details: Any = Column(JSON, nullable=True)
    created_at: Any = Column(
        DateTime,
        nullable=False,
        default=datetime.utcnow,
        server_default=func.now(),
    )


class PromotionRequest(TimestampMixin, Base):
    """
    A formal request to promote a strategy candidate to a target environment.

    Responsibilities:
    - Capture promotion intent (candidate, target environment, rationale).
    - Record the review decision and the reviewing operator.
    - Provide the link to supporting evidence required for SOC 2 compliance.

    Does NOT:
    - Execute the promotion.
    - Enforce separation-of-duties (service layer responsibility).

    Attributes:
        id: ULID primary key.
        candidate_id: FK to Candidate being promoted (nullable for orphan recovery).
        requester_id: FK to User initiating the promotion.
        target_environment: Target env (paper, live).
        status: Lifecycle status (pending, approved, rejected, withdrawn).
        rationale: Free-text justification for promotion.
        evidence_link: Absolute HTTP/HTTPS URI to supporting evidence.
        reviewer_id: FK to reviewing User (nullable until decided).
        decision_rationale: Reviewer's free-text decision justification.
        decided_at: When the review decision was made.
        created_at: Request submission timestamp.
        updated_at: Last modification timestamp.
    """

    __tablename__ = "promotion_requests"
    __table_args__ = (
        CheckConstraint(
            "status IN ('pending', 'validating', 'approved', 'rejected', "
            "'deploying', 'completed', 'failed')",
            name="chk_promotion_requests_status",
        ),
        CheckConstraint(
            "target_environment IN ('paper', 'live')",
            name="chk_promotion_requests_target_environment",
        ),
    )

    id: Any = Column(String(26), primary_key=True, nullable=False)
    candidate_id: Any = Column(
        String(26), ForeignKey("candidates.id", ondelete="RESTRICT"), nullable=True, index=True
    )
    requester_id: Any = Column(
        String(26), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    target_environment: Any = Column(String(50), nullable=False)
    status: Any = Column(String(50), nullable=False, default="pending")
    rationale: Any = Column(Text, nullable=True)
    evidence_link: Any = Column(String(512), nullable=True)
    reviewer_id: Any = Column(
        String(26), ForeignKey("users.id", ondelete="RESTRICT"), nullable=True, index=True
    )
    decision_rationale: Any = Column(Text, nullable=True)
    decided_at: Any = Column(DateTime, nullable=True)


# ---------------------------------------------------------------------------
# Phase 4: Execution models
# ---------------------------------------------------------------------------


class Order(TimestampMixin, Base):
    """
    Broker order record in the normalized execution model.

    Responsibilities:
    - Persist every order submitted through any execution mode (shadow/paper/live).
    - Track order lifecycle from submission through fill/cancel/reject.
    - Enforce idempotency via unique client_order_id constraint.

    Does NOT:
    - Contain order submission logic (service layer responsibility).
    - Perform risk checks (risk gate service responsibility).

    Attributes:
        id: ULID primary key.
        client_order_id: Caller-assigned idempotency key (unique).
        deployment_id: FK to Deployment that owns this order.
        strategy_id: FK to Strategy that generated the signal.
        symbol: Instrument ticker (e.g. "AAPL", "ES=F").
        side: Order direction ("buy" or "sell").
        order_type: Order type ("market", "limit", "stop", "stop_limit").
        quantity: Requested quantity (string for decimal precision).
        limit_price: Limit price (nullable; required for limit/stop_limit).
        stop_price: Stop price (nullable; required for stop/stop_limit).
        time_in_force: Duration policy ("day", "gtc", "ioc", "fok").
        status: Current lifecycle status.
        broker_order_id: Broker-assigned identifier (nullable until ack).
        submitted_at: When the order was sent to the broker.
        filled_at: When the order was fully filled (nullable).
        cancelled_at: When the order was cancelled (nullable).
        average_fill_price: VWAP of all fills (string for precision).
        filled_quantity: Cumulative filled quantity (string for precision).
        rejected_reason: Human-readable rejection reason (nullable).
        correlation_id: Distributed tracing ID from the originating signal.
        execution_mode: Execution mode ("shadow", "paper", "live").

    Example:
        order = Order(
            id="01HORDER...",
            client_order_id="ord-001",
            deployment_id="01HDEPLOY...",
            strategy_id="01HSTRAT...",
            symbol="AAPL",
            side="buy",
            order_type="market",
            quantity="100",
            time_in_force="day",
            status="submitted",
            correlation_id="corr-abc",
            execution_mode="paper",
        )
    """

    __tablename__ = "orders"
    __table_args__ = (
        CheckConstraint(
            "side IN ('buy', 'sell')",
            name="chk_orders_side",
        ),
        CheckConstraint(
            "order_type IN ('market', 'limit', 'stop', 'stop_limit')",
            name="chk_orders_order_type",
        ),
        CheckConstraint(
            "time_in_force IN ('day', 'gtc', 'ioc', 'fok')",
            name="chk_orders_time_in_force",
        ),
        CheckConstraint(
            "status IN ('pending', 'submitted', 'partial_fill', 'filled', "
            "'cancelled', 'rejected', 'expired')",
            name="chk_orders_status",
        ),
        CheckConstraint(
            "execution_mode IN ('shadow', 'paper', 'live')",
            name="chk_orders_execution_mode",
        ),
    )

    id: Any = Column(String(26), primary_key=True, nullable=False)
    client_order_id: Any = Column(String(255), nullable=False, unique=True, index=True)
    deployment_id: Any = Column(
        String(26),
        ForeignKey("deployments.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    strategy_id: Any = Column(
        String(26),
        ForeignKey("strategies.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    symbol: Any = Column(String(50), nullable=False, index=True)
    side: Any = Column(String(10), nullable=False)
    order_type: Any = Column(String(20), nullable=False)
    quantity: Any = Column(String(50), nullable=False)
    limit_price: Any = Column(String(50), nullable=True)
    stop_price: Any = Column(String(50), nullable=True)
    time_in_force: Any = Column(String(10), nullable=False, default="day")
    status: Any = Column(String(20), nullable=False, default="pending")
    broker_order_id: Any = Column(String(255), nullable=True, index=True)
    submitted_at: Any = Column(DateTime, nullable=True)
    filled_at: Any = Column(DateTime, nullable=True)
    cancelled_at: Any = Column(DateTime, nullable=True)
    average_fill_price: Any = Column(String(50), nullable=True)
    filled_quantity: Any = Column(String(50), nullable=False, default="0")
    rejected_reason: Any = Column(Text, nullable=True)
    correlation_id: Any = Column(String(255), nullable=False, index=True)
    execution_mode: Any = Column(String(10), nullable=False)
    row_version: Any = Column(Integer, nullable=False, default=1, server_default="1")

    fills = relationship(
        "OrderFill", back_populates="order", uselist=True, cascade="all, delete-orphan"
    )
    execution_events = relationship(
        "ExecutionEvent", back_populates="order", uselist=True, cascade="all, delete-orphan"
    )


class OrderFill(TimestampMixin, Base):
    """
    Individual fill event for an order.

    Responsibilities:
    - Record each partial or complete fill from the broker adapter.
    - Support reconciliation by linking broker execution IDs to internal orders.

    Does NOT:
    - Aggregate fills (service layer computes VWAP from fills).
    - Contain business logic.

    Attributes:
        id: ULID primary key.
        order_id: FK to Order.
        fill_id: Broker-assigned fill identifier.
        price: Execution price per unit (string for precision).
        quantity: Units filled in this event (string for precision).
        commission: Broker commission charged (string for precision).
        filled_at: When this fill occurred.
        broker_execution_id: Broker-assigned execution/trade ID.
        correlation_id: Distributed tracing ID.

    Example:
        fill = OrderFill(
            id="01HFILL...",
            order_id="01HORDER...",
            fill_id="fill-001",
            price="175.50",
            quantity="50",
            commission="0.00",
            filled_at=datetime(2026, 4, 11, 10, 0, 0),
            correlation_id="corr-abc",
        )
    """

    __tablename__ = "order_fills"

    id: Any = Column(String(26), primary_key=True, nullable=False)
    order_id: Any = Column(
        String(26),
        ForeignKey("orders.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    fill_id: Any = Column(String(255), nullable=False)
    price: Any = Column(String(50), nullable=False)
    quantity: Any = Column(String(50), nullable=False)
    commission: Any = Column(String(50), nullable=False, default="0")
    filled_at: Any = Column(DateTime, nullable=False)
    broker_execution_id: Any = Column(String(255), nullable=True)
    correlation_id: Any = Column(String(255), nullable=False, index=True)

    order: Any = relationship("Order", back_populates="fills")


class Position(TimestampMixin, Base):
    """
    Current position state for a deployment × symbol pair.

    Responsibilities:
    - Track the current position for each instrument in each deployment.
    - Support reconciliation by comparing internal state vs broker snapshot.

    Does NOT:
    - Compute position changes (service layer responsibility).
    - Contain risk logic.

    Attributes:
        id: ULID primary key.
        deployment_id: FK to Deployment.
        symbol: Instrument ticker.
        quantity: Current position size (string; negative for short).
        average_entry_price: Volume-weighted average entry price (string).
        market_price: Latest market price (string).
        market_value: quantity × market_price (string).
        unrealized_pnl: Unrealized P&L (string).
        realized_pnl: Cumulative realized P&L (string).
        cost_basis: Total cost basis (string).

    Example:
        pos = Position(
            id="01HPOS...",
            deployment_id="01HDEPLOY...",
            symbol="AAPL",
            quantity="100",
            average_entry_price="175.00",
            market_price="180.00",
            market_value="18000.00",
            unrealized_pnl="500.00",
            realized_pnl="0.00",
            cost_basis="17500.00",
        )
    """

    __tablename__ = "positions"

    id: Any = Column(String(26), primary_key=True, nullable=False)
    deployment_id: Any = Column(
        String(26),
        ForeignKey("deployments.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    symbol: Any = Column(String(50), nullable=False, index=True)
    quantity: Any = Column(String(50), nullable=False, default="0")
    average_entry_price: Any = Column(String(50), nullable=False, default="0")
    market_price: Any = Column(String(50), nullable=False, default="0")
    market_value: Any = Column(String(50), nullable=False, default="0")
    unrealized_pnl: Any = Column(String(50), nullable=False, default="0")
    realized_pnl: Any = Column(String(50), nullable=False, default="0")
    cost_basis: Any = Column(String(50), nullable=False, default="0")


class ExecutionEvent(Base):
    """
    Append-only execution audit event for order timeline reconstruction.

    Responsibilities:
    - Record every lifecycle event for an order (submitted, filled, cancelled, etc.).
    - Support correlation ID search for debugging and compliance replay.
    - Provide the data source for order timeline views (M8).

    Does NOT:
    - Contain business logic or execution orchestration.
    - Support UPDATE or DELETE (append-only).

    Attributes:
        id: ULID primary key.
        order_id: FK to Order.
        event_type: Lifecycle event type (submitted, partial_fill, filled,
                    cancelled, rejected, risk_checked, risk_failed, etc.).
        timestamp: When the event occurred.
        details: JSON blob with event-specific context.
        correlation_id: Distributed tracing ID.

    Example:
        evt = ExecutionEvent(
            id="01HEVT...",
            order_id="01HORDER...",
            event_type="submitted",
            timestamp=datetime(2026, 4, 11, 10, 0, 0),
            details={"broker_order_id": "ALPACA-12345"},
            correlation_id="corr-abc",
        )
    """

    __tablename__ = "execution_events"

    __allow_unmapped__ = True

    id: Any = Column(String(26), primary_key=True, nullable=False)
    order_id: Any = Column(
        String(26),
        ForeignKey("orders.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    event_type: Any = Column(String(50), nullable=False, index=True)
    timestamp: Any = Column(DateTime, nullable=False)
    details: Any = Column(JSON, nullable=False, default=dict)
    correlation_id: Any = Column(String(255), nullable=False, index=True)

    order: Any = relationship("Order", back_populates="execution_events")


class KillSwitchEvent(TimestampMixin, Base):
    """
    Kill switch activation/deactivation record.

    Responsibilities:
    - Record every kill switch activation and deactivation for audit trail.
    - Track scope (global, per-strategy, per-symbol) and target.
    - Support MTTH measurement (time from activation to all-orders-cancelled).

    Does NOT:
    - Enforce kill switch logic (service layer responsibility).
    - Revoke permissions directly.

    Attributes:
        id: ULID primary key.
        scope: Kill switch scope ("global", "strategy", "symbol").
        target_id: Target identifier (strategy_id, symbol, or "global").
        activated_by: ULID of the user or system identity that activated.
        activated_at: When the kill switch was activated.
        deactivated_at: When the kill switch was deactivated (nullable).
        reason: Human-readable activation reason.
        mtth_ms: Measured mean time to halt in milliseconds (nullable).

    Example:
        ks = KillSwitchEvent(
            id="01HKS...",
            scope="strategy",
            target_id="01HSTRAT...",
            activated_by="user:01HUSER...",
            activated_at=datetime(2026, 4, 11, 10, 0, 0),
            reason="Daily loss limit breached",
        )
    """

    __tablename__ = "kill_switch_events"
    __table_args__ = (
        CheckConstraint(
            "scope IN ('global', 'strategy', 'symbol')",
            name="chk_kill_switch_events_scope",
        ),
    )

    id: Any = Column(String(26), primary_key=True, nullable=False)
    scope: Any = Column(String(20), nullable=False, index=True)
    target_id: Any = Column(String(255), nullable=False, index=True)
    activated_by: Any = Column(String(255), nullable=False)
    activated_at: Any = Column(DateTime, nullable=False)
    deactivated_at: Any = Column(DateTime, nullable=True)
    reason: Any = Column(Text, nullable=False)
    mtth_ms: Any = Column(Integer, nullable=True)


class ReconciliationReport(TimestampMixin, Base):
    """
    Reconciliation run result record.

    Responsibilities:
    - Record every reconciliation run (startup, reconnect, scheduled, manual).
    - Track discrepancies found and resolution status.
    - Support audit trail for compliance.

    Does NOT:
    - Execute reconciliation logic (service layer responsibility).
    - Resolve discrepancies automatically.

    Attributes:
        id: ULID primary key.
        deployment_id: FK to Deployment being reconciled.
        trigger: What triggered this recon run ("startup", "reconnect",
                 "scheduled", "manual").
        started_at: When the recon run began.
        completed_at: When the recon run finished (nullable until done).
        status: Run status ("running", "completed", "failed").
        discrepancies: JSON array of discrepancy records.
        resolved_count: Number of discrepancies auto-resolved.
        unresolved_count: Number of discrepancies requiring operator review.

    Example:
        report = ReconciliationReport(
            id="01HRECON...",
            deployment_id="01HDEPLOY...",
            trigger="startup",
            started_at=datetime(2026, 4, 11, 10, 0, 0),
            status="running",
        )
    """

    __tablename__ = "reconciliation_reports"
    __table_args__ = (
        CheckConstraint(
            "status IN ('running', 'completed', 'failed')",
            name="chk_reconciliation_reports_status",
        ),
        CheckConstraint(
            "trigger IN ('startup', 'reconnect', 'scheduled', 'manual')",
            name="chk_reconciliation_reports_trigger",
        ),
    )

    id: Any = Column(String(26), primary_key=True, nullable=False)
    deployment_id: Any = Column(
        String(26),
        ForeignKey("deployments.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    trigger: Any = Column(String(20), nullable=False)
    started_at: Any = Column(DateTime, nullable=False)
    completed_at: Any = Column(DateTime, nullable=True)
    status: Any = Column(String(20), nullable=False, default="running")
    discrepancies: Any = Column(JSON, nullable=False, default=list)
    resolved_count: Any = Column(Integer, nullable=False, default=0)
    unresolved_count: Any = Column(Integer, nullable=False, default=0)


class RiskEvent(Base):
    """
    Append-only risk check audit event for pre-trade risk gate decisions.

    Responsibilities:
    - Record every pre-trade risk check result for compliance audit trail.
    - Support filtering by deployment, severity, and time range.
    - Provide durable persistence for risk events (replacing in-memory storage).

    Does NOT:
    - Make risk decisions (RiskGateService responsibility).
    - Support UPDATE or DELETE (append-only semantics).

    Attributes:
        id: ULID primary key.
        deployment_id: FK to Deployment being risk-checked.
        order_id: FK to Order that triggered the check (nullable for non-order checks).
        check_name: Name of the risk check performed (e.g. "position_limit",
                    "daily_loss", "max_order_value").
        passed: Whether the check passed.
        severity: Event severity level ("info", "warning", "critical", "halt").
        reason: Human-readable reason for failure (nullable if passed).
        current_value: The current value that was checked (decimal string).
        limit_value: The limit value compared against (decimal string).
        order_client_id: Client order ID that triggered the check (nullable).
        symbol: Symbol involved in the check (nullable).
        correlation_id: Distributed tracing ID (nullable).
        created_at: Timestamp when the event was recorded.

    Example:
        evt = RiskEvent(
            id="01HRISK...",
            deployment_id="01HDEPLOY...",
            check_name="daily_loss",
            passed=False,
            severity="critical",
            reason="Daily loss $6000 exceeds limit $5000",
            current_value="6000",
            limit_value="5000",
            correlation_id="corr-abc",
        )
    """

    __tablename__ = "risk_events"
    __table_args__ = (
        CheckConstraint(
            "severity IN ('info', 'warning', 'critical', 'halt')",
            name="chk_risk_events_severity",
        ),
    )

    __allow_unmapped__ = True

    id: Any = Column(String(26), primary_key=True, nullable=False)
    deployment_id: Any = Column(
        String(26),
        ForeignKey("deployments.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    order_id: Any = Column(
        String(26),
        ForeignKey("orders.id", ondelete="SET NULL"),
        nullable=True,
    )
    check_name: Any = Column(String(100), nullable=False)
    passed: Any = Column(Boolean, nullable=False)
    severity: Any = Column(String(20), nullable=False, index=True)
    reason: Any = Column(Text, nullable=True)
    current_value: Any = Column(String(50), nullable=True)
    limit_value: Any = Column(String(50), nullable=True)
    order_client_id: Any = Column(String(255), nullable=True)
    symbol: Any = Column(String(50), nullable=True)
    correlation_id: Any = Column(String(255), nullable=True, index=True)
    created_at: Any = Column(DateTime, nullable=False)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


class PnlSnapshot(TimestampMixin, Base):
    """
    Daily P&L snapshot for a deployment.

    Responsibilities:
    - Record daily P&L state for historical tracking, timeseries, and
      performance attribution analysis.
    - Support equity curve rendering and drawdown calculations.
    - Provide the data source for P&L timeseries endpoints (M9).

    Does NOT:
    - Compute P&L values (PnlAttributionService responsibility).
    - Contain business logic or aggregation.
    - Support real-time P&L (use position table for current state).

    Attributes:
        id: ULID primary key.
        deployment_id: FK to Deployment owning this snapshot.
        snapshot_date: Date of the snapshot (date only, no time component).
        realized_pnl: Cumulative realized P&L as string (decimal precision).
        unrealized_pnl: Unrealized P&L at snapshot time as string.
        commission: Cumulative commissions paid as string.
        fees: Cumulative exchange/regulatory fees as string.
        positions_count: Number of open positions at snapshot time.

    Example:
        snapshot = PnlSnapshot(
            id="01HSNAP001ABC...",
            deployment_id="01HDEPLOY...",
            snapshot_date=date(2026, 4, 12),
            realized_pnl="1250.50",
            unrealized_pnl="340.25",
            commission="52.00",
            fees="0",
            positions_count=5,
        )
    """

    __tablename__ = "pnl_snapshots"
    __table_args__ = (
        UniqueConstraint(
            "deployment_id",
            "snapshot_date",
            name="uq_pnl_snapshots_deployment_date",
        ),
    )

    id: Any = Column(String(26), primary_key=True, nullable=False)
    deployment_id: Any = Column(
        String(26),
        ForeignKey("deployments.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    snapshot_date: Any = Column(Date, nullable=False, index=True)
    realized_pnl: Any = Column(String(50), nullable=False, default="0")
    unrealized_pnl: Any = Column(String(50), nullable=False, default="0")
    commission: Any = Column(String(50), nullable=False, default="0")
    fees: Any = Column(String(50), nullable=False, default="0")
    positions_count: Any = Column(Integer, nullable=False, default=0)


# ---------------------------------------------------------------------------
# Archive tables (Phase 6 — M12: Data Retention Policy)
# ---------------------------------------------------------------------------


class ArchivedAuditEvent(Base):
    """
    Archive table for soft-deleted audit events.

    Mirrors the AuditEvent table columns plus an archived_at timestamp
    indicating when the record was moved to the archive.  Records in
    this table are recoverable during the grace period and permanently
    purged after it expires.

    Responsibilities:
        - Hold audit events past their retention period.
        - Track when records were archived for grace period enforcement.

    Does NOT:
        - Contain business logic.
        - Modify the source table (service responsibility).
    """

    __tablename__ = "archived_audit_events"

    id: Any = Column(String(26), primary_key=True, nullable=False)
    actor: Any = Column(String(255), nullable=False, index=True)
    action: Any = Column(String(255), nullable=False)
    object_id: Any = Column(String(26), nullable=False)
    object_type: Any = Column(String(100), nullable=False)
    event_metadata: Any = Column("metadata", JSON, nullable=False, default=dict)
    created_at: Any = Column(DateTime, nullable=False)
    archived_at: Any = Column(
        DateTime,
        nullable=False,
        default=datetime.utcnow,
        server_default=func.now(),
    )


class ArchivedOrder(Base):
    """
    Archive table for soft-deleted orders.

    Mirrors key Order table columns plus an archived_at timestamp.
    Records in this table are recoverable during the grace period and
    permanently purged after it expires.

    Responsibilities:
        - Hold orders past their retention period.
        - Track when records were archived.

    Does NOT:
        - Contain business logic.
        - Track fills (OrderFill records are archived separately if needed).
    """

    __tablename__ = "archived_orders"

    id: Any = Column(String(26), primary_key=True, nullable=False)
    client_order_id: Any = Column(String(255), nullable=False)
    deployment_id: Any = Column(String(26), nullable=False, index=True)
    strategy_id: Any = Column(String(26), nullable=False)
    symbol: Any = Column(String(20), nullable=False)
    side: Any = Column(String(10), nullable=False)
    order_type: Any = Column(String(20), nullable=False)
    quantity: Any = Column(String(50), nullable=False)
    status: Any = Column(String(50), nullable=False)
    execution_mode: Any = Column(String(20), nullable=False)
    submitted_at: Any = Column(DateTime, nullable=True)
    created_at: Any = Column(DateTime, nullable=False)
    updated_at: Any = Column(DateTime, nullable=True)
    archived_at: Any = Column(
        DateTime,
        nullable=False,
        default=datetime.utcnow,
        server_default=func.now(),
    )


class AuditExportJob(Base):
    """
    Persisted audit export job metadata.

    Tracks the status, parameters, and results of audit export operations
    so they can be retrieved later for download.

    Responsibilities:
        - Store export job lifecycle (pending → running → completed/failed).
        - Record content hash for tamper detection.

    Does NOT:
        - Store the export content bytes (stored separately as files/blobs).
    """

    __tablename__ = "audit_export_jobs"

    id: Any = Column(String(26), primary_key=True, nullable=False)
    status: Any = Column(String(20), nullable=False, default="pending")
    record_count: Any = Column(Integer, nullable=False, default=0)
    content_hash: Any = Column(String(128), nullable=False, default="")
    byte_size: Any = Column(Integer, nullable=False, default=0)
    format: Any = Column(String(10), nullable=False, default="json")
    compressed: Any = Column(Boolean, nullable=False, default=False)
    created_by: Any = Column(String(255), nullable=False, default="")
    error_message: Any = Column(Text, nullable=False, default="")
    created_at: Any = Column(
        DateTime,
        nullable=False,
        default=datetime.utcnow,
        server_default=func.now(),
    )
    completed_at: Any = Column(DateTime, nullable=True)


# ---------------------------------------------------------------------------
# Market Data — OHLCV candle storage (Phase 7 M0)
# ---------------------------------------------------------------------------


class CandleRecord(Base):
    """
    Persisted OHLCV candlestick record.

    Stores normalized market data from any provider (Alpaca, Schwab, etc.)
    in a single canonical table. Keyed by (symbol, interval, timestamp) to
    enforce uniqueness and enable efficient time-range queries.

    Responsibilities:
    - Store one OHLCV bar per (symbol, interval, timestamp) triple.
    - Support bulk upsert (INSERT ON CONFLICT UPDATE) for idempotent ingestion.
    - Support efficient time-ordered reads via composite index.

    Does NOT:
    - Contain indicator calculation logic.
    - Know which provider supplied the data.

    Attributes:
        id: Auto-increment integer primary key (internal — not exposed in API).
        symbol: Ticker symbol (e.g., "AAPL"). Indexed.
        interval: Candle interval string (e.g., "1m", "1d").
        timestamp: UTC timestamp of the candle open. Part of unique constraint.
        open: Opening price (string for decimal precision).
        high: Highest price in interval (string).
        low: Lowest price in interval (string).
        close: Closing price (string).
        volume: Total shares/contracts traded.
        vwap: Volume-weighted average price (nullable).
        trade_count: Number of individual trades (nullable).

    Example:
        record = CandleRecord(
            symbol="AAPL",
            interval="1d",
            timestamp=datetime(2026, 4, 10),
            open="174.50",
            high="176.25",
            low="173.80",
            close="175.90",
            volume=58000000,
        )
    """

    __tablename__ = "candle_records"
    __table_args__ = (
        UniqueConstraint(
            "symbol",
            "interval",
            "timestamp",
            name="uq_candle_symbol_interval_timestamp",
        ),
    )

    id: Any = Column(Integer, primary_key=True, autoincrement=True)
    symbol: Any = Column(String(10), nullable=False, index=True)
    interval: Any = Column(String(5), nullable=False, index=True)
    timestamp: Any = Column(DateTime, nullable=False, index=True)
    open: Any = Column(String(50), nullable=False)
    high: Any = Column(String(50), nullable=False)
    low: Any = Column(String(50), nullable=False)
    close: Any = Column(String(50), nullable=False)
    volume: Any = Column(Integer, nullable=False, default=0)
    vwap: Any = Column(String(50), nullable=True)
    trade_count: Any = Column(Integer, nullable=True)


class DataGapRecord(Base):
    """
    Detected data gap in candle records.

    Tracks gaps in market data for monitoring and backfill scheduling.
    A gap means that consecutive candles have a time difference exceeding
    the expected interval duration (accounting for a tolerance factor).

    Responsibilities:
    - Persist detected data gaps for operator review.
    - Enable gap backfill task scheduling.

    Does NOT:
    - Trigger backfill automatically (scheduler responsibility).
    - Account for market hours (caller filters for trading hours).

    Attributes:
        id: Auto-increment integer primary key.
        symbol: Ticker symbol where the gap was detected.
        interval: Candle interval where the gap was detected.
        gap_start: Timestamp of the last candle before the gap.
        gap_end: Timestamp of the first candle after the gap.
        detected_at: When the gap was detected.

    Example:
        gap = DataGapRecord(
            symbol="AAPL",
            interval="1m",
            gap_start=datetime(2026, 4, 10, 14, 30),
            gap_end=datetime(2026, 4, 10, 14, 35),
            detected_at=datetime(2026, 4, 10, 15, 0),
        )
    """

    __tablename__ = "data_gap_records"

    id: Any = Column(Integer, primary_key=True, autoincrement=True)
    symbol: Any = Column(String(10), nullable=False, index=True)
    interval: Any = Column(String(5), nullable=False)
    gap_start: Any = Column(DateTime, nullable=False)
    gap_end: Any = Column(DateTime, nullable=False)
    detected_at: Any = Column(
        DateTime,
        nullable=False,
        default=datetime.utcnow,
        server_default=func.now(),
    )


class RiskAlertConfigRecord(Base):
    """
    Persisted risk alert configuration per deployment (Phase 7 — M11).

    Stores threshold values for VaR, concentration, and correlation alerts.
    Each deployment has at most one active configuration (upsert on save).

    Responsibilities:
    - Persist risk alert thresholds per deployment.
    - Support enable/disable toggle.

    Does NOT:
    - Evaluate alerts (service responsibility).
    - Dispatch notifications (IncidentManager responsibility).

    Attributes:
        deployment_id: Primary key — one config per deployment.
        var_threshold_pct: VaR 95% threshold as percentage string.
        concentration_threshold_pct: Concentration threshold as percentage string.
        correlation_threshold: Correlation threshold as string.
        lookback_days: Lookback period for metrics computation.
        enabled: Whether alerting is active for this deployment.
        updated_at: Last modification timestamp.

    Example:
        record = RiskAlertConfigRecord(
            deployment_id="01HTESTDEPLOY000000000000",
            var_threshold_pct="5.0",
            concentration_threshold_pct="30.0",
            correlation_threshold="0.90",
        )
    """

    __tablename__ = "risk_alert_configs"

    deployment_id: Any = Column(String(26), primary_key=True)
    var_threshold_pct: Any = Column(String(20), nullable=False, default="5.0")
    concentration_threshold_pct: Any = Column(String(20), nullable=False, default="30.0")
    correlation_threshold: Any = Column(String(20), nullable=False, default="0.90")
    lookback_days: Any = Column(Integer, nullable=False, default=252)
    enabled: Any = Column(Boolean, nullable=False, default=True)
    updated_at: Any = Column(
        DateTime,
        nullable=False,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
        server_default=func.now(),
    )


# ---------------------------------------------------------------------------
# Data Quality tables (Phase 8 — M0: Data Quality Contracts & Schema)
# ---------------------------------------------------------------------------


class DataAnomalyRecord(Base):
    """
    Persistent record of a detected data quality anomaly.

    Responsibilities:
    - Store anomaly details for audit trail and trend analysis.
    - Support filtering by symbol, interval, severity, and time range.

    Does NOT:
    - Detect anomalies (service responsibility).
    - Trigger alerts (notification infrastructure responsibility).

    Attributes:
        id: Unique anomaly identifier (ULID or UUID string).
        symbol: Ticker symbol where anomaly was detected.
        interval: Candle interval that was evaluated (e.g. "1m", "1d").
        anomaly_type: Classification of the anomaly.
        severity: Anomaly severity level ("info", "warning", "critical").
        detected_at: When the anomaly was detected.
        bar_timestamp: Timestamp of the affected bar (nullable).
        details: JSON blob with anomaly-specific details.
        resolved: Whether the anomaly has been resolved.
        resolved_at: When the anomaly was resolved (nullable).

    Example:
        record = DataAnomalyRecord(
            id="anom-001",
            symbol="AAPL",
            interval="1m",
            anomaly_type="ohlcv_violation",
            severity="critical",
            detected_at=datetime.utcnow(),
            details={"high": "170.00", "low": "175.00"},
        )
    """

    __tablename__ = "data_anomalies"
    __table_args__ = (
        CheckConstraint(
            "severity IN ('info', 'warning', 'critical')",
            name="chk_data_anomalies_severity",
        ),
        CheckConstraint(
            "anomaly_type IN ('missing_bar', 'stale_data', 'ohlcv_violation', "
            "'price_spike', 'volume_anomaly', 'timestamp_gap', 'duplicate_bar')",
            name="chk_data_anomalies_type",
        ),
    )

    id: Any = Column(String(255), primary_key=True, nullable=False)
    symbol: Any = Column(String(20), nullable=False, index=True)
    interval: Any = Column(String(5), nullable=False)
    anomaly_type: Any = Column(String(30), nullable=False)
    severity: Any = Column(String(10), nullable=False)
    detected_at: Any = Column(DateTime, nullable=False, index=True)
    bar_timestamp: Any = Column(DateTime, nullable=True)
    details: Any = Column(JSON, nullable=False, default=dict)
    resolved: Any = Column(Boolean, nullable=False, default=False)
    resolved_at: Any = Column(DateTime, nullable=True)


class QualityScoreRecord(Base):
    """
    Persistent record of a composite data quality score.

    Responsibilities:
    - Store quality dimension scores and composite grade.
    - Support upsert on (symbol, interval, window_start) for idempotency.
    - Enable quality trend analysis and trading readiness queries.

    Does NOT:
    - Compute quality scores (service responsibility).
    - Make trading readiness decisions (service responsibility).

    Attributes:
        id: Auto-increment primary key.
        symbol: Ticker symbol evaluated.
        interval: Candle interval evaluated (e.g. "1m", "1d").
        window_start: Start of the evaluation window.
        window_end: End of the evaluation window.
        completeness: Completeness dimension score [0.0, 1.0].
        timeliness: Timeliness dimension score [0.0, 1.0].
        consistency: Consistency dimension score [0.0, 1.0].
        accuracy: Accuracy dimension score [0.0, 1.0].
        composite_score: Weighted composite of all dimensions [0.0, 1.0].
        grade: Letter grade (A/B/C/D/F).
        anomaly_count: Number of anomalies in the evaluation window.
        scored_at: When the score was computed.

    Example:
        record = QualityScoreRecord(
            id="qs-001",
            symbol="AAPL",
            interval="1d",
            window_start=datetime(2026, 4, 12),
            window_end=datetime(2026, 4, 13),
            completeness=0.98,
            timeliness=0.95,
            consistency=1.0,
            accuracy=0.99,
            composite_score=0.98,
            grade="A",
            anomaly_count=1,
        )
    """

    __tablename__ = "quality_scores"
    __table_args__ = (
        UniqueConstraint(
            "symbol",
            "interval",
            "window_start",
            name="uq_quality_scores_symbol_interval_window",
        ),
        CheckConstraint(
            "grade IN ('A', 'B', 'C', 'D', 'F')",
            name="chk_quality_scores_grade",
        ),
    )

    id: Any = Column(String(255), primary_key=True, nullable=False)
    symbol: Any = Column(String(20), nullable=False, index=True)
    interval: Any = Column(String(5), nullable=False)
    window_start: Any = Column(DateTime, nullable=False, index=True)
    window_end: Any = Column(DateTime, nullable=False)
    completeness: Any = Column(String(20), nullable=False)
    timeliness: Any = Column(String(20), nullable=False)
    consistency: Any = Column(String(20), nullable=False)
    accuracy: Any = Column(String(20), nullable=False)
    composite_score: Any = Column(String(20), nullable=False)
    grade: Any = Column(String(1), nullable=False)
    anomaly_count: Any = Column(Integer, nullable=False, default=0)
    scored_at: Any = Column(
        DateTime,
        nullable=False,
        default=datetime.utcnow,
        server_default=func.now(),
    )


class SignalRecord(Base):
    """
    Persistent record of a trading signal.

    Responsibilities:
    - Store signal details for audit trail and performance analysis.
    - Support filtering by strategy, symbol, direction, and time range.

    Does NOT:
    - Generate signals (strategy responsibility).
    - Evaluate risk gates (service responsibility).

    Attributes:
        id: Unique signal identifier (ULID).
        strategy_id: ID of the originating strategy.
        deployment_id: Deployment context.
        symbol: Ticker symbol.
        direction: Signal direction (long/short/flat).
        signal_type: Signal type (entry/exit/scale_in/scale_out/stop_adjustment).
        strength: Signal strength (strong/moderate/weak).
        suggested_entry: Suggested entry price (nullable).
        suggested_stop: Suggested stop-loss price (nullable).
        suggested_target: Suggested take-profit price (nullable).
        confidence: Confidence level [0.0, 1.0].
        indicators_used: JSON blob of indicator name → value.
        bar_timestamp: Timestamp of the triggering bar.
        generated_at: When the signal was generated.
        metadata: JSON blob of strategy-specific metadata.
        correlation_id: Request correlation ID.

    Example:
        record = SignalRecord(
            id="01HTEST0000000000000000001",
            strategy_id="strat-sma-cross",
            deployment_id="deploy-001",
            symbol="AAPL",
            direction="long",
            signal_type="entry",
            strength="strong",
            confidence=0.85,
            generated_at=datetime.utcnow(),
            correlation_id="corr-001",
        )
    """

    __tablename__ = "signals"
    __table_args__ = (
        CheckConstraint(
            "direction IN ('long', 'short', 'flat')",
            name="chk_signals_direction",
        ),
        CheckConstraint(
            "signal_type IN ('entry', 'exit', 'scale_in', 'scale_out', 'stop_adjustment')",
            name="chk_signals_type",
        ),
        CheckConstraint(
            "strength IN ('strong', 'moderate', 'weak')",
            name="chk_signals_strength",
        ),
    )

    id: Any = Column(String(255), primary_key=True, nullable=False)
    strategy_id: Any = Column(String(255), nullable=False, index=True)
    deployment_id: Any = Column(String(255), nullable=False)
    symbol: Any = Column(String(20), nullable=False, index=True)
    direction: Any = Column(String(10), nullable=False)
    signal_type: Any = Column(String(20), nullable=False)
    strength: Any = Column(String(10), nullable=False)
    suggested_entry: Any = Column(String(30), nullable=True)
    suggested_stop: Any = Column(String(30), nullable=True)
    suggested_target: Any = Column(String(30), nullable=True)
    confidence: Any = Column(String(10), nullable=False)
    indicators_used: Any = Column(JSON, nullable=False, default=dict)
    bar_timestamp: Any = Column(DateTime, nullable=False)
    generated_at: Any = Column(DateTime, nullable=False, index=True)
    metadata_blob: Any = Column(JSON, nullable=False, default=dict)
    correlation_id: Any = Column(String(255), nullable=False)


class SignalEvaluationRecord(Base):
    """
    Persistent record of a signal evaluation (risk gate results).

    Responsibilities:
    - Store evaluation outcomes for audit and traceability.
    - Support lookup by signal ID.

    Does NOT:
    - Evaluate risk gates (service responsibility).

    Attributes:
        id: Auto-increment primary key.
        signal_id: Foreign key to signals table.
        approved: Whether the signal was approved.
        risk_gate_results: JSON blob of gate results.
        position_size: Computed position size (nullable).
        adjusted_stop: Risk-adjusted stop-loss (nullable).
        rejection_reason: Reason for rejection (nullable).
        evaluated_at: When the evaluation was performed.

    Example:
        record = SignalEvaluationRecord(
            id="eval-001",
            signal_id="01HTEST0000000000000000001",
            approved=True,
            evaluated_at=datetime.utcnow(),
        )
    """

    __tablename__ = "signal_evaluations"

    id: Any = Column(String(255), primary_key=True, nullable=False)
    signal_id: Any = Column(
        String(255),
        ForeignKey("signals.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    approved: Any = Column(Boolean, nullable=False)
    risk_gate_results: Any = Column(JSON, nullable=False, default=list)
    position_size: Any = Column(String(30), nullable=True)
    adjusted_stop: Any = Column(String(30), nullable=True)
    rejection_reason: Any = Column(String(500), nullable=True)
    evaluated_at: Any = Column(DateTime, nullable=False)


class ExportJob(Base):
    """
    Persistent record of an asynchronous export job.

    Tracks export requests for data bundles (trades, runs, artifacts) through
    their lifecycle: pending → processing → complete/failed.

    Attributes:
        id: ULID primary key.
        export_type: Type of export (trades, runs, artifacts).
        object_id: ULID of the object being exported.
        status: Lifecycle status (pending, processing, complete, failed).
        artifact_uri: URI where the exported data is stored (set on completion).
        requested_by: ULID of the user who requested the export.
        error_message: Error description if status is failed.
        override_watermark: JSON metadata for watermark overrides (spec §8.2).
        created_at: When the job was created.
        updated_at: When the job was last updated.

    Example:
        export_job = ExportJob(
            id="01HEXPORT00000000000001",
            export_type="trades",
            object_id="01HRUN00000000000001",
            status="pending",
            requested_by="01HUSER00000000000001",
        )
    """

    __tablename__ = "export_jobs"
    __table_args__ = (
        CheckConstraint(
            "export_type IN ('trades', 'runs', 'artifacts')",
            name="chk_export_jobs_export_type",
        ),
        CheckConstraint(
            "status IN ('pending', 'processing', 'complete', 'failed')",
            name="chk_export_jobs_status",
        ),
    )

    id: Any = Column(String(26), primary_key=True, nullable=False)
    export_type: Any = Column(String(20), nullable=False)
    object_id: Any = Column(String(26), nullable=False, index=True)
    status: Any = Column(String(20), nullable=False, default="pending")
    artifact_uri: Any = Column(Text, nullable=True)
    requested_by: Any = Column(String(255), nullable=False, index=True)
    error_message: Any = Column(Text, nullable=True)
    override_watermark: Any = Column(JSON, nullable=True)
    created_at: Any = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at: Any = Column(
        DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow
    )


class ResearchRun(Base):
    """
    Persistent record of a research run (backtest, walk-forward, Monte Carlo,
    or composite pipeline).

    Stores the configuration as JSON and the engine result as JSON. Status
    tracks the full lifecycle: pending → queued → running → completed/failed/cancelled.

    Attributes:
        id: ULID primary key.
        run_type: Type of research (backtest, walk_forward, monte_carlo, composite).
        strategy_id: FK-like reference to the researched strategy.
        status: Current lifecycle status.
        config_json: Serialised ResearchRunConfig.
        result_json: Serialised ResearchRunResult (nullable until COMPLETED).
        error_message: Error description if FAILED.
        created_by: ULID of the submitting user.
        started_at: When execution began.
        completed_at: When execution finished.
        row_version: Optimistic locking counter.

    Example:
        record = ResearchRun(
            id="01HRUN00000000000000000001",
            run_type="backtest",
            strategy_id="01HSTRAT0000000000000001",
            status="pending",
            config_json='{"run_type": "backtest", ...}',
            created_by="01HUSER00000000000000001",
        )
    """

    __tablename__ = "research_runs"
    __table_args__ = (
        CheckConstraint(
            "run_type IN ('backtest', 'walk_forward', 'monte_carlo', 'composite')",
            name="chk_research_runs_run_type",
        ),
        CheckConstraint(
            "status IN ('pending', 'queued', 'running', 'completed', 'failed', 'cancelled')",
            name="chk_research_runs_status",
        ),
    )

    id: Any = Column(String(26), primary_key=True, nullable=False)
    run_type: Any = Column(String(50), nullable=False)
    strategy_id: Any = Column(String(26), nullable=False, index=True)
    status: Any = Column(String(50), nullable=False, default="pending")
    config_json: Any = Column(JSON, nullable=False)
    result_json: Any = Column(JSON, nullable=True)
    error_message: Any = Column(String(2000), nullable=True)
    summary_metrics: Any = Column(JSON, nullable=True)
    created_by: Any = Column(String(26), nullable=False, index=True)
    created_at: Any = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at: Any = Column(
        DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow
    )
    started_at: Any = Column(DateTime, nullable=True)
    completed_at: Any = Column(DateTime, nullable=True)
    row_version: Any = Column(Integer, nullable=False, default=1, server_default="1")


# ---------------------------------------------------------------------------
# Alertmanager webhook notifications (Phase 11 — Observability Gate)
# ---------------------------------------------------------------------------


class AlertNotificationRecord(Base):
    """
    Persisted notification received from the Prometheus Alertmanager
    webhook receiver.

    Responsibilities:
    - Append-only log of every alert the API has received, for audit
      and post-incident reconstruction.
    - Carry both flattened convenience columns (alertname, severity,
      fingerprint) and the full Alertmanager label/annotation maps so
      historical lookups do not lose fidelity.

    Does NOT:
    - Drive alerting logic (that is Alertmanager's job).
    - Deduplicate — duplicates are expected and meaningful (they
      represent Alertmanager's repeat_interval re-sends).

    Attributes:
        id: ULID primary key generated by the ingest service.
        fingerprint: Alertmanager stable alert identifier, indexed.
        status: 'firing' or 'resolved'.
        alertname: Flattened labels['alertname'] for cheap filtering.
        severity: Flattened labels['severity'].
        starts_at: When the alert started firing.
        ends_at: When the alert resolved (NULL while still firing).
        labels: Full Alertmanager labels map (JSON).
        annotations: Full Alertmanager annotations map (JSON).
        generator_url: Prometheus URL that generated the alert.
        receiver: Alertmanager receiver name.
        external_url: Alertmanager external URL at delivery.
        group_key: Alertmanager group key (stable per group).
        received_at: Wall-clock time when the API received the webhook.

    Example:
        record = AlertNotificationRecord(
            id="01HWEBHOOK000000000000000001",
            fingerprint="abcdef1234567890",
            status="firing",
            alertname="APIHighLatency",
            severity="warning",
            starts_at=datetime.utcnow(),
            received_at=datetime.utcnow(),
            receiver="default_webhook",
            group_key="{}:{alertname='APIHighLatency'}",
        )
    """

    __tablename__ = "alert_notifications"
    __table_args__ = (
        CheckConstraint(
            "status IN ('firing', 'resolved')",
            name="chk_alert_notifications_status",
        ),
    )

    id: Any = Column(String(40), primary_key=True, nullable=False)
    fingerprint: Any = Column(String(128), nullable=False, index=True)
    status: Any = Column(String(32), nullable=False, index=True)
    alertname: Any = Column(String(256), nullable=False, default="", index=True)
    severity: Any = Column(String(32), nullable=False, default="", index=True)
    starts_at: Any = Column(DateTime, nullable=False, index=True)
    ends_at: Any = Column(DateTime, nullable=True)
    labels: Any = Column(JSON, nullable=False, default=dict)
    annotations: Any = Column(JSON, nullable=False, default=dict)
    generator_url: Any = Column(Text, nullable=False, default="")
    receiver: Any = Column(String(256), nullable=False)
    external_url: Any = Column(Text, nullable=False, default="")
    group_key: Any = Column(Text, nullable=False)
    received_at: Any = Column(
        DateTime,
        nullable=False,
        default=datetime.utcnow,
        server_default=func.now(),
        index=True,
    )


__all__ = [
    "Base",
    "AlertNotificationRecord",
    "ApprovalRequest",
    "ArchivedAuditEvent",
    "ArchivedOrder",
    "Artifact",
    "AuditEvent",
    "AuditExportJob",
    "Candidate",
    "CandleRecord",
    "CertificationEvent",
    "ChartCacheEntry",
    "DataAnomalyRecord",
    "DataGapRecord",
    "Deployment",
    "DeploymentTransition",
    "DraftAutosave",
    "ExecutionEvent",
    "ExportJob",
    "Feed",
    "FeedHealthEvent",
    "KillSwitchEvent",
    "Order",
    "OrderFill",
    "Override",
    "OverrideWatermark",
    "ParityEvent",
    "PnlSnapshot",
    "Position",
    "PromotionRequest",
    "QualityScoreRecord",
    "ReconciliationReport",
    "ResearchRun",
    "RevokedToken",
    "RiskAlertConfigRecord",
    "RiskEvent",
    "Run",
    "SignalEvaluationRecord",
    "SignalRecord",
    "Strategy",
    "StrategyBuild",
    "SymbolLineageEntry",
    "Trial",
    "User",
]
