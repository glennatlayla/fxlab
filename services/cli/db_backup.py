"""
Postgres database backup / restore / verify CLI.

Purpose:
    Operator tool that wraps ``pg_dump`` / ``psql`` for the FXLab
    Postgres instance so an operator can capture and restore the
    application database without remembering the exact command shape
    or having to copy a connection string out of an env file. Supports
    three modes:

    1. ``--mode backup --output PATH``: shell out to ``pg_dump``,
       writing a SQL dump to ``PATH``.
    2. ``--mode restore --input PATH``: shell out to ``psql``,
       applying the dump to the database referenced by ``DATABASE_URL``.
       Refuses to run if any user table already has rows unless
       ``--force`` is passed (prevents an operator from accidentally
       overwriting a populated DB).
    3. ``--mode verify --input PATH``: parse the SQL dump locally
       (no DB I/O) and report per-table row counts so the operator
       can preview what a restore would load. This is the "I'm about
       to restore — what's in this file?" check.

    Real operator need: today there is no backup tooling, so a single
    Postgres data-volume corruption loses every imported strategy and
    every backtest history record. This CLI closes that gap with the
    minimum viable surface (one entry per mode) and a corresponding
    Makefile target for muscle memory.

Responsibilities:
    - Resolve ``DATABASE_URL`` from the process environment, parse out
      its components (user/password/host/port/database), and pass them
      to ``pg_dump`` / ``psql`` via the standard ``PG*`` environment
      variables (``PGPASSWORD``, ``PGUSER``, ``PGHOST``, ``PGPORT``,
      ``PGDATABASE``). NEVER embed the password in argv (where it
      would show up in ``ps`` and shell history).
    - Discover the ``pg_dump`` / ``psql`` binaries via ``shutil.which``
      and exit with a clear "binary not found" message when missing.
    - Apply per-mode subprocess timeouts (default 600s for backup,
      1200s for restore, none for verify).
    - For restore: run a pre-flight SELECT to count rows across user
      tables and refuse to proceed when the DB is non-empty, unless
      ``--force`` is set.
    - For verify: parse the SQL dump's ``COPY ... FROM stdin`` blocks
      and ``INSERT INTO ... VALUES`` lines to count rows per table,
      WITHOUT executing any SQL.
    - Emit operator-readable progress + summary to stdout.
    - Redact the password in every log line / error message
      (``postgresql://user:***@host:5432/db``).

Does NOT:
    - Talk to the broker, the API, or anything outside Postgres.
    - Stream the dump through encryption / compression. The operator
      can pipe through ``gzip`` / ``age`` outside the CLI; embedding
      compression would couple the tool to a specific format choice
      and complicate the verify path.
    - Mutate the database in any mode other than restore.
    - Print or log the password from ``DATABASE_URL`` anywhere — log
      lines, error messages, and stderr all use the redacted form
      ``postgresql://user:***@host:5432/db``.

Dependencies:
    - ``pg_dump`` / ``psql`` binaries on PATH (the standard Postgres
      client tools). Provided by the ``postgresql-client-N`` package
      on Debian/Ubuntu and bundled with most Postgres installs.
    - ``DATABASE_URL`` environment variable: a Postgres connection
      string of the form
      ``postgresql://user:password@host:5432/database``.

Error conditions:
    - ``DATABASE_URL`` missing or non-Postgres → exit 1.
    - ``pg_dump`` / ``psql`` not on PATH → exit 1.
    - Subprocess returns non-zero → exit 1, stderr surfaced.
    - Subprocess exceeds timeout → exit 1, killed.
    - Restore against a non-empty DB without ``--force`` → exit 1.

Example:
    # Capture a backup
    DATABASE_URL=postgresql://fxlab:secret@localhost:5432/fxlab \\
        .venv/bin/python -m services.cli.db_backup \\
        --mode backup --output /tmp/fxlab-backup.sql

    # Verify a backup before restoring
    .venv/bin/python -m services.cli.db_backup \\
        --mode verify --input /tmp/fxlab-backup.sql

    # Restore (only into an empty database; --force to overwrite)
    DATABASE_URL=postgresql://fxlab:secret@localhost:5432/fxlab \\
        .venv/bin/python -m services.cli.db_backup \\
        --mode restore --input /tmp/fxlab-backup.sql
"""

