#!/usr/bin/env python3
"""
Validate the FXLab migration chain against a live database.

Purpose:
    Single entry point used by CI (GitHub Actions) and operators to prove
    that every Alembic migration upgrades, downgrades, and re-upgrades
    cleanly against the target database. This is the only layer that
    catches dialect-specific DDL errors (such as ``BOOLEAN DEFAULT 0`` on
    PostgreSQL) before deployment.

Exit codes:
    0 — validation succeeded (full round-trip completed, invariants held).
    1 — validation failed (see stderr / logs for the failing phase).
    2 — usage error (missing DATABASE_URL).

Environment variables:
    DATABASE_URL
        SQLAlchemy-compatible URL of the database to validate against.
        Must be writable and a dedicated test instance — the validator
        drops and recreates the public schema in its first step.
    CORRELATION_ID
        Optional opaque ID propagated through structured log events.
        When running from GitHub Actions, pass ``${{ github.run_id }}``.

Usage:
    DATABASE_URL="postgresql://fxlab_test:fxlab_test@localhost:5433/fxlab_test" \\
        python scripts/validate_migrations.py

Safety:
    The script refuses to run when the URL looks like a production
    database. Specifically, the URL is rejected if any of
    ``production``, ``prod``, ``live`` appears in the database name or host
    portion. Override with ``--allow-dangerous-url`` only if you know what
    you are doing.
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
from pathlib import Path
from urllib.parse import urlparse

# Make the repo root importable when the script is invoked directly
# (``python scripts/validate_migrations.py``). Module-style invocation
# (``python -m scripts.validate_migrations``) would find libs/ without
# this, but the direct form is the documented usage and CI invokes it
# that way.
_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from sqlalchemy import create_engine  # noqa: E402
from sqlalchemy.exc import SQLAlchemyError  # noqa: E402

from libs.dev.alembic_migration_runner import (  # noqa: E402
    AlembicMigrationRunner,
)
from libs.dev.migration_integrity_validator import (  # noqa: E402
    MigrationIntegrityError,
    MigrationIntegrityValidator,
)

#: Substrings that look like a production URL. Used by the safety guard.
_DANGEROUS_URL_MARKERS: tuple[str, ...] = ("production", "prod", "live")


def _build_logger(level: str) -> logging.Logger:
    """
    Configure and return a module logger.

    Args:
        level: Log level name (e.g. "INFO", "DEBUG").

    Returns:
        Configured logger that writes to stderr so stdout stays clean for
        machine parsing of the final summary line.
    """
    logger = logging.getLogger("validate_migrations")
    logger.setLevel(level)
    handler = logging.StreamHandler(stream=sys.stderr)
    handler.setFormatter(
        logging.Formatter("%(asctime)s [%(levelname)s] %(message)s %(_structured_extras)s")
    )

    class _ExtraFormatter(logging.Formatter):
        """
        Render the standard log line plus any structured ``extra`` fields.
        Keeps the output readable in CI logs while still carrying
        structured metadata.
        """

        def format(self, record: logging.LogRecord) -> str:
            base = super().format(record)
            extras = {
                k: v
                for k, v in record.__dict__.items()
                if k
                not in logging.LogRecord(
                    name="",
                    level=0,
                    pathname="",
                    lineno=0,
                    msg="",
                    args=None,
                    exc_info=None,
                ).__dict__
                and not k.startswith("_")
                and k not in {"message", "asctime"}
            }
            if extras:
                return f"{base} | {extras}"
            return base

    handler.setFormatter(_ExtraFormatter("%(asctime)s [%(levelname)s] %(message)s"))
    logger.handlers = [handler]
    logger.propagate = False
    return logger


def _is_dangerous_url(database_url: str) -> bool:
    """
    Return True if the URL looks like a production database.

    Checks the hostname and database name for well-known markers so the
    script refuses to run a destructive round-trip against production.
    """
    try:
        parsed = urlparse(database_url)
    except Exception:
        return False
    candidates = {
        (parsed.hostname or "").lower(),
        (parsed.path or "").lstrip("/").lower(),
    }
    return any(marker in candidate for candidate in candidates for marker in _DANGEROUS_URL_MARKERS)


def _reset_schema(database_url: str, logger: logging.Logger) -> None:
    """
    Drop and recreate the ``public`` schema on PostgreSQL so the round-trip
    starts from a known-empty state.

    For SQLite the call is a no-op: the validator cannot round-trip on
    SQLite anyway (see the integration test module for context).

    Args:
        database_url: SQLAlchemy URL.
        logger: Logger for structured feedback.

    Raises:
        SQLAlchemyError: If the reset fails. The caller translates this
            into a non-zero exit.
    """
    if not database_url.startswith("postgresql"):
        logger.info(
            "validate_migrations.schema_reset_skipped",
            extra={"reason": "non-postgres-url"},
        )
        return

    engine = create_engine(database_url, future=True)
    try:
        with engine.begin() as connection:
            connection.exec_driver_sql("DROP SCHEMA IF EXISTS public CASCADE")
            connection.exec_driver_sql("CREATE SCHEMA public")
    finally:
        engine.dispose()
    logger.info("validate_migrations.schema_reset_complete")


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Validate the FXLab migration chain (up → down → up) against "
            "the database referenced by DATABASE_URL."
        )
    )
    parser.add_argument(
        "--alembic-ini",
        default=str(Path(__file__).resolve().parent.parent / "alembic.ini"),
        help="Path to alembic.ini (default: repo root).",
    )
    parser.add_argument(
        "--log-level",
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        help="Log verbosity (default: INFO).",
    )
    parser.add_argument(
        "--allow-dangerous-url",
        action="store_true",
        help=(
            "Disable the production-URL safety guard. DO NOT use this "
            "against a production database — the script destroys and "
            "recreates the public schema."
        ),
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    """
    Entry point used by both CLI invocation and automated callers.

    Args:
        argv: Optional CLI arguments (defaults to ``sys.argv[1:]``).

    Returns:
        Process exit code.
    """
    args = _parse_args(argv)
    logger = _build_logger(args.log_level)

    database_url = os.environ.get("DATABASE_URL")
    correlation_id = os.environ.get("CORRELATION_ID")
    if not database_url:
        logger.error(
            "validate_migrations.missing_database_url",
            extra={"hint": "export DATABASE_URL before running this script"},
        )
        return 2

    if _is_dangerous_url(database_url) and not args.allow_dangerous_url:
        logger.error(
            "validate_migrations.refused_dangerous_url",
            extra={
                "reason": "URL matches production marker",
                "hint": "use --allow-dangerous-url to override (NOT recommended)",
            },
        )
        return 2

    try:
        _reset_schema(database_url, logger)
    except SQLAlchemyError as exc:
        logger.error(
            "validate_migrations.schema_reset_failed",
            extra={"error": str(exc)},
        )
        return 1

    runner = AlembicMigrationRunner(
        database_url=database_url,
        alembic_ini_path=args.alembic_ini,
    )
    validator = MigrationIntegrityValidator(runner=runner, logger=logger)

    try:
        result = validator.validate(correlation_id=correlation_id)
    except MigrationIntegrityError as exc:
        logger.error(
            "validate_migrations.failed",
            extra={"phase": exc.phase, "error": str(exc)},
        )
        return 1

    # Machine-parseable summary on stdout (logs go to stderr)
    print(result.summary())
    logger.info(
        "validate_migrations.succeeded",
        extra={"summary": result.summary()},
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
