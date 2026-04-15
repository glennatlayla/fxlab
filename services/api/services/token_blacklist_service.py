"""
Token blacklist service for JWT revocation (AUTH-3).

Purpose:
    Manage revocation of JWT tokens by their JTI (JWT ID) claim.
    Provides a database-backed blacklist checked during token validation.

Responsibilities:
    - Check if a token JTI is in the revocation blacklist.
    - Add a token JTI to the blacklist (revoke).
    - Purge expired entries from the blacklist.
    - Log all revocation operations with correlation IDs.

Does NOT:
    - Create or sign tokens.
    - Enforce revocation business rules (that is the auth layer's job).
    - Handle token parsing (auth layer provides the JTI).

Dependencies:
    - SQLAlchemy Session: Injected via constructor.
    - RevokedToken ORM model: Imports from libs.contracts.models.
    - structlog: Structured logging.
    - services.api.middleware.correlation: Correlation ID context.

Error conditions:
    - Database unavailable: Raises sqlalchemy.exc.OperationalError (caught upstream).
    - Invalid JTI format: No validation; upstream guarantees UUID format.

Example:
    from sqlalchemy.orm import Session
    from services.api.db import SessionLocal
    from services.api.services.token_blacklist_service import TokenBlacklistService
    from datetime import datetime, timedelta, timezone

    db = SessionLocal()
    service = TokenBlacklistService(db)

    # Check if revoked
    if service.is_revoked("abc123..."):
        raise HTTPException(401, "Token revoked")

    # Revoke a token
    service.revoke("abc123...", datetime.now(timezone.utc) + timedelta(minutes=30))

    # Cleanup
    purged = service.purge_expired()
    db.close()
"""

from __future__ import annotations

from datetime import datetime

import structlog
from sqlalchemy import select
from sqlalchemy.orm import Session

from libs.contracts.models import RevokedToken
from services.api.middleware.correlation import correlation_id_var

logger = structlog.get_logger(__name__)


class TokenBlacklistService:
    """
    Database-backed blacklist for revoked JWT tokens.

    Attributes:
        _db: SQLAlchemy session (injected).

    Example:
        service = TokenBlacklistService(db)
        if service.is_revoked(jti):
            raise HTTPException(401, "Token has been revoked")
        service.revoke(jti, expires_at)
    """

    def __init__(self, db: Session) -> None:
        """
        Initialise the token blacklist service.

        Args:
            db: SQLAlchemy session (injected, typically from Depends(get_db)).

        Example:
            service = TokenBlacklistService(db)
        """
        self._db = db

    def _log_context(self) -> dict[str, str]:
        """Build common structured log fields including correlation ID."""
        return {
            "component": "token_blacklist",
            "correlation_id": correlation_id_var.get("no-corr"),
        }

    def is_revoked(self, jti: str) -> bool:
        """
        Check if a JTI is in the revocation blacklist.

        Performs a fast primary-key lookup to check if the JTI exists in the
        revoked_tokens table. Returns False if the JTI is not present (token
        is valid) or if database lookup fails (permissive — accept the token).

        Args:
            jti: JWT ID claim value (typically a UUID string).

        Returns:
            True if the JTI is in the blacklist (token is revoked).
            False if the JTI is not in the blacklist or on database error.

        Example:
            if service.is_revoked("550e8400-e29b-41d4-a716-446655440000"):
                raise HTTPException(401, "Token has been revoked")
        """
        try:
            record = self._db.get(RevokedToken, jti)
            is_revoked = record is not None
            if is_revoked:
                logger.debug(
                    "token_blacklist.jti_found",
                    jti=jti,
                    **self._log_context(),
                )
            return is_revoked
        except Exception as exc:
            # Fail-secure: on database error, treat the token as revoked.
            # For a fintech trading platform, accepting a potentially revoked
            # token during a DB outage is more dangerous than briefly rejecting
            # valid tokens. Operators can monitor this via the log event.
            logger.error(
                "token_blacklist.lookup_failed",
                jti=jti,
                error=str(exc),
                result="denied",
                detail="Database error during revocation check — failing secure "
                "(treating token as revoked). If this persists, check "
                "database connectivity.",
                exc_info=True,
                **self._log_context(),
            )
            return True

    def revoke(self, jti: str, expires_at: datetime, reason: str = "") -> None:
        """
        Add a JTI to the revocation blacklist.

        Creates a RevokedToken record with the given JTI and stores its
        original expiry time for cleanup (purge_expired operation).
        Does NOT commit the session — caller (auth layer) manages transactions.

        Args:
            jti: JWT ID claim value.
            expires_at: Absolute UTC expiry timestamp of the original token.
            reason: Optional free-text reason for revocation (e.g. "logout", "compromised").

        Raises:
            sqlalchemy.exc.IntegrityError: If the JTI is already in the blacklist
                (attempted duplicate revocation — caught upstream).

        Example:
            from datetime import datetime, timedelta, timezone

            expires_at = datetime.now(timezone.utc) + timedelta(minutes=30)
            service.revoke("550e8400-e29b-41d4-a716-446655440000", expires_at)
        """
        from datetime import datetime, timezone

        now = datetime.now(timezone.utc)
        revoked_token = RevokedToken(
            jti=jti,
            revoked_at=now,
            expires_at=expires_at,
            reason=reason if reason else None,
        )
        self._db.add(revoked_token)
        # NOTE: do not flush/commit here — let the transaction scope (request)
        # manage commit/rollback as an atomic unit.
        logger.info(
            "token_blacklist.jti_revoked",
            jti=jti,
            reason=reason,
            **self._log_context(),
        )

    def purge_expired(self) -> int:
        """
        Remove blacklist entries for tokens that have naturally expired.

        Deletes all RevokedToken records where expires_at <= now().
        Called periodically (e.g., on app startup or via background job)
        to keep the revoked_tokens table bounded.
        Does NOT commit the session — caller manages transactions.

        Returns:
            Count of deleted records.

        Example:
            purged = service.purge_expired()
            logger.info(f"Purged {purged} expired revocations")
        """
        from datetime import datetime, timezone

        now = datetime.now(timezone.utc)
        stmt = select(RevokedToken).where(RevokedToken.expires_at <= now)
        expired_records = self._db.execute(stmt).scalars().all()
        deleted_count = len(expired_records)

        for record in expired_records:
            self._db.delete(record)

        # Flush deletes within the current transaction so subsequent queries
        # in the same session see the purged state. Caller still owns commit.
        if deleted_count > 0:
            self._db.flush()
            logger.info(
                "token_blacklist.expired_entries_purged",
                count=deleted_count,
                **self._log_context(),
            )

        return deleted_count