from __future__ import annotations

import argparse
import os
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import unquote, urlparse

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

#: Default subprocess timeout (seconds) for ``pg_dump``. Backups for
#: the M3 fxlab database fit in <30s on a developer laptop, but the
#: ceiling is set high enough that a slow disk or a CI runner under
#: load does not spuriously time out. Override at the CLI with
#: ``--timeout``.
_DEFAULT_BACKUP_TIMEOUT_S: int = 600

#: Default subprocess timeout (seconds) for ``psql`` restore. Restores
#: are I/O-bound and can be substantially slower than backups when the
#: dump contains large COPY blocks; the ceiling is doubled relative to
#: backup. Override at the CLI with ``--timeout``.
_DEFAULT_RESTORE_TIMEOUT_S: int = 1200

#: Exit codes. We deliberately expose only 0 (success) and 1 (any
#: failure) — the operator cares whether the backup succeeded, not
#: which subroutine of the CLI failed.
_EXIT_OK: int = 0
_EXIT_FAIL: int = 1


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------


class DbBackupError(Exception):
    """
    Raised by any helper in this module when the operation cannot
    proceed. Always carries an operator-readable message that already
    has the password redacted from any URL it embeds. The CLI catches
    this in :func:`main` and exits with status 1 after writing the
    message to stderr.
    """


# ---------------------------------------------------------------------------
# DATABASE_URL parsing + redaction
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _DatabaseUrl:
    """
    Parsed Postgres connection components.

    Attributes:
        user: The Postgres role to connect as.
        password: The role's password. NEVER printed; consumed only as
            ``PGPASSWORD`` in the subprocess env.
        host: The Postgres server hostname.
        port: TCP port (default 5432 if absent in the URL).
        database: The database name.
        redacted: Display form of the URL with ``password`` replaced
            by ``***``. Used in every log / error message that needs
            to identify the target.
    """

    user: str
    password: str
    host: str
    port: int
    database: str
    redacted: str


def _parse_database_url(url: str) -> _DatabaseUrl:
    """
    Parse a Postgres ``DATABASE_URL`` into typed components.

    Args:
        url: A connection string of the form
            ``postgresql://user:password@host:port/database`` (the
            ``postgres://`` legacy scheme is also accepted).

    Returns:
        :class:`_DatabaseUrl` with parsed components and a redacted
        display form.

    Raises:
        DbBackupError: when the URL is empty, has the wrong scheme,
            or is missing required fields (user, host, database).
    """
    if not url:
        raise DbBackupError(
            "DATABASE_URL is not set. Set it to a postgresql:// connection string "
            "(e.g. postgresql://fxlab:secret@localhost:5432/fxlab) and re-run."
        )
    parsed = urlparse(url)
    if parsed.scheme not in ("postgresql", "postgres"):
        raise DbBackupError(
            f"DATABASE_URL must use the postgresql:// scheme; got {parsed.scheme!r}. "
            "This CLI does not support SQLite or other engines."
        )
    user = unquote(parsed.username or "")
    password = unquote(parsed.password or "")
    host = parsed.hostname or ""
    port = parsed.port or 5432
    # urlparse leaves the leading slash on the path; strip it for the
    # database name. Reject any URL whose path component is "/" or
    # missing; pg_dump cannot connect without a database name.
    database = (parsed.path or "").lstrip("/")
    if not user:
        raise DbBackupError("DATABASE_URL is missing the user component.")
    if not host:
        raise DbBackupError("DATABASE_URL is missing the host component.")
    if not database:
        raise DbBackupError("DATABASE_URL is missing the database component.")
    redacted = f"postgresql://{user}:***@{host}:{port}/{database}"
    return _DatabaseUrl(
        user=user,
        password=password,
        host=host,
        port=port,
        database=database,
        redacted=redacted,
    )


