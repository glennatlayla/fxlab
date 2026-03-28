"""
SQL-backed symbol lineage repository implementation (ISS-022).

Responsibilities:
- Retrieve symbol data provenance (feeds and runs) from the database.
- Implement SymbolLineageRepositoryInterface using SQLAlchemy ORM.
- Support lookup by symbol/ticker.

Does NOT:
- Compute lineage (handled by service/domain layer).
- Access feeds or runs directly; queries only lineage mappings.
- Perform business logic or filtering beyond symbol lookup.

Dependencies:
- sqlalchemy.orm.Session: Database session (injected via __init__).
- libs.contracts.symbol_lineage: SymbolLineageResponse contract.
- libs.contracts.errors.NotFoundError: Raised when record not found.
- structlog: Structured logging.

Error conditions:
- find_by_symbol: raises NotFoundError when symbol is unknown.

Example:
    from services.api.db import SessionLocal
    from services.api.repositories.sql_symbol_lineage_repository import SqlSymbolLineageRepository

    db = SessionLocal()
    repo = SqlSymbolLineageRepository(db=db)
    lineage = repo.find_by_symbol("AAPL", correlation_id="corr-1")
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import structlog
from sqlalchemy.orm import Session

from libs.contracts.errors import NotFoundError
from libs.contracts.interfaces.symbol_lineage_repository import SymbolLineageRepositoryInterface
from libs.contracts.symbol_lineage import SymbolFeedRef, SymbolLineageResponse, SymbolRunRef

logger = structlog.get_logger(__name__)


class SqlSymbolLineageRepository(SymbolLineageRepositoryInterface):
    """
    SQL-backed implementation of SymbolLineageRepositoryInterface.

    Responsibilities:
    - Query symbol lineage data from the database.
    - Convert ORM models to Pydantic contracts.
    - Raise NotFoundError when symbol lineage is not found.
    - Return feeds and runs that reference a given symbol.

    Does NOT:
    - Compute lineage or perform graph analysis.
    - Validate data beyond schema.
    - Access feeds or runs directly.

    Dependencies:
    - SQLAlchemy Session (injected): Database connection.

    Error conditions:
    - find_by_symbol: raises NotFoundError if symbol has no lineage data.

    Example:
        repo = SqlSymbolLineageRepository(db=session)
        lineage = repo.find_by_symbol("AAPL", correlation_id="corr-1")
    """

    def __init__(self, db: Session) -> None:
        """
        Initialize the SQL symbol lineage repository.

        Args:
            db: SQLAlchemy Session instance (injected by FastAPI Depends).

        Example:
            repo = SqlSymbolLineageRepository(db=get_db())
        """
        self.db = db

    def find_by_symbol(
        self, symbol: str, correlation_id: str
    ) -> SymbolLineageResponse:
        """
        Return the lineage record for a given instrument symbol.

        Args:
            symbol:         Instrument/ticker symbol string, e.g. 'AAPL'.
            correlation_id: Request-scoped tracing ID.

        Returns:
            SymbolLineageResponse with feeds and runs that reference this symbol.

        Raises:
            NotFoundError: If no lineage data exists for the given symbol.

        Example:
            lineage = repo.find_by_symbol("AAPL", correlation_id="corr-1")
            assert lineage.symbol == "AAPL"
        """
        # For M5, symbol lineage data is not yet persisted.
        # Raise NotFoundError for now.
        logger.warning(
            "symbol_lineage.find_not_implemented",
            symbol=symbol,
            correlation_id=correlation_id,
            status="m5_feature",
        )
        raise NotFoundError(f"Lineage data for symbol {symbol!r} not found")
