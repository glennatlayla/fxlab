"""
Alpaca broker configuration model.

Responsibilities:
- Define the configuration schema for Alpaca API authentication.
- Validate base URL, API credentials presence, and API version.
- Provide factory methods for paper and live trading environments.

Does NOT:
- Store or manage secrets (that's the SecretProvider's job).
- Make API calls or validate credentials against Alpaca.
- Contain business logic.

Dependencies:
- pydantic: Validation and serialization.

Error conditions:
- ValidationError: Missing or invalid configuration fields.

Example:
    config = AlpacaConfig(
        api_key="AKXXXXXXXXXX",
        api_secret="xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx",
        base_url="https://paper-api.alpaca.markets",
    )
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, field_validator


class AlpacaConfig(BaseModel):
    """
    Pydantic configuration model for Alpaca Trading API v2.

    Attributes:
        api_key: Alpaca API key ID (e.g. "AKXXXXXXXXXX").
        api_secret: Alpaca API secret key.
        base_url: Alpaca API base URL. Defaults to paper trading.
            Paper: https://paper-api.alpaca.markets
            Live: https://api.alpaca.markets
        api_version: API version string. Default "v2".

    Example:
        config = AlpacaConfig(
            api_key="AKTEST123",
            api_secret="secret123",
            base_url="https://paper-api.alpaca.markets",
        )
        # config.orders_url == "https://paper-api.alpaca.markets/v2/orders"
    """

    model_config = ConfigDict(frozen=True)

    api_key: str = Field(
        ...,
        min_length=1,
        description="Alpaca API key ID",
    )
    api_secret: str = Field(
        ...,
        min_length=1,
        description="Alpaca API secret key",
    )
    base_url: str = Field(
        default="https://paper-api.alpaca.markets",
        description="Alpaca API base URL (paper or live)",
    )
    api_version: str = Field(
        default="v2",
        description="Alpaca API version",
    )
    data_feed: str = Field(
        default="iex",
        description="Market data feed: 'iex' (free) or 'sip' (paid)",
    )
    data_base_url: str = Field(
        default="https://data.alpaca.markets",
        description="Alpaca Market Data API base URL",
    )

    @field_validator("base_url", "data_base_url")
    @classmethod
    def _validate_base_url(cls, v: str) -> str:
        """Strip trailing slash from base URLs for consistent URL construction."""
        return v.rstrip("/")

    @property
    def orders_url(self) -> str:
        """Full URL for the orders endpoint."""
        return f"{self.base_url}/{self.api_version}/orders"

    @property
    def positions_url(self) -> str:
        """Full URL for the positions endpoint."""
        return f"{self.base_url}/{self.api_version}/positions"

    @property
    def account_url(self) -> str:
        """Full URL for the account endpoint."""
        return f"{self.base_url}/{self.api_version}/account"

    @property
    def clock_url(self) -> str:
        """Full URL for the market clock endpoint."""
        return f"{self.base_url}/{self.api_version}/clock"

    def bars_url(self, symbol: str) -> str:
        """
        Full URL for the historical bars endpoint for a specific symbol.

        Uses the Market Data API (data.alpaca.markets), not the trading API.

        Args:
            symbol: Ticker symbol (e.g. "AAPL").

        Returns:
            URL string for the bars endpoint.

        Example:
            config.bars_url("AAPL")
            # "https://data.alpaca.markets/v2/stocks/AAPL/bars"
        """
        return f"{self.data_base_url}/{self.api_version}/stocks/{symbol}/bars"

    @property
    def market_data_stream_url(self) -> str:
        """WebSocket URL for the Alpaca real-time market data stream."""
        return f"wss://stream.data.alpaca.markets/{self.api_version}/{self.data_feed}"

    @property
    def trade_updates_stream_url(self) -> str:
        """
        WebSocket URL for Alpaca trade/order update events.

        Paper: wss://paper-api.alpaca.markets/stream
        Live:  wss://api.alpaca.markets/stream
        """
        return f"wss://{self.base_url.split('://')[1]}/stream"

    @property
    def auth_headers(self) -> dict[str, str]:
        """HTTP headers for Alpaca API authentication."""
        return {
            "APCA-API-KEY-ID": self.api_key,
            "APCA-API-SECRET-KEY": self.api_secret,
        }

    @classmethod
    def paper(cls, *, api_key: str, api_secret: str) -> AlpacaConfig:
        """
        Create config for Alpaca paper trading.

        Args:
            api_key: Alpaca API key ID.
            api_secret: Alpaca API secret key.

        Returns:
            AlpacaConfig pointed at paper-api.alpaca.markets.

        Example:
            config = AlpacaConfig.paper(api_key="AK...", api_secret="...")
        """
        return cls(
            api_key=api_key,
            api_secret=api_secret,
            base_url="https://paper-api.alpaca.markets",
        )

    @classmethod
    def live(cls, *, api_key: str, api_secret: str) -> AlpacaConfig:
        """
        Create config for Alpaca live trading.

        Args:
            api_key: Alpaca API key ID.
            api_secret: Alpaca API secret key.

        Returns:
            AlpacaConfig pointed at api.alpaca.markets.

        Example:
            config = AlpacaConfig.live(api_key="AK...", api_secret="...")
        """
        return cls(
            api_key=api_key,
            api_secret=api_secret,
            base_url="https://api.alpaca.markets",
        )
