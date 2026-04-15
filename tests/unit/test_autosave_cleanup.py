"""
Unit tests for draft autosave cleanup functionality.

Tests verify:
- Autosaves older than 30 days are deleted.
- Autosaves within 30 days are preserved.
- The cleanup function returns the correct count of deleted records.
- Integration with the repository interface.
"""

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from libs.contracts.models import Base, DraftAutosave, User
from services.api.repositories.sql_draft_autosave_repository import (
    SqlDraftAutosaveRepository,
)


@pytest.fixture
def in_memory_db_with_user() -> Session:
    """
    In-memory SQLite database with a test user for autosave cleanup tests.

    Creates all tables, inserts a test user, yields an active session,
    then cleans up.
    """
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(bind=engine)
    session = SessionLocal()

    # Create a test user for foreign key constraint.
    test_user = User(
        id="01HQZXYZ123456789ABCDEFGHJK",
        email="testuser@example.com",
        hashed_password="hashed_password",
        role="operator",
        is_active=True,
    )
    session.add(test_user)
    session.commit()

    yield session
    session.close()
    Base.metadata.drop_all(engine)


class TestAutosaveCleanup:
    """Tests for draft autosave purge_expired method."""

    def test_purge_expired_deletes_autosaves_older_than_30_days(
        self, in_memory_db_with_user: Session
    ) -> None:
        """
        Verify that purge_expired deletes autosaves older than 30 days.

        Given autosaves created 40 days ago,
        When purge_expired(max_age_days=30) is called,
        Then those autosaves are deleted.
        """
        repo = SqlDraftAutosaveRepository(db=in_memory_db_with_user)

        # Create autosave 40 days ago (should be deleted).
        old_date = datetime.now(tz=timezone.utc) - timedelta(days=40)
        old_autosave = DraftAutosave(
            id="01HQZXYZ000000000000000001",
            user_id="01HQZXYZ123456789ABCDEFGHJK",
            draft_payload={"name": "OldDraft"},
            created_at=old_date,
            updated_at=old_date,
        )
        in_memory_db_with_user.add(old_autosave)
        in_memory_db_with_user.commit()

        # Verify it exists before cleanup.
        existing = (
            in_memory_db_with_user.query(DraftAutosave)
            .filter(DraftAutosave.id == "01HQZXYZ000000000000000001")
            .first()
        )
        assert existing is not None

        # Run cleanup.
        deleted_count = repo.purge_expired(max_age_days=30)

        # Verify it was deleted.
        assert deleted_count == 1
        cleaned = (
            in_memory_db_with_user.query(DraftAutosave)
            .filter(DraftAutosave.id == "01HQZXYZ000000000000000001")
            .first()
        )
        assert cleaned is None

    def test_purge_expired_preserves_autosaves_within_30_days(
        self, in_memory_db_with_user: Session
    ) -> None:
        """
        Verify that purge_expired preserves autosaves within 30 days.

        Given autosaves created 20 days ago,
        When purge_expired(max_age_days=30) is called,
        Then those autosaves are NOT deleted.
        """
        repo = SqlDraftAutosaveRepository(db=in_memory_db_with_user)

        # Create autosave 20 days ago (should be preserved).
        recent_date = datetime.now(tz=timezone.utc) - timedelta(days=20)
        recent_autosave = DraftAutosave(
            id="01HQZXYZ000000000000000002",
            user_id="01HQZXYZ123456789ABCDEFGHJK",
            draft_payload={"name": "RecentDraft"},
            created_at=recent_date,
            updated_at=recent_date,
        )
        in_memory_db_with_user.add(recent_autosave)
        in_memory_db_with_user.commit()

        # Run cleanup.
        deleted_count = repo.purge_expired(max_age_days=30)

        # Verify it was NOT deleted.
        assert deleted_count == 0
        preserved = (
            in_memory_db_with_user.query(DraftAutosave)
            .filter(DraftAutosave.id == "01HQZXYZ000000000000000002")
            .first()
        )
        assert preserved is not None

    def test_purge_expired_returns_correct_count(self, in_memory_db_with_user: Session) -> None:
        """
        Verify that purge_expired returns the count of deleted records.

        Given 3 autosaves (2 old, 1 recent),
        When purge_expired(max_age_days=30) is called,
        Then return value is 2.
        """
        repo = SqlDraftAutosaveRepository(db=in_memory_db_with_user)

        # Create 2 old autosaves (40 days ago).
        old_date = datetime.now(tz=timezone.utc) - timedelta(days=40)
        old_autosave_1 = DraftAutosave(
            id="01HQZXYZ000000000000000003",
            user_id="01HQZXYZ123456789ABCDEFGHJK",
            draft_payload={"name": "OldDraft1"},
            created_at=old_date,
            updated_at=old_date,
        )
        old_autosave_2 = DraftAutosave(
            id="01HQZXYZ000000000000000004",
            user_id="01HQZXYZ123456789ABCDEFGHJK",
            draft_payload={"name": "OldDraft2"},
            created_at=old_date,
            updated_at=old_date,
        )

        # Create 1 recent autosave (20 days ago).
        recent_date = datetime.now(tz=timezone.utc) - timedelta(days=20)
        recent_autosave = DraftAutosave(
            id="01HQZXYZ000000000000000005",
            user_id="01HQZXYZ123456789ABCDEFGHJK",
            draft_payload={"name": "RecentDraft"},
            created_at=recent_date,
            updated_at=recent_date,
        )

        in_memory_db_with_user.add_all([old_autosave_1, old_autosave_2, recent_autosave])
        in_memory_db_with_user.commit()

        # Run cleanup.
        deleted_count = repo.purge_expired(max_age_days=30)

        # Verify the count.
        assert deleted_count == 2

        # Verify only the recent autosave remains.
        remaining = in_memory_db_with_user.query(DraftAutosave).all()
        assert len(remaining) == 1
        assert remaining[0].id == "01HQZXYZ000000000000000005"

    def test_purge_expired_with_custom_max_age(self, in_memory_db_with_user: Session) -> None:
        """
        Verify that purge_expired respects a custom max_age_days parameter.

        Given autosaves created 60 days ago,
        When purge_expired(max_age_days=90) is called,
        Then those autosaves are preserved.
        """
        repo = SqlDraftAutosaveRepository(db=in_memory_db_with_user)

        # Create autosave 60 days ago.
        old_date = datetime.now(tz=timezone.utc) - timedelta(days=60)
        autosave = DraftAutosave(
            id="01HQZXYZ000000000000000006",
            user_id="01HQZXYZ123456789ABCDEFGHJK",
            draft_payload={"name": "SixtyDayOld"},
            created_at=old_date,
            updated_at=old_date,
        )
        in_memory_db_with_user.add(autosave)
        in_memory_db_with_user.commit()

        # Run cleanup with 90-day window.
        deleted_count = repo.purge_expired(max_age_days=90)

        # Verify it was NOT deleted (it's only 60 days old).
        assert deleted_count == 0
        preserved = (
            in_memory_db_with_user.query(DraftAutosave)
            .filter(DraftAutosave.id == "01HQZXYZ000000000000000006")
            .first()
        )
        assert preserved is not None

    def test_purge_expired_handles_empty_table(self, in_memory_db_with_user: Session) -> None:
        """
        Verify that purge_expired returns 0 when no autosaves exist.

        Given an empty draft_autosaves table,
        When purge_expired(max_age_days=30) is called,
        Then return value is 0.
        """
        repo = SqlDraftAutosaveRepository(db=in_memory_db_with_user)

        # Run cleanup on empty table.
        deleted_count = repo.purge_expired(max_age_days=30)

        # Verify the count.
        assert deleted_count == 0
