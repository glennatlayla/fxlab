"""
Seed an initial admin user on a fresh FXLab database.

Purpose:
    Create the first admin account so an operator can log in after a fresh
    install. Idempotent — skips silently when users already exist.

Responsibilities:
    - Check whether the users table is empty.
    - If empty: generate a cryptographically random password, bcrypt-hash it,
      insert an admin User row, and return the plaintext credentials.
    - If not empty: return a skip result with no side effects.
    - Provide formatted output suitable for operator capture in install logs.

Does NOT:
    - Manage user accounts beyond first-run seeding.
    - Run database migrations (that is entrypoint.sh's job).
    - Store plaintext passwords anywhere — the plaintext is printed once
      to stdout and never persisted.

Dependencies:
    - SQLAlchemy session (injected, not created here except in CLI entrypoint).
    - bcrypt for password hashing.
    - python-ulid for primary key generation.
    - libs.contracts.models.User ORM model.

Error conditions:
    - Database unreachable → logged, main() returns exit code 1.
    - Constraint violation (e.g. duplicate email) → logged, exit code 1.

Example (CLI):
    python -m services.api.cli.seed_admin
    python -m services.api.cli.seed_admin --email ops@fxlab.io

Example (programmatic):
    from services.api.cli.seed_admin import seed_admin_user
    result = seed_admin_user(db_session)
    if result.created:
        print(f"Password: {result.plaintext_password}")
"""

from __future__ import annotations

import argparse
import secrets
import sys
from dataclasses import dataclass

import bcrypt
import structlog
import ulid as _ulid_mod
from sqlalchemy.orm import Session

from libs.contracts.models import User

logger = structlog.get_logger(__name__)

# Minimum password length — 24 chars of url-safe base64 ≈ 144 bits of entropy.
_MIN_PASSWORD_LENGTH = 24


@dataclass(frozen=True)
class SeedResult:
    """
    Result of a seed_admin_user() call.

    Attributes:
        email: The admin user's email address.
        plaintext_password: The generated password (None if seed was skipped).
        created: True if a new user was inserted, False if skipped.

    Example:
        result = seed_admin_user(session)
        if result.created:
            print(result.plaintext_password)
    """

    email: str
    plaintext_password: str | None
    created: bool


def seed_admin_user(
    session: Session,
    email: str = "admin@fxlab.io",
) -> SeedResult:
    """
    Create an initial admin user if the users table is empty.

    Idempotent: if any user already exists, returns a skip result with
    ``created=False`` and ``plaintext_password=None``. This is not an
    error — it means the database was already seeded.

    Args:
        session: An active SQLAlchemy session connected to the FXLab
            database. The caller is responsible for committing or
            rolling back after this call.
        email: Email address for the admin account.
            Default: "admin@fxlab.io".

    Returns:
        SeedResult with the email, plaintext password (if created),
        and a boolean indicating whether a user was actually inserted.

    Raises:
        sqlalchemy.exc.IntegrityError: If the email already exists
            (should not happen when this function is used correctly,
            since it checks for existing users first).

    Example:
        result = seed_admin_user(db_session)
        if result.created:
            print(f"Admin password: {result.plaintext_password}")
    """
    # Check if any users exist — if so, skip silently.
    existing_count = session.query(User.id).limit(1).count()
    if existing_count > 0:
        logger.info(
            "seed_admin.skipped",
            reason="users table is not empty",
            component="seed_admin",
        )
        return SeedResult(email=email, plaintext_password=None, created=False)

    # Generate a cryptographically random password.
    # secrets.token_urlsafe produces URL-safe base64 characters.
    # With 24 bytes of randomness → 32 chars of output ≈ 192 bits entropy.
    plaintext_password = secrets.token_urlsafe(24)

    # BCrypt hash the password.
    hashed = bcrypt.hashpw(
        plaintext_password.encode("utf-8"),
        bcrypt.gensalt(),
    ).decode("utf-8")

    # Generate a ULID primary key — same pattern as all other FXLab entities.
    user_id = str(_ulid_mod.ULID())

    # Verify the plaintext password round-trips through bcrypt BEFORE
    # persisting anything. If this check fails, bcrypt or encoding is
    # broken and we must not tell the operator a password that won't work.
    if not bcrypt.checkpw(plaintext_password.encode("utf-8"), hashed.encode("utf-8")):
        raise RuntimeError(
            "CRITICAL: bcrypt verification failed — generated hash does not "
            "match the plaintext password. This indicates a bcrypt or encoding "
            "bug. No user was created."
        )

    # Generate a ULID primary key — same pattern as all other FXLab entities.
    user_id = str(_ulid_mod.ULID())

    user = User(
        id=user_id,
        email=email,
        hashed_password=hashed,
        role="admin",
        is_active=True,
    )
    session.add(user)
    session.flush()  # Flush within caller's transaction; let caller commit.

    # Post-insert verification: re-read the row from the session and verify
    # the stored hash still matches. Guards against truncation (VARCHAR(255)
    # vs actual hash length) or any ORM transformation mangling the value.
    session.refresh(user)
    stored_hash = user.hashed_password
    if not bcrypt.checkpw(plaintext_password.encode("utf-8"), stored_hash.encode("utf-8")):
        raise RuntimeError(
            "CRITICAL: post-insert verification failed — the hash stored in "
            "the database does not match the plaintext password. Possible "
            "cause: column truncation or encoding issue. Rolling back."
        )

    logger.info(
        "seed_admin.created",
        email=email,
        user_id=user_id,
        role="admin",
        component="seed_admin",
        verification="passed",
    )

    return SeedResult(email=email, plaintext_password=plaintext_password, created=True)


