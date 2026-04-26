"""
Unit tests for ``services.cli.db_backup``.

Coverage:

1. URL parsing + redaction.
2. Backup mode mocks ``subprocess.run`` and asserts:
       * the right command is built (binary, ``--file``, no password
         in argv);
       * ``PGPASSWORD`` / ``PGUSER`` / etc. are passed via env;
       * the configured timeout is honoured;
       * the password never appears in stdout/stderr.
3. Restore mode:
       * refuses to run when the empty-probe returns rows > 0
         (without ``--force``);
       * proceeds when ``--force`` is passed even if the DB is non-empty;
       * skips the empty-probe entirely when ``--force`` is set
         (asserted via mock-call shape);
       * succeeds when the DB is empty.
4. Verify mode parses an inline SQL fixture and reports per-table
   row counts WITHOUT shelling out to anything.
5. Missing-binary path returns exit 1 with a clear message.
6. Subprocess timeout is propagated as exit 1.
7. Missing ``DATABASE_URL`` returns exit 1 with a clear message.
8. Subprocess failure (non-zero exit) returns exit 1 and surfaces
   stderr WITHOUT the password.

Does NOT:
    - Shell out to a real ``pg_dump`` / ``psql`` binary; every
      ``subprocess.run`` call is mocked. The tests run on a CI image
      that has neither the binaries nor a Postgres server.
    - Talk to a real Postgres database.
"""

from __future__ import annotations

import io
import subprocess
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest import mock

import pytest

from services.cli import db_backup as cli

# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

_VALID_URL: str = "postgresql://fxlab:s3cret@db.example.com:5432/fxlab"
_REDACTED_FORM: str = "postgresql://fxlab:***@db.example.com:5432/fxlab"


def _ok_completed(stdout: str = "", stderr: str = "") -> subprocess.CompletedProcess[str]:
    """Build a CompletedProcess with returncode=0 (subprocess success)."""
    return subprocess.CompletedProcess(args=[], returncode=0, stdout=stdout, stderr=stderr)


def _fail_completed(stdout: str = "", stderr: str = "boom") -> subprocess.CompletedProcess[str]:
    """Build a CompletedProcess with returncode=1 (subprocess failure)."""
    return subprocess.CompletedProcess(args=[], returncode=1, stdout=stdout, stderr=stderr)


def _run_main(argv: list[str], env: dict[str, str] | None = None) -> tuple[int, str, str]:
    """
    Invoke :func:`cli.main` with ``argv``, optionally patching the
    process env. Captures stdout + stderr.

    Returns:
        ``(exit_code, stdout, stderr)``.
    """
    out_buf = io.StringIO()
    err_buf = io.StringIO()
    if env is None:
        with redirect_stdout(out_buf), redirect_stderr(err_buf):
            exit_code = cli.main(argv)
    else:
        with mock.patch.dict("os.environ", env, clear=False):
            with redirect_stdout(out_buf), redirect_stderr(err_buf):
                exit_code = cli.main(argv)
    return exit_code, out_buf.getvalue(), err_buf.getvalue()


# ---------------------------------------------------------------------------
# URL parsing + redaction
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_parse_database_url_extracts_components_and_redacts_password() -> None:
    """Happy-path parse populates every field and the redacted form hides the password."""
    db = cli._parse_database_url(_VALID_URL)
    assert db.user == "fxlab"
    assert db.password == "s3cret"
    assert db.host == "db.example.com"
    assert db.port == 5432
    assert db.database == "fxlab"
    assert db.redacted == _REDACTED_FORM
    assert "s3cret" not in db.redacted


@pytest.mark.unit
def test_parse_database_url_rejects_missing_url() -> None:
    """Empty DATABASE_URL produces an actionable error."""
    with pytest.raises(cli.DbBackupError, match="DATABASE_URL is not set"):
        cli._parse_database_url("")


@pytest.mark.unit
def test_parse_database_url_rejects_non_postgres_scheme() -> None:
    """Non-Postgres schemes (sqlite, mysql) are rejected."""
    with pytest.raises(cli.DbBackupError, match="postgresql:// scheme"):
        cli._parse_database_url("sqlite:///tmp/x.db")


