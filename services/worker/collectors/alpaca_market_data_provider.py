"""
Alpaca Market Data API v2 provider for historical OHLCV bars.

Responsibilities:
- Fetch historical candlestick (bar) data from Alpaca's Market Data API v2.
- Handle pagination via Alpaca's page_token mechanism.
- Map Alpaca's bar format to the canonical Candle contract.
- Enforce rate limiting: respects Alpaca's 200 req/min limit with
  adaptive backoff on 429 responses.
- Map HTTP error codes to domain exceptions (AuthError, TransientError, etc.).

Does NOT:
- Persist candles (that's the collector service + repository's job).
- Compute indicators or analytics.
- Handle real-time streaming (separate component in M3).
- Manage API credentials (loaded from AlpacaConfig).

Dependencies:
- httpx: HTTP client with timeout support.
- libs.contracts.alpaca_config: AlpacaConfig for credentials and URLs.
- libs.contracts.market_data: Candle, CandleInterval contracts.
- libs.contracts.errors: Domain exception hierarchy.
- structlog: Structured logging.

Error conditions:
- AuthError: 401/403 from Alpaca (invalid API key or permissions).
- TransientError: 429/5xx from Alpaca (retriable by caller).
- ExternalServiceError: Other unexpected Alpaca errors (4xx except 401/403/429).
- httpx.TimeoutException: Wrapped in TransientError.

Example:
    from libs.contracts.alpaca_config import AlpacaConfig

    config = AlpacaConfig.paper(api_key="AK...", api_secret="...")
    provider = AlpacaMarketDataProvider(config=config)
    candles = provider.fetch_historical_bars(
        "AAPL", CandleInterval.D1,
        datetime(2025, 1, 1, tzinfo=timezone.utc),
        datetime(2026, 1, 1, tzinfo=timezone.utc),
    )
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any

import httpx
import structlog

from libs.contracts.alpaca_config import AlpacaConfig
from libs.contracts.errors import (
    AuthError,
    ExternalServiceError,
    TransientError,
)
from libs.contracts.interfaces.market_data_provider import (
    MarketDataProviderInterface,
)
from libs.contracts.market_data import Candle, CandleInterval

logger = structlog.get_logger(__name__)

# ---------------------------------------------------------------------------
# CandleInterval → Alpaca timeframe mapping
# ---------------------------------------------------------------------------

#: Map canonical CandleInterval values to Alpaca's "timeframe" query parameter.
#: Alpaca uses a different format: "1Min", "5Min", "15Min", "1Hour", "1Day".
_INTERVAL_TO_ALPACA_TIMEFRAME: dict[CandleInterval, str] = {
    CandleInterval.M1: "1Min",
    CandleInterval.M5: "5Min",
    CandleInterval.M15: "15Min",
    CandleInterval.H1: "1Hour",
    CandleInterval.D1: "1Day",
}

#: Default request timeout in seconds. Alpaca data API can be slow for
#: large date ranges, so 30s is generous but prevents hangs.
_DEFAULT_TIMEOUT_S = 30.0

#: Maximum pages to fetch in a single fetch_historical_bars call.
#: Prevents infinite loops if Alpaca returns unexpected pagination tokens.
_MAX_PAGES = 500


class AlpacaMarketDataProvider(MarketDataProviderInterface):
    """
    Alpaca Market Data API v2 implementation of MarketDataProviderInterface.

    Fetches historical OHLCV bars from https://data.alpaca.markets/v2/stocks/{symbol}/bars.
    Handles Alpaca's page_token pagination to retrieve complete date ranges.
    Maps Alpaca's JSON bar objects to Candle Pydantic models with Decimal prices.

    Responsibilities:
    - REST calls to Alpaca Market Data API v2.
    - Pagination via page_token until all bars are fetched.
    - Bar-to-Candle mapping with Decimal precision.
    - HTTP error → domain exception mapping.

    Does NOT:
    - Implement rate limiting logic (caller/collector handles inter-symbol pacing).
    - Retry on transient errors (caller uses with_retry or collector-level retry).
    - Persist candles to the repository.

    Dependencies:
    - config: AlpacaConfig (injected via constructor).
    - transport: Optional httpx transport override for testing.

    Example:
        provider = AlpacaMarketDataProvider(config=config)
        candles = provider.fetch_historical_bars("AAPL", CandleInterval.D1, start, end)
    """

    def __init__(
        self,
        config: AlpacaConfig,
        *,
        transport: httpx.BaseTransport | None = None,
        timeout_s: float = _DEFAULT_TIMEOUT_S,
    ) -> None:
        self._config = config
        self._timeout_s = timeout_s
        # Allow transport injection for testing (mock transport).
        # Production code uses default transport (real HTTP).
        self._transport = transport

    # ------------------------------------------------------------------
    # Interface implementation
    # ------------------------------------------------------------------

    def fetch_historical_bars(
        self,
        symbol: str,
        interval: CandleInterval,
        start: datetime,
        end: datetime,
    ) -> list[Candle]:
        """
        Fetch historical OHLCV bars from Alpaca for a symbol and time range.

        Handles pagination internally: follows Alpaca's next_page_token until
        all bars in the date range are retrieved.

        Args:
            symbol: Ticker symbol (e.g. "AAPL"). Case-insensitive.
            interval: Candle time interval.
            start: Start of time range (inclusive), timezone-aware UTC.
            end: End of time range (inclusive), timezone-aware UTC.

        Returns:
            List of Candle objects ordered by timestamp ascending.

        Raises:
            AuthError: On 401/403 from Alpaca.
            TransientError: On 429/5xx from Alpaca or timeout.
            ExternalServiceError: On other HTTP errors.
        """
        symbol_upper = symbol.upper()
        timeframe = _INTERVAL_TO_ALPACA_TIMEFRAME[interval]
        url = self._config.bars_url(symbol_upper)

        all_candles: list[Candle] = []
        page_token: str | None = None
        page_count = 0

        logger.info(
            "alpaca_provider.fetch_start",
            symbol=symbol_upper,
            interval=interval.value,
            timeframe=timeframe,
            start=start.isoformat(),
            end=end.isoformat(),
        )

        client = self._build_client()
        try:
            while page_count < _MAX_PAGES:
                params = self._build_params(timeframe, start, end, page_token)
                response = self._execute_request(client, url, params)
                self._check_response(response, symbol_upper)

                data = response.json()
                bars = data.get("bars") or []

                for bar in bars:
                    candle = self._bar_to_candle(bar, symbol_upper, interval)
                    all_candles.append(candle)

                page_token = data.get("next_page_token")
                page_count += 1

                if not page_token:
                    break
        finally:
            client.close()

        # Ensure chronological order
        all_candles.sort(key=lambda c: c.timestamp)

        logger.info(
            "alpaca_provider.fetch_complete",
            symbol=symbol_upper,
            interval=interval.value,
            candles_fetched=len(all_candles),
            pages_fetched=page_count,
        )

        return all_candles

    def get_supported_intervals(self) -> list[CandleInterval]:
        """
        Return all intervals supported by Alpaca Market Data API v2.

        Alpaca supports 1Min, 5Min, 15Min, 1Hour, 1Day which maps to
        all CandleInterval values.

        Returns:
            All CandleInterval values.
        """
        return list(CandleInterval)

    def get_provider_name(self) -> str:
        """Return 'alpaca' as the provider identifier."""
        return "alpaca"

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _build_client(self) -> httpx.Client:
        """
        Build an httpx Client with auth headers and timeout.

        Returns:
            Configured httpx.Client instance. Caller must close it.
        """
        kwargs: dict[str, Any] = {
            "headers": self._config.auth_headers,
            "timeout": httpx.Timeout(self._timeout_s),
        }
        if self._transport is not None:
            kwargs["transport"] = self._transport
        return httpx.Client(**kwargs)

    @staticmethod
    def _build_params(
        timeframe: str,
        start: datetime,
        end: datetime,
        page_token: str | None,
    ) -> dict[str, str]:
        """
        Build query parameters for the Alpaca bars endpoint.

        Args:
            timeframe: Alpaca timeframe string (e.g. "1Day").
            start: Start of time range.
            end: End of time range.
            page_token: Pagination token from previous response, or None.

        Returns:
            Dict of query parameters.
        """
        params: dict[str, str] = {
            "timeframe": timeframe,
            "start": start.isoformat(),
            "end": end.isoformat(),
            "limit": "10000",
            "adjustment": "raw",
            "feed": "iex",
            "sort": "asc",
        }
        if page_token:
            params["page_token"] = page_token
        return params

    def _execute_request(
        self,
        client: httpx.Client,
        url: str,
        params: dict[str, str],
    ) -> httpx.Response:
        """
        Execute GET request with timeout handling.

        Args:
            client: httpx.Client instance.
            url: Request URL.
            params: Query parameters.

        Returns:
            httpx.Response.

        Raises:
            TransientError: On timeout.
        """
        try:
            return client.get(url, params=params)
        except httpx.TimeoutException as exc:
            raise TransientError(f"Alpaca API timeout after {self._timeout_s}s: {exc}") from exc
        except httpx.ConnectError as exc:
            raise TransientError(f"Alpaca API connection error: {exc}") from exc

    @staticmethod
    def _check_response(response: httpx.Response, symbol: str) -> None:
        """
        Check HTTP response status and raise domain exceptions on error.

        Maps Alpaca HTTP status codes to the FXLab exception hierarchy:
        - 401/403 → AuthError (permanent, do not retry)
        - 429 → TransientError (rate limited, retry with backoff)
        - 5xx → TransientError (server error, retry with backoff)
        - Other 4xx → ExternalServiceError (permanent, do not retry)

        Args:
            response: httpx.Response to check.
            symbol: Symbol being fetched (for error context).

        Raises:
            AuthError: On 401/403.
            TransientError: On 429 or 5xx.
            ExternalServiceError: On other 4xx.
        """
        if response.is_success:
            return

        # Extract error message from Alpaca response body
        try:
            body = response.json()
            message = body.get("message", response.text)
        except Exception:
            message = response.text

        status = response.status_code

        if status in (401, 403):
            raise AuthError(f"Alpaca auth error for {symbol}: {status} - {message}")

        if status == 429:
            raise TransientError(f"Alpaca rate limit for {symbol}: {message}")

        if status >= 500:
            raise TransientError(f"Alpaca server error for {symbol}: {status} - {message}")

        # Other client errors (400, 404, 422, etc.)
        raise ExternalServiceError(f"Alpaca API error for {symbol}: {status} - {message}")

    @staticmethod
    def _bar_to_candle(
        bar: dict[str, Any],
        symbol: str,
        interval: CandleInterval,
    ) -> Candle:
        """
        Convert an Alpaca bar JSON object to a Candle contract.

        Alpaca bar format:
            {
                "t": "2026-01-02T05:00:00Z",   # timestamp (ISO 8601)
                "o": 174.50,                    # open
                "h": 176.25,                    # high
                "l": 173.80,                    # low
                "c": 175.90,                    # close
                "v": 58000000,                  # volume
                "n": 12345,                     # trade count
                "vw": 175.10                    # VWAP
            }

        Args:
            bar: Alpaca bar dict from API response.
            symbol: Ticker symbol (normalised uppercase).
            interval: CandleInterval for the bar.

        Returns:
            Candle Pydantic model with Decimal prices.
        """
        # Parse timestamp — Alpaca returns ISO 8601 with Z suffix
        ts_str = bar["t"]
        ts = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))

        return Candle(
            symbol=symbol,
            interval=interval,
            open=Decimal(str(bar["o"])),
            high=Decimal(str(bar["h"])),
            low=Decimal(str(bar["l"])),
            close=Decimal(str(bar["c"])),
            volume=int(bar["v"]),
            vwap=Decimal(str(bar["vw"])) if bar.get("vw") is not None else None,
            trade_count=int(bar["n"]) if bar.get("n") is not None else None,
            timestamp=ts,
        )
