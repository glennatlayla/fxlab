"""
Unit tests for SqlAlertNotificationRepository.

Scope:
    Verify the SQL-backed alert-notification repository against an
    in-memory SQLite database. Covers:
        - happy-path batch insert
        - empty batch no-op
        - duplicate fingerprints (append-only behaviour is deliberate)
        - count_by_fingerprint accuracy
        - driver error → AlertNotificationRepositoryError
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import datetime, timezone
from unittest.mock import patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session, sessionmaker

from libs.contracts.alertmanager_webhook import AlertNotification
from libs.contracts.interfaces.alert_notification_repository import (
    AlertNotificationRepositoryError,
)
from libs.contracts.models import Base
from services.api.repositories.sql_alert_notification_repository import (
    SqlAlertNotificationRepository,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def db_session() -> Iterator[Session]:
    """Provide a clean in-memory SQLite session per test."""
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    TestSession = sessionmaker(bind=engine)
    session = TestSession()
    try:
        yield session
    finally:
        session.rollback()
        session.close()
        engine.dispose()


def _make_notification(
    *,
    id_: str = "01HNOT00000000000000000001",
    fingerprint: str = "fp-0001",
    status: str = "firing",
) -> AlertNotification:
    return AlertNotification(
        id=id_,
        fingerprint=fingerprint,
        status=status,
        alertname="APIHighLatency",
        severity="warning",
        starts_at=datetime(2026, 4, 15, 12, 0, tzinfo=timezone.utc),
        ends_at=None,
        labels={"alertname": "APIHighLatency", "severity": "warning"},
        annotations={"summary": "p99 > 1s"},
        generator_url="http://prom:9090/graph",
        receiver="default_webhook",
        external_url="http://alertmanager:9093",
        group_key='{}:{alertname="APIHighLatency"}',
        received_at=datetime(2026, 4, 15, 12, 0, 30, tzinfo=timezone.utc),
    )


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------


def test_save_batch_persists_all_rows(db_session: Session) -> None:
    repo = SqlAlertNotificationRepository(db=db_session)
    batch = [_make_notification(id_=f"01HNOT{i:020d}", fingerprint=f"fp-{i:04d}") for i in range(3)]

    persisted = repo.save_batch(batch)

    assert persisted == 3
    assert repo.count_by_fingerprint("fp-0000") == 1
    assert repo.count_by_fingerprint("fp-0001") == 1
    assert repo.count_by_fingerprint("fp-0002") == 1


def test_save_batch_accepts_empty_list(db_session: Session) -> None:
    repo = SqlAlertNotificationRepository(db=db_session)
    assert repo.save_batch([]) == 0


def test_save_batch_is_append_only_for_duplicate_fingerprints(
    db_session: Session,
) -> None:
    """Alertmanager's repeat_interval produces duplicates — they are
    preserved, not deduped."""
    repo = SqlAlertNotificationRepository(db=db_session)
    repo.save_batch([_make_notification(id_="01HNOT00000000000000000001", fingerprint="same")])
    repo.save_batch([_make_notification(id_="01HNOT00000000000000000002", fingerprint="same")])

    assert repo.count_by_fingerprint("same") == 2


def test_count_by_fingerprint_returns_zero_for_unknown(
    db_session: Session,
) -> None:
    repo = SqlAlertNotificationRepository(db=db_session)
    assert repo.count_by_fingerprint("never-seen") == 0


# ---------------------------------------------------------------------------
# Error path
# ---------------------------------------------------------------------------


def test_save_batch_wraps_driver_error_as_repo_error(
    db_session: Session,
) -> None:
    repo = SqlAlertNotificationRepository(db=db_session)

    with patch.object(
        db_session,
        "flush",
        side_effect=OperationalError("stmt", {}, Exception("db gone")),
    ):
        with pytest.raises(AlertNotificationRepositoryError) as excinfo:
            repo.save_batch([_make_notification()])
        assert isinstance(excinfo.value.__cause__, OperationalError)


def test_count_wraps_driver_error_as_repo_error(db_session: Session) -> None:
    repo = SqlAlertNotificationRepository(db=db_session)

    with patch.object(
        db_session,
        "query",
        side_effect=OperationalError("stmt", {}, Exception("db gone")),
    ):
        with pytest.raises(AlertNotificationRepositoryError) as excinfo:
            repo.count_by_fingerprint("anything")
        assert isinstance(excinfo.value.__cause__, OperationalError)


def test_save_batch_rolls_back_on_failure(db_session: Session) -> None:
    """After a failed flush the session must be rolled back so the caller
    can retry or move on without seeing partial state."""
    repo = SqlAlertNotificationRepository(db=db_session)

    with patch.object(
        db_session,
        "flush",
        side_effect=OperationalError("stmt", {}, Exception("db gone")),
    ):
        with pytest.raises(AlertNotificationRepositoryError):
            repo.save_batch([_make_notification()])

    # The session should be clean — the next save_batch must succeed.
    assert repo.save_batch([_make_notification(id_="01HNOT00000000000000000099")]) == 1
