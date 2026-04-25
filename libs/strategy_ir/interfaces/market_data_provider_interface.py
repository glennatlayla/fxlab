"""
Market-data provider port (M4.E2 swap point for the Oanda v20 adapter).

==============================================================================
M4.E2 SWAP POINT -- READ THIS BEFORE EXTENDING
==============================================================================

Track E milestone M4.E2 stands up the real Oanda v20 market-data
adapter. This module already publishes:

    *   The :class:`MarketDataProviderInterface` Protocol every
        adapter (mock, paper, live) satisfies.
    *   The :class:`OandaMarketDataProvider` placeholder, an abstract
        subclass that documents exactly what M4.E2 has to fill in
        and refuses to construct without a working v20 client.

When M4.E2 lands, the swap is mechanical:

    1.  Implement the three abstract methods
        (:meth:`fetch_bars`, :meth:`get_pip_size`, :meth:`supports`)
        on :class:`OandaMarketDataProvider` by delegating to the
        injected ``_oanda_client`` (the v20 SDK or a thin httpx
        wrapper, decided in the M4.E2 design note).
    2.  Wire the constructed provider into the data-pipeline service
        in place of any prior in-memory or vendor-X implementation.
    3.  No call site changes -- consumers depend on the Protocol.

Until M4.E2 ships, the live constructor refuses to build (raises
:class:`OandaCredsMissingError` at construction time when no client
is supplied) and the abstract methods cannot be inherited as-is. This
is deliberate: it keeps the file ready for the swap without leaving
any "silent stub" behaviour in production code paths -- the very
thing CLAUDE.md §0 forbids.

==============================================================================

Responsibilities:
    - Define :class:`MarketDataProviderInterface`, the Protocol every
      strategy-IR market-data adapter implements.
    - Define :class:`OandaMarketDataProvider`, the abstract M4.E2
      placeholder whose concrete methods will be filled in during
      that milestone.
    - Re-export :class:`OandaCredsMissingError` so call sites only
      need one import to handle "no Oanda creds available" failures.

Does NOT:
    - Implement any concrete provider. The mock implementation lives
      under :mod:`libs.strategy_ir.mocks.mock_market_data_provider`.
      The live Oanda implementation lives in this same file but its
      methods are abstract until M4.E2.
    - Make any HTTP call. The :class:`OandaMarketDataProvider`
      constructor accepts a pre-built ``_oanda_client`` so this
      module never imports an HTTP library.

Dependencies:
    - Pydantic v2-free: this module declares only Protocols and
      abstract base classes. The :class:`Candle` value object comes
      from :mod:`libs.contracts.market_data` (Pydantic v2 there,
      consumed here by reference only).
    - :mod:`libs.strategy_ir.oanda_creds` for the
      :class:`OandaCredsMissingError` re-export.

Example::

    from libs.strategy_ir.interfaces.market_data_provider_interface import (
        MarketDataProviderInterface,
    )

    def fetch_warmup(provider: MarketDataProviderInterface) -> list[Candle]:
        return provider.fetch_bars(
            symbol="EURUSD",
            timeframe="H1",
            start=warmup_start,
            end=warmup_end,
        )
"""

from __future__ import annotations

from abc import abstractmethod
from datetime import datetime
from decimal import Decimal
from typing import Any, Protocol, runtime_checkable

from libs.contracts.market_data import Candle
from libs.strategy_ir.oanda_creds import OandaCredsMissingError

# ---------------------------------------------------------------------------
# Protocol every market-data provider satisfies
# ---------------------------------------------------------------------------


