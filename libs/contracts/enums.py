"""
Enums used throughout the FXLab platform.
All project enums live here.
"""
from enum import Enum


class RunStatus(str, Enum):
    """Status of a strategy run."""
    pending = "pending"
    running = "running"
    completed = "completed"
    failed = "failed"
    cancelled = "cancelled"


class ResearchPhase(Enum):
    """Phase of research process."""
    DESIGN = "design"
    EXECUTION = "execution"
    ANALYSIS = "analysis"
    COMPLETE = "complete"

# -- merged (accumulator): libs/contracts/enums.py --
class EnvironmentType(str, Enum):
    """Environment types for deployments."""
    DEV = "dev"
    STAGING = "staging"
    PRODUCTION = "production"

class FeedLifecycleStatus(str, Enum):
    """Lifecycle status for data feeds."""
    DRAFT = "draft"
    ACTIVE = "active"
    DEPRECATED = "deprecated"
    RETIRED = "retired"

# -- merged (accumulator): libs/contracts/enums.py --
class HealthStatus(Enum):
    """Overall system health status."""
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNHEALTHY = "unhealthy"

class FeedStatus(str, Enum):
    """Status of a data feed."""
    healthy = "healthy"
    degraded = "degraded"
    unhealthy = "unhealthy"
    unknown = "unknown"

class StrategyType(Enum):
    """Type of trading strategy."""
    TECHNICAL = "technical"
    FUNDAMENTAL = "fundamental"
    HYBRID = "hybrid"
    STATISTICAL = "statistical"
    ML_BASED = "ml_based"

# -- merged (accumulator): libs/contracts/enums.py --
class JobStatus(str, Enum):
    """Status of an async job."""
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"

class Environment(str, Enum):
    """Target environments for strategy deployment."""
    research = "research"
    paper = "paper"
    live = "live"

class StrategyState(str, Enum):
    """Lifecycle state of a strategy."""
    DRAFT = "draft"
    SUBMITTED = "submitted"
    TESTING = "testing"
    APPROVED = "approved"
    DEPLOYED = "deployed"
    RETIRED = "retired"

class ApprovalStatus(str, Enum):
    """Status of an approval request."""
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"

class AuditEventType(str, Enum):
    """Types of audit events."""
    promotion_requested = "promotion_requested"
    promotion_approved = "promotion_approved"
    promotion_rejected = "promotion_rejected"
    promotion_completed = "promotion_completed"
    approval_requested = "approval_requested"
    approval_granted = "approval_granted"
    approval_denied = "approval_denied"
    override_applied = "override_applied"
    strategy_created = "strategy_created"
    strategy_modified = "strategy_modified"
    run_started = "run_started"
    run_completed = "run_completed"

class ReadinessStatus(str, Enum):
    """Overall readiness assessment status."""
    READY = "ready"
    NOT_READY = "not_ready"
    CONDITIONAL = "conditional"

# -- merged (accumulator): libs/contracts/enums.py --
class DeploymentEnvironment(str, Enum):
    """Target deployment environments for strategy promotion."""
    BACKTEST = "backtest"
    PAPER = "paper"
    LIVE = "live"

class ArtifactType(str, Enum):
    """Types of artifacts."""
    model = "model"
    dataset = "dataset"
    config = "config"
    report = "report"
    log = "log"

class ArtifactStatus(str, Enum):
    """Artifact storage and processing status."""
    PENDING = "pending"
    AVAILABLE = "available"
    FAILED = "failed"
    ARCHIVED = "archived"

class OptimizationStatus(str, Enum):
    """Parameter optimization job status."""
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"

class QueuePriority(str, Enum):
    """Priority levels for queue items."""
    low = "low"
    normal = "normal"
    high = "high"
    critical = "critical"

class AuditAction(str, Enum):
    """Types of auditable actions in the system."""
    CREATE = "create"
    UPDATE = "update"
    DELETE = "delete"
    APPROVE = "approve"
    REJECT = "reject"
    PROMOTE = "promote"
    OVERRIDE = "override"

class CorrelationLevel(str, Enum):
    """Strategy correlation severity levels."""
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"

# -- merged (accumulator): libs/contracts/enums.py --
class ReadinessGrade(str, Enum):
    """
    Readiness assessment grades for backtest runs.
    
    Determines whether a run is suitable for production promotion.
    """
    GREEN = "GREEN"  # Ready for production
    YELLOW = "YELLOW"  # Conditionally ready, review required
    RED = "RED"  # Not ready, blockers must be resolved
    GRAY = "GRAY"  # Assessment incomplete or unavailable

class ChartType(str, Enum):
    """Types of charts that can be generated."""
    EQUITY_CURVE = "EQUITY_CURVE"
    DRAWDOWN = "DRAWDOWN"
    RETURNS_DISTRIBUTION = "RETURNS_DISTRIBUTION"
    CORRELATION_MATRIX = "CORRELATION_MATRIX"
    TRADE_ANALYSIS = "TRADE_ANALYSIS"

class ExportFormat(str, Enum):
    """Supported export formats."""
    JSON = "JSON"
    CSV = "CSV"
    PARQUET = "PARQUET"
    PDF = "PDF"

class ExportStatus(str, Enum):
    """Status of an export job."""
    PENDING = "PENDING"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"

class GovernanceAction(str, Enum):
    """Types of governance actions."""
    APPROVE = "APPROVE"
    REJECT = "REJECT"
    REQUEST_CHANGES = "REQUEST_CHANGES"

class PromotionStatus(str, Enum):
    """Status of a promotion workflow."""
    pending = "pending"
    validating = "validating"
    approved = "approved"
    rejected = "rejected"
    deploying = "deploying"
    completed = "completed"
    failed = "failed"

class StrategyStatus(str, Enum):
    """Status of a strategy."""
    draft = "draft"
    active = "active"
    paused = "paused"
    archived = "archived"

# -- new symbols merged: libs/contracts/enums.py --
class ReadinessLevel(str, Enum):
    """Readiness assessment levels."""
    not_ready = "not_ready"
    needs_review = "needs_review"
    ready = "ready"
    approved = "approved"

class UserRole(str, Enum):
    """User roles for RBAC."""
    viewer = "viewer"
    analyst = "analyst"
    researcher = "researcher"
    approver = "approver"
    admin = "admin"
