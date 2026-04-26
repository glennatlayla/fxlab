"""
Unit tests for SqlDatasetRepository (M4.E3).

Scope:
    Verify the SQL-backed dataset repository against an in-memory
    SQLite database. Covers:
        - INSERT happy path + read-back
        - UPDATE in place (upsert semantics)
        - find_by_ref miss returns None
        - list_all sort order
        - list_known_refs sort order
        - driver error → DatasetRepositoryError
"""

from __future__ import annotations

from collections.abc import Iterator
from unittest.mock import patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session, sessionmaker

from libs.contracts.interfaces.dataset_repository_interface import (
    DatasetRecord,
    DatasetRepositoryError,
)
from libs.contracts.models import Base
from services.api.repositories.sql_dataset_repository import SqlDatasetRepository

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


def _make_record(
    *,
    id_: str = "01HDATASET00000000000000001",
    dataset_ref: str = "fx-eurusd-15m-certified-v3",
    symbols: list[str] | None = None,
    timeframe: str = "15m",
    source: str = "synthetic",
    version: str = "v3",
    is_certified: bool = False,
    created_by: str | None = None,
) -> DatasetRecord:
    return DatasetRecord(
        id=id_,
        dataset_ref=dataset_ref,
        symbols=list(symbols) if symbols is not None else ["EURUSD"],
        timeframe=timeframe,
        source=source,
        version=version,
        is_certified=is_certified,
        created_by=created_by,
    )


# ---------------------------------------------------------------------------
# Happy path — INSERT
# ---------------------------------------------------------------------------


def test_save_inserts_new_row(db_session: Session) -> None:
    repo = SqlDatasetRepository(db=db_session)
    saved = repo.save(_make_record())
    assert saved.id == "01HDATASET00000000000000001"
    assert saved.dataset_ref == "fx-eurusd-15m-certified-v3"
    assert saved.symbols == ["EURUSD"]
    assert saved.timeframe == "15m"
    assert saved.source == "synthetic"
    assert saved.version == "v3"
    assert saved.is_certified is False
    assert saved.created_at is not None


def test_find_by_ref_returns_saved_row(db_session: Session) -> None:
    repo = SqlDatasetRepository(db=db_session)
    repo.save(_make_record())
    found = repo.find_by_ref("fx-eurusd-15m-certified-v3")
    assert found is not None
    assert found.dataset_ref == "fx-eurusd-15m-certified-v3"
    assert found.symbols == ["EURUSD"]


def test_find_by_ref_miss_returns_none(db_session: Session) -> None:
    repo = SqlDatasetRepository(db=db_session)
    assert repo.find_by_ref("does-not-exist") is None


def test_save_persists_multiple_symbols(db_session: Session) -> None:
    repo = SqlDatasetRepository(db=db_session)
    repo.save(
        _make_record(
            id_="01HDATASET00000000000000002",
            dataset_ref="fx-majors-h1-certified-v1",
            symbols=["EURUSD", "GBPUSD", "USDJPY"],
            timeframe="1h",
            version="v1",
        )
    )
    found = repo.find_by_ref("fx-majors-h1-certified-v1")
    assert found is not None
    assert found.symbols == ["EURUSD", "GBPUSD", "USDJPY"]


# ---------------------------------------------------------------------------
# UPDATE / upsert
# ---------------------------------------------------------------------------


def test_save_updates_existing_row_in_place(db_session: Session) -> None:
    repo = SqlDatasetRepository(db=db_session)
    repo.save(_make_record(symbols=["EURUSD"], version="v3"))

    # Re-save with new metadata under same dataset_ref → UPDATE.
    repo.save(
        _make_record(
            id_="01HDATASET99999999999999999",  # ignored — natural key wins
            symbols=["EURUSD", "GBPUSD"],
            version="v4",
        )
    )

    found = repo.find_by_ref("fx-eurusd-15m-certified-v3")
    assert found is not None
    assert found.symbols == ["EURUSD", "GBPUSD"]
    assert found.version == "v4"
    # The original ID survives the update.
    assert found.id == "01HDATASET00000000000000001"


def test_save_preserves_is_certified_round_trip(db_session: Session) -> None:
    repo = SqlDatasetRepository(db=db_session)
    repo.save(_make_record(is_certified=True))
    found = repo.find_by_ref("fx-eurusd-15m-certified-v3")
    assert found is not None
    assert found.is_certified is True


# ---------------------------------------------------------------------------
# list_all + list_known_refs
# ---------------------------------------------------------------------------


def test_list_all_returns_sorted_rows(db_session: Session) -> None:
    repo = SqlDatasetRepository(db=db_session)
    repo.save(_make_record(id_="01HD0000000000000000000003", dataset_ref="z-ref"))
    repo.save(_make_record(id_="01HD0000000000000000000001", dataset_ref="a-ref"))
    repo.save(_make_record(id_="01HD0000000000000000000002", dataset_ref="m-ref"))

    rows = repo.list_all()
    assert [r.dataset_ref for r in rows] == ["a-ref", "m-ref", "z-ref"]


def test_list_all_empty_returns_empty_list(db_session: Session) -> None:
    repo = SqlDatasetRepository(db=db_session)
    assert repo.list_all() == []


