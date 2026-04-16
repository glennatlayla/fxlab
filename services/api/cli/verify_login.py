"""
End-to-end login verification for FXLab CLI tools.

Purpose:
    Verify that credentials actually work by exercising the same code
    path the frontend uses: query the user, verify the bcrypt hash,
    and generate a JWT token. This catches issues that a simple
    bcrypt.checkpw cannot — like user lookup failures, inactive flags,
    token generation errors, or ORM session state issues.

Responsibilities:
    - Look up a user by email in the database.
    - Verify the plaintext password against the stored bcrypt hash.
    - Generate a JWT access token (same as /auth/token password grant).
    - Return a pass/fail result with diagnostic information.

Does NOT:
    - Modify any data (read-only verification).
    - Make HTTP requests (tests the auth code directly, not via network).
    - Store or persist tokens (the token is generated and discarded).

Dependencies:
    - SQLAlchemy session for user lookup.
    - bcrypt for password verification.
    - services.api.auth for JWT token creation.
    - libs.contracts.models.User ORM model.

Error conditions:
    - User not found → VerifyResult with passed=False.
    - Password mismatch → VerifyResult with passed=False.
    - Token generation failure → VerifyResult with passed=False.

Example:
    from services.api.cli.verify_login import verify_login
    result = verify_login(session, "admin@fxlab.io", "the-password")
    if result.passed:
        print("Login will work")
"""

from __future__ import annotations

from dataclasses import dataclass

import bcrypt
import structlog
from sqlalchemy.orm import Session

from libs.contracts.models import User

logger = structlog.get_logger(__name__)


@dataclass(frozen=True)
class VerifyResult:
    """
    Result of an end-to-end login verification.

    Attributes:
        passed: True if the full login flow succeeded.
        email: The email address tested.
        stage: The stage that failed (None if passed).
            One of: "user_lookup", "user_active", "bcrypt_verify",
            "token_generation".
        detail: Human-readable diagnostic message.

    Example:
        result = verify_login(session, "admin@fxlab.io", "pass")
        if not result.passed:
            print(f"Failed at: {result.stage} — {result.detail}")
    """

    passed: bool
    email: str
    stage: str | None = None
    detail: str = ""


def verify_login(
    session: Session,
    email: str,
    plaintext_password: str,
) -> VerifyResult:
    """
    Verify that credentials will work through the full auth flow.

    Exercises the same code path as the /auth/token password grant:
    user lookup → active check → bcrypt verify → JWT generation.
    Does NOT persist anything or create refresh tokens.

    Args:
        session: Active SQLAlchemy session.
        email: User's email address.
        plaintext_password: Password to verify.

    Returns:
        VerifyResult indicating pass/fail with diagnostics.

    Example:
        result = verify_login(session, "admin@fxlab.io", "s3cret")
        assert result.passed
    """
    # Stage 1: User lookup
    user = session.query(User).filter(User.email == email).first()
    if user is None:
        return VerifyResult(
            passed=False,
            email=email,
            stage="user_lookup",
            detail=f"No user found with email '{email}' in the database.",
        )

    # Stage 2: Active check
    if not user.is_active:
        return VerifyResult(
            passed=False,
            email=email,
            stage="user_active",
            detail=f"User '{email}' exists but is_active=False.",
        )

    # Stage 3: BCrypt verification (same as _verify_password in auth.py)
    password_ok = bcrypt.checkpw(
        plaintext_password.encode("utf-8"),
        user.hashed_password.encode("utf-8"),
    )
    if not password_ok:
        return VerifyResult(
            passed=False,
            email=email,
            stage="bcrypt_verify",
            detail=(
                f"bcrypt.checkpw failed. Hash length={len(user.hashed_password)}, "
                f"hash prefix={user.hashed_password[:7]}..., "
                f"password length={len(plaintext_password)}."
            ),
        )

    # Stage 4: JWT token generation (same as password grant handler)
    try:
        from services.api.auth import ROLE_SCOPES, create_access_token

        scopes = ROLE_SCOPES.get(user.role, [])
        token = create_access_token(
            user_id=user.id,
            role=user.role,
            email=user.email,
            expires_minutes=30,
            scopes=scopes,
        )
        if not token or len(token) < 10:
            return VerifyResult(
                passed=False,
                email=email,
                stage="token_generation",
                detail="create_access_token returned an empty or suspiciously short token.",
            )
    except Exception as exc:
        return VerifyResult(
            passed=False,
            email=email,
            stage="token_generation",
            detail=f"JWT token generation raised: {exc}",
        )

    logger.info(
        "verify_login.passed",
        email=email,
        user_id=user.id,
        role=user.role,
        token_length=len(token),
        component="verify_login",
    )

    return VerifyResult(
        passed=True,
        email=email,
        detail=f"Login verified: user lookup OK, bcrypt OK, JWT generated ({len(token)} chars).",
    )
