"""
Unit tests for SqlKillSwitchEventRepository.

Purpose:
    Verify the SQL kill switch event repository correctly persists,
    retrieves, deactivates, and queries kill switch events using an
    in-memory SQLite database.

Dependencies:
    - SQLAlchemy (in-memory SQLite engine).
    - libs.contracts.models: ORM models.
    - services.api.repositories.sql_kill_switch_event_repository.

Example:
    pytest tests/unit/test_sql_kill_switch_event_repository.py -v
"""

from __future__ import annotations

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from libs.contracts.errors import NotFoundError
from libs.contracts.models import Base

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def db_session() -> Session:
    """Create a fresh in-memory SQLite session for each test."""
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine)
    session = session_factory()
    try:
        yield session
    finally:
        session.close()


# ---------------------------------------------------------------------------
# Tests: Save
# ---------------------------------------------------------------------------


class TestSqlKillSwitchEventRepositorySave:
    """Verify save creates kill switch event records."""

    def test_save_creates_record(self, db_session: Session) -> None:
        """Saved event has correct scope, target, and reason."""
        from services.api.repositories.sql_kill_switch_event_repository import (
            SqlKillSwitchEventRepository,
        )

        repo = SqlKillSwitchEventRepository(db=db_session)

        event = repo.save(
            scope="global",
            target_id="global",
            activated_by="user:01HTESTNG0SR000000000000C1",
            activated_at="2026-04-11T10:00:00+00:00",
            reason="Daily loss limit breached",
        )

        assert event["scope"] == "global"
        assert event["target_id"] == "global"
        assert event["activated_by"] == "user:01HTESTNG0SR000000000000C1"
        assert event["reason"] == "Daily loss limit breached"
        assert event["deactivated_at"] is None

    def test_save_generates_ulid(self, db_session: Session) -> None:
        """Generated ID is a 26-character ULID."""
        from services.api.repositories.sql_kill_switch_event_repository import (
            SqlKillSwitchEventRepository,
        )

        repo = SqlKillSwitchEventRepository(db=db_session)

        event = repo.save(
            scope="strategy",
            target_id="01HTESTNG0STRT0000000000C1",
            activated_by="system",
            activated_at="2026-04-11T10:00:00+00:00",
            reason="Automated risk breach",
        )

        assert len(event["id"]) == 26

    def test_save_with_mtth_ms(self, db_session: Session) -> None:
        """MTTH measurement is persisted correctly."""
        from services.api.repositories.sql_kill_switch_event_repository import (
            SqlKillSwitchEventRepository,
        )

        repo = SqlKillSwitchEventRepository(db=db_session)

        event = repo.save(
            scope="symbol",
            target_id="AAPL",
            activated_by="system",
            activated_at="2026-04-11T10:00:00+00:00",
            reason="Symbol-level halt",
            mtth_ms=250,
        )

        assert event["mtth_ms"] == 250


# ---------------------------------------------------------------------------
# Tests: Get Active
# ---------------------------------------------------------------------------


class TestSqlKillSwitchEventRepositoryGetActive:
    """Verify get_active returns currently active events."""

    def test_get_active_returns_active_event(self, db_session: Session) -> None:
        """Active event (deactivated_at is NULL) is returned."""
        from services.api.repositories.sql_kill_switch_event_repository import (
            SqlKillSwitchEventRepository,
        )

        repo = SqlKillSwitchEventRepository(db=db_session)

        repo.save(
            scope="global",
            target_id="global",
            activated_by="system",
            activated_at="2026-04-11T10:00:00+00:00",
            reason="Manual halt",
        )

        active = repo.get_active(scope="global", target_id="global")
        assert active is not None
        assert active["scope"] == "global"
        assert active["deactivated_at"] is None

    def test_get_active_returns_none_when_deactivated(self, db_session: Session) -> None:
        """Deactivated event is not returned by get_active."""
        from services.api.repositories.sql_kill_switch_event_repository import (
            SqlKillSwitchEventRepository,
        )

        repo = SqlKillSwitchEventRepository(db=db_session)

        event = repo.save(
            scope="global",
            target_id="global",
            activated_by="system",
            activated_at="2026-04-11T10:00:00+00:00",
            reason="Temporary halt",
        )

        repo.deactivate(
            event_id=event["id"],
            deactivated_at="2026-04-11T10:05:00+00:00",
        )

        active = repo.get_active(scope="global", target_id="global")
        assert active is None

    def test_get_active_returns_none_for_nonexistent(self, db_session: Session) -> None:
        """No event for scope+target returns None."""
        from services.api.repositories.sql_kill_switch_event_repository import (
            SqlKillSwitchEventRepository,
        )

        repo = SqlKillSwitchEventRepository(db=db_session)

        active = repo.get_active(scope="symbol", target_id="AAPL")
        assert active is None


