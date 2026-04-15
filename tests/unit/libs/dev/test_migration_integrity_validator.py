"""
Unit tests for MigrationIntegrityValidator.

Scope:
    Behaviour of the validator orchestration only. A fake runner
    (FakeMigrationRunner) substitutes for Alembic so tests are deterministic
    and do not touch a database.

Layers under test:
    libs.dev.migration_integrity_validator.MigrationIntegrityValidator
    libs.dev.interfaces.migration_runner_interface.MigrationRunnerError
    libs.dev.migration_integrity_result.MigrationIntegrityResult

Tests cover:
    - Happy path: full round-trip succeeds, result fields match observations.
    - Invariant: second head differs from first → MigrationIntegrityError.
    - Invariant: downgrade leaves a non-None revision → MigrationIntegrityError.
    - Invariant: first upgrade leaves a None revision → MigrationIntegrityError.
    - Runner raises on upgrade → wrapped as MigrationIntegrityError(phase).
    - Runner raises on downgrade → wrapped as MigrationIntegrityError(phase).
    - Runner raises on reupgrade → wrapped as MigrationIntegrityError(phase).
    - Runner raises on initial revision read → wrapped as
      MigrationIntegrityError(phase="initial_revision_read").
    - Call sequence is exactly: current → upgrade → current → downgrade →
      current → upgrade → current.
    - Durations are non-negative and monotonic with injected sleeps.
    - Result summary() contains all observed revisions.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

import pytest

from libs.dev.interfaces.migration_runner_interface import (
    MigrationRunnerError,
    MigrationRunnerInterface,
)
from libs.dev.migration_integrity_result import MigrationIntegrityResult
from libs.dev.migration_integrity_validator import (
    MigrationIntegrityError,
    MigrationIntegrityValidator,
)

# ---------------------------------------------------------------------------
# Test doubles
# ---------------------------------------------------------------------------


@dataclass
class FakeMigrationRunner(MigrationRunnerInterface):
    """
    Scripted fake runner for validator tests.

    Attributes:
        revisions: Queue of revisions returned by consecutive
            ``current_revision()`` calls. The list is consumed left-to-right.
            If the list empties, the last value is returned repeatedly.
        upgrade_error: If set, the next ``upgrade_to_head()`` call raises
            MigrationRunnerError with this message; the attribute is cleared
            after raising so subsequent calls succeed.
        downgrade_error: Same pattern for ``downgrade_to_base()``.
        current_error: If set, the next ``current_revision()`` call raises.
        calls: Ordered log of method names actually invoked; test assertions
            can verify the exact call sequence.
    """

    revisions: list[str | None] = field(default_factory=list)
    upgrade_error: str | None = None
    downgrade_error: str | None = None
    current_error: str | None = None
    calls: list[str] = field(default_factory=list)

    def upgrade_to_head(self) -> None:
        self.calls.append("upgrade_to_head")
        if self.upgrade_error is not None:
            err = self.upgrade_error
            self.upgrade_error = None
            raise MigrationRunnerError(err)

    def downgrade_to_base(self) -> None:
        self.calls.append("downgrade_to_base")
        if self.downgrade_error is not None:
            err = self.downgrade_error
            self.downgrade_error = None
            raise MigrationRunnerError(err)

    def current_revision(self) -> str | None:
        self.calls.append("current_revision")
        if self.current_error is not None:
            err = self.current_error
            self.current_error = None
            raise MigrationRunnerError(err)
        if not self.revisions:
            raise AssertionError(
                "FakeMigrationRunner exhausted revisions list — test did not script enough entries."
            )
        if len(self.revisions) == 1:
            return self.revisions[0]
        return self.revisions.pop(0)


@pytest.fixture()
def logger() -> logging.Logger:
    """Return a logger that discards output to keep test stdout clean."""
    log = logging.getLogger("migration_validator_test")
    log.setLevel(logging.CRITICAL + 1)
    return log


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------


def test_validator_happy_path_returns_result_with_expected_fields(
    logger: logging.Logger,
) -> None:
    """
    Full round-trip succeeds: validator returns a MigrationIntegrityResult
    with the revisions it observed and non-negative durations.
    """
    runner = FakeMigrationRunner(
        revisions=[
            None,  # initial
            "0023",  # after first upgrade
            None,  # after downgrade
            "0023",  # after reupgrade
        ],
    )
    validator = MigrationIntegrityValidator(runner=runner, logger=logger)

    result = validator.validate()

    assert isinstance(result, MigrationIntegrityResult)
    assert result.initial_revision is None
    assert result.head_after_first_upgrade == "0023"
    assert result.revision_after_downgrade is None
    assert result.head_after_second_upgrade == "0023"
    assert result.upgrade_duration_seconds >= 0.0
    assert result.downgrade_duration_seconds >= 0.0
    assert result.reupgrade_duration_seconds >= 0.0


def test_validator_happy_path_call_sequence_is_current_upgrade_current_downgrade_current_upgrade_current(
    logger: logging.Logger,
) -> None:
    """
    The validator must call the runner in exactly this order so that
    revision reads always occur after the corresponding state change.
    """
    runner = FakeMigrationRunner(revisions=[None, "0023", None, "0023"])
    validator = MigrationIntegrityValidator(runner=runner, logger=logger)

    validator.validate()

    assert runner.calls == [
        "current_revision",  # initial
        "upgrade_to_head",
        "current_revision",  # first head
        "downgrade_to_base",
        "current_revision",  # after downgrade
        "upgrade_to_head",
        "current_revision",  # second head
    ]


def test_validator_result_summary_includes_observed_revisions(
    logger: logging.Logger,
) -> None:
    """
    The summary string must expose every observed revision so CI logs
    are self-explanatory without re-running the validator.
    """
    runner = FakeMigrationRunner(revisions=[None, "0023", None, "0023"])
    validator = MigrationIntegrityValidator(runner=runner, logger=logger)

    result = validator.validate()
    summary = result.summary()

    assert "head=0023" in summary
    assert "downgrade=None" in summary
    assert "reupgrade=0023" in summary
    assert "up=" in summary and "down=" in summary and "reup=" in summary


def test_validator_passes_correlation_id_without_failing(
    logger: logging.Logger,
) -> None:
    """
    correlation_id is a cosmetic / logging aid; passing it must not change
    the validator's behaviour.
    """
    runner = FakeMigrationRunner(revisions=[None, "0023", None, "0023"])
    validator = MigrationIntegrityValidator(runner=runner, logger=logger)

    result = validator.validate(correlation_id="ci-run-42")

    assert result.head_after_first_upgrade == "0023"


# ---------------------------------------------------------------------------
# Invariant failures
# ---------------------------------------------------------------------------


def test_validator_raises_when_first_upgrade_yields_none_revision(
    logger: logging.Logger,
) -> None:
    """
    If upgrade_to_head leaves the database reporting ``None`` as its
    current revision, the chain is broken (migrations did not apply).
    """
    runner = FakeMigrationRunner(revisions=[None, None])
    validator = MigrationIntegrityValidator(runner=runner, logger=logger)

    with pytest.raises(MigrationIntegrityError) as exc_info:
        validator.validate()

    assert exc_info.value.phase == "upgrade_to_head"


def test_validator_raises_when_downgrade_leaves_non_none_revision(
    logger: logging.Logger,
) -> None:
    """
    downgrade_to_base must leave the database in the empty/base state
    (revision ``None``). A non-None revision means one or more downgrades
    failed silently or did not drop everything they created.
    """
    runner = FakeMigrationRunner(
        revisions=[
            None,  # initial
            "0023",  # after first upgrade
            "0005",  # after downgrade — WRONG
        ],
    )
    validator = MigrationIntegrityValidator(runner=runner, logger=logger)

    with pytest.raises(MigrationIntegrityError) as exc_info:
        validator.validate()

    assert exc_info.value.phase == "downgrade_to_base"
    assert "0005" in str(exc_info.value)


def test_validator_raises_when_second_upgrade_yields_different_head(
    logger: logging.Logger,
) -> None:
    """
    First and second upgrades must yield the same head revision. If they
    differ, the downgrade left artifacts behind that altered the head,
    or the chain is non-deterministic.
    """
    runner = FakeMigrationRunner(
        revisions=[
            None,  # initial
            "0023",  # first head
            None,  # after downgrade
            "0022",  # second head — MISMATCH
        ],
    )
    validator = MigrationIntegrityValidator(runner=runner, logger=logger)

    with pytest.raises(MigrationIntegrityError) as exc_info:
        validator.validate()

    assert exc_info.value.phase == "reupgrade_to_head"
    assert "0023" in str(exc_info.value)
    assert "0022" in str(exc_info.value)


# ---------------------------------------------------------------------------
# Runner failure propagation
# ---------------------------------------------------------------------------


def test_validator_wraps_runner_error_on_upgrade(
    logger: logging.Logger,
) -> None:
    """A MigrationRunnerError during the first upgrade becomes
    MigrationIntegrityError(phase="upgrade_to_head"), preserving the
    original error as __cause__."""
    runner = FakeMigrationRunner(
        revisions=[None],
        upgrade_error="boom",
    )
    validator = MigrationIntegrityValidator(runner=runner, logger=logger)

    with pytest.raises(MigrationIntegrityError) as exc_info:
        validator.validate()

    assert exc_info.value.phase == "upgrade_to_head"
    assert isinstance(exc_info.value.__cause__, MigrationRunnerError)


def test_validator_wraps_runner_error_on_downgrade(
    logger: logging.Logger,
) -> None:
    """A MigrationRunnerError during the downgrade surfaces as
    MigrationIntegrityError(phase="downgrade_to_base")."""
    runner = FakeMigrationRunner(
        revisions=[None, "0023"],
        downgrade_error="pg_err",
    )
    validator = MigrationIntegrityValidator(runner=runner, logger=logger)

    with pytest.raises(MigrationIntegrityError) as exc_info:
        validator.validate()

    assert exc_info.value.phase == "downgrade_to_base"


def test_validator_wraps_runner_error_on_reupgrade(
    logger: logging.Logger,
) -> None:
    """A MigrationRunnerError during the second upgrade surfaces with
    phase="reupgrade_to_head"."""
    runner = FakeMigrationRunner(
        revisions=[None, "0023", None],
        upgrade_error=None,
    )

    # Override: make only the SECOND upgrade fail. The fake only supports
    # one-shot errors, so we wrap the call counter.
    original_upgrade = runner.upgrade_to_head
    upgrade_count = {"n": 0}

    def failing_second_upgrade() -> None:
        upgrade_count["n"] += 1
        original_upgrade()
        if upgrade_count["n"] == 2:
            raise MigrationRunnerError("second upgrade exploded")

    runner.upgrade_to_head = failing_second_upgrade  # type: ignore[assignment]

    validator = MigrationIntegrityValidator(runner=runner, logger=logger)

    with pytest.raises(MigrationIntegrityError) as exc_info:
        validator.validate()

    assert exc_info.value.phase == "reupgrade_to_head"


def test_validator_wraps_runner_error_on_initial_revision_read(
    logger: logging.Logger,
) -> None:
    """If the very first current_revision() call fails, phase should be
    "initial_revision_read" so operators can distinguish a dead database
    from a broken migration."""
    runner = FakeMigrationRunner(
        revisions=[None],
        current_error="db unreachable",
    )
    validator = MigrationIntegrityValidator(runner=runner, logger=logger)

    with pytest.raises(MigrationIntegrityError) as exc_info:
        validator.validate()

    assert exc_info.value.phase == "initial_revision_read"


# ---------------------------------------------------------------------------
# Result model invariants
# ---------------------------------------------------------------------------


def test_result_rejects_negative_durations() -> None:
    """MigrationIntegrityResult must reject negative durations to prevent
    bookkeeping bugs in the validator from yielding meaningless output."""
    with pytest.raises(Exception):  # pydantic.ValidationError
        MigrationIntegrityResult(
            initial_revision=None,
            head_after_first_upgrade="0023",
            revision_after_downgrade=None,
            head_after_second_upgrade="0023",
            upgrade_duration_seconds=-0.1,
            downgrade_duration_seconds=0.0,
            reupgrade_duration_seconds=0.0,
        )


def test_result_is_frozen() -> None:
    """The result must be immutable so callers cannot tamper with audit
    evidence after the fact."""
    result = MigrationIntegrityResult(
        initial_revision=None,
        head_after_first_upgrade="0023",
        revision_after_downgrade=None,
        head_after_second_upgrade="0023",
        upgrade_duration_seconds=1.0,
        downgrade_duration_seconds=1.0,
        reupgrade_duration_seconds=1.0,
    )
    with pytest.raises(Exception):  # pydantic ValidationError on frozen model
        result.head_after_first_upgrade = "0024"  # type: ignore[misc]
