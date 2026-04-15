"""
Migration integrity validator.

Purpose:
    Drives a round-trip migration test (``upgrade head → downgrade base →
    upgrade head``) against any database the supplied runner is configured
    to talk to. The round-trip proves three properties simultaneously:

      1. Every upgrade in the chain applies cleanly against the target
         database dialect.
      2. Every downgrade successfully reverts the change (catches missing
         drop_table / drop_column / drop_constraint calls).
      3. Applying the chain twice to the same database is idempotent after
         a clean teardown (catches accidental side effects that survive
         downgrade, e.g. orphaned indexes or sequences).

    The validator is deliberately dialect-agnostic. Wired against a
    PostgreSQL runner in CI, it catches dialect-specific type mismatches
    (such as ``BOOLEAN DEFAULT 0``) that offline SQL generation silently
    accepts. Wired against SQLite it serves as a sanity check for fast
    local runs.

Responsibilities:
    - Call the runner in the correct sequence.
    - Measure wall-clock duration of each phase.
    - Validate the observed revisions match expected invariants.
    - Emit structured log events at every significant step.

Does NOT:
    - Know anything about Alembic or a specific database engine.
    - Open or close database connections (that is the runner's job).
    - Decide which URL to connect to (the runner owns that config).

Dependencies:
    - MigrationRunnerInterface (injected).
    - A structured logger (injected; must accept ``extra`` kwargs or a
      compatible structlog binding).

Raises:
    - MigrationIntegrityError: any validation invariant violated, or the
      underlying runner raised MigrationRunnerError.

Example:
    from libs.dev.migration_integrity_validator import (
        MigrationIntegrityValidator,
    )

    validator = MigrationIntegrityValidator(runner=runner, logger=logger)
    result = validator.validate()
    print(result.summary())
"""

from __future__ import annotations

import logging
import time
from typing import Any

from libs.dev.interfaces.migration_runner_interface import (
    MigrationRunnerError,
    MigrationRunnerInterface,
)
from libs.dev.migration_integrity_result import MigrationIntegrityResult


class MigrationIntegrityError(Exception):
    """
    Raised when the migration integrity validator detects a failed invariant
    or a runner error during round-trip validation.

    Attributes:
        phase: Human-readable phase name in which the error occurred
            (e.g. "upgrade_to_head", "downgrade_to_base",
            "reupgrade_to_head", "invariant_check").
    """

    def __init__(self, message: str, *, phase: str) -> None:
        super().__init__(message)
        self.phase: str = phase