def format_credentials_output(result: SeedResult) -> str:
    """
    Format seed result for operator-facing output.

    Produces a human-readable block of text suitable for printing to
    the install log. Includes the email and password when a user was
    created, or a skip message when no action was taken.

    Args:
        result: The SeedResult from seed_admin_user().

    Returns:
        Formatted multi-line string.

    Example:
        output = format_credentials_output(result)
        print(output)
    """
    if not result.created:
        return (
            "[seed_admin] Skipped — users already exist in the database.\n"
            "[seed_admin] No changes were made."
        )

    # Build a prominent output block so the operator notices the credentials
    # in the install log. This is the ONLY time the plaintext password is
    # visible — it is not stored anywhere.
    lines = [
        "",
        "=" * 70,
        "  FXLAB INITIAL ADMIN CREDENTIALS",
        "=" * 70,
        f"  Email:    {result.email}",
        f"  Password: {result.plaintext_password}",
        "=" * 70,
        "  IMPORTANT: Change this password immediately after first login.",
        "  This password will NOT be displayed again.",
        "=" * 70,
        "",
    ]
    return "\n".join(lines)


def _create_session() -> Session:
    """
    Create a database session using the standard FXLab engine.

    Separated into its own function so tests can patch it to inject
    an in-memory SQLite session.

    Returns:
        A new SQLAlchemy Session connected to the configured database.
    """
    # Import here to avoid circular imports and to allow db.py's module-level
    # engine initialization to complete before we reference SessionLocal.
    from services.api.db import SessionLocal

    return SessionLocal()


def main(argv: list[str] | None = None) -> int:
    """
    CLI entrypoint for seeding the initial admin user.

    Designed to be called from entrypoint.sh after migrations complete,
    or manually by an operator via:
        docker compose exec api python -m services.api.cli.seed_admin

    Args:
        argv: Command-line arguments (defaults to sys.argv[1:]).

    Returns:
        0 on success (seed or skip), 1 on error.

    Example:
        # From entrypoint.sh:
        python -m services.api.cli.seed_admin
        python -m services.api.cli.seed_admin --email ops@fxlab.io
    """
    parser = argparse.ArgumentParser(
        description="Seed the initial FXLab admin user.",
        prog="python -m services.api.cli.seed_admin",
    )
    parser.add_argument(
        "--email",
        default="admin@fxlab.io",
        help="Email for the admin account (default: admin@fxlab.io)",
    )
    args = parser.parse_args(argv)

    session = _create_session()
    try:
        result = seed_admin_user(session, email=args.email)
        session.commit()
        print(format_credentials_output(result))
        return 0
    except Exception as exc:
        session.rollback()
        logger.error(
            "seed_admin.failed",
            error=str(exc),
            exc_info=True,
            component="seed_admin",
        )
        print(f"[seed_admin] FATAL: {exc}", file=sys.stderr)
        return 1
    finally:
        session.close()


if __name__ == "__main__":
    sys.exit(main())