@runtime_checkable
class MarketDataProviderInterface(Protocol):
    """
    Port for fetching historical candle bars from a market-data source.

    Implementations:
        - :class:`libs.strategy_ir.mocks.mock_market_data_provider.MockMarketDataProvider`
          (in-memory, deterministic; the canonical test double).
        - :class:`OandaMarketDataProvider` (abstract until M4.E2).

    Why a Protocol rather than an ABC:
        Strategy-IR consumers only need structural typing -- any
        object with the three methods below can be injected. This
        keeps the surface friendly for ad-hoc fakes used in higher-
        level integration tests.

    Methods:
        fetch_bars: Pull a closed-interval window of candles for one
            (symbol, timeframe).
        get_pip_size: Return the pip size as a Decimal for a single
            symbol (used by risk and slippage translators).
        supports: Quick boolean check -- does this provider know how
            to serve the given symbol?
    """

    def fetch_bars(
        self,
        *,
        symbol: str,
        timeframe: str,
        start: datetime,
        end: datetime,
    ) -> list[Candle]:
        """
        Fetch closed candles in ``[start, end]`` (UTC, inclusive).

        Args:
            symbol: Tradable instrument (e.g. ``"EURUSD"``).
            timeframe: Bar resolution as a string the provider
                understands (``"M1"``, ``"M5"``, ``"H1"``, ``"D"``...).
                The Protocol does not constrain the alphabet so adapters
                can map directly to vendor names; consumers should
                document their expected values.
            start: Inclusive start of the window, timezone-aware UTC.
            end: Inclusive end of the window, timezone-aware UTC.

        Returns:
            Candles ordered by ``timestamp`` ascending. Empty list when
            the vendor has no data in the window (NOT an error).
        """
        ...

    def get_pip_size(self, symbol: str) -> Decimal:
        """
        Return the pip size for ``symbol`` as a Decimal.

        Args:
            symbol: Tradable instrument.

        Returns:
            Pip size (``Decimal("0.0001")`` for most majors,
            ``Decimal("0.01")`` for JPY pairs).
        """
        ...

    def supports(self, symbol: str) -> bool:
        """
        Return whether this provider can serve ``symbol``.

        Args:
            symbol: Tradable instrument.

        Returns:
            ``True`` if the provider knows the symbol; ``False``
            otherwise. Callers use this to route requests to the
            appropriate adapter when more than one is registered.
        """
        ...


# ---------------------------------------------------------------------------
# M4.E2 placeholder -- abstract Oanda adapter
# ---------------------------------------------------------------------------


class OandaMarketDataProvider(MarketDataProviderInterface):
    """
    Abstract M4.E2 placeholder for the live Oanda v20 market-data adapter.

    Why this class exists today:
        The codebase needs a stable import path
        (``libs.strategy_ir.interfaces.market_data_provider_interface``)
        where higher-layer code can already type its dependencies
        against the eventual Oanda implementation. By landing the
        class as an abstract subclass that REFUSES to construct
        without a working ``_oanda_client``, we get the import
        ergonomics without ever exposing a half-implemented method
        in a production code path (CLAUDE.md §0 forbids
        :class:`NotImplementedError` placeholders).

    M4.E2 must:
        - Drop the ``abstractmethod`` decorator from
          :meth:`fetch_bars`, :meth:`get_pip_size`, :meth:`supports`
          and supply real implementations that delegate to
          ``self._oanda_client``.
        - Keep the constructor contract: refuse to build if no client
          is supplied. The :class:`OandaCredsMissingError` raised here
          is the same exception
          :func:`libs.strategy_ir.oanda_creds.load_oanda_creds_from_env`
          raises, so call sites only catch one type.

    Constructor:
        oanda_client: Pre-built v20 SDK client. The client itself is
            an M4.E2 dependency and is NOT imported by this module.
            Strict-typed as ``Any`` here so we do not pre-commit to a
            specific SDK shape.

    Raises:
        OandaCredsMissingError: At construction time if
            ``oanda_client`` is ``None`` or omitted.
    """

    def __init__(self, *, oanda_client: Any | None = None) -> None:
        if oanda_client is None:
            raise OandaCredsMissingError(
                "OandaMarketDataProvider requires a working _oanda_client "
                "constructed from valid OandaCreds. Until M4.E2 lands, this "
                "class is intentionally inert: the abstract methods will be "
                "filled in during that milestone. See the M4.E2 SWAP POINT "
                "banner in this module's docstring."
            )
        self._oanda_client = oanda_client

    @abstractmethod
    def fetch_bars(
        self,
        *,
        symbol: str,
        timeframe: str,
        start: datetime,
        end: datetime,
    ) -> list[Candle]:
        """M4.E2 fills this in by calling ``self._oanda_client``."""

    @abstractmethod
    def get_pip_size(self, symbol: str) -> Decimal:
        """M4.E2 fills this in using the Oanda v20 instruments endpoint."""

    @abstractmethod
    def supports(self, symbol: str) -> bool:
        """M4.E2 fills this in using a cached instruments list."""


__all__ = [
    "MarketDataProviderInterface",
    "OandaCredsMissingError",
    "OandaMarketDataProvider",
]
