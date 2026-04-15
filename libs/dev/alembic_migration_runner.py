"""
Alembic-backed implementation of MigrationRunnerInterface.

Purpose:
    Concrete adapter that drives Alembic's ``upgrade``, ``downgrade``, and
    revision-introspection commands against a live database. Wraps all
    Alembic and SQLAlchemy errors in MigrationRunnerError so the service
    layer only has to handle one exception type.

Responsibilities:
    - Build an Alembic ``Config`` object using the supplied ``alembic.ini``
      path and database URL.
    - Delegate to ``alembic.command`` for upgrade/downgrade.
    - Use ``alembic.runtime.migration.MigrationContext`` to read the
      current head revision directly from the ``alembic_version`` table.

Does NOT:
    - Know about PostgreSQL specifically (any dialect Alembic + SQLAlchemy
      supports will work).
    - Retry on transient failures (that is the caller's concern).
    - Expose Alembic internals outside this module.

Dependencies:
    - Alembic (already a project dependency).
    - SQLAlchemy (already a project dependency).

Error conditions:
    - MigrationRunnerError: raised for any underlying Alembic / SQLAlchemy
      error encountered during the requested operation.

Example:
    runner = AlembicMigrationRunner(
        database_url="postgresql://user:pw@localhost:5433/fxlab",
        alembic_ini_path="/app/alembic.ini",
    )
    runner.upgrade_to_head()
    assert runner.current_revision() is not None
"""

from __future__ import annotations

from pathlib import Path

from alembic import command
from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from sqlalchemy import create_engine
from sqlalchemy.exc import SQLAlchemyError

from libs.dev.interfaces.migration_runner_interface import (
    MigrationRunnerError,
    MigrationRunnerInterface,
)


class AlembicMigrationRunner(MigrationRunnerInterface):
    """
    Production Alembic adapter.

    Attributes:
        _database_url: SQLAlchemy URL to connect to.
        _alembic_ini_path: Absolute path to alembic.ini.

    Example:
        runner = AlembicMigrationRunner(
            database_url="postgresql://fxlab:pw@localhost:5432/fxlab",
            alembic_ini_path="/opt/fxlab/alembic.ini",
        )
        runner.upgrade_to_head()
    """

    def __init__(
        self,
        *,
        database_url: str,
        alembic_ini_path: str | Path,
    ) -> None:
        """
        Args:
            database_url: SQLAlchemy-compatible connection URL. Passed both
                to Alembic (via ``sqlalchemy.url`` override) and to any
                direct introspection queries this adapter performs.
            alembic_ini_path: Path to the project's ``alembic.ini``.

        Raises:
            MigrationRunnerError: If ``alembic.ini`` is missing.
        """
        ini_path = Path(alembic_ini_path)
        if not ini_path.is_file():
            raise MigrationRunnerError(f"alembic.ini not found at {ini_path}")
        if not database_url:
            raise MigrationRunnerError("database_url must be a non-empty string.")
        self._database_url: str = database_url
        self._alembic_ini_path: Path = ini_path

    # ---------------------------------------------------------------- public

    def upgrade_to_head(self) -> None:
        """
        Apply every pending migration up to ``head``.

        Raises:
            MigrationRunnerError: If Alembic or SQLAlchemy raises during
                the upgrade. The underlying exception is attached as the
                cause.
        """
        try:
            command.upgrade(self._build_config(), "head")
        except (SQLAlchemyError, Exception) as exc:
            # Alembic raises command.CommandError which subclasses Exception.
            # We intentionally catch Exception here to guarantee the service
            # layer only has to handle MigrationRunnerError — but we attach
            # the original exception via ``from`` so the root cause is never
            # lost.
            raise MigrationRunnerError(f"alembic upgrade head failed: {exc}") from exc

    def downgrade_to_base(self) -> None:
        """
        Revert every applied migration down to ``base`` (empty schema).

        Raises:
            MigrationRunnerError: If Alembic or SQLAlchemy raises during
                the downgrade.
        """
        try:
            command.downgrade(self._build_config(), "base")
        except (SQLAlchemyError, Exception) as exc:
            raise MigrationRunnerError(f"alembic downgrade base failed: {exc}") from exc

    def current_revision(self) -> str | None:
        """
        Return the revision currently recorded in ``alembic_version``.

        Returns:
            The current revision string, or ``None`` when the database has
            no applied migrations (empty / base state or the
            ``alembic_version`` table does not exist yet).

        Raises:
            MigrationRunnerError: On any SQLAlchemy or Alembic error that
                is not simply "table missing".
        """
        try:
            engine = create_engine(self._database_url, future=True)
            try:
                with engine.connect() as connection:
                    context = MigrationContext.configure(connection)
                    # get_current_revision() returns None when no
                    # migration has ever been applied OR when the
                    # alembic_version table does not exist.
                    return context.get_current_revision()
            finally:
                engine.dispose()
        except SQLAlchemyError as exc:
            raise MigrationRunnerError(f"reading current revision failed: {exc}") from exc

    # --------------------------------------------------------------- helpers

    def _build_config(self) -> Config:
        """
        Construct a fresh Alembic ``Config`` with the database URL injected.

        A new Config is built for every command rather than cached because
        Alembic mutates internal state (logger handles, section cache) on
        each command invocation — reusing an instance causes duplicated
        handlers in long-running validators.
        """
        config = Config(str(self._alembic_ini_path))
        config.set_main_option("sqlalchemy.url", self._database_url)
        return config
