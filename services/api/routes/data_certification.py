"""
Data certification route (Phase 3 — M8: Verification + Gaps + Anomalies + Certification).

Purpose:
    Expose GET /data/certification for the certification viewer UI, surfacing
    which feeds are certified, blocked (with human-readable reasons), pending,
    or expired.

Responsibilities:
    - GET /data/certification → CertificationReport (aggregate + per-feed records).
    - Compute aggregate counts (total, blocked, certified) from the repository list.
    - Translate all datetimes to ISO strings before returning.

Does NOT:
    - Run certification checks (those belong in the service/domain layer).
    - Persist certification decisions.
    - Connect to any database directly (delegates to CertificationRepositoryInterface).

Dependencies:
    - CertificationRepositoryInterface (injected via Depends).
    - libs.contracts.certification: CertificationEvent, CertificationStatus.

Error conditions:
    - No 404 path — GET /data/certification always returns a (possibly empty) report.

Example:
    GET /data/certification
    → {
        "certifications": [...],
        "total_count": 10,
        "blocked_count": 2,
        "certified_count": 7,
        "generated_at": "2026-03-27T..."
      }
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import structlog
from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse

from libs.contracts.certification import CertificationEvent, CertificationStatus
from libs.contracts.interfaces.certification_repository import (
    CertificationRepositoryInterface,
)

logger = structlog.get_logger(__name__)

router = APIRouter()


# ---------------------------------------------------------------------------
# Dependency provider
# ---------------------------------------------------------------------------


def get_certification_repository() -> CertificationRepositoryInterface:
    """
    Provide a CertificationRepositoryInterface implementation.

    Returns:
        MockCertificationRepository bootstrap stub until SQL wiring is complete.

    Note:
        ISS-019 — Wire SqlCertificationRepository via lifespan DI container.
    """
    import os

    if os.environ.get("ENVIRONMENT", "test") != "test":
        from services.api.db import get_db
        from services.api.repositories.sql_certification_repository import SqlCertificationRepository

        db = next(get_db())
        return SqlCertificationRepository(db=db)

    from libs.contracts.mocks.mock_certification_repository import (  # pragma: no cover
        MockCertificationRepository,
    )
    return MockCertificationRepository()  # pragma: no cover


# ---------------------------------------------------------------------------
# Serialization helpers (LL-008: explicit model_dump + JSONResponse)
# ---------------------------------------------------------------------------


def _serialize_certification_event(event: CertificationEvent) -> dict[str, Any]:
    """
    Serialize one CertificationEvent to a JSON-safe dict.

    Args:
        event: CertificationEvent with optional datetime fields.

    Returns:
        Dict with all datetime fields as ISO strings or None.

    Example:
        d = _serialize_certification_event(event)
        assert isinstance(d["generated_at"], str)
    """
    raw = event.model_dump()
    for field in ("certified_at", "expires_at", "generated_at"):
        val = raw.get(field)
        if val is not None and hasattr(val, "isoformat"):
            raw[field] = val.isoformat()
    # CertificationStatus is a str-enum — model_dump() already returns the string value.
    # No defensive .value guard needed (would be logically unreachable — LL-011).
    return raw


def _serialize_certification_report(
    events: list[CertificationEvent],
    generated_at: datetime,
) -> dict[str, Any]:
    """
    Build and serialize a CertificationReport from a list of events.

    Args:
        events:       List of CertificationEvent from the repository.
        generated_at: Report generation timestamp.

    Returns:
        Dict with 'certifications', 'total_count', 'blocked_count',
        'certified_count', and 'generated_at'.

    Example:
        payload = _serialize_certification_report(events, datetime.now(timezone.utc))
        assert payload["total_count"] == len(events)
    """
    blocked_count = sum(
        1 for e in events if e.status == CertificationStatus.BLOCKED
    )
    certified_count = sum(
        1 for e in events if e.status == CertificationStatus.CERTIFIED
    )
    return {
        "certifications": [_serialize_certification_event(e) for e in events],
        "total_count": len(events),
        "blocked_count": blocked_count,
        "certified_count": certified_count,
        "generated_at": (
            generated_at.isoformat()
            if hasattr(generated_at, "isoformat")
            else str(generated_at)
        ),
    }


# ---------------------------------------------------------------------------
# Route handler
# ---------------------------------------------------------------------------


@router.get("/data/certification")
def get_data_certification(
    x_correlation_id: str = "no-corr",
    repo: CertificationRepositoryInterface = Depends(get_certification_repository),
) -> JSONResponse:
    """
    Return the certification report for all feeds.

    Args:
        x_correlation_id: Request correlation ID for structured logging.
        repo:             Injected certification repository.

    Returns:
        JSONResponse containing CertificationReport shape:
        {certifications, total_count, blocked_count, certified_count, generated_at}.

    Example:
        GET /data/certification
        → {"certifications": [...], "total_count": 10, ...}
    """
    corr = x_correlation_id or "no-corr"
    logger.info("data_certification.request", correlation_id=corr)

    events = repo.list(correlation_id=corr)
    generated_at = datetime.now(timezone.utc)

    logger.info(
        "data_certification.response",
        feed_count=len(events),
        correlation_id=corr,
    )
    return JSONResponse(
        content=_serialize_certification_report(events, generated_at)
    )