class MigrationIntegrityValidator:
    """
    Round-trip migration integrity validator.

    Responsibilities:
    - Drive the injected runner through upgrade → downgrade → upgrade.
    - Measure and record durations.
    - Enforce:
        a) First and second upgrade yield the same head revision.
        b) Downgrade produces the base (empty) state (revision is ``None``).

    Does NOT:
    - Create or tear down the target database.
    - Reset schema between runs (callers are expected to hand in a clean
      database — the validator proves the chain itself cleans up).

    Dependencies:
    - runner: MigrationRunnerInterface — executes the actual migration
      commands.
    - logger: structured logger — one ``INFO`` per phase start/finish,
      one ``ERROR`` on failure. ``correlation_id`` is accepted but not
      manufactured; callers pass it in via ``validate(correlation_id=...)``.

    Error conditions:
    - MigrationIntegrityError (phase=<phase>): raised on any failure.

    Example:
        runner = AlembicMigrationRunner(database_url="...", alembic_ini="...")
        validator = MigrationIntegrityValidator(runner=runner, logger=logger)
        result = validator.validate(correlation_id="ci-run-42")
    """

    #: Component name used in structured log events.
    _COMPONENT: str = "MigrationIntegrityValidator"

    def __init__(
        self,
        runner: MigrationRunnerInterface,
        logger: logging.Logger | None = None,
    ) -> None:
        """
        Args:
            runner: Concrete adapter that executes migration commands.
            logger: Optional structured logger. When omitted, a module-level
                logger is used. The logger must support ``extra=`` kwargs
                (standard library ``logging.Logger`` suffices).
        """
        self._runner: MigrationRunnerInterface = runner
        self._logger: logging.Logger = logger or logging.getLogger(__name__)

    def validate(
        self,
        *,
        correlation_id: str | None = None,
    ) -> MigrationIntegrityResult:
        """
        Execute a full round-trip validation.

        Args:
            correlation_id: Optional ID propagated to every log event so
                that operators can correlate validator output with a wider
                install / CI run.

        Returns:
            MigrationIntegrityResult with timings and observed revisions.

        Raises:
            MigrationIntegrityError: If any phase fails or an invariant is
                violated. The ``phase`` attribute identifies the failing
                step for operators.
        """
        initial = self._safe_current_revision(
            phase="initial_revision_read",
            correlation_id=correlation_id,
        )
        self._log_info(
            "migration_validator.started",
            correlation_id=correlation_id,
            initial_revision=initial,
        )

        first_head, upgrade_seconds = self._run_phase(
            phase="upgrade_to_head",
            correlation_id=correlation_id,
            operation=self._runner.upgrade_to_head,
        )
        if first_head is None:
            raise MigrationIntegrityError(
                "After upgrade_to_head the current revision is None; "
                "expected a valid head revision.",
                phase="upgrade_to_head",
            )

        after_downgrade, downgrade_seconds = self._run_phase(
            phase="downgrade_to_base",
            correlation_id=correlation_id,
            operation=self._runner.downgrade_to_base,
        )
        if after_downgrade is not None:
            raise MigrationIntegrityError(
                f"After downgrade_to_base the current revision is "
                f"{after_downgrade!r}; expected None (base state).",
                phase="downgrade_to_base",
            )

        second_head, reupgrade_seconds = self._run_phase(
            phase="reupgrade_to_head",
            correlation_id=correlation_id,
            operation=self._runner.upgrade_to_head,
        )
        if second_head != first_head:
            raise MigrationIntegrityError(
                f"Head revision after reupgrade ({second_head!r}) "
                f"differs from the first upgrade ({first_head!r}); "
                "the chain is not idempotent.",
                phase="reupgrade_to_head",
            )

        result = MigrationIntegrityResult(
            initial_revision=initial,
            head_after_first_upgrade=first_head,
            revision_after_downgrade=after_downgrade,
            head_after_second_upgrade=second_head,
            upgrade_duration_seconds=upgrade_seconds,
            downgrade_duration_seconds=downgrade_seconds,
            reupgrade_duration_seconds=reupgrade_seconds,
        )

        self._log_info(
            "migration_validator.succeeded",
            correlation_id=correlation_id,
            result="success",
            summary=result.summary(),
        )
        return result

    # ------------------------------------------------------------------ helpers

    def _safe_current_revision(
        self,
        *,
        phase: str,
        correlation_id: str | None,
    ) -> str | None:
        """Read the runner's current revision, wrapping any error."""
        try:
            return self._runner.current_revision()
        except MigrationRunnerError as exc:
            self._log_error(
                "migration_validator.phase_failed",
                correlation_id=correlation_id,
                phase=phase,
                error=str(exc),
            )
            raise MigrationIntegrityError(
                f"Reading current revision failed in phase {phase!r}: {exc}",
                phase=phase,
            ) from exc

    def _run_phase(
        self,
        *,
        phase: str,
        correlation_id: str | None,
        operation: Any,
    ) -> tuple[str | None, float]:
        """
        Execute one phase of the round-trip.

        Returns:
            Tuple of (revision_after_phase, duration_seconds).

        Raises:
            MigrationIntegrityError: If the operation or the subsequent
                revision read raises.
        """
        self._log_info(
            "migration_validator.phase_started",
            correlation_id=correlation_id,
            phase=phase,
        )
        start = time.perf_counter()
        try:
            operation()
        except MigrationRunnerError as exc:
            duration = time.perf_counter() - start
            self._log_error(
                "migration_validator.phase_failed",
                correlation_id=correlation_id,
                phase=phase,
                duration_ms=int(duration * 1000),
                error=str(exc),
            )
            raise MigrationIntegrityError(
                f"Phase {phase!r} failed: {exc}",
                phase=phase,
            ) from exc
        duration = time.perf_counter() - start

        revision = self._safe_current_revision(
            phase=phase,
            correlation_id=correlation_id,
        )
        self._log_info(
            "migration_validator.phase_completed",
            correlation_id=correlation_id,
            phase=phase,
            duration_ms=int(duration * 1000),
            revision=revision,
        )
        return revision, duration

    def _log_info(self, event: str, **fields: Any) -> None:
        """Log an informational event with structured extra fields."""
        self._logger.info(event, extra=self._extras(event, fields))

    def _log_error(self, event: str, **fields: Any) -> None:
        """Log an error event with structured extra fields."""
        self._logger.error(event, extra=self._extras(event, fields))

    def _extras(self, operation: str, fields: dict[str, Any]) -> dict[str, Any]:
        """Build structured logging extras for a log call."""
        extras: dict[str, Any] = {
            "operation": operation,
            "component": self._COMPONENT,
        }
        extras.update({k: v for k, v in fields.items() if v is not None})
        return extras
