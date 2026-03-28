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

from sqlalchemy import JSON, Boolean, Column, DateTime, ForeignKey, Integer, String, Text, func
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
    created_by: Any = Column(String(26), ForeignKey("users.id"), nullable=True)
    is_active: Any = Column(Boolean, nullable=False, default=True)

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

    id: Any = Column(String(26), primary_key=True, nullable=False)
    strategy_id: Any = Column(String(26), ForeignKey("strategies.id"), nullable=False, index=True)
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

    id: Any = Column(String(26), primary_key=True, nullable=False)
    strategy_id: Any = Column(String(26), ForeignKey("strategies.id"), nullable=False, index=True)
    status: Any = Column(String(50), nullable=False, default="draft")
    submitted_by: Any = Column(String(26), ForeignKey("users.id"), nullable=True)


class Deployment(TimestampMixin, Base):
    """
    A strategy deployment to a target environment.

    Attributes:
        id: ULID primary key.
        strategy_id: FK to Strategy.
        environment: Target environment (paper, live).
        status: Deployment status.
        deployed_by: ULID of deploying user.
    """

    __tablename__ = "deployments"

    id: Any = Column(String(26), primary_key=True, nullable=False)
    strategy_id: Any = Column(String(26), ForeignKey("strategies.id"), nullable=False, index=True)
    environment: Any = Column(String(50), nullable=False)
    status: Any = Column(String(50), nullable=False, default="pending")
    deployed_by: Any = Column(String(26), ForeignKey("users.id"), nullable=True)


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

    id: Any = Column(String(26), primary_key=True, nullable=False)
    strategy_id: Any = Column(String(26), ForeignKey("strategies.id"), nullable=True, index=True)
    run_type: Any = Column(String(50), nullable=False, default="backtest")
    status: Any = Column(String(50), nullable=False, default="pending")
    started_at: Any = Column(DateTime, nullable=True)
    completed_at: Any = Column(DateTime, nullable=True)

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

    id: Any = Column(String(26), primary_key=True, nullable=False)
    run_id: Any = Column(String(26), ForeignKey("runs.id"), nullable=False, index=True)
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
    run_id: Any = Column(String(26), ForeignKey("runs.id"), nullable=True, index=True)
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
    actor: Any = Column(String(255), nullable=False)
    action: Any = Column(String(255), nullable=False)
    object_id: Any = Column(String(26), nullable=False, index=True)
    object_type: Any = Column(String(100), nullable=False)
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
    feed_type: Any = Column(String(100), nullable=False)
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

    id: Any = Column(String(26), primary_key=True, nullable=False)
    feed_id: Any = Column(String(26), ForeignKey("feeds.id"), nullable=False, index=True)
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

    id: Any = Column(String(26), primary_key=True, nullable=False)
    feed_id: Any = Column(String(26), ForeignKey("feeds.id"), nullable=True, index=True)
    reference_feed_id: Any = Column(String(26), ForeignKey("feeds.id"), nullable=True)
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

    id: Any = Column(String(26), primary_key=True, nullable=False)
    target_id: Any = Column(String(26), nullable=False, index=True)
    target_type: Any = Column(String(100), nullable=False)
    override_type: Any = Column(String(100), nullable=False)
    governance_gate: Any = Column(String(100), nullable=True)
    rationale: Any = Column(Text, nullable=True)
    evidence_link: Any = Column(String(512), nullable=True)
    submitter_id: Any = Column(String(26), ForeignKey("users.id"), nullable=True)
    status: Any = Column(String(50), nullable=False, default="pending")
    reviewer_id: Any = Column(String(26), ForeignKey("users.id"), nullable=True)
    decision_rationale: Any = Column(Text, nullable=True)
    decided_at: Any = Column(DateTime, nullable=True)
    # JSON snapshots of the entity state before and after the override.
    # Required for compliance: reviewers must see what changed.
    original_state: Any = Column(JSON, nullable=True)
    new_state: Any = Column(JSON, nullable=True)
    applied_by: Any = Column(String(26), ForeignKey("users.id"), nullable=True)
    is_active: Any = Column(Boolean, nullable=False, default=True)

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

    id: Any = Column(String(26), primary_key=True, nullable=False)
    candidate_id: Any = Column(String(26), ForeignKey("candidates.id"), nullable=True, index=True)
    requested_by: Any = Column(String(26), ForeignKey("users.id"), nullable=True)
    status: Any = Column(String(50), nullable=False, default="pending")
    reviewer_id: Any = Column(String(26), ForeignKey("users.id"), nullable=True)
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
        String(26), ForeignKey("overrides.id"), nullable=False, index=True
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
    user_id: Any = Column(String(26), ForeignKey("users.id"), nullable=False, index=True)
    strategy_id: Any = Column(
        String(26), ForeignKey("strategies.id"), nullable=True, index=True
    )
    draft_payload: Any = Column(JSON, nullable=False, default=dict)
    # UI recovery context — captured on every autosave for DraftRecoveryBanner.
    form_step: Any = Column(String(100), nullable=True)
    session_id: Any = Column(String(255), nullable=True)
    client_ts: Any = Column(String(50), nullable=True)


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
        String(26), ForeignKey("runs.id"), nullable=False, unique=True, index=True
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

    id: Any = Column(String(26), primary_key=True, nullable=False)
    feed_id: Any = Column(String(26), ForeignKey("feeds.id"), nullable=True, index=True)
    run_id: Any = Column(String(26), ForeignKey("runs.id"), nullable=True, index=True)
    certification_type: Any = Column(String(100), nullable=False)
    status: Any = Column(String(50), nullable=False, default="pending")
    blocked: Any = Column(Boolean, nullable=False, default=False)
    details: Any = Column(JSON, nullable=True)
    certified_at: Any = Column(DateTime, nullable=True)


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
    feed_id: Any = Column(String(26), ForeignKey("feeds.id"), nullable=True, index=True)
    run_id: Any = Column(String(26), ForeignKey("runs.id"), nullable=True, index=True)
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

    id: Any = Column(String(26), primary_key=True, nullable=False)
    candidate_id: Any = Column(
        String(26), ForeignKey("candidates.id"), nullable=True, index=True
    )
    requester_id: Any = Column(String(26), ForeignKey("users.id"), nullable=True)
    target_environment: Any = Column(String(50), nullable=False)
    status: Any = Column(String(50), nullable=False, default="pending")
    rationale: Any = Column(Text, nullable=True)
    evidence_link: Any = Column(String(512), nullable=True)
    reviewer_id: Any = Column(String(26), ForeignKey("users.id"), nullable=True)
    decision_rationale: Any = Column(Text, nullable=True)
    decided_at: Any = Column(DateTime, nullable=True)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

__all__ = [
    "Base",
    "ApprovalRequest",
    "Artifact",
    "AuditEvent",
    "Candidate",
    "CertificationEvent",
    "ChartCacheEntry",
    "Deployment",
    "DraftAutosave",
    "Feed",
    "FeedHealthEvent",
    "Override",
    "OverrideWatermark",
    "ParityEvent",
    "PromotionRequest",
    "Run",
    "Strategy",
    "StrategyBuild",
    "SymbolLineageEntry",
    "Trial",
    "User",
]
