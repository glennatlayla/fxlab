"""
Unit tests for :meth:`ExportService.stream_run_blotter_csv` (run-blotter CSV
export — Tranche L follow-on).

Scope:
    Verify the streaming CSV exporter that lifts trade legs out of a
    completed :class:`ResearchRunRecord`, pairs them into round-trip rows
    matching :class:`libs.contracts.run_results.TradeBlotterRow`, and
    yields header + chunked CSV bytes for the route layer to stream.

    These tests intentionally live in a sibling file to
    ``tests/unit/test_export_service.py`` so the existing job-bundle
    behaviour stays untouched. The new method extends the public API
    surface without altering the existing ``create_export`` / ``get_export``
    / ``list_exports`` / ``download_export`` paths.

Test matrix:
    * Header is always the first yielded chunk and matches
      :data:`RUN_BLOTTER_CSV_COLUMNS`.
    * Run with N closed round-trips produces N+1 lines (header + rows).
    * Empty blotter (zero trades) produces only the header row.
    * Missing run -> NotFoundError.
    * Pending / queued / running run -> RunNotCompletedError.
    * Long blotter (> :data:`RUN_BLOTTER_EXPORT_CHUNK_SIZE` rows) yields
      multiple chunks so memory stays bounded.
    * Open positions at run end surface with empty exit_time / exit_price
      / realized_pnl / holding_period_seconds cells.
    * Decimal formatting matches the JSON blotter's ``str(Decimal)`` shape.
"""

from __future__ import annotations

import csv
import io
from collections.abc import Iterator
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

import pytest

from libs.contracts.backtest import (
    BacktestConfig,
    BacktestResult,
    BacktestTrade,
)
from libs.contracts.errors import NotFoundError
from libs.contracts.mocks.mock_export_repository import MockExportRepository
from libs.contracts.mocks.mock_research_run_repository import (
    MockResearchRunRepository,
)
from libs.contracts.research_run import (
    ResearchRunConfig,
    ResearchRunRecord,
    ResearchRunResult,
    ResearchRunStatus,
    ResearchRunType,
)
from libs.contracts.run_results import (
    RUN_BLOTTER_CSV_COLUMNS,
    RUN_BLOTTER_EXPORT_CHUNK_SIZE,
)
from libs.storage.base import ArtifactStorageBase
from services.api.services.export_service import ExportService
from services.api.services.research_run_service import RunNotCompletedError

# ---------------------------------------------------------------------------
# Test doubles
# ---------------------------------------------------------------------------


class _NoOpArtifactStorage(ArtifactStorageBase):
    """
    Minimal :class:`ArtifactStorageBase` test double.

    The streaming CSV path does not touch artifact storage at all (it
    streams directly to the wire), but :class:`ExportService.__init__`
    requires the dependency for backwards-compatibility with the
    job-bundle methods that DO use it. This double satisfies the
    constructor without exercising the storage path.
    """

    def __init__(self) -> None:
        self._init_called = False

    def initialize(self, correlation_id: str) -> None:
        self._init_called = True

    def is_initialized(self) -> bool:
        return self._init_called

    def health_check(self, correlation_id: str) -> bool:
        return True

    def put(
        self,
        data: bytes,
        bucket: str,
        key: str,
        metadata: dict[str, object] | None = None,
        correlation_id: str | None = None,
    ) -> str:
        raise AssertionError("storage.put must not be called by stream_run_blotter_csv")

    def get(self, bucket: str, key: str, correlation_id: str) -> bytes:
        raise AssertionError("storage.get must not be called by stream_run_blotter_csv")

    def get_with_metadata(
        self, bucket: str, key: str, correlation_id: str
    ) -> tuple[bytes, dict[str, object]]:
        raise AssertionError(
            "storage.get_with_metadata must not be called by stream_run_blotter_csv"
        )

    def list(
        self,
        bucket: str,
        prefix: str,
        correlation_id: str,
        max_keys: int | None = None,
    ) -> list[str]:
        return []

    def delete(self, bucket: str, key: str, correlation_id: str) -> None:
        raise AssertionError("storage.delete must not be called by stream_run_blotter_csv")


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

_RUN_ID_COMPLETED = "01HRESDNE00000000000000001"
_RUN_ID_PENDING = "01HRESPND00000000000000002"
_RUN_ID_MISSING = "01HRESMSNG0000000000000099"


@pytest.fixture()
def run_repo() -> MockResearchRunRepository:
    return MockResearchRunRepository()


@pytest.fixture()
def export_repo() -> MockExportRepository:
    return MockExportRepository()


@pytest.fixture()
def storage() -> _NoOpArtifactStorage:
    return _NoOpArtifactStorage()


