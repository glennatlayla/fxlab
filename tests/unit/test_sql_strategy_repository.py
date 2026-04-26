"""
Tests for the SqlStrategyRepository soft-archive lifecycle.

Verifies:
- ``list_strategies`` excludes archived rows by default.
- ``list_strategies(include_archived=True)`` surfaces archived rows.
- ``list_with_total`` mirrors the same behaviour for the M2.D5 envelope.
- ``set_archived`` persists archived_at, bumps row_version, and returns
  the updated dict.
- ``set_archived`` returns None for a missing row (no exception).
- ``set_archived`` raises RowVersionConflictError on stale
  ``expected_row_version``.

The tests reuse the in-memory SQLite session built from Base.metadata
(the ``in_memory_db`` fixture in tests/unit/conftest.py) so they run
without a docker postgres dependency.

Example:
    pytest tests/unit/test_sql_strategy_repository.py -v
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import pytest
from sqlalchemy.orm import Session
from ulid import ULID

from libs.contracts.errors import RowVersionConflictError
from libs.contracts.models import Strategy
from services.api.repositories.sql_strategy_repository import SqlStrategyRepository

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _seed_user(session: Session, user_id: str) -> None:
    """
    Insert a minimal user row so ``strategies.created_by`` FK constraint
    is satisfied. The Strategy ORM declares ``created_by`` as a NOT NULL
    FK with ``ON DELETE RESTRICT`` so we cannot bypass it; the user row
    is the cheapest thing to seed.
    """
    from libs.contracts.models import User

    existing = session.query(User).filter(User.id == user_id).first()
    if existing is not None:
        return
    user = User(
        id=user_id,
        email=f"{user_id.lower()}@fxlab.test",
        hashed_password="x" * 60,
        role="operator",
    )
    session.add(user)
    session.flush()


def _make_strategy(
    session: Session,
    *,
    name: str,
    created_by: str,
    archived_at: datetime | None = None,
) -> dict[str, Any]:
    """Insert a strategy directly via the ORM, bypassing the repo create path.

    Lets the test pre-set ``archived_at`` so the list-filter assertions
    can be written without first running an archive cycle.
    """
    sid = str(ULID())
    record = Strategy(
        id=sid,
        name=name,
        code="{}",
        version="0.1.0",
        created_by=created_by,
        is_active=True,
        source="draft_form",
        archived_at=archived_at,
    )
    session.add(record)
    session.flush()
    return {
        "id": record.id,
        "name": record.name,
        "row_version": record.row_version,
        "archived_at": record.archived_at,
    }


# ---------------------------------------------------------------------------
# include_archived filter — list_strategies
# ---------------------------------------------------------------------------


class TestListStrategiesIncludeArchived:
    """Cover the include_archived gate on ``SqlStrategyRepository.list_strategies``."""

    def test_default_excludes_archived_rows(self, in_memory_db: Session) -> None:
        """Without include_archived, only active rows appear."""
        _seed_user(in_memory_db, "01HUSER000000000000000001")
        active = _make_strategy(in_memory_db, name="Active", created_by="01HUSER000000000000000001")
        _make_strategy(
            in_memory_db,
            name="Already Archived",
            created_by="01HUSER000000000000000001",
            archived_at=datetime.now(timezone.utc),
        )

        repo = SqlStrategyRepository(db=in_memory_db)
        rows = repo.list_strategies()

        ids = [r["id"] for r in rows]
        assert active["id"] in ids
        assert len(ids) == 1

    def test_include_archived_true_returns_everything(self, in_memory_db: Session) -> None:
        """include_archived=True surfaces both active and archived rows."""
        _seed_user(in_memory_db, "01HUSER000000000000000001")
        active = _make_strategy(in_memory_db, name="Active", created_by="01HUSER000000000000000001")
        archived = _make_strategy(
            in_memory_db,
            name="Already Archived",
            created_by="01HUSER000000000000000001",
            archived_at=datetime.now(timezone.utc),
        )

        repo = SqlStrategyRepository(db=in_memory_db)
        rows = repo.list_strategies(include_archived=True)

        ids = {r["id"] for r in rows}
        assert {active["id"], archived["id"]}.issubset(ids)


class TestListWithTotalIncludeArchived:
    """Cover the include_archived gate on ``list_with_total`` (M2.D5 envelope)."""

    def test_default_total_count_excludes_archived(self, in_memory_db: Session) -> None:
        """The total_count reflects the post-filter row count."""
        _seed_user(in_memory_db, "01HUSER000000000000000001")
        _make_strategy(in_memory_db, name="A", created_by="01HUSER000000000000000001")
        _make_strategy(
            in_memory_db,
            name="B",
            created_by="01HUSER000000000000000001",
            archived_at=datetime.now(timezone.utc),
        )

        repo = SqlStrategyRepository(db=in_memory_db)
        rows, total = repo.list_with_total()

        assert total == 1
        assert len(rows) == 1
        assert rows[0]["archived_at"] is None

    def test_include_archived_true_total_count_spans_everything(
        self, in_memory_db: Session
    ) -> None:
        """include_archived=True bumps total_count to include archived rows."""
        _seed_user(in_memory_db, "01HUSER000000000000000001")
        _make_strategy(in_memory_db, name="A", created_by="01HUSER000000000000000001")
        _make_strategy(
            in_memory_db,
            name="B",
            created_by="01HUSER000000000000000001",
            archived_at=datetime.now(timezone.utc),
        )

        repo = SqlStrategyRepository(db=in_memory_db)
        rows, total = repo.list_with_total(include_archived=True)

        assert total == 2
        assert len(rows) == 2
        # The archived row carries a non-None ISO-8601 timestamp.
        archived_rows = [r for r in rows if r["archived_at"] is not None]
        assert len(archived_rows) == 1


# ---------------------------------------------------------------------------
# set_archived — write path with optimistic-lock guard
# ---------------------------------------------------------------------------


class TestSetArchived:
    """Cover the SQL ``set_archived`` operation end-to-end."""

    def test_set_archived_persists_timestamp_and_bumps_row_version(
        self, in_memory_db: Session
    ) -> None:
        """Writing a non-None archived_at bumps row_version and returns the dict."""
        _seed_user(in_memory_db, "01HUSER000000000000000001")
        seed = _make_strategy(
            in_memory_db, name="To Archive", created_by="01HUSER000000000000000001"
        )

        repo = SqlStrategyRepository(db=in_memory_db)
        when = datetime.now(timezone.utc)
        updated = repo.set_archived(seed["id"], archived_at=when)

        assert updated is not None
        assert updated["archived_at"] is not None
        # The dict carries the ISO-8601 string the API surfaces, not the
        # datetime object — match the existing _strategy_to_dict format.
        assert "T" in updated["archived_at"]
        # row_version started at 1; expect 2 after a single write.
        assert updated["row_version"] == seed["row_version"] + 1

        # Re-read confirms persistence inside the session.
        re_read = in_memory_db.query(Strategy).filter(Strategy.id == seed["id"]).first()
        assert re_read is not None
        assert re_read.archived_at is not None
        assert re_read.row_version == seed["row_version"] + 1

    def test_set_archived_clears_timestamp_on_restore(self, in_memory_db: Session) -> None:
        """Writing archived_at=None clears the column and bumps row_version."""
        _seed_user(in_memory_db, "01HUSER000000000000000001")
        seed = _make_strategy(
            in_memory_db,
            name="Already Archived",
            created_by="01HUSER000000000000000001",
            archived_at=datetime.now(timezone.utc),
        )

        repo = SqlStrategyRepository(db=in_memory_db)
        updated = repo.set_archived(seed["id"], archived_at=None)

        assert updated is not None
        assert updated["archived_at"] is None
        assert updated["row_version"] == seed["row_version"] + 1

    def test_set_archived_returns_none_for_missing_row(self, in_memory_db: Session) -> None:
        """Missing strategy_id returns None — caller maps to NotFound."""
        _seed_user(in_memory_db, "01HUSER000000000000000001")
        repo = SqlStrategyRepository(db=in_memory_db)

        result = repo.set_archived(
            "01HMISSING0000000000000001", archived_at=datetime.now(timezone.utc)
        )
        assert result is None

    def test_set_archived_raises_row_version_conflict_on_stale_expected(
        self, in_memory_db: Session
    ) -> None:
        """Stale expected_row_version raises RowVersionConflictError; no write."""
        _seed_user(in_memory_db, "01HUSER000000000000000001")
        seed = _make_strategy(
            in_memory_db, name="Stale Lock", created_by="01HUSER000000000000000001"
        )

        repo = SqlStrategyRepository(db=in_memory_db)
        with pytest.raises(RowVersionConflictError) as excinfo:
            repo.set_archived(
                seed["id"],
                archived_at=datetime.now(timezone.utc),
                expected_row_version=seed["row_version"] + 99,
            )

        assert excinfo.value.entity_id == seed["id"]
        assert excinfo.value.actual_row_version == seed["row_version"]
        assert excinfo.value.expected_row_version == seed["row_version"] + 99

        # The conflict path persists nothing — re-read still has
        # archived_at None and the original row_version.
        re_read = in_memory_db.query(Strategy).filter(Strategy.id == seed["id"]).first()
        assert re_read is not None
        assert re_read.archived_at is None
        assert re_read.row_version == seed["row_version"]

    def test_set_archived_with_matching_expected_succeeds(self, in_memory_db: Session) -> None:
        """Matching expected_row_version accepts the write."""
        _seed_user(in_memory_db, "01HUSER000000000000000001")
        seed = _make_strategy(
            in_memory_db, name="Matching Lock", created_by="01HUSER000000000000000001"
        )

        repo = SqlStrategyRepository(db=in_memory_db)
        updated = repo.set_archived(
            seed["id"],
            archived_at=datetime.now(timezone.utc),
            expected_row_version=seed["row_version"],
        )

        assert updated is not None
        assert updated["archived_at"] is not None
