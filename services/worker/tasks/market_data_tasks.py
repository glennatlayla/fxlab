"""
Celery tasks for scheduled market data collection.

Responsibilities:
- Define Celery tasks for daily backfill and on-demand gap repair.
- Wire together the Alpaca provider, SQL repository, and collector service.
- Provide idempotent task execution (upsert semantics prevent duplicates).
- Parse configuration from environment variables for symbol watchlist.

Does NOT:
- Contain business logic (delegates to MarketDataCollectorService).
- Own database sessions or HTTP clients (created per invocation).
- Define Celery beat schedules (configured in Celery beat config).

Dependencies:
- celery: Task decorator and app instance.
- MarketDataCollectorService: Collection orchestration.
- AlpacaMarketDataProvider: External data source.
- SqlMarketDataRepository: Durable candle persistence.
- AlpacaConfig: API credentials.
- SQLAlchemy Session: Database access.

Error conditions:
- ConfigError: Missing required environment variables.
- Tasks log errors and return structured results (never raise to Celery).

Example:
    # Trigger via Celery:
    from services.worker.tasks.market_data_tasks import collect_historical_bars
    result = collect_historical_bars.delay()

    # Or call directly for testing:
    result = collect_historical_bars()
"""

from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone

import structlog

from libs.contracts.alpaca_config import AlpacaConfig
from libs.contracts.errors import ConfigError
from libs.contracts.market_data import CandleInterval

logger = structlog.get_logger(__name__)

#: Default symbols to collect if MARKET_DATA_SYMBOLS is not set.
_DEFAULT_SYMBOLS = ["AAPL", "SPY", "QQQ", "MSFT", "GOOGL", "AMZN", "META", "NVDA", "TSLA", "JPM"]

#: Default interval for scheduled collection.
_DEFAULT_INTERVAL = CandleInterval.D1

#: Default backfill lookback in days for scheduled daily collection.
_DEFAULT_LOOKBACK_DAYS = 7


def _get_symbols() -> list[str]:
    """
    Parse symbol watchlist from MARKET_DATA_SYMBOLS environment variable.

    Expected format: comma-separated uppercase symbols.
    Falls back to _DEFAULT_SYMBOLS if not set.

    Returns:
        List of ticker symbol strings.

    Example:
        # MARKET_DATA_SYMBOLS="AAPL,SPY,QQQ"
        symbols = _get_symbols()  # ["AAPL", "SPY", "QQQ"]
    """
    raw = os.environ.get("MARKET_DATA_SYMBOLS", "")
    if raw.strip():
        return [s.strip().upper() for s in raw.split(",") if s.strip()]
    return list(_DEFAULT_SYMBOLS)


def _get_alpaca_config() -> AlpacaConfig:
    """
    Build AlpacaConfig from environment variables.

    Required env vars:
    - ALPACA_DATA_API_KEY: Alpaca API key ID.
    - ALPACA_DATA_API_SECRET: Alpaca API secret.

    Optional env vars:
    - ALPACA_DATA_BASE_URL: Data API base URL (default: https://data.alpaca.markets).

    Returns:
        AlpacaConfig instance.

    Raises:
        ConfigError: If required credentials are missing.
    """
    api_key = os.environ.get("ALPACA_DATA_API_KEY", "")
    api_secret = os.environ.get("ALPACA_DATA_API_SECRET", "")

    if not api_key or not api_secret:
        raise ConfigError(
            "ALPACA_DATA_API_KEY and ALPACA_DATA_API_SECRET must be set. "
            "These credentials are required for Alpaca Market Data API access."
        )

    data_base_url = os.environ.get("ALPACA_DATA_BASE_URL", "https://data.alpaca.markets")

    return AlpacaConfig(
        api_key=api_key,
        api_secret=api_secret,
        data_base_url=data_base_url,
    )


def _build_collector():  # type: ignore[no-untyped-def]
    """
    Build a MarketDataCollectorService with production dependencies.

    Wires together AlpacaMarketDataProvider and SqlMarketDataRepository.
    Creates a new SQLAlchemy session for the task invocation.

    Returns:
        Tuple of (collector, db_session) — caller must close the session.

    Raises:
        ConfigError: If Alpaca credentials are missing.
    """
    # Lazy imports to avoid circular dependencies and to allow testing
    # without a database connection.
    from services.api.database import get_db
    from services.api.repositories.sql_market_data_repository import (
        SqlMarketDataRepository,
    )
    from services.worker.collectors.alpaca_market_data_provider import (
        AlpacaMarketDataProvider,
    )
    from services.worker.collectors.market_data_collector import (
        MarketDataCollectorService,
    )

    config = _get_alpaca_config()
    provider = AlpacaMarketDataProvider(config=config)

    db_session = next(get_db())
    repository = SqlMarketDataRepository(db=db_session)

    collector = MarketDataCollectorService(
        provider=provider,
        repository=repository,
    )

    return collector, db_session


