"""
Unit tests for market data Celery task configuration helpers.

Tests the symbol parsing, config building, and task orchestration logic
without requiring a Celery broker or database.

Naming convention: test_<unit>_<scenario>_<expected_outcome>
"""

from __future__ import annotations

import os
from unittest.mock import patch

import pytest

from libs.contracts.errors import ConfigError
from services.worker.tasks.market_data_tasks import (
    _DEFAULT_SYMBOLS,
    _get_alpaca_config,
    _get_symbols,
)

# ---------------------------------------------------------------------------
# _get_symbols tests
# ---------------------------------------------------------------------------


class TestGetSymbols:
    """Tests for _get_symbols environment variable parsing."""

    def test_returns_default_symbols_when_env_not_set(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            symbols = _get_symbols()
            assert symbols == list(_DEFAULT_SYMBOLS)

    def test_returns_default_when_env_empty(self) -> None:
        with patch.dict(os.environ, {"MARKET_DATA_SYMBOLS": ""}):
            symbols = _get_symbols()
            assert symbols == list(_DEFAULT_SYMBOLS)

    def test_parses_comma_separated_symbols(self) -> None:
        with patch.dict(os.environ, {"MARKET_DATA_SYMBOLS": "AAPL,SPY,QQQ"}):
            symbols = _get_symbols()
            assert symbols == ["AAPL", "SPY", "QQQ"]

    def test_strips_whitespace_and_uppercases(self) -> None:
        with patch.dict(os.environ, {"MARKET_DATA_SYMBOLS": " aapl , spy , qqq "}):
            symbols = _get_symbols()
            assert symbols == ["AAPL", "SPY", "QQQ"]

    def test_ignores_empty_entries(self) -> None:
        with patch.dict(os.environ, {"MARKET_DATA_SYMBOLS": "AAPL,,SPY,"}):
            symbols = _get_symbols()
            assert symbols == ["AAPL", "SPY"]


# ---------------------------------------------------------------------------
# _get_alpaca_config tests
# ---------------------------------------------------------------------------


class TestGetAlpacaConfig:
    """Tests for _get_alpaca_config environment variable parsing."""

    def test_builds_config_from_env_vars(self) -> None:
        with patch.dict(
            os.environ,
            {
                "ALPACA_DATA_API_KEY": "AKTEST123",
                "ALPACA_DATA_API_SECRET": "secret123",
            },
        ):
            config = _get_alpaca_config()
            assert config.api_key == "AKTEST123"
            assert config.api_secret == "secret123"
            assert config.data_base_url == "https://data.alpaca.markets"

    def test_custom_base_url(self) -> None:
        with patch.dict(
            os.environ,
            {
                "ALPACA_DATA_API_KEY": "AKTEST123",
                "ALPACA_DATA_API_SECRET": "secret123",
                "ALPACA_DATA_BASE_URL": "https://custom.alpaca.test",
            },
        ):
            config = _get_alpaca_config()
            assert config.data_base_url == "https://custom.alpaca.test"

    def test_raises_config_error_when_key_missing(self) -> None:
        with (
            patch.dict(os.environ, {"ALPACA_DATA_API_SECRET": "secret"}, clear=True),
            pytest.raises(ConfigError, match="ALPACA_DATA_API_KEY"),
        ):
            _get_alpaca_config()

    def test_raises_config_error_when_secret_missing(self) -> None:
        with (
            patch.dict(os.environ, {"ALPACA_DATA_API_KEY": "key"}, clear=True),
            pytest.raises(ConfigError, match="ALPACA_DATA_API_SECRET"),
        ):
            _get_alpaca_config()

    def test_raises_config_error_when_both_missing(self) -> None:
        with patch.dict(os.environ, {}, clear=True), pytest.raises(ConfigError):
            _get_alpaca_config()