def _subprocess_env(db: _DatabaseUrl) -> dict[str, str]:
    """
    Build a subprocess environment that passes Postgres credentials
    through the standard ``PG*`` env vars.

    Why env vars rather than CLI flags:
        ``pg_dump`` / ``psql`` accept ``--password`` only via interactive
        prompt; the non-interactive path is ``PGPASSWORD``. Putting the
        password in argv would expose it in ``ps`` output and shell
        history. Env-only is the standard, audited approach.

    Args:
        db: Parsed connection components.

    Returns:
        A new dict (the existing ``os.environ`` is copied, not mutated)
        with ``PGPASSWORD`` / ``PGUSER`` / ``PGHOST`` / ``PGPORT`` /
        ``PGDATABASE`` overridden to ``db``'s values.
    """
    env = dict(os.environ)
    env["PGPASSWORD"] = db.password
    env["PGUSER"] = db.user
    env["PGHOST"] = db.host
    env["PGPORT"] = str(db.port)
    env["PGDATABASE"] = db.database
    return env


# ---------------------------------------------------------------------------
# Binary discovery
# ---------------------------------------------------------------------------


def _resolve_binary(name: str) -> str:
    """
    Resolve a Postgres client binary on PATH.

    Args:
        name: ``"pg_dump"`` or ``"psql"``.

    Returns:
        Absolute path to the binary.

    Raises:
        DbBackupError: when the binary is not on PATH. Message names
            the missing binary so the operator knows what to install.
    """
    resolved = shutil.which(name)
    if resolved is None:
        raise DbBackupError(
            f"{name} not found in PATH. Install the Postgres client tools "
            "(e.g. `sudo apt install postgresql-client` on Debian/Ubuntu) "
            "and re-run."
        )
    return resolved


# ---------------------------------------------------------------------------
# Mode: backup
# ---------------------------------------------------------------------------


