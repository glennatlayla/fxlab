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
from datetime import datetime, timedelta
from unittest.mock import patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session, sessionmaker

from libs.contracts.interfaces.dataset_repository_interface import (
    DatasetRecord,
    DatasetRepositoryError,
)
from libs.contracts.models import (
    Base,
    CandleRecord,
    ResearchRun,
    Strategy,
    User,
)
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


# ---------------------------------------------------------------------------
# count
# ---------------------------------------------------------------------------


def test_count_empty_returns_zero(db_session: Session) -> None:
    repo = SqlDatasetRepository(db=db_session)
    assert repo.count() == 0


def test_count_returns_number_of_rows(db_session: Session) -> None:
    repo = SqlDatasetRepository(db=db_session)
    _seed_three(repo)
    assert repo.count() == 3


def test_count_after_save_increases_by_one(db_session: Session) -> None:
    repo = SqlDatasetRepository(db=db_session)
    assert repo.count() == 0
    repo.save(_make_record())
    assert repo.count() == 1
    repo.save(
        _make_record(
            id_="01HD0000000000000000000099",
            dataset_ref="another-ref",
        )
    )
    assert repo.count() == 2


def test_count_wraps_driver_error(db_session: Session) -> None:
    repo = SqlDatasetRepository(db=db_session)
    with patch.object(
        db_session,
        "execute",
        side_effect=OperationalError("stmt", {}, Exception("db gone")),
    ):
        with pytest.raises(DatasetRepositoryError):
            repo.count()


# ---------------------------------------------------------------------------
# Detail-page helpers (M4.E3 follow-up)
# ---------------------------------------------------------------------------


def _seed_user(db: Session, *, user_id: str = "01HUSER000000000000000001") -> str:
    """Insert a user row so Strategy.created_by FK can be satisfied."""
    user = User(
        id=user_id,
        email=f"{user_id}@fxlab.test",
        hashed_password="x",
        role="admin",
        is_active=True,
    )
    db.add(user)
    db.flush()
    return user_id


def _seed_strategy(
    db: Session,
    *,
    strategy_id: str,
    name: str,
    created_by: str,
) -> str:
    """Insert a strategy row tied to a pre-existing user."""
    strategy = Strategy(
        id=strategy_id,
        name=name,
        code="def signals(): pass",
        version="v1",
        created_by=created_by,
        is_active=True,
        source="draft_form",
    )
    db.add(strategy)
    db.flush()
    return strategy_id


def _seed_run(
    db: Session,
    *,
    run_id: str,
    strategy_id: str,
    dataset_ref: str | None,
    status: str = "completed",
    completed_at: datetime | None = None,
    created_by: str = "01HUSER000000000000000001",
    created_at: datetime | None = None,
) -> str:
    """Insert a research_runs row with a config_json carrying the ref."""
    config: dict = {
        "run_type": "backtest",
        "strategy_id": strategy_id,
    }
    if dataset_ref is not None:
        config["data_selection"] = {"dataset_ref": dataset_ref}

    run = ResearchRun(
        id=run_id,
        run_type="backtest",
        strategy_id=strategy_id,
        status=status,
        config_json=config,
        result_json=None,
        created_by=created_by,
        created_at=created_at or datetime(2026, 4, 1, 12, 0, 0),
        updated_at=created_at or datetime(2026, 4, 1, 12, 0, 0),
        started_at=None,
        completed_at=completed_at,
    )
    db.add(run)
    db.flush()
    return run_id


# ---------------------------------------------------------------------------
# get_bar_inventory
# ---------------------------------------------------------------------------


def test_get_bar_inventory_empty_symbols_returns_empty(db_session: Session) -> None:
    repo = SqlDatasetRepository(db=db_session)
    assert repo.get_bar_inventory(symbols=[], timeframe="15m") == []


def test_get_bar_inventory_returns_zero_row_for_symbol_without_bars(
    db_session: Session,
) -> None:
    repo = SqlDatasetRepository(db=db_session)
    rows = repo.get_bar_inventory(symbols=["EURUSD"], timeframe="15m")
    assert len(rows) == 1
    assert rows[0].symbol == "EURUSD"
    assert rows[0].timeframe == "15m"
    assert rows[0].row_count == 0
    assert rows[0].min_ts is None
    assert rows[0].max_ts is None


def test_get_bar_inventory_aggregates_count_min_max(db_session: Session) -> None:
    repo = SqlDatasetRepository(db=db_session)
    base = datetime(2026, 4, 1, 0, 0, 0)
    for n in range(5):
        bar = CandleRecord(
            symbol="EURUSD",
            interval="15m",
            timestamp=base + timedelta(minutes=15 * n),
            open="1.0",
            high="1.0",
            low="1.0",
            close="1.0",
            volume=1,
        )
        db_session.add(bar)
    db_session.flush()

    rows = repo.get_bar_inventory(symbols=["EURUSD"], timeframe="15m")
    assert len(rows) == 1
    assert rows[0].row_count == 5
    assert rows[0].min_ts == base
    assert rows[0].max_ts == base + timedelta(minutes=60)


