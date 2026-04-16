"""
Reset a user's password in the FXLab database.

Purpose:
    Operator tool for resetting a user's password when the original
    credentials are lost. Generates a new cryptographically random
    password, verifies it round-trips through bcrypt, then persists
    the new hash and prints the plaintext once to stdout.

Responsibilities:
    - Look up user by email address.
    - Generate a cryptographically random replacement password.
    - BCrypt-hash the new password.
    - Verify the hash matches the plaintext BEFORE persisting (pre-write check).
    - Update the user row in the database.
    - Verify the stored hash matches the plaintext AFTER persisting (post-write check).
    - Print the new credentials to stdout exactly once.

Does NOT:
    - Create new users (use seed_admin for that).
    - Store plaintext passwords anywhere — printed once, never persisted.
    - Send email notifications (operator responsibility).

Dependencies:
    - SQLAlchemy session (injected, or created via _create_session for CLI use).
    - bcrypt for password hashing and verification.
    - libs.contracts.models.User ORM model.

Error conditions:
    - User not found → logged, exit code 1.
    - BCrypt pre-write verification fails → RuntimeError, no DB change.
    - Post-write verification fails → RuntimeError, transaction rolled back.
    - Database unreachable → logged, exit code 1.

Example (CLI — from inside the API container):
    python -m services.api.cli.reset_password --email admin@fxlab.io

Example (Docker):
    docker compose -f docker-compose.prod.yml exec api python -m services.api.cli.reset_password --email admin@fxlab.io

Example (programmatic):
    from services.api.cli.reset_password import reset_user_password
    result = reset_user_password(db_session, "admin@fxlab.io")
    if result.reset:
        print(f"New password: {result.plaintext_password}")
"""

from __future__ import annotations

import argparse
import secrets
import sys
from dataclasses import dataclass

import bcrypt
import structlog
from sqlalchemy.orm import Session

from libs.contracts.models import User

logger = structlog.get_logger(__name__)


@dataclass(frozen=True)
class ResetResult:
    """
    Result of a reset_user_password() call.

    Attributes:
        email: The user's email address.
        plaintext_password: The new password (None if reset failed).
        reset: True if the password was changed, False otherwise.
        error: Error message if reset is False, None otherwise.

    Example:
        result = reset_user_password(session, "admin@fxlab.io")
        if result.reset:
            print(result.plaintext_password)
    """

    email: str
    plaintext_password: str | None
    reset: bool
    error: str | None = None


