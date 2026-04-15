"""
Result contract for MigrationIntegrityValidator.

Purpose:
    Immutable result object returned by the validator. Captures the three
    revisions observed during a round-trip and the wall-clock durations of
    each phase so that operators and CI logs can reason about migration
    runtime regressions.

Responsibilities:
    - Carry a single source of truth for the outcome of one validation run.
    - Provide a human-readable summary for log output without exposing
      mutable internals.

Does NOT:
    - Perform any I/O.
    - Know about Alembic, PostgreSQL, or the validator orchestration.

Dependencies:
    - Pydantic (already a project dependency) for immutability and
      field-level validation.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class MigrationIntegrityResult(BaseModel):
    """
    Outcome of a full up/down/up migration round-trip.

    Fields:
        initial_revision: Revision at the start (usually ``None`` for a
            freshly provisioned database).
        head_after_first_upgrade: Revision after the first upgrade_to_head.
        revision_after_downgrade: Revision after downgrade_to_base (expected
            to be ``None`` — the empty/base state).
        head_after_second_upgrade: Revision after the second upgrade_to_head.
        upgrade_duration_seconds: Wall-clock seconds for the first upgrade.
        downgrade_duration_seconds: Wall-clock seconds for the downgrade.
        reupgrade_duration_seconds: Wall-clock seconds for the second upgrade.

    Invariants (enforced by the validator, not by this model):
        - ``head_after_first_upgrade == head_after_second_upgrade``
        - ``revision_after_downgrade is None``
        - All three durations are non-negative.

    Example:
        result = MigrationIntegrityResult(
            initial_revision=None,
            head_after_first_upgrade="0023",
            revision_after_downgrade=None,
            head_after_second_upgrade="0023",
            upgrade_duration_seconds=12.34,
            downgrade_duration_seconds=3.21,
            reupgrade_duration_seconds=11.98,
        )
        print(result.summary())
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    initial_revision: str | None = Field(
        default=None,
        description="Current revision before any operation.",
    )
    head_after_first_upgrade: str = Field(
        ...,
        min_length=1,
        description="Revision after the first upgrade_to_head call.",
    )
    revision_after_downgrade: str | None = Field(
        default=None,
        description="Revision after downgrade_to_base (expected None).",
    )
    head_after_second_upgrade: str = Field(
        ...,
        min_length=1,
        description="Revision after the second upgrade_to_head call.",
    )
    upgrade_duration_seconds: float = Field(..., ge=0.0)
    downgrade_duration_seconds: float = Field(..., ge=0.0)
    reupgrade_duration_seconds: float = Field(..., ge=0.0)

    def summary(self) -> str:
        """
        Return a one-line human-readable summary of the result.

        Example output:
            "initial=None  head=0023  downgrade=None  reupgrade=0023  "
            "up=12.34s  down=3.21s  reup=11.98s"
        """
        return (
            f"initial={self.initial_revision}  "
            f"head={self.head_after_first_upgrade}  "
            f"downgrade={self.revision_after_downgrade}  "
            f"reupgrade={self.head_after_second_upgrade}  "
            f"up={self.upgrade_duration_seconds:.2f}s  "
            f"down={self.downgrade_duration_seconds:.2f}s  "
            f"reup={self.reupgrade_duration_seconds:.2f}s"
        )