def test_get_bar_inventory_filters_by_timeframe(db_session: Session) -> None:
    repo = SqlDatasetRepository(db=db_session)
    base = datetime(2026, 4, 1, 0, 0, 0)
    db_session.add(
        CandleRecord(
            symbol="EURUSD",
            interval="15m",
            timestamp=base,
            open="1.0",
            high="1.0",
            low="1.0",
            close="1.0",
            volume=1,
        )
    )
    db_session.add(
        CandleRecord(
            symbol="EURUSD",
            interval="1h",
            timestamp=base,
            open="1.0",
            high="1.0",
            low="1.0",
            close="1.0",
            volume=1,
        )
    )
    db_session.flush()

    rows = repo.get_bar_inventory(symbols=["EURUSD"], timeframe="15m")
    assert rows[0].row_count == 1


def test_get_bar_inventory_returns_one_row_per_input_symbol(db_session: Session) -> None:
    repo = SqlDatasetRepository(db=db_session)
    base = datetime(2026, 4, 1, 0, 0, 0)
    db_session.add(
        CandleRecord(
            symbol="EURUSD",
            interval="15m",
            timestamp=base,
            open="1.0",
            high="1.0",
            low="1.0",
            close="1.0",
            volume=1,
        )
    )
    db_session.flush()

    rows = repo.get_bar_inventory(symbols=["EURUSD", "GBPUSD"], timeframe="15m")
    assert {r.symbol for r in rows} == {"EURUSD", "GBPUSD"}
    eur = next(r for r in rows if r.symbol == "EURUSD")
    gbp = next(r for r in rows if r.symbol == "GBPUSD")
    assert eur.row_count == 1
    assert gbp.row_count == 0
    assert gbp.min_ts is None


def test_get_bar_inventory_wraps_driver_error(db_session: Session) -> None:
    repo = SqlDatasetRepository(db=db_session)
    with patch.object(
        db_session,
        "execute",
        side_effect=OperationalError("stmt", {}, Exception("db gone")),
    ):
        with pytest.raises(DatasetRepositoryError):
            repo.get_bar_inventory(symbols=["EURUSD"], timeframe="15m")


# ---------------------------------------------------------------------------
# get_strategies_using
# ---------------------------------------------------------------------------


def test_get_strategies_using_empty_ref_returns_empty(db_session: Session) -> None:
    repo = SqlDatasetRepository(db=db_session)
    assert repo.get_strategies_using("") == []


def test_get_strategies_using_zero_limit_returns_empty(db_session: Session) -> None:
    repo = SqlDatasetRepository(db=db_session)
    assert repo.get_strategies_using("any-ref", limit=0) == []


def test_get_strategies_using_no_runs_returns_empty(db_session: Session) -> None:
    repo = SqlDatasetRepository(db=db_session)
    assert repo.get_strategies_using("never-referenced") == []


def test_get_strategies_using_returns_distinct_with_name(db_session: Session) -> None:
    repo = SqlDatasetRepository(db=db_session)
    user_id = _seed_user(db_session)
    strat_a = _seed_strategy(
        db_session,
        strategy_id="01HSTRAT00000000000000000A",
        name="Strategy A",
        created_by=user_id,
    )
    strat_b = _seed_strategy(
        db_session,
        strategy_id="01HSTRAT00000000000000000B",
        name="Strategy B",
        created_by=user_id,
    )
    _seed_run(
        db_session,
        run_id="01HRUN00000000000000000001",
        strategy_id=strat_a,
        dataset_ref="match-ref",
        completed_at=datetime(2026, 4, 24, 12, 0, 0),
    )
    _seed_run(
        db_session,
        run_id="01HRUN00000000000000000002",
        strategy_id=strat_a,
        dataset_ref="match-ref",
        completed_at=datetime(2026, 4, 25, 12, 0, 0),
    )
    _seed_run(
        db_session,
        run_id="01HRUN00000000000000000003",
        strategy_id=strat_b,
        dataset_ref="match-ref",
        completed_at=datetime(2026, 4, 24, 12, 0, 0),
    )

    rows = repo.get_strategies_using("match-ref")
    assert [r.strategy_id for r in rows] == [strat_a, strat_b]
    assert rows[0].name == "Strategy A"
    assert rows[0].last_used_at == datetime(2026, 4, 25, 12, 0, 0)
    assert rows[1].name == "Strategy B"


def test_get_strategies_using_filters_by_dataset_ref(db_session: Session) -> None:
    repo = SqlDatasetRepository(db=db_session)
    user_id = _seed_user(db_session)
    strat_a = _seed_strategy(
        db_session,
        strategy_id="01HSTRAT00000000000000000A",
        name="Strategy A",
        created_by=user_id,
    )
    _seed_run(
        db_session,
        run_id="01HRUN00000000000000000001",
        strategy_id=strat_a,
        dataset_ref="match-ref",
        completed_at=datetime(2026, 4, 25, 12, 0, 0),
    )
    _seed_run(
        db_session,
        run_id="01HRUN00000000000000000002",
        strategy_id=strat_a,
        dataset_ref="other-ref",
        completed_at=datetime(2026, 4, 25, 12, 0, 0),
    )
    rows = repo.get_strategies_using("match-ref")
    assert len(rows) == 1
    assert rows[0].strategy_id == strat_a