@pytest.fixture()
def service(
    run_repo: MockResearchRunRepository,
    export_repo: MockExportRepository,
    storage: _NoOpArtifactStorage,
) -> ExportService:
    """
    Build an :class:`ExportService` with the new
    ``research_run_repo`` constructor dependency wired.

    The pre-existing job-bundle methods continue to depend on
    ``repo`` (export jobs) and ``storage``; the new run-blotter
    streamer depends on ``research_run_repo`` (research runs).
    Marking the new dep optional keeps the existing call sites
    in main.py from breaking.
    """
    return ExportService(
        repo=export_repo,
        storage=storage,
        research_run_repo=run_repo,
    )


def _make_trade(
    *,
    minutes_offset: int,
    side: str,
    quantity: Decimal = Decimal("100"),
    price: Decimal = Decimal("1.1000"),
    commission: Decimal = Decimal("0.50"),
    slippage: Decimal = Decimal("0.10"),
    symbol: str = "EURUSD",
    base_ts: datetime = datetime(2025, 1, 1, 9, 30, tzinfo=timezone.utc),
) -> BacktestTrade:
    return BacktestTrade(
        timestamp=base_ts + timedelta(minutes=minutes_offset),
        symbol=symbol,
        side=side,
        quantity=quantity,
        price=price,
        commission=commission,
        slippage=slippage,
    )


def _seed_completed(
    repo: MockResearchRunRepository,
    *,
    run_id: str = _RUN_ID_COMPLETED,
    trades: list[BacktestTrade] | None = None,
) -> ResearchRunRecord:
    """Insert a COMPLETED run record carrying the supplied trade legs."""
    if trades is None:
        trades = []
    config = ResearchRunConfig(
        run_type=ResearchRunType.BACKTEST,
        strategy_id="01HSTRATBACKTEST0000000001",
        symbols=["EURUSD"],
        initial_equity=Decimal("100000"),
    )
    backtest = BacktestResult(
        config=BacktestConfig(
            strategy_id=config.strategy_id,
            symbols=config.symbols,
            start_date=date(2025, 1, 1),
            end_date=date(2025, 1, 31),
        ),
        total_trades=len(trades),
        trades=trades,
    )
    result = ResearchRunResult(
        backtest_result=backtest,
        summary_metrics={"total_trades": str(len(trades))},
    )
    record = ResearchRunRecord(
        id=run_id,
        config=config,
        status=ResearchRunStatus.COMPLETED,
        result=result,
        created_by="01HUSER0000000000000000001",
        completed_at=datetime(2025, 2, 1, tzinfo=timezone.utc),
    )
    with repo._lock:  # noqa: SLF001 — test seeding only
        repo._store[record.id] = record  # noqa: SLF001 — test seeding only
    return record


def _seed_pending(
    repo: MockResearchRunRepository,
    *,
    run_id: str = _RUN_ID_PENDING,
    status: ResearchRunStatus = ResearchRunStatus.PENDING,
) -> ResearchRunRecord:
    config = ResearchRunConfig(
        run_type=ResearchRunType.BACKTEST,
        strategy_id="01HSTRATBACKTEST0000000001",
        symbols=["EURUSD"],
    )
    record = ResearchRunRecord(
        id=run_id,
        config=config,
        status=status,
        created_by="01HUSER0000000000000000001",
    )
    with repo._lock:  # noqa: SLF001 — test seeding only
        repo._store[record.id] = record  # noqa: SLF001 — test seeding only
    return record


def _drain(stream: Iterator[bytes]) -> tuple[bytes, int]:
    """Materialise a streaming iterator and return (full_body, chunk_count)."""
    chunks: list[bytes] = []
    for chunk in stream:
        assert isinstance(chunk, (bytes, bytearray)), (
            f"Expected bytes from CSV stream, got {type(chunk).__name__}"
        )
        chunks.append(bytes(chunk))
    return b"".join(chunks), len(chunks)


def _parse_csv(body: bytes) -> list[list[str]]:
    """Round-trip the streamed body through csv.reader."""
    reader = csv.reader(io.StringIO(body.decode("utf-8")))
    return list(reader)


# ---------------------------------------------------------------------------
# Header / column-order contract
# ---------------------------------------------------------------------------


def test_stream_first_chunk_is_header_row(
    service: ExportService,
    run_repo: MockResearchRunRepository,
) -> None:
    _seed_completed(run_repo)  # zero trades

    chunks = list(service.stream_run_blotter_csv(_RUN_ID_COMPLETED))
    assert chunks, "stream must yield at least the header chunk"

    first_line = chunks[0].decode("utf-8").splitlines()[0]
    header = next(csv.reader(io.StringIO(first_line)))
    assert tuple(header) == RUN_BLOTTER_CSV_COLUMNS