@pytest.mark.unit
def test_parse_database_url_rejects_missing_database() -> None:
    """Missing database name is rejected."""
    with pytest.raises(cli.DbBackupError, match="missing the database component"):
        cli._parse_database_url("postgresql://user:pw@host:5432/")


@pytest.mark.unit
def test_subprocess_env_passes_password_via_env_not_argv() -> None:
    """
    The CLI's password-redaction guarantee relies on `_subprocess_env`
    being the only place the plaintext password is visible.
    """
    db = cli._parse_database_url(_VALID_URL)
    env = cli._subprocess_env(db)
    assert env["PGPASSWORD"] == "s3cret"
    assert env["PGUSER"] == "fxlab"
    assert env["PGHOST"] == "db.example.com"
    assert env["PGPORT"] == "5432"
    assert env["PGDATABASE"] == "fxlab"


# ---------------------------------------------------------------------------
# Backup mode
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_backup_mode_invokes_pg_dump_with_correct_args(tmp_path: Path) -> None:
    """
    Backup mode discovers pg_dump, calls subprocess.run with the right
    command shape, passes the password via env (NOT argv), and reports
    the redacted URL in stdout.
    """
    output = tmp_path / "dump.sql"
    # The CLI logs the byte-size of the resulting file; create an
    # empty placeholder so .stat() succeeds inside the mocked path.
    output.write_text("-- empty dump\n", encoding="utf-8")

    with (
        mock.patch.object(cli.shutil, "which", return_value="/usr/bin/pg_dump"),
        mock.patch.object(cli.subprocess, "run", return_value=_ok_completed()) as mock_run,
    ):
        exit_code, stdout, stderr = _run_main(
            ["--mode", "backup", "--output", str(output)],
            env={"DATABASE_URL": _VALID_URL},
        )

    assert exit_code == 0, f"stderr={stderr!r}"
    assert mock_run.call_count == 1
    call = mock_run.call_args
    cmd = call.args[0]
    # Binary path is the resolved pg_dump.
    assert cmd[0] == "/usr/bin/pg_dump"
    # The dump file path is passed via --file.
    assert "--file" in cmd
    assert str(output) in cmd
    # Password is NEVER in argv.
    assert all("s3cret" not in str(token) for token in cmd)
    # Password IS in the subprocess env.
    env = call.kwargs["env"]
    assert env["PGPASSWORD"] == "s3cret"
    assert env["PGUSER"] == "fxlab"
    # Default timeout applied.
    assert call.kwargs["timeout"] == cli._DEFAULT_BACKUP_TIMEOUT_S
    # Stdout reports the redacted URL only.
    assert _REDACTED_FORM in stdout
    assert "s3cret" not in stdout
    assert "s3cret" not in stderr


@pytest.mark.unit
def test_backup_mode_honours_custom_timeout(tmp_path: Path) -> None:
    """The --timeout flag overrides the default backup timeout."""
    output = tmp_path / "dump.sql"
    output.write_text("-- empty dump\n", encoding="utf-8")
    with (
        mock.patch.object(cli.shutil, "which", return_value="/usr/bin/pg_dump"),
        mock.patch.object(cli.subprocess, "run", return_value=_ok_completed()) as mock_run,
    ):
        exit_code, _, _ = _run_main(
            ["--mode", "backup", "--output", str(output), "--timeout", "42"],
            env={"DATABASE_URL": _VALID_URL},
        )
    assert exit_code == 0
    assert mock_run.call_args.kwargs["timeout"] == 42


