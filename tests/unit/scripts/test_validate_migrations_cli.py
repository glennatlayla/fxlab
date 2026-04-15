"""
Unit tests for the validate_migrations CLI script.

Scope:
    Argument parsing, exit codes, and the production-URL safety guard.
    The Alembic runner and validator are mocked out so these tests
    complete in milliseconds and do not require a database.
"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

# Import path: scripts/ is not a package in the normal sense, but once the
# repo root is on sys.path Python resolves ``scripts.validate_migrations``.
from scripts import validate_migrations as cli  # noqa: E402

# ---------------------------------------------------------------------------
# Safety guard
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "url",
    [
        "postgresql://u:p@db.example.com:5432/fxlab_production",
        "postgresql://u:p@fxlab-prod.example.com/fxlab",
        "postgresql://u:p@host/fxlab_live",
    ],
)
def test_is_dangerous_url_catches_production_markers(url: str) -> None:
    assert cli._is_dangerous_url(url) is True


@pytest.mark.parametrize(
    "url",
    [
        "postgresql://u:p@localhost:5433/fxlab_test",
        "postgresql://fxlab_test:fxlab_test@127.0.0.1:5432/fxlab_test",
        "sqlite:///./test.db",
    ],
)
def test_is_dangerous_url_accepts_test_urls(url: str) -> None:
    assert cli._is_dangerous_url(url) is False


# ---------------------------------------------------------------------------
# Exit codes
# ---------------------------------------------------------------------------


def test_main_exits_2_when_database_url_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("DATABASE_URL", raising=False)
    assert cli.main([]) == 2


def test_main_exits_2_when_url_looks_like_production(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(
        "DATABASE_URL",
        "postgresql://u:p@db/fxlab_production",
    )
    assert cli.main([]) == 2


def test_main_exits_1_when_validator_raises(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """A MigrationIntegrityError from the validator yields exit code 1."""
    # Use a non-postgres URL to skip the schema-reset step cleanly.
    monkeypatch.setenv("DATABASE_URL", "sqlite:///:memory:")

    from libs.dev.migration_integrity_validator import MigrationIntegrityError

    with patch.object(
        cli.MigrationIntegrityValidator,
        "validate",
        side_effect=MigrationIntegrityError("boom", phase="upgrade_to_head"),
    ):
        assert cli.main([]) == 1


def test_main_exits_0_on_success(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A successful validation yields exit 0 and prints a summary line."""
    monkeypatch.setenv("DATABASE_URL", "sqlite:///:memory:")

    from libs.dev.migration_integrity_result import MigrationIntegrityResult

    fake_result = MigrationIntegrityResult(
        initial_revision=None,
        head_after_first_upgrade="0023",
        revision_after_downgrade=None,
        head_after_second_upgrade="0023",
        upgrade_duration_seconds=1.0,
        downgrade_duration_seconds=0.5,
        reupgrade_duration_seconds=0.9,
    )
    with patch.object(cli.MigrationIntegrityValidator, "validate", return_value=fake_result):
        assert cli.main([]) == 0


# ---------------------------------------------------------------------------
# Allow-dangerous override
# ---------------------------------------------------------------------------


def test_allow_dangerous_url_flag_bypasses_guard(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """With --allow-dangerous-url, a production URL is permitted through
    the guard (the validator itself is still mocked out here — the point
    of the test is to confirm the guard logic, not run migrations)."""
    monkeypatch.setenv(
        "DATABASE_URL",
        "postgresql://u:p@db/fxlab_production",
    )

    from libs.dev.migration_integrity_result import MigrationIntegrityResult

    fake_result = MigrationIntegrityResult(
        initial_revision=None,
        head_after_first_upgrade="0023",
        revision_after_downgrade=None,
        head_after_second_upgrade="0023",
        upgrade_duration_seconds=1.0,
        downgrade_duration_seconds=0.5,
        reupgrade_duration_seconds=0.9,
    )
    with (
        patch.object(cli.MigrationIntegrityValidator, "validate", return_value=fake_result),
        patch.object(cli, "_reset_schema", return_value=None),
    ):
        assert cli.main(["--allow-dangerous-url"]) == 0
