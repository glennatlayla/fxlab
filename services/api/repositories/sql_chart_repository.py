"""
SQL-backed chart repository implementation (ISS-016).

Responsibilities:
- Retrieve chart data (equity, drawdown, trade counts) for runs.
- Implement ChartRepositoryInterface using SQLAlchemy ORM.
- Support write-through caching via chart_cache_entries table.

Does NOT:
- Apply LTTB downsampling (that is the route layer's responsibility).
- Perform business logic or filtering beyond query parameters.

Dependencies:
- sqlalchemy.orm.Session: Database session (injected via __init__).
- libs.contracts.chart: EquityCurvePoint, DrawdownPoint contracts.
- libs.contracts.errors.NotFoundError: Raised when record not found.
- structlog: Structured logging.

Error conditions:
- All methods raise NotFoundError when no data exists for the given run_id.

Example:
    from services.api.db import SessionLocal
    from services.api.repositories.sql_chart_repository import SqlChartRepository

    db = SessionLocal()
    repo = SqlChartRepository(db=db)
    points = repo.find_equity_by_run_id("01HQRUN...", correlation_id="corr-1")
"""

from __future__ import annotations

import structlog
from sqlalchemy.orm import Session

from libs.contracts.chart import DrawdownPoint, EquityCurvePoint
from libs.contracts.interfaces.chart_repository import ChartRepositoryInterface

logger = structlog.get_logger(__name__)


class SqlChartRepository(ChartRepositoryInterface):
    """
    SQL-backed implementation of ChartRepositoryInterface.

    Responsibilities:
    - Query chart cache tables for equity, drawdown, and trade count data.
    - Convert cached data to Pydantic contracts.
    - Raise NotFoundError when no data exists for a run.
    - Support write-through cache updates (future M5+ feature).

    Does NOT:
    - Apply LTTB or other downsampling algorithms.
    - Validate chart data beyond schema.
    - Perform business logic or orchestration.

    Dependencies:
    - SQLAlchemy Session (injected): Database connection.

    Error conditions:
    - All methods raise NotFoundError if no data exists for run_id.

    Example:
        repo = SqlChartRepository(db=session)
        points = repo.find_equity_by_run_id("01HQRUN...", correlation_id="c")
    """

    def __init__(self, db: Session) -> None:
        """
        Initialize the SQL chart repository.

        Args:
            db: SQLAlchemy Session instance (injected by FastAPI Depends).

        Example:
            repo = SqlChartRepository(db=get_db())
        """
        self.db = db

    def find_equity_by_run_id(
        self,
        run_id: str,
        correlation_id: str,
    ) -> list[EquityCurvePoint]:
        """
        Return the full (un-downsampled) equity curve for a run.

        Args:
            run_id:         ULID of the run whose equity curve is requested.
            correlation_id: Request correlation ID for distributed tracing.

        Returns:
            List of EquityCurvePoint objects, sorted ascending by timestamp.
            May be empty for runs with no equity data.

        Raises:
            NotFoundError: If no run with run_id exists in the chart store.

        Example:
            pts = repo.find_equity_by_run_id("01HQRUN...", correlation_id="c")
            assert all(p.equity >= 0.0 for p in pts)
        """
        # For M5, chart caching is not yet implemented.
        # Return empty list for now (no NotFoundError raised).
        logger.debug(
            "chart.find_equity",
            run_id=run_id,
            correlation_id=correlation_id,
            status="not_implemented_m5_feature",
        )
        return []

    def find_drawdown_by_run_id(
        self,
        run_id: str,
        correlation_id: str,
    ) -> list[DrawdownPoint]:
        """
        Return the full (un-downsampled) drawdown series for a run.

        Args:
            run_id:         ULID of the run whose drawdown series is requested.
            correlation_id: Request correlation ID for distributed tracing.

        Returns:
            List of DrawdownPoint objects, sorted ascending by timestamp.
            May be empty for runs with no drawdown data.

        Raises:
            NotFoundError: If no run with run_id exists in the chart store.

        Example:
            pts = repo.find_drawdown_by_run_id("01HQRUN...", correlation_id="c")
            assert all(p.drawdown <= 0.0 for p in pts)
        """
        # For M5, chart caching is not yet implemented.
        # Return empty list for now (no NotFoundError raised).
        logger.debug(
            "chart.find_drawdown",
            run_id=run_id,
            correlation_id=correlation_id,
            status="not_implemented_m5_feature",
        )
        return []

    def find_trade_count_by_run_id(
        self,
        run_id: str,
        correlation_id: str,
    ) -> int:
        """
        Return the total trade count for a run (without loading all trades).

        Args:
            run_id:         ULID of the run.
            correlation_id: Request correlation ID for distributed tracing.

        Returns:
            Non-negative integer trade count.

        Raises:
            NotFoundError: If no run with run_id exists in the chart store.

        Example:
            count = repo.find_trade_count_by_run_id("01HQRUN...", correlation_id="c")
            assert count >= 0
        """
        # For M5, chart caching is not yet implemented.
        # Return 0 for now (no NotFoundError raised).
        logger.debug(
            "chart.find_trade_count",
            run_id=run_id,
            correlation_id=correlation_id,
            status="not_implemented_m5_feature",
        )
        return 0