@pytest.mark.unit
def test_backup_mode_subprocess_failure_returns_exit_one(tmp_path: Path) -> None:
    """A non-zero pg_dump exit propagates as exit 1; password stays redacted in stderr."""
    output = tmp_path / "dump.sql"
    with (
        mock.patch.object(cli.shutil, "which", return_value="/usr/bin/pg_dump"),
        mock.patch.object(
            cli.subprocess, "run", return_value=_fail_completed(stderr="connection refused")
        ),
    ):
        exit_code, stdout, stderr = _run_main(
            ["--mode", "backup", "--output", str(output)],
            env={"DATABASE_URL": _VALID_URL},
        )
    assert exit_code == 1
    assert "pg_dump failed" in stderr
    assert "connection refused" in stderr
    # Critical: even on failure, the password never leaks.
    assert "s3cret" not in stderr
    assert "s3cret" not in stdout


@pytest.mark.unit
def test_backup_mode_subprocess_timeout_returns_exit_one(tmp_path: Path) -> None:
    """A subprocess timeout is reported with the configured limit; password stays hidden."""
    output = tmp_path / "dump.sql"
    with (
        mock.patch.object(cli.shutil, "which", return_value="/usr/bin/pg_dump"),
        mock.patch.object(
            cli.subprocess,
            "run",
            side_effect=subprocess.TimeoutExpired(cmd="pg_dump", timeout=600),
        ),
    ):
        exit_code, _, stderr = _run_main(
            ["--mode", "backup", "--output", str(output)],
            env={"DATABASE_URL": _VALID_URL},
        )
    assert exit_code == 1
    assert "exceeded" in stderr
    assert "s3cret" not in stderr


@pytest.mark.unit
def test_backup_mode_missing_pg_dump_returns_exit_one(tmp_path: Path) -> None:
    """A missing pg_dump binary on PATH yields a clear error and exit 1."""
    output = tmp_path / "dump.sql"
    with mock.patch.object(cli.shutil, "which", return_value=None):
        exit_code, _, stderr = _run_main(
            ["--mode", "backup", "--output", str(output)],
            env={"DATABASE_URL": _VALID_URL},
        )
    assert exit_code == 1
    assert "pg_dump not found in PATH" in stderr


@pytest.mark.unit
def test_backup_mode_missing_database_url_returns_exit_one(tmp_path: Path) -> None:
    """No DATABASE_URL in env yields a clear actionable error."""
    output = tmp_path / "dump.sql"
    # Force-clear DATABASE_URL even if present in the test process.
    with mock.patch.dict("os.environ", {}, clear=True):
        out_buf = io.StringIO()
        err_buf = io.StringIO()
        with redirect_stdout(out_buf), redirect_stderr(err_buf):
            exit_code = cli.main(["--mode", "backup", "--output", str(output)])
    assert exit_code == 1
    assert "DATABASE_URL is not set" in err_buf.getvalue()


@pytest.mark.unit
def test_backup_mode_missing_output_returns_exit_one() -> None:
    """--mode=backup without --output is rejected."""
    exit_code, _, stderr = _run_main(
        ["--mode", "backup"],
        env={"DATABASE_URL": _VALID_URL},
    )
    assert exit_code == 1
    assert "--output is required" in stderr


# ---------------------------------------------------------------------------
# Restore mode
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_restore_mode_refuses_non_empty_db_without_force(tmp_path: Path) -> None:
    """
    The pre-flight empty-probe returns >0; restore must abort with a
    clear message and no actual psql -f invocation.
    """
    dump = tmp_path / "dump.sql"
    dump.write_text("-- dump\n", encoding="utf-8")

    # First subprocess.run = empty probe (returns "42" rows).
    # No second call should occur because we abort.
    probe = _ok_completed(stdout="42\n")
    with (
        mock.patch.object(cli.shutil, "which", return_value="/usr/bin/psql"),
        mock.patch.object(cli.subprocess, "run", return_value=probe) as mock_run,
    ):
        exit_code, stdout, stderr = _run_main(
            ["--mode", "restore", "--input", str(dump)],
            env={"DATABASE_URL": _VALID_URL},
        )
    assert exit_code == 1
    assert mock_run.call_count == 1, "should bail after the empty-probe; no restore call"
    assert "refusing to restore" in stderr
    assert "42" in stderr
    assert "s3cret" not in stderr
    assert "s3cret" not in stdout