def collect_historical_bars(
    symbols: list[str] | None = None,
    interval: str | None = None,
    lookback_days: int | None = None,
) -> dict:
    """
    Collect historical bars for the configured symbol watchlist.

    This is the primary entry point for scheduled daily backfill.
    Collects the last N days of data (default 7) to catch any gaps
    from missed runs. Upsert semantics ensure no duplicates.

    Args:
        symbols: Override symbol list (default: MARKET_DATA_SYMBOLS env var).
        interval: Override interval string (default: "1d").
        lookback_days: Override lookback period (default: 7 days).

    Returns:
        Dict with collection summary (JSON-serializable for Celery result).

    Example:
        # Default scheduled run:
        result = collect_historical_bars()

        # Custom invocation:
        result = collect_historical_bars(
            symbols=["AAPL", "SPY"],
            interval="1d",
            lookback_days=30,
        )
    """
    syms = symbols or _get_symbols()
    ivl = CandleInterval(interval) if interval else _DEFAULT_INTERVAL
    days = lookback_days or _DEFAULT_LOOKBACK_DAYS

    end = datetime.now(timezone.utc)
    start = end - timedelta(days=days)

    logger.info(
        "task.collect_historical_bars.start",
        symbols_count=len(syms),
        interval=ivl.value,
        lookback_days=days,
        start=start.isoformat(),
        end=end.isoformat(),
    )

    collector, db_session = _build_collector()
    try:
        result = collector.collect(
            symbols=syms,
            interval=ivl,
            start=start,
            end=end,
        )
        db_session.commit()

        summary = {
            "status": "success" if not result.symbols_failed else "partial",
            "symbols_requested": len(result.symbols_requested),
            "symbols_succeeded": len(result.symbols_succeeded),
            "symbols_failed": result.symbols_failed,
            "total_candles_collected": result.total_candles_collected,
            "total_candles_persisted": result.total_candles_persisted,
            "total_gaps_detected": result.total_gaps_detected,
            "started_at": result.started_at.isoformat(),
            "completed_at": result.completed_at.isoformat() if result.completed_at else None,
        }

        logger.info("task.collect_historical_bars.complete", **summary)
        return summary

    except Exception as exc:
        db_session.rollback()
        logger.error(
            "task.collect_historical_bars.failed",
            error_type=type(exc).__name__,
            error_message=str(exc),
            exc_info=True,
        )
        return {
            "status": "error",
            "error": f"{type(exc).__name__}: {exc}",
        }
    finally:
        db_session.close()


def backfill_gaps(
    symbol: str,
    interval: str = "1d",
    start: str | None = None,
    end: str | None = None,
) -> dict:
    """
    On-demand task to backfill detected data gaps for a specific symbol.

    Detects existing gaps in the repository and re-fetches data for
    each gap period from the provider.

    Args:
        symbol: Ticker symbol to backfill.
        interval: Candle interval string (default "1d").
        start: ISO 8601 start of scan range (default: 1 year ago).
        end: ISO 8601 end of scan range (default: now).

    Returns:
        Dict with backfill summary.

    Example:
        result = backfill_gaps(symbol="AAPL", interval="1d")
    """
    ivl = CandleInterval(interval)
    now = datetime.now(timezone.utc)
    scan_start = datetime.fromisoformat(start) if start else now - timedelta(days=365)
    scan_end = datetime.fromisoformat(end) if end else now

    logger.info(
        "task.backfill_gaps.start",
        symbol=symbol,
        interval=ivl.value,
        scan_start=scan_start.isoformat(),
        scan_end=scan_end.isoformat(),
    )

    collector, db_session = _build_collector()
    try:
        # Detect gaps first
        from services.api.repositories.sql_market_data_repository import (
            SqlMarketDataRepository,
        )

        repo = SqlMarketDataRepository(db=db_session)
        gaps = repo.detect_gaps(symbol, ivl, scan_start, scan_end)

        if not gaps:
            logger.info(
                "task.backfill_gaps.no_gaps",
                symbol=symbol,
                interval=ivl.value,
            )
            return {
                "status": "success",
                "symbol": symbol,
                "gaps_found": 0,
                "candles_collected": 0,
            }

        # Collect data for each gap period
        total_collected = 0
        total_persisted = 0
        for gap in gaps:
            result = collector.collect(
                symbols=[symbol],
                interval=ivl,
                start=gap.gap_start,
                end=gap.gap_end,
            )
            total_collected += result.total_candles_collected
            total_persisted += result.total_candles_persisted

        db_session.commit()

        summary = {
            "status": "success",
            "symbol": symbol,
            "gaps_found": len(gaps),
            "candles_collected": total_collected,
            "candles_persisted": total_persisted,
        }

        logger.info("task.backfill_gaps.complete", **summary)
        return summary

    except Exception as exc:
        db_session.rollback()
        logger.error(
            "task.backfill_gaps.failed",
            symbol=symbol,
            error_type=type(exc).__name__,
            error_message=str(exc),
            exc_info=True,
        )
        return {
            "status": "error",
            "symbol": symbol,
            "error": f"{type(exc).__name__}: {exc}",
        }
    finally:
        db_session.close()