def _run_backup(db: _DatabaseUrl, output: Path, timeout_s: int) -> None:
    """
    Execute ``pg_dump`` against ``db`` and write to ``output``.

    Args:
        db: Parsed connection components. The password is passed via
            ``PGPASSWORD`` so it never appears in argv.
        output: Filesystem path the dump is written to. Parent
            directory is created if missing.
        timeout_s: Subprocess timeout in seconds.

    Raises:
        DbBackupError: when ``pg_dump`` fails, times out, or is missing.
    """
    pg_dump = _resolve_binary("pg_dump")
    output.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        pg_dump,
        # Plain-text SQL dump: works with `psql -f` for restore and is
        # parseable by --mode verify. ``-c`` adds DROP statements so a
        # restore over an existing schema is reproducible. ``--if-exists``
        # makes the DROPs tolerant of missing tables (the M3 schema is
        # still evolving; not every backup will match the live schema
        # one-to-one).
        "--clean",
        "--if-exists",
        "--no-owner",
        "--no-privileges",
        "--format=plain",
        "--file",
        str(output),
    ]
    sys.stdout.write(f"db-backup: dumping {db.redacted} -> {output}\n")
    try:
        result = subprocess.run(
            cmd,
            env=_subprocess_env(db),
            capture_output=True,
            text=True,
            timeout=timeout_s,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise DbBackupError(
            f"pg_dump exceeded {timeout_s}s timeout against {db.redacted}; aborted."
        ) from exc
    if result.returncode != 0:
        # pg_dump's stderr is operator-actionable; surface it but still
        # ensure no password leaks (the URL is passed via env, so stderr
        # only contains pg_dump's own diagnostics — but be explicit).
        stderr = (result.stderr or "").strip()
        raise DbBackupError(
            f"pg_dump failed (exit {result.returncode}) against {db.redacted}: {stderr}"
        )
    size_bytes = output.stat().st_size if output.exists() else 0
    sys.stdout.write(f"db-backup: wrote {size_bytes} bytes to {output} from {db.redacted}\n")


# ---------------------------------------------------------------------------
# Mode: restore
# ---------------------------------------------------------------------------


#: SQL run by --mode restore's pre-flight check. Counts rows across
#: every user table in the public schema. The restore refuses to
#: proceed if the sum is > 0 unless --force is set. Schema-only tables
#: (sequences, types) are intentionally excluded; only relation row
#: counts matter for "is this DB empty?".
_NON_EMPTY_PROBE_SQL: str = (
    "SELECT COALESCE(SUM(c.reltuples::bigint), 0)::bigint AS total_rows "
    "FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace "
    "WHERE c.relkind = 'r' AND n.nspname = 'public';"
)


def _check_database_empty(db: _DatabaseUrl, timeout_s: int) -> int:
    """
    Run the non-empty probe and return the row-count estimate.

    Why pg_class.reltuples instead of SELECT COUNT(*) per table:
        ``reltuples`` is Postgres's planner statistic — instant to read
        and "good enough" for the empty/non-empty signal. A real
        ``SELECT COUNT(*)`` per table would require iterating the
        catalog and could take minutes against a large schema.

    Returns:
        An integer estimate of total rows across all public tables.
        ``0`` means the DB is empty (or has only empty tables); any
        positive value is treated as non-empty.

    Raises:
        DbBackupError: when the psql probe fails.
    """
    psql = _resolve_binary("psql")
    cmd = [
        psql,
        "--no-psqlrc",
        "--quiet",
        "--no-align",
        "--tuples-only",
        "--command",
        _NON_EMPTY_PROBE_SQL,
    ]
    try:
        result = subprocess.run(
            cmd,
            env=_subprocess_env(db),
            capture_output=True,
            text=True,
            timeout=timeout_s,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise DbBackupError(
            f"psql empty-probe exceeded {timeout_s}s against {db.redacted}; aborted."
        ) from exc
    if result.returncode != 0:
        raise DbBackupError(
            f"psql empty-probe failed (exit {result.returncode}) against "
            f"{db.redacted}: {(result.stderr or '').strip()}"
        )
    out = (result.stdout or "").strip()
    try:
        return int(out)
    except ValueError as exc:
        raise DbBackupError(
            f"psql empty-probe returned non-integer output {out!r} against {db.redacted}"
        ) from exc


def _run_restore(
    db: _DatabaseUrl,
    input_path: Path,
    *,
    force: bool,
    timeout_s: int,
) -> None:
    """
    Execute ``psql`` against ``db`` to apply the dump at ``input_path``.

    Pre-flight: counts rows across user tables; refuses to proceed when
    the count is positive unless ``force`` is True. This is the "don't
    accidentally clobber a populated production DB" guardrail.

    Args:
        db: Parsed connection components.
        input_path: Filesystem path to the SQL dump produced by
            ``--mode backup``.
        force: When True, skips the non-empty pre-flight and overwrites
            existing data. When False (default), refuses if the DB
            already has rows.
        timeout_s: Subprocess timeout in seconds.

    Raises:
        DbBackupError: when the dump file is missing, the pre-flight
            fails, the DB is non-empty without ``force``, or psql fails.
    """
    if not input_path.exists():
        raise DbBackupError(f"dump file not found: {input_path}")
    psql = _resolve_binary("psql")

    # Pre-flight: only when force is False. If the operator has already
    # accepted the risk by passing --force, there is no reason to spend
    # a round-trip on the catalog query.
    if not force:
        existing_rows = _check_database_empty(db, timeout_s=timeout_s)
        if existing_rows > 0:
            raise DbBackupError(
                f"refusing to restore: {db.redacted} appears non-empty "
                f"(reltuples estimate = {existing_rows}). Pass --force to "
                "overwrite, or drop+recreate the database manually first."
            )

    sys.stdout.write(f"db-restore: applying {input_path} -> {db.redacted} (force={force})\n")
    cmd = [
        psql,
        "--no-psqlrc",
        "--quiet",
        # Stop at the first SQL error. Without this psql by default
        # continues past errors, leaving a partially-populated DB that
        # is hard to reason about.
        "--set=ON_ERROR_STOP=1",
        "--single-transaction",
        "--file",
        str(input_path),
    ]
    try:
        result = subprocess.run(
            cmd,
            env=_subprocess_env(db),
            capture_output=True,
            text=True,
            timeout=timeout_s,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise DbBackupError(
            f"psql restore exceeded {timeout_s}s against {db.redacted}; aborted."
        ) from exc
    if result.returncode != 0:
        stderr = (result.stderr or "").strip()
        raise DbBackupError(
            f"psql restore failed (exit {result.returncode}) against {db.redacted}: {stderr}"
        )
    sys.stdout.write(f"db-restore: restored {input_path} into {db.redacted}\n")


# ---------------------------------------------------------------------------
# Mode: verify
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _VerifyReport:
    """
    Result of parsing a SQL dump in ``--mode verify``.

    Attributes:
        path: The dump file path.
        size_bytes: File size on disk.
        table_row_counts: Mapping of fully-qualified table name to
            row count parsed from the dump. Both ``COPY ... FROM stdin``
            blocks and ``INSERT INTO ... VALUES (...);`` statements
            are counted.
        copy_blocks: Number of ``COPY`` blocks observed.
        insert_statements: Number of ``INSERT INTO`` statements observed.
    """

    path: Path
    size_bytes: int
    table_row_counts: dict[str, int]
    copy_blocks: int
    insert_statements: int


# Matches "COPY <qualified_name> (col, col, ...) FROM stdin;"
# and    "COPY <qualified_name> FROM stdin;"
# The qualified name is captured as group 1; we normalise quoting
# (strip surrounding double-quotes) downstream so output is stable.
_COPY_RE: re.Pattern[str] = re.compile(
    r"^\s*COPY\s+([\w\.\"]+)(?:\s*\([^)]*\))?\s+FROM\s+stdin\s*;\s*$",
    re.IGNORECASE,
)

# Matches "INSERT INTO <qualified_name> ..." anywhere on a line.
_INSERT_RE: re.Pattern[str] = re.compile(
    r"^\s*INSERT\s+INTO\s+([\w\.\"]+)\b",
    re.IGNORECASE,
)


def _parse_dump(path: Path) -> _VerifyReport:
    """
    Parse a SQL dump and count per-table rows WITHOUT executing SQL.

    Recognised forms:

    1. ``COPY <table> [(cols)] FROM stdin;`` followed by tab-separated
       data lines and a terminating ``\\.`` line. Each non-terminator
       data line counts as one row. This is ``pg_dump --format=plain``'s
       default for table data.
    2. ``INSERT INTO <table> [(cols)] VALUES (...);``. Each statement
       counts as one row. This is ``pg_dump --inserts``'s output, used
       for some legacy backups.

    Args:
        path: Filesystem path to the SQL dump.

    Returns:
        :class:`_VerifyReport` with per-table counts and totals.

    Raises:
        DbBackupError: when the file does not exist or cannot be read.
    """
    if not path.exists():
        raise DbBackupError(f"dump file not found: {path}")
    size_bytes = path.stat().st_size
    counts: dict[str, int] = {}
    copy_blocks = 0
    insert_statements = 0

    in_copy: bool = False
    current_table: str | None = None

    try:
        # Stream the file line-by-line; backups can be large, and a
        # single .read() would balloon memory.
        with path.open("r", encoding="utf-8", errors="replace") as fh:
            for raw_line in fh:
                line = raw_line.rstrip("\n")
                if in_copy:
                    if line.strip() == r"\.":
                        # End of COPY block.
                        in_copy = False
                        current_table = None
                        continue
                    # Skip blank lines defensively (pg_dump never emits
                    # them inside a COPY block, but malformed dumps
                    # might).
                    if line == "":
                        continue
                    if current_table is not None:
                        counts[current_table] = counts.get(current_table, 0) + 1
                    continue

                copy_match = _COPY_RE.match(line)
                if copy_match:
                    in_copy = True
                    copy_blocks += 1
                    current_table = _normalise_table_name(copy_match.group(1))
                    counts.setdefault(current_table, 0)
                    continue

                insert_match = _INSERT_RE.match(line)
                if insert_match:
                    insert_statements += 1
                    table = _normalise_table_name(insert_match.group(1))
                    counts[table] = counts.get(table, 0) + 1
                    continue
    except OSError as exc:
        raise DbBackupError(f"failed to read dump {path}: {exc}") from exc

    return _VerifyReport(
        path=path,
        size_bytes=size_bytes,
        table_row_counts=counts,
        copy_blocks=copy_blocks,
        insert_statements=insert_statements,
    )


def _normalise_table_name(raw: str) -> str:
    """
    Strip optional double-quote surroundings from a table identifier.

    pg_dump emits both ``public.users`` and ``"public"."users"`` shapes
    depending on identifier-case rules. Normalising to the unquoted
    form lets the verify report group both shapes under one key.
    """
    return raw.replace('"', "")


def _format_verify(report: _VerifyReport) -> str:
    """
    Render :class:`_VerifyReport` as a human-readable multi-line string.

    Format: header line with file + size, then one ``table=count`` line
    per table sorted alphabetically, then the totals.
    """
    lines = [
        f"db-verify: file={report.path}",
        f"db-verify: size_bytes={report.size_bytes}",
        f"db-verify: copy_blocks={report.copy_blocks}",
        f"db-verify: insert_statements={report.insert_statements}",
    ]
    total_rows = sum(report.table_row_counts.values())
    lines.append(f"db-verify: total_rows={total_rows}")
    for table in sorted(report.table_row_counts):
        lines.append(f"db-verify: table={table} rows={report.table_row_counts[table]}")
    return "\n".join(lines) + "\n"


def _run_verify(input_path: Path) -> None:
    """
    Parse ``input_path`` and print a verify report to stdout.

    Raises:
        DbBackupError: propagated from :func:`_parse_dump`.
    """
    report = _parse_dump(input_path)
    sys.stdout.write(_format_verify(report))


# ---------------------------------------------------------------------------
# Argparse + main
# ---------------------------------------------------------------------------


def _build_parser() -> argparse.ArgumentParser:
    """
    Build the argparse parser.

    Why a dedicated builder:
        Tests construct the parser directly to assert help text and
        defaults without invoking :func:`main`.
    """
    parser = argparse.ArgumentParser(
        prog="python -m services.cli.db_backup",
        description=(
            "Backup, restore, or verify a Postgres dump. Reads DATABASE_URL "
            "from the environment for backup/restore. The verify mode parses "
            "a dump locally and never touches the database."
        ),
    )
    parser.add_argument(
        "--mode",
        required=True,
        choices=("backup", "restore", "verify"),
        help="Operation to perform.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Where to write the SQL dump (required when --mode=backup).",
    )
    parser.add_argument(
        "--input",
        type=Path,
        default=None,
        dest="input_path",
        help="SQL dump to read (required when --mode=restore or --mode=verify).",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        default=False,
        help="With --mode=restore, overwrite a non-empty database.",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=None,
        help=(
            "Subprocess timeout in seconds. Defaults: "
            f"{_DEFAULT_BACKUP_TIMEOUT_S}s for backup, "
            f"{_DEFAULT_RESTORE_TIMEOUT_S}s for restore. Ignored by verify."
        ),
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    """
    CLI entry point.

    Args:
        argv: argument vector; defaults to ``sys.argv[1:]`` when None.

    Returns:
        ``0`` on success, ``1`` on any failure (with a redacted-URL
        error message on stderr).
    """
    parser = _build_parser()
    args = parser.parse_args(argv)
    try:
        _dispatch(args)
    except DbBackupError as exc:
        sys.stderr.write(f"ERROR: {exc}\n")
        return _EXIT_FAIL
    return _EXIT_OK


def _dispatch(args: argparse.Namespace) -> None:
    """
    Route to the per-mode runner based on ``args.mode``.

    Raises:
        DbBackupError: any expected failure path.
    """
    if args.mode == "backup":
        if args.output is None:
            raise DbBackupError("--output is required when --mode=backup")
        db = _parse_database_url(os.environ.get("DATABASE_URL", ""))
        timeout_s = args.timeout if args.timeout is not None else _DEFAULT_BACKUP_TIMEOUT_S
        _run_backup(db, args.output, timeout_s=timeout_s)
        return
    if args.mode == "restore":
        if args.input_path is None:
            raise DbBackupError("--input is required when --mode=restore")
        db = _parse_database_url(os.environ.get("DATABASE_URL", ""))
        timeout_s = args.timeout if args.timeout is not None else _DEFAULT_RESTORE_TIMEOUT_S
        _run_restore(db, args.input_path, force=args.force, timeout_s=timeout_s)
        return
    if args.mode == "verify":
        if args.input_path is None:
            raise DbBackupError("--input is required when --mode=verify")
        _run_verify(args.input_path)
        return
    # Argparse's `choices` already rejects unknown modes; this branch
    # is defensive.
    raise DbBackupError(f"unknown mode: {args.mode!r}")


__all__ = [
    "DbBackupError",
    "main",
]


if __name__ == "__main__":  # pragma: no cover -- module entry point
    raise SystemExit(main())