def test_get_strategies_using_caps_at_limit(db_session: Session) -> None:
    repo = SqlDatasetRepository(db=db_session)
    user_id = _seed_user(db_session)
    base_ts = datetime(2026, 4, 1, 0, 0, 0)
    for n in range(15):
        sid = f"01HSTRAT00000000000000{n:04d}"[:26]
        _seed_strategy(
            db_session,
            strategy_id=sid,
            name=f"Strategy {n}",
            created_by=user_id,
        )
        _seed_run(
            db_session,
            run_id=f"01HRUN0000000000000000{n:04d}"[:26],
            strategy_id=sid,
            dataset_ref="match-ref",
            completed_at=base_ts + timedelta(hours=n),
        )

    rows = repo.get_strategies_using("match-ref", limit=10)
    assert len(rows) == 10


# ---------------------------------------------------------------------------
# get_recent_runs
# ---------------------------------------------------------------------------


def test_get_recent_runs_empty_ref_returns_empty(db_session: Session) -> None:
    repo = SqlDatasetRepository(db=db_session)
    assert repo.get_recent_runs("") == []


def test_get_recent_runs_zero_limit_returns_empty(db_session: Session) -> None:
    repo = SqlDatasetRepository(db=db_session)
    assert repo.get_recent_runs("any-ref", limit=0) == []


def test_get_recent_runs_returns_filtered_and_ordered(db_session: Session) -> None:
    repo = SqlDatasetRepository(db=db_session)
    user_id = _seed_user(db_session)
    strat_a = _seed_strategy(
        db_session,
        strategy_id="01HSTRAT00000000000000000A",
        name="A",
        created_by=user_id,
    )

    _seed_run(
        db_session,
        run_id="01HRUN000000000000000OLDER",
        strategy_id=strat_a,
        dataset_ref="match-ref",
        completed_at=datetime(2026, 4, 20, 12, 0, 0),
    )
    _seed_run(
        db_session,
        run_id="01HRUN000000000000000NEWER",
        strategy_id=strat_a,
        dataset_ref="match-ref",
        completed_at=datetime(2026, 4, 25, 12, 0, 0),
    )
    _seed_run(
        db_session,
        run_id="01HRUN000000000000000RUNNG",
        strategy_id=strat_a,
        dataset_ref="match-ref",
        status="running",
        completed_at=None,
    )
    # An "other-ref" run that must be filtered out.
    _seed_run(
        db_session,
        run_id="01HRUN000000000000000OTHER",
        strategy_id=strat_a,
        dataset_ref="other-ref",
        completed_at=datetime(2026, 4, 26, 12, 0, 0),
    )

    rows = repo.get_recent_runs("match-ref")
    ids = [r.run_id for r in rows]
    # Still-running (NULL completed_at) surfaces first; then most-recent
    # completed; "other-ref" run is excluded.
    assert ids == [
        "01HRUN000000000000000RUNNG",
        "01HRUN000000000000000NEWER",
        "01HRUN000000000000000OLDER",
    ]
    assert rows[0].status == "running"
    assert rows[0].completed_at is None


def test_get_recent_runs_caps_at_limit(db_session: Session) -> None:
    repo = SqlDatasetRepository(db=db_session)
    user_id = _seed_user(db_session)
    strat_a = _seed_strategy(
        db_session,
        strategy_id="01HSTRAT00000000000000000A",
        name="A",
        created_by=user_id,
    )
    base = datetime(2026, 4, 1, 0, 0, 0)
    for n in range(15):
        _seed_run(
            db_session,
            run_id=f"01HRUN0000000000000000{n:04d}"[:26],
            strategy_id=strat_a,
            dataset_ref="match-ref",
            completed_at=base + timedelta(hours=n),
        )
    rows = repo.get_recent_runs("match-ref", limit=10)
    assert len(rows) == 10


def test_get_recent_runs_skips_runs_without_data_selection(db_session: Session) -> None:
    """Runs with a config_json missing data_selection must not match."""
    repo = SqlDatasetRepository(db=db_session)
    user_id = _seed_user(db_session)
    strat_a = _seed_strategy(
        db_session,
        strategy_id="01HSTRAT00000000000000000A",
        name="A",
        created_by=user_id,
    )
    _seed_run(
        db_session,
        run_id="01HRUN000000000000000NODSL",
        strategy_id=strat_a,
        dataset_ref=None,  # No data_selection at all.
        completed_at=datetime(2026, 4, 25, 12, 0, 0),
    )
    assert repo.get_recent_runs("match-ref") == []


def test_get_recent_runs_wraps_driver_error(db_session: Session) -> None:
    repo = SqlDatasetRepository(db=db_session)
    with patch.object(
        db_session,
        "execute",
        side_effect=OperationalError("stmt", {}, Exception("db gone")),
    ):
        with pytest.raises(DatasetRepositoryError):
            repo.get_recent_runs("any-ref")