@pytest.mark.unit
def test_restore_mode_proceeds_when_db_is_empty(tmp_path: Path) -> None:
    """An empty-probe of 0 rows lets the restore proceed; psql -f is invoked once."""
    dump = tmp_path / "dump.sql"
    dump.write_text("-- dump\n", encoding="utf-8")

    # Two calls: empty probe (returns "0"), then the actual restore.
    side = [_ok_completed(stdout="0\n"), _ok_completed()]
    with (
        mock.patch.object(cli.shutil, "which", return_value="/usr/bin/psql"),
        mock.patch.object(cli.subprocess, "run", side_effect=side) as mock_run,
    ):
        exit_code, stdout, stderr = _run_main(
            ["--mode", "restore", "--input", str(dump)],
            env={"DATABASE_URL": _VALID_URL},
        )
    assert exit_code == 0, f"stderr={stderr!r}"
    assert mock_run.call_count == 2
    # Second call is the actual restore.
    restore_call = mock_run.call_args_list[1]
    cmd = restore_call.args[0]
    assert cmd[0] == "/usr/bin/psql"
    assert "--file" in cmd
    assert str(dump) in cmd
    # Password redacted everywhere.
    assert _REDACTED_FORM in stdout
    assert "s3cret" not in stdout
    assert "s3cret" not in stderr


@pytest.mark.unit
def test_restore_mode_force_skips_empty_probe(tmp_path: Path) -> None:
    """With --force, only one subprocess.run is made (the actual restore)."""
    dump = tmp_path / "dump.sql"
    dump.write_text("-- dump\n", encoding="utf-8")
    with (
        mock.patch.object(cli.shutil, "which", return_value="/usr/bin/psql"),
        mock.patch.object(cli.subprocess, "run", return_value=_ok_completed()) as mock_run,
    ):
        exit_code, _, stderr = _run_main(
            ["--mode", "restore", "--input", str(dump), "--force"],
            env={"DATABASE_URL": _VALID_URL},
        )
    assert exit_code == 0, stderr
    assert mock_run.call_count == 1
    # No probe — first (and only) call is the restore itself.
    cmd = mock_run.call_args.args[0]
    assert "--file" in cmd
    assert str(dump) in cmd


@pytest.mark.unit
def test_restore_mode_missing_input_file_returns_exit_one(tmp_path: Path) -> None:
    """A non-existent dump file is reported clearly."""
    missing = tmp_path / "does-not-exist.sql"
    with mock.patch.object(cli.shutil, "which", return_value="/usr/bin/psql"):
        exit_code, _, stderr = _run_main(
            ["--mode", "restore", "--input", str(missing)],
            env={"DATABASE_URL": _VALID_URL},
        )
    assert exit_code == 1
    assert "dump file not found" in stderr


@pytest.mark.unit
def test_restore_mode_subprocess_failure_returns_exit_one(tmp_path: Path) -> None:
    """A psql restore failure surfaces stderr without leaking the password."""
    dump = tmp_path / "dump.sql"
    dump.write_text("-- dump\n", encoding="utf-8")
    side = [_ok_completed(stdout="0\n"), _fail_completed(stderr="syntax error at line 12")]
    with (
        mock.patch.object(cli.shutil, "which", return_value="/usr/bin/psql"),
        mock.patch.object(cli.subprocess, "run", side_effect=side),
    ):
        exit_code, stdout, stderr = _run_main(
            ["--mode", "restore", "--input", str(dump)],
            env={"DATABASE_URL": _VALID_URL},
        )
    assert exit_code == 1
    assert "psql restore failed" in stderr
    assert "syntax error at line 12" in stderr
    assert "s3cret" not in stderr
    assert "s3cret" not in stdout


@pytest.mark.unit
def test_restore_mode_missing_input_arg_returns_exit_one() -> None:
    """--mode=restore without --input is rejected."""
    exit_code, _, stderr = _run_main(
        ["--mode", "restore"],
        env={"DATABASE_URL": _VALID_URL},
    )
    assert exit_code == 1
    assert "--input is required" in stderr