def test_list_known_refs_returns_sorted(db_session: Session) -> None:
    repo = SqlDatasetRepository(db=db_session)
    repo.save(_make_record(id_="01HD0000000000000000000003", dataset_ref="z-ref"))
    repo.save(_make_record(id_="01HD0000000000000000000001", dataset_ref="a-ref"))

    assert repo.list_known_refs() == ["a-ref", "z-ref"]


def test_list_known_refs_empty(db_session: Session) -> None:
    repo = SqlDatasetRepository(db=db_session)
    assert repo.list_known_refs() == []


# ---------------------------------------------------------------------------
# Error paths
# ---------------------------------------------------------------------------


def test_find_by_ref_wraps_driver_error(db_session: Session) -> None:
    repo = SqlDatasetRepository(db=db_session)
    with patch.object(
        db_session,
        "execute",
        side_effect=OperationalError("stmt", {}, Exception("db gone")),
    ):
        with pytest.raises(DatasetRepositoryError) as excinfo:
            repo.find_by_ref("anything")
        assert isinstance(excinfo.value.__cause__, OperationalError)


def test_save_wraps_driver_error_and_rolls_back(db_session: Session) -> None:
    repo = SqlDatasetRepository(db=db_session)
    with patch.object(
        db_session,
        "flush",
        side_effect=OperationalError("stmt", {}, Exception("db gone")),
    ):
        with pytest.raises(DatasetRepositoryError) as excinfo:
            repo.save(_make_record())
        assert isinstance(excinfo.value.__cause__, OperationalError)

    # Session must still be usable after the rollback.
    saved = repo.save(_make_record(id_="01HD0000000000000000000077"))
    assert saved.dataset_ref == "fx-eurusd-15m-certified-v3"


def test_list_all_wraps_driver_error(db_session: Session) -> None:
    repo = SqlDatasetRepository(db=db_session)
    with patch.object(
        db_session,
        "execute",
        side_effect=OperationalError("stmt", {}, Exception("db gone")),
    ):
        with pytest.raises(DatasetRepositoryError):
            repo.list_all()


def test_list_known_refs_wraps_driver_error(db_session: Session) -> None:
    repo = SqlDatasetRepository(db=db_session)
    with patch.object(
        db_session,
        "execute",
        side_effect=OperationalError("stmt", {}, Exception("db gone")),
    ):
        with pytest.raises(DatasetRepositoryError):
            repo.list_known_refs()


# ---------------------------------------------------------------------------
# list_paged
# ---------------------------------------------------------------------------


def _seed_three(repo: SqlDatasetRepository) -> None:
    """Seed three rows with varied source / certification / refs."""
    repo.save(
        _make_record(
            id_="01HD0000000000000000000001",
            dataset_ref="a-eurusd",
            symbols=["EURUSD"],
            source="oanda",
            is_certified=True,
        )
    )
    repo.save(
        _make_record(
            id_="01HD0000000000000000000002",
            dataset_ref="b-gbpusd",
            symbols=["GBPUSD"],
            source="alpaca",
            is_certified=False,
        )
    )
    repo.save(
        _make_record(
            id_="01HD0000000000000000000003",
            dataset_ref="c-usdjpy",
            symbols=["USDJPY"],
            source="oanda",
            is_certified=False,
        )
    )


def test_list_paged_returns_sorted_slice_with_total(db_session: Session) -> None:
    repo = SqlDatasetRepository(db=db_session)
    _seed_three(repo)
    rows, total = repo.list_paged(limit=2, offset=0)
    assert [r.dataset_ref for r in rows] == ["a-eurusd", "b-gbpusd"]
    assert total == 3


def test_list_paged_offset_advances_correctly(db_session: Session) -> None:
    repo = SqlDatasetRepository(db=db_session)
    _seed_three(repo)
    rows, total = repo.list_paged(limit=2, offset=2)
    assert [r.dataset_ref for r in rows] == ["c-usdjpy"]
    assert total == 3


def test_list_paged_filters_by_source(db_session: Session) -> None:
    repo = SqlDatasetRepository(db=db_session)
    _seed_three(repo)
    rows, total = repo.list_paged(limit=10, offset=0, source="oanda")
    assert {r.dataset_ref for r in rows} == {"a-eurusd", "c-usdjpy"}
    assert total == 2


def test_list_paged_filters_by_is_certified(db_session: Session) -> None:
    repo = SqlDatasetRepository(db=db_session)
    _seed_three(repo)
    rows, total = repo.list_paged(limit=10, offset=0, is_certified=True)
    assert [r.dataset_ref for r in rows] == ["a-eurusd"]
    assert total == 1


def test_list_paged_filters_by_q_substring(db_session: Session) -> None:
    repo = SqlDatasetRepository(db=db_session)
    _seed_three(repo)
    rows, total = repo.list_paged(limit=10, offset=0, q="usdjpy")
    assert [r.dataset_ref for r in rows] == ["c-usdjpy"]
    assert total == 1


def test_list_paged_empty_returns_empty_with_zero_total(db_session: Session) -> None:
    repo = SqlDatasetRepository(db=db_session)
    rows, total = repo.list_paged(limit=10, offset=0)
    assert rows == []
    assert total == 0


def test_list_paged_wraps_driver_error(db_session: Session) -> None:
    repo = SqlDatasetRepository(db=db_session)
    with patch.object(
        db_session,
        "execute",
        side_effect=OperationalError("stmt", {}, Exception("db gone")),
    ):
        with pytest.raises(DatasetRepositoryError):
            repo.list_paged(limit=10, offset=0)
