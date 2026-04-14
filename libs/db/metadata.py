"""
Metadata database interface and implementation.
Provides connection lifecycle, transaction support, and query execution
with structured logging and correlation ID propagation.
"""

from typing import Any, Literal, Protocol

import structlog
from sqlalchemy import Engine, create_engine, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker

logger = structlog.get_logger(__name__)


class TransactionContext(Protocol):
    """Protocol for database transaction context managers."""

    def commit(self) -> None:
        """Commit the transaction."""
        ...

    def rollback(self) -> None:
        """Rollback the transaction."""
        ...

    def __enter__(self) -> "TransactionContext":
        """Enter transaction context."""
        ...

    def __exit__(self, exc_type, exc_val, exc_tb) -> bool:
        """Exit transaction context, rollback on exception."""
        ...


class MetadataDatabase:
    """
    Metadata database connection manager.

    Provides:
    - Connection lifecycle (connect, disconnect, health_check)
    - Transaction support with context manager
    - Query execution with parameter binding
    - Structured logging with correlation IDs
    """

    def __init__(self, connection_string: str):
        """
        Initialize database connection manager.

        Args:
            connection_string: SQLAlchemy database URL
        """
        self.connection_string = connection_string
        self.engine: Engine | None = None
        self.SessionLocal: sessionmaker | None = None
        self.logger = logger.bind(component="metadata_database")

    def connect(self, correlation_id: str) -> None:
        """
        Establish database connection.

        Args:
            correlation_id: Request correlation ID for tracing

        Raises:
            ConnectionError: If connection fails
        """
        self.logger.info("database.connect.start", correlation_id=correlation_id, action="connect")

        try:
            self.engine = create_engine(
                self.connection_string, pool_pre_ping=True, pool_size=5, max_overflow=10
            )
            self.SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=self.engine)

            # Test connection
            with self.engine.connect() as conn:
                conn.execute(text("SELECT 1"))

            self.logger.info("database.connect.success", correlation_id=correlation_id)

        except Exception as e:
            self.logger.error(
                "database.connect.failed", correlation_id=correlation_id, error=str(e)
            )
            raise ConnectionError(f"Failed to connect to database: {e}")

    def is_connected(self) -> bool:
        """
        Check if database is connected.

        Returns:
            True if connected, False otherwise
        """
        return self.engine is not None and self.SessionLocal is not None

    def health_check(self, correlation_id: str) -> bool:
        """
        Perform database health check.

        Args:
            correlation_id: Request correlation ID for tracing

        Returns:
            True if healthy, False otherwise
        """
        if not self.is_connected():
            self.logger.debug(
                "database.health_check.disconnected", correlation_id=correlation_id, healthy=False
            )
            return False

        try:
            with self.engine.connect() as conn:
                conn.execute(text("SELECT 1"))

            self.logger.debug(
                "database.health_check.success", correlation_id=correlation_id, healthy=True
            )
            return True

        except Exception as e:
            self.logger.error(
                "database.health_check.failed",
                correlation_id=correlation_id,
                error=str(e),
                healthy=False,
            )
            return False

    def disconnect(self, correlation_id: str) -> None:
        """
        Close database connection gracefully.
        Idempotent - safe to call multiple times.

        Args:
            correlation_id: Request correlation ID for tracing
        """
        self.logger.info(
            "database.disconnect.start", correlation_id=correlation_id, action="disconnect"
        )

        if self.engine is not None:
            try:
                self.engine.dispose()
                self.logger.info("database.disconnect.success", correlation_id=correlation_id)
            except Exception as e:
                self.logger.error(
                    "database.disconnect.error", correlation_id=correlation_id, error=str(e)
                )
            finally:
                self.engine = None
                self.SessionLocal = None
        else:
            self.logger.debug(
                "database.disconnect.already_disconnected", correlation_id=correlation_id
            )

    def begin_transaction(self, correlation_id: str) -> "SQLAlchemyTransaction":
        """
        Begin a new database transaction.

        Args:
            correlation_id: Request correlation ID for tracing

        Returns:
            Transaction context manager
        """
        self.logger.debug("database.transaction.begin", correlation_id=correlation_id)

        session = self.SessionLocal()
        return SQLAlchemyTransaction(session, correlation_id, self.logger)

    def execute(
        self,
        query: str,
        params: dict[str, Any] | None = None,
        correlation_id: str | None = None,
    ) -> list[dict[str, Any]]:
        """
        Execute a SQL query with parameter binding.

        Args:
            query: SQL query string with named parameters
            params: Dictionary of parameter values
            correlation_id: Request correlation ID for tracing

        Returns:
            List of result rows as dictionaries
        """
        self.logger.info(
            "database.execute",
            correlation_id=correlation_id,
            query=query,
            has_params=params is not None,
        )

        try:
            with self.engine.connect() as conn:
                result = conn.execute(text(query), params or {})

                # Convert result to list of dicts
                rows = []
                if result.returns_rows:
                    keys = result.keys()
                    rows = [dict(zip(keys, row, strict=False)) for row in result.fetchall()]

                self.logger.debug(
                    "database.execute.success", correlation_id=correlation_id, row_count=len(rows)
                )

                return rows

        except SQLAlchemyError as e:
            self.logger.error(
                "database.execute.failed", correlation_id=correlation_id, error=str(e)
            )
            raise


class SQLAlchemyTransaction:
    """
    SQLAlchemy transaction context manager.
    Supports explicit commit/rollback and automatic rollback on exception.
    """

    def __init__(self, session: Session, correlation_id: str, logger):
        """
        Initialize transaction context.

        Args:
            session: SQLAlchemy session
            correlation_id: Request correlation ID
            logger: Structured logger instance
        """
        self.session = session
        self.correlation_id = correlation_id
        self.logger = logger

    def commit(self) -> None:
        """Commit the transaction."""
        self.logger.debug("database.transaction.commit", correlation_id=self.correlation_id)
        self.session.commit()

    def rollback(self) -> None:
        """Rollback the transaction."""
        self.logger.debug("database.transaction.rollback", correlation_id=self.correlation_id)
        self.session.rollback()

    def __enter__(self) -> "SQLAlchemyTransaction":
        """Enter transaction context."""
        self.logger.debug("database.transaction.enter", correlation_id=self.correlation_id)
        return self

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> Literal[False]:
        """
        Exit transaction context.
        Rollback on exception, commit otherwise.

        Returns:
            False to propagate exceptions
        """
        if exc_type is not None:
            self.logger.warning(
                "database.transaction.exception_rollback",
                correlation_id=self.correlation_id,
                exception_type=exc_type.__name__ if exc_type else None,
            )
            self.rollback()

        self.session.close()

        self.logger.debug("database.transaction.exit", correlation_id=self.correlation_id)

        # Return False to propagate exceptions
        return False