# ---------------------------------------------------------------------------
# Verify mode
# ---------------------------------------------------------------------------


_SAMPLE_DUMP: str = """\
--
-- PostgreSQL database dump
--

SET statement_timeout = 0;

CREATE TABLE public.users (id integer, email text);

COPY public.users (id, email) FROM stdin;
1\talice@example.com
2\tbob@example.com
3\tcharlie@example.com
\\.

CREATE TABLE "public"."strategies" (id integer, name text);

INSERT INTO public.strategies (id, name) VALUES (1, 'lien');
INSERT INTO public.strategies (id, name) VALUES (2, 'macd');

COPY "public"."runs" (id) FROM stdin;
10
20
\\.

--
-- Done
--
"""


@pytest.mark.unit
def test_verify_mode_parses_copy_and_insert_blocks(tmp_path: Path) -> None:
    """
    Verify mode parses an inline SQL fixture, sums COPY rows + INSERT
    statements per table, and reports the totals on stdout.
    """
    dump = tmp_path / "dump.sql"
    dump.write_text(_SAMPLE_DUMP, encoding="utf-8")

    exit_code, stdout, stderr = _run_main(["--mode", "verify", "--input", str(dump)])
    assert exit_code == 0, stderr
    # Per-table line for users (3 COPY rows).
    assert "table=public.users rows=3" in stdout
    # Per-table line for strategies (2 INSERT statements).
    assert "table=public.strategies rows=2" in stdout
    # The quoted "public"."runs" should normalise to public.runs.
    assert "table=public.runs rows=2" in stdout
    # Totals.
    assert "total_rows=7" in stdout
    assert "copy_blocks=2" in stdout
    assert "insert_statements=2" in stdout


@pytest.mark.unit
def test_verify_mode_missing_input_returns_exit_one(tmp_path: Path) -> None:
    """A missing --input path returns a clear error and exit 1."""
    missing = tmp_path / "missing.sql"
    exit_code, _, stderr = _run_main(["--mode", "verify", "--input", str(missing)])
    assert exit_code == 1
    assert "dump file not found" in stderr


@pytest.mark.unit
def test_verify_mode_does_not_invoke_subprocess(tmp_path: Path) -> None:
    """
    Verify is a pure parse — it must NOT shell out to pg_dump or psql,
    even by accident. Asserting this with a mock catches a future
    regression that wires verify through subprocess.
    """
    dump = tmp_path / "dump.sql"
    dump.write_text(_SAMPLE_DUMP, encoding="utf-8")
    with mock.patch.object(cli.subprocess, "run") as mock_run:
        exit_code, _, _ = _run_main(["--mode", "verify", "--input", str(dump)])
    assert exit_code == 0
    assert mock_run.call_count == 0


@pytest.mark.unit
def test_verify_mode_missing_input_arg_returns_exit_one() -> None:
    """--mode=verify without --input is rejected."""
    exit_code, _, stderr = _run_main(["--mode", "verify"])
    assert exit_code == 1
    assert "--input is required" in stderr


# ---------------------------------------------------------------------------
# Format helpers
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_format_verify_renders_sorted_table_lines(tmp_path: Path) -> None:
    """
    The verify report sorts table names alphabetically so the output
    is deterministic regardless of dump order.
    """
    report = cli._VerifyReport(
        path=tmp_path / "x.sql",
        size_bytes=42,
        table_row_counts={"public.zeta": 1, "public.alpha": 2},
        copy_blocks=1,
        insert_statements=1,
    )
    out = cli._format_verify(report)
    alpha_idx = out.index("table=public.alpha")
    zeta_idx = out.index("table=public.zeta")
    assert alpha_idx < zeta_idx
    assert "total_rows=3" in out
    assert "size_bytes=42" in out


# ---------------------------------------------------------------------------
# Argparse builder
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_parser_help_lists_three_modes() -> None:
    """The CLI help text exposes the three supported modes."""
    parser = cli._build_parser()
    help_text = parser.format_help()
    assert "backup" in help_text
    assert "restore" in help_text
    assert "verify" in help_text