def test_empty_blotter_yields_header_only(
    service: ExportService,
    run_repo: MockResearchRunRepository,
) -> None:
    _seed_completed(run_repo, trades=[])

    body, _ = _drain(service.stream_run_blotter_csv(_RUN_ID_COMPLETED))
    rows = _parse_csv(body)
    assert len(rows) == 1, "empty blotter must produce header-only CSV"
    assert tuple(rows[0]) == RUN_BLOTTER_CSV_COLUMNS


# ---------------------------------------------------------------------------
# Round-trip pairing
# ---------------------------------------------------------------------------


def test_long_then_close_produces_one_round_trip_row(
    service: ExportService,
    run_repo: MockResearchRunRepository,
) -> None:
    """A buy-then-sell pair on the same symbol becomes one row."""
    open_leg = _make_trade(
        minutes_offset=0,
        side="buy",
        quantity=Decimal("100"),
        price=Decimal("1.1000"),
    )
    close_leg = _make_trade(
        minutes_offset=60,
        side="sell",
        quantity=Decimal("100"),
        price=Decimal("1.1050"),
    )
    _seed_completed(run_repo, trades=[open_leg, close_leg])

    body, _ = _drain(service.stream_run_blotter_csv(_RUN_ID_COMPLETED))
    rows = _parse_csv(body)
    assert len(rows) == 2, f"expected header + 1 data row, got {len(rows)}"

    header = rows[0]
    data = dict(zip(header, rows[1], strict=True))

    assert data["symbol"] == "EURUSD"
    assert data["side"] == "buy", "side must reflect the OPENING leg"
    assert data["entry_time"] == "2025-01-01T09:30:00+00:00"
    assert data["exit_time"] == "2025-01-01T10:30:00+00:00"
    assert Decimal(data["units"]) == Decimal("100")
    assert Decimal(data["entry_price"]) == Decimal("1.1000")
    assert Decimal(data["exit_price"]) == Decimal("1.1050")
    # Fees aggregate both legs: 0.50 + 0.10 + 0.50 + 0.10 = 1.20
    assert Decimal(data["fees"]) == Decimal("1.20")
    # Realized PnL for a long round-trip:
    #   (exit_price - entry_price) * units - fees
    #   = (1.1050 - 1.1000) * 100 - 1.20 = 0.50 - 1.20 = -0.70
    assert Decimal(data["realized_pnl"]) == Decimal("-0.70")
    assert int(data["holding_period_seconds"]) == 3600


def test_short_round_trip_pnl_uses_entry_minus_exit(
    service: ExportService,
    run_repo: MockResearchRunRepository,
) -> None:
    """A sell-then-buy pair (short round-trip) computes PnL with the
    sign convention reversed: ``(entry_price - exit_price) * units``."""
    open_leg = _make_trade(
        minutes_offset=0,
        side="sell",
        quantity=Decimal("50"),
        price=Decimal("1.2000"),
        commission=Decimal("0"),
        slippage=Decimal("0"),
    )
    close_leg = _make_trade(
        minutes_offset=120,
        side="buy",
        quantity=Decimal("50"),
        price=Decimal("1.1900"),
        commission=Decimal("0"),
        slippage=Decimal("0"),
    )
    _seed_completed(run_repo, trades=[open_leg, close_leg])

    body, _ = _drain(service.stream_run_blotter_csv(_RUN_ID_COMPLETED))
    rows = _parse_csv(body)
    data = dict(zip(rows[0], rows[1], strict=True))

    assert data["side"] == "sell"
    # Realised PnL: (1.20 - 1.19) * 50 - 0 = 0.50
    assert Decimal(data["realized_pnl"]) == Decimal("0.50")
    assert int(data["holding_period_seconds"]) == 7200


def test_open_position_at_run_end_surfaces_blank_exit_fields(
    service: ExportService,
    run_repo: MockResearchRunRepository,
) -> None:
    """A bare opening leg with no matching close yields a row with
    empty ``exit_time``, ``exit_price``, ``realized_pnl``, and
    ``holding_period_seconds`` cells."""
    open_leg = _make_trade(
        minutes_offset=0,
        side="buy",
        quantity=Decimal("75"),
        price=Decimal("1.0500"),
    )
    _seed_completed(run_repo, trades=[open_leg])

    body, _ = _drain(service.stream_run_blotter_csv(_RUN_ID_COMPLETED))
    rows = _parse_csv(body)
    data = dict(zip(rows[0], rows[1], strict=True))

    assert data["entry_time"] == "2025-01-01T09:30:00+00:00"
    assert data["exit_time"] == "", "open positions surface blank exit_time"
    assert data["exit_price"] == ""
    assert data["realized_pnl"] == ""
    assert data["holding_period_seconds"] == ""
    # Fees still cover the opening leg: 0.50 + 0.10 = 0.60
    assert Decimal(data["fees"]) == Decimal("0.60")


