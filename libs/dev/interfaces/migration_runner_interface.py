"""
Migration runner port — abstract interface for executing Alembic migrations.

Purpose:
    Defines the contract a migration runner must satisfy for the migration
    integrity validator to drive it. Hides the concrete migration framework
    (Alembic) behind an interface so the validator can be unit-tested with a
    fake runner without requiring a database or the Alembic machinery.

Responsibilities:
    - Expose the three operations required for round-trip validation:
      upgrade to head, downgrade to base, read current revision.
    - Raise a typed exception on failure so callers can distinguish
      framework errors from validator logic errors.

Does NOT:
    - Know about PostgreSQL, SQLite, or any specific database engine.
    - Contain business logic or orchestration (that belongs in the service).
    - Perform I/O directly; concrete adapters do that.

Dependencies:
    - None beyond the standard library.

Error conditions:
    - MigrationRunnerError: any failure inside a concrete adapter while
      attempting one of the operations. The adapter must always wrap
      framework-specific exceptions in MigrationRunnerError so the service
      layer sees a single exception type.

Example:
    from libs.dev.interfaces.migration_runner_interface import (
        MigrationRunnerInterface,
    )

    class MyRunner(MigrationRunnerInterface):
        def upgrade_to_head(self) -> None: ...
        def downgrade_to_base(self) -> None: ...
        def current_revision(self) -> str | None: ...
"""

from __future__ import annotations

from abc import ABC, abstractmethod


class MigrationRunnerError(Exception):
    """
    Raised when a migration runner operation fails.

    Concrete adapters MUST wrap framework-specific errors (e.g. Alembic's
    CommandError, SQLAlchemy's OperationalError) in this exception so the
    service layer can handle one error type. The original cause should be
    attached via ``raise ... from exc``.
    """


class MigrationRunnerInterface(ABC):
    """
    Contract for a migration runner.

    Implementations:
        - AlembicMigrationRunner: production adapter using Alembic commands
          against a live database configured via DATABASE_URL / alembic.ini.
        - InMemoryMigrationRunnerFake (test): records calls and can be
          configured to raise at specific steps.
    """

    @abstractmethod
    def upgrade_to_head(self) -> None:
        """
        Apply every pending migration up to the head revision.

        Raises:
            MigrationRunnerError: If any migration fails to apply.
        """

    @abstractmethod
    def downgrade_to_base(self) -> None:
        """
        Revert every applied migration back to the empty schema (``base``).

        Raises:
            MigrationRunnerError: If any downgrade fails.
        """

    @abstractmethod
    def current_revision(self) -> str | None:
        """
        Return the current revision ID applied to the database.

        Returns:
            The current revision identifier (e.g. "0023"), or ``None`` when
            no migrations have been applied yet (empty schema / base state).

        Raises:
            MigrationRunnerError: If the revision cannot be read (for example
                because the database connection is broken).
        """