# ---------------------------------------------------------------------------
# Tests: List Active
# ---------------------------------------------------------------------------


class TestSqlKillSwitchEventRepositoryListActive:
    """Verify list_active returns all non-deactivated events."""

    def test_list_active_returns_only_active_events(self, db_session: Session) -> None:
        """Deactivated events are excluded from list_active."""
        from services.api.repositories.sql_kill_switch_event_repository import (
            SqlKillSwitchEventRepository,
        )

        repo = SqlKillSwitchEventRepository(db=db_session)

        event1 = repo.save(
            scope="global",
            target_id="global",
            activated_by="system",
            activated_at="2026-04-11T10:00:00+00:00",
            reason="Global halt",
        )
        repo.save(
            scope="strategy",
            target_id="01HTESTNG0STRT0000000000C1",
            activated_by="system",
            activated_at="2026-04-11T10:01:00+00:00",
            reason="Strategy halt",
        )

        # Deactivate the first event
        repo.deactivate(
            event_id=event1["id"],
            deactivated_at="2026-04-11T10:05:00+00:00",
        )

        active = repo.list_active()
        assert len(active) == 1
        assert active[0]["scope"] == "strategy"


# ---------------------------------------------------------------------------
# Tests: Deactivate
# ---------------------------------------------------------------------------


class TestSqlKillSwitchEventRepositoryDeactivate:
    """Verify deactivate sets deactivated_at and optional mtth_ms."""

    def test_deactivate_sets_deactivated_at(self, db_session: Session) -> None:
        """Deactivation timestamp is set correctly."""
        from services.api.repositories.sql_kill_switch_event_repository import (
            SqlKillSwitchEventRepository,
        )

        repo = SqlKillSwitchEventRepository(db=db_session)

        event = repo.save(
            scope="global",
            target_id="global",
            activated_by="system",
            activated_at="2026-04-11T10:00:00+00:00",
            reason="Manual halt",
        )

        deactivated = repo.deactivate(
            event_id=event["id"],
            deactivated_at="2026-04-11T10:10:00+00:00",
            mtth_ms=500,
        )

        assert deactivated["deactivated_at"] is not None
        assert deactivated["mtth_ms"] == 500

    def test_deactivate_raises_not_found_for_missing_event(self, db_session: Session) -> None:
        """Deactivating non-existent event raises NotFoundError."""
        from services.api.repositories.sql_kill_switch_event_repository import (
            SqlKillSwitchEventRepository,
        )

        repo = SqlKillSwitchEventRepository(db=db_session)

        with pytest.raises(NotFoundError):
            repo.deactivate(
                event_id="01HNONEXISTENT0000000000C1",
                deactivated_at="2026-04-11T10:00:00+00:00",
            )


# ---------------------------------------------------------------------------
# Tests: List By Scope
# ---------------------------------------------------------------------------


class TestSqlKillSwitchEventRepositoryListByScope:
    """Verify list_by_scope filters and limits correctly."""

    def test_list_by_scope_returns_matching_events(self, db_session: Session) -> None:
        """Only events with the specified scope are returned."""
        from services.api.repositories.sql_kill_switch_event_repository import (
            SqlKillSwitchEventRepository,
        )

        repo = SqlKillSwitchEventRepository(db=db_session)

        repo.save(
            scope="global",
            target_id="global",
            activated_by="system",
            activated_at="2026-04-11T10:00:00+00:00",
            reason="Global halt",
        )
        repo.save(
            scope="strategy",
            target_id="01HTESTNG0STRT0000000000C1",
            activated_by="system",
            activated_at="2026-04-11T10:01:00+00:00",
            reason="Strategy halt",
        )
        repo.save(
            scope="strategy",
            target_id="01HTESTNG0STRT0000000000C2",
            activated_by="system",
            activated_at="2026-04-11T10:02:00+00:00",
            reason="Another strategy halt",
        )

        strategy_events = repo.list_by_scope(scope="strategy")
        assert len(strategy_events) == 2
        # Most recent first
        assert strategy_events[0]["reason"] == "Another strategy halt"

    def test_list_by_scope_respects_limit(self, db_session: Session) -> None:
        """Limit parameter restricts result count."""
        from services.api.repositories.sql_kill_switch_event_repository import (
            SqlKillSwitchEventRepository,
        )

        repo = SqlKillSwitchEventRepository(db=db_session)

        for i in range(5):
            repo.save(
                scope="symbol",
                target_id=f"SYM{i}",
                activated_by="system",
                activated_at=f"2026-04-11T10:0{i}:00+00:00",
                reason=f"Symbol halt {i}",
            )

        events = repo.list_by_scope(scope="symbol", limit=3)
        assert len(events) == 3