def test_n_round_trips_produce_n_plus_one_lines(
    service: ExportService,
    run_repo: MockResearchRunRepository,
) -> None:
    """Three closed round-trips → header + 3 data rows."""
    trades: list[BacktestTrade] = []
    for i in range(3):
        trades.append(
            _make_trade(
                minutes_offset=i * 60,
                side="buy",
                price=Decimal("1.1000") + Decimal(i) / Decimal("10000"),
            )
        )
        trades.append(
            _make_trade(
                minutes_offset=i * 60 + 30,
                side="sell",
                price=Decimal("1.1010") + Decimal(i) / Decimal("10000"),
            )
        )
    _seed_completed(run_repo, trades=trades)

    body, _ = _drain(service.stream_run_blotter_csv(_RUN_ID_COMPLETED))
    rows = _parse_csv(body)
    assert len(rows) == 1 + 3


def test_rows_are_sorted_by_entry_time(
    service: ExportService,
    run_repo: MockResearchRunRepository,
) -> None:
    """Identical queries must produce identical output ordered by
    entry_time so spreadsheet diffs stay stable."""
    # Emit two round-trips deliberately out of order.
    trades = [
        # Round-trip B (later entry)
        _make_trade(minutes_offset=120, side="buy", price=Decimal("1.2000")),
        _make_trade(minutes_offset=180, side="sell", price=Decimal("1.2010")),
        # Round-trip A (earlier entry)
        _make_trade(minutes_offset=0, side="buy", price=Decimal("1.1000")),
        _make_trade(minutes_offset=60, side="sell", price=Decimal("1.1010")),
    ]
    _seed_completed(run_repo, trades=trades)

    body, _ = _drain(service.stream_run_blotter_csv(_RUN_ID_COMPLETED))
    rows = _parse_csv(body)
    data_rows = rows[1:]
    assert len(data_rows) == 2
    times = [r[3] for r in data_rows]  # entry_time column
    assert times == sorted(times), "rows must be sorted by entry_time ascending"


# ---------------------------------------------------------------------------
# Error paths
# ---------------------------------------------------------------------------


def test_missing_run_raises_not_found_error(
    service: ExportService,
) -> None:
    with pytest.raises(NotFoundError):
        # Drain the iterator so the lookup actually executes.
        list(service.stream_run_blotter_csv(_RUN_ID_MISSING))


@pytest.mark.parametrize(
    "status",
    [
        ResearchRunStatus.PENDING,
        ResearchRunStatus.QUEUED,
        ResearchRunStatus.RUNNING,
    ],
)
def test_non_terminal_run_raises_run_not_completed_error(
    service: ExportService,
    run_repo: MockResearchRunRepository,
    status: ResearchRunStatus,
) -> None:
    _seed_pending(run_repo, status=status)
    with pytest.raises(RunNotCompletedError):
        list(service.stream_run_blotter_csv(_RUN_ID_PENDING))


def test_research_run_repo_dependency_required(
    export_repo: MockExportRepository,
    storage: _NoOpArtifactStorage,
) -> None:
    """Calling stream_run_blotter_csv without the optional repo wired
    must raise a clear RuntimeError rather than silently returning."""
    bare_service = ExportService(repo=export_repo, storage=storage)
    with pytest.raises(RuntimeError, match="research_run_repo"):
        list(bare_service.stream_run_blotter_csv(_RUN_ID_COMPLETED))


# ---------------------------------------------------------------------------
# Streaming bound: large blotters yield more than one chunk
# ---------------------------------------------------------------------------


def test_large_blotter_yields_multiple_chunks(
    service: ExportService,
    run_repo: MockResearchRunRepository,
) -> None:
    """A blotter with > RUN_BLOTTER_EXPORT_CHUNK_SIZE round-trips must
    yield more than one byte chunk so memory stays bounded."""
    chunk_size = RUN_BLOTTER_EXPORT_CHUNK_SIZE
    # Need chunk_size + 1 round-trips → 2 * (chunk_size + 1) trade legs.
    pair_count = chunk_size + 1
    trades: list[BacktestTrade] = []
    for i in range(pair_count):
        trades.append(_make_trade(minutes_offset=i * 2, side="buy"))
        trades.append(_make_trade(minutes_offset=i * 2 + 1, side="sell"))
    _seed_completed(run_repo, trades=trades)

    body, chunk_count = _drain(service.stream_run_blotter_csv(_RUN_ID_COMPLETED))
    rows = _parse_csv(body)
    assert len(rows) == 1 + pair_count
    assert chunk_count >= 2, f"expected >=2 chunks for {pair_count} round-trips, got {chunk_count}"
