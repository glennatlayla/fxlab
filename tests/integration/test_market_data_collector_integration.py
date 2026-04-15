"""
Integration tests for the market data collection pipeline.

Tests the full flow: MockProvider → MarketDataCollectorService → SqlMarketDataRepository.
Validates that fetched candles are persisted correctly and gaps are detected.

Architecture:
- Mock provider simulates Alpaca API responses.
- Real SQLAlchemy session bound to SQLite in-memory.
- SAVEPOINT isolation via integration_db_session fixture.

Does NOT:
- Make real HTTP calls to Alpaca (mock provider).
- Test Celery task dispatching (tested separately).

Dependencies:
- integration_db_session fixture (conftest.py): per-test SAVEPOINT session.
- MockMarketDataProvider: Simulated external data source.
- SqlMarketDataRepository: Real SQL persistence.
- MarketDataCollectorService: System under test.

Example:
    pytest tests/integration/test_market_data_collector_integration.py -v
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal

from sqlalchemy.orm import Session

from libs.contracts.market_data import (
    Candle,
    CandleInterval,
    MarketDataQuery,
)
from libs.contracts.mocks.mock_market_data_provider import (
    MockMarketDataProvider,
)
from services.api.repositories.sql_market_data_repository import (
    SqlMarketDataRepository,
)
from services.worker.collectors.market_data_collector import (
    MarketDataCollectorService,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_BASE_TS = datetime(2026, 1, 2, 0, 0, 0, tzinfo=timezone.utc)


def _make_candle(
    symbol: str = "AAPL",
    interval: CandleInterval = CandleInterval.D1,
    timestamp: datetime | None = None,
    close: str = "175.90",
) -> Candle:
    """Create a valid Candle with sensible defaults."""
    return Candle(
        symbol=symbol,
        interval=interval,
        open=Decimal("174.50"),
        high=Decimal("176.25"),
        low=Decimal("173.80"),
        close=Decimal(close),
        volume=58_000_000,
        timestamp=timestamp or _BASE_TS,
    )


def _make_daily_candles(
    symbol: str = "AAPL", count: int = 10, start: datetime | None = None
) -> list[Candle]:
    """Create a series of daily candles."""
    base = start or _BASE_TS
    return [
        _make_candle(
            symbol=symbol,
            timestamp=base + timedelta(days=i),
            close=str(Decimal("170.00") + Decimal(str(i))),
        )
        for i in range(count)
    ]


def _make_minute_candles(
    symbol: str = "AAPL",
    count: int = 60,
    start: datetime | None = None,
    gap_at: int | None = None,
) -> list[Candle]:
    """Create a series of 1-minute candles, optionally skipping one."""
    base = start or _BASE_TS
    candles = []
    for i in range(count):
        if gap_at is not None and i == gap_at:
            continue
        candles.append(
            _make_candle(
                symbol=symbol,
                interval=CandleInterval.M1,
                timestamp=base + timedelta(minutes=i),
                close=str(Decimal("175.00") + Decimal(str(i)) * Decimal("0.01")),
            )
        )
    return candles


# ---------------------------------------------------------------------------
# Full pipeline tests
# ---------------------------------------------------------------------------


class TestCollectorPipelineIntegration:
    """Integration tests: provider → collector → SQL repository."""

    def test_full_pipeline_persists_candles_to_sql(self, integration_db_session: Session) -> None:
        """Candles fetched from provider are persisted in the SQL repository."""
        provider = MockMarketDataProvider()
        repo = SqlMarketDataRepository(db=integration_db_session)
        provider.set_bars("AAPL", CandleInterval.D1, _make_daily_candles(count=10))

        collector = MarketDataCollectorService(provider=provider, repository=repo)
        result = collector.collect(
            symbols=["AAPL"],
            interval=CandleInterval.D1,
            start=_BASE_TS,
            end=_BASE_TS + timedelta(days=100),
        )

        assert result.total_candles_collected == 10
        assert result.total_candles_persisted == 10

        # Verify data in SQL
        page = repo.query_candles(MarketDataQuery(symbol="AAPL", interval=CandleInterval.D1))
        assert page.total_count == 10

    def test_pipeline_detects_gaps_in_minute_data(self, integration_db_session: Session) -> None:
        """Gaps in collected minute data are detected and reported."""
        provider = MockMarketDataProvider()
        repo = SqlMarketDataRepository(db=integration_db_session)
        candles_with_gap = _make_minute_candles(count=60, gap_at=30)
        provider.set_bars("AAPL", CandleInterval.M1, candles_with_gap)

        collector = MarketDataCollectorService(provider=provider, repository=repo)
        result = collector.collect(
            symbols=["AAPL"],
            interval=CandleInterval.M1,
            start=_BASE_TS,
            end=_BASE_TS + timedelta(hours=1),
        )

        assert result.total_candles_collected == 59
        assert result.total_gaps_detected >= 1

    def test_pipeline_multi_symbol_isolation(self, integration_db_session: Session) -> None:
        """Failure in one symbol does not prevent others from being collected."""
        provider = MockMarketDataProvider()
        repo = SqlMarketDataRepository(db=integration_db_session)
        provider.set_bars("AAPL", CandleInterval.D1, _make_daily_candles("AAPL", 5))
        from libs.contracts.errors import ExternalServiceError

        provider.set_error("SPY", ExternalServiceError("API down"))
        provider.set_bars("QQQ", CandleInterval.D1, _make_daily_candles("QQQ", 3))

        collector = MarketDataCollectorService(provider=provider, repository=repo)
        result = collector.collect(
            symbols=["AAPL", "SPY", "QQQ"],
            interval=CandleInterval.D1,
            start=_BASE_TS,
            end=_BASE_TS + timedelta(days=100),
        )

        assert set(result.symbols_succeeded) == {"AAPL", "QQQ"}
        assert result.symbols_failed == ["SPY"]
        assert result.total_candles_collected == 8

    def test_pipeline_idempotent_re_run(self, integration_db_session: Session) -> None:
        """Re-running collection does not create duplicates (upsert semantics)."""
        provider = MockMarketDataProvider()
        repo = SqlMarketDataRepository(db=integration_db_session)
        candles = _make_daily_candles(count=5)
        provider.set_bars("AAPL", CandleInterval.D1, candles)

        collector = MarketDataCollectorService(provider=provider, repository=repo)

        # First run
        collector.collect(
            symbols=["AAPL"],
            interval=CandleInterval.D1,
            start=_BASE_TS,
            end=_BASE_TS + timedelta(days=100),
        )

        # Second run (same data) — upsert semantics prevent duplicates
        collector.collect(
            symbols=["AAPL"],
            interval=CandleInterval.D1,
            start=_BASE_TS,
            end=_BASE_TS + timedelta(days=100),
        )

        page = repo.query_candles(MarketDataQuery(symbol="AAPL", interval=CandleInterval.D1))
        assert page.total_count == 5  # No duplicates

    def test_pipeline_large_batch_collection(self, integration_db_session: Session) -> None:
        """Collecting data for 20 symbols with chunk_size=5 processes correctly."""
        provider = MockMarketDataProvider()
        repo = SqlMarketDataRepository(db=integration_db_session)
        symbols = [f"SYM{i:02d}" for i in range(20)]
        for sym in symbols:
            provider.set_bars(sym, CandleInterval.D1, _make_daily_candles(sym, 3))

        collector = MarketDataCollectorService(provider=provider, repository=repo, chunk_size=5)
        result = collector.collect(
            symbols=symbols,
            interval=CandleInterval.D1,
            start=_BASE_TS,
            end=_BASE_TS + timedelta(days=100),
        )

        assert len(result.symbols_succeeded) == 20
        assert result.total_candles_collected == 60  # 20 * 3