def reset_user_password(
    session: Session,
    email: str,
) -> ResetResult:
    """
    Reset a user's password and verify the new credentials work.

    Performs two verification steps:
    1. Pre-write: verifies the bcrypt hash matches the plaintext before
       touching the database.
    2. Post-write: re-reads the stored hash from the database and verifies
       it still matches. Catches column truncation, encoding bugs, or ORM
       transformations that could silently corrupt the hash.

    If either verification fails, the transaction is NOT committed and
    a RuntimeError is raised.

    Args:
        session: An active SQLAlchemy session. Caller is responsible for
            commit/rollback after this call.
        email: Email address of the user whose password to reset.

    Returns:
        ResetResult with the email, new plaintext password, and status.

    Raises:
        RuntimeError: If bcrypt verification fails at either stage.

    Example:
        result = reset_user_password(session, "admin@fxlab.io")
        # result.reset == True
        # result.plaintext_password == "new-random-password"
    """
    user = session.query(User).filter(User.email == email).first()
    if user is None:
        logger.warning(
            "reset_password.user_not_found",
            email=email,
            component="reset_password",
        )
        return ResetResult(
            email=email,
            plaintext_password=None,
            reset=False,
            error=f"No user found with email: {email}",
        )

    if not user.is_active:
        logger.warning(
            "reset_password.user_inactive",
            email=email,
            user_id=user.id,
            component="reset_password",
        )
        return ResetResult(
            email=email,
            plaintext_password=None,
            reset=False,
            error=f"User {email} is deactivated. Activate the account first.",
        )

    # Generate a cryptographically random password.
    plaintext_password = secrets.token_urlsafe(24)

    # BCrypt hash the new password.
    hashed = bcrypt.hashpw(
        plaintext_password.encode("utf-8"),
        bcrypt.gensalt(),
    ).decode("utf-8")

    # PRE-WRITE VERIFICATION: confirm the hash matches the plaintext
    # before we touch the database. If bcrypt is broken or encoding is
    # wrong, we catch it here with zero side effects.
    if not bcrypt.checkpw(plaintext_password.encode("utf-8"), hashed.encode("utf-8")):
        raise RuntimeError(
            "CRITICAL: bcrypt pre-write verification failed — generated hash "
            "does not match the plaintext password. No database change was made."
        )

    # Update the password in the database.
    user.hashed_password = hashed
    session.flush()

    # POST-WRITE VERIFICATION: re-read the hash from the database and
    # verify it still matches. Guards against column truncation (e.g.
    # VARCHAR too short), encoding transformations by the ORM, or any
    # other persistence-layer issue that could silently corrupt the hash.
    session.refresh(user)
    stored_hash = user.hashed_password
    if not bcrypt.checkpw(plaintext_password.encode("utf-8"), stored_hash.encode("utf-8")):
        raise RuntimeError(
            "CRITICAL: post-write verification failed — the hash stored in "
            "the database does not match the plaintext password. Possible "
            "cause: column truncation or encoding issue. Rolling back."
        )

    # End-to-end verification: exercise the full login flow (user lookup →
    # active check → bcrypt verify → JWT generation) to guarantee the
    # credentials we're about to print will actually work at /auth/token.
    from services.api.cli.verify_login import verify_login

    login_check = verify_login(session, email, plaintext_password)
    if not login_check.passed:
        raise RuntimeError(
            f"CRITICAL: end-to-end login verification failed at stage "
            f"'{login_check.stage}': {login_check.detail}. "
            f"The password was updated but login would fail. Rolling back."
        )

    logger.info(
        "reset_password.success",
        email=email,
        user_id=user.id,
        component="reset_password",
        verification="e2e_passed",
    )

    return ResetResult(
        email=email,
        plaintext_password=plaintext_password,
        reset=True,
    )


def format_reset_output(result: ResetResult) -> str:
    """
    Format reset result for operator-facing output.

    Args:
        result: The ResetResult from reset_user_password().

    Returns:
        Formatted multi-line string suitable for terminal output.

    Example:
        print(format_reset_output(result))
    """
    if not result.reset:
        return f"[reset_password] FAILED: {result.error}"

    lines = [
        "",
        "=" * 70,
        "  FXLAB PASSWORD RESET — VERIFIED",
        "=" * 70,
        f"  Email:        {result.email}",
        f"  New Password: {result.plaintext_password}",
        "=" * 70,
        "  This password has been verified against the database.",
        "  Change it after first login. It will NOT be displayed again.",
        "=" * 70,
        "",
    ]
    return "\n".join(lines)


def _create_session() -> Session:
    """
    Create a database session using the standard FXLab engine.

    Separated for testability — tests patch this to inject in-memory SQLite.

    Returns:
        A new SQLAlchemy Session connected to the configured database.
    """
    from services.api.db import SessionLocal

    return SessionLocal()


def main(argv: list[str] | None = None) -> int:
    """
    CLI entrypoint for resetting a user's password.

    Args:
        argv: Command-line arguments (defaults to sys.argv[1:]).

    Returns:
        0 on success, 1 on error.

    Example:
        python -m services.api.cli.reset_password --email admin@fxlab.io
    """
    parser = argparse.ArgumentParser(
        description="Reset a FXLab user's password.",
        prog="python -m services.api.cli.reset_password",
    )
    parser.add_argument(
        "--email",
        required=True,
        help="Email of the user whose password to reset",
    )
    args = parser.parse_args(argv)

    session = _create_session()
    try:
        result = reset_user_password(session, email=args.email)
        if result.reset:
            session.commit()
            print(format_reset_output(result))
            return 0
        else:
            session.rollback()
            print(format_reset_output(result), file=sys.stderr)
            return 1
    except Exception as exc:
        session.rollback()
        logger.error(
            "reset_password.failed",
            error=str(exc),
            exc_info=True,
            component="reset_password",
        )
        print(f"[reset_password] FATAL: {exc}", file=sys.stderr)
        return 1
    finally:
        session.close()


if __name__ == "__main__":
    sys.exit(main())
