"""
Broker adapter port (M4.E5 swap point for the Oanda v20 broker adapter).

==============================================================================
M4.E5 SWAP POINT -- READ THIS BEFORE EXTENDING
==============================================================================

Track E milestone M4.E5 stands up the real Oanda v20 broker adapter
(order placement, cancellation, position queries, account state).
This module already publishes:

    *   The :class:`BrokerAdapterInterface` Protocol every adapter
        (mock, paper, live) satisfies.
    *   The :class:`OandaBrokerAdapter` placeholder, an abstract
        subclass that documents exactly what M4.E5 has to fill in
        and refuses to construct without a working v20 client.
    *   The narrow value objects (:class:`OrderRef`, :class:`Position`,
        :class:`AccountState`, :class:`OrderSide`, :class:`OrderType`)
        the IR layer needs to talk about orders without depending on
        the heavier :mod:`libs.contracts.execution` schemas (those
        carry execution-service-specific fields).

When M4.E5 lands, the swap is mechanical:

    1.  Implement the four abstract methods
        (:meth:`place_order`, :meth:`cancel_order`,
        :meth:`get_position`, :meth:`get_account_state`) on
        :class:`OandaBrokerAdapter` by delegating to the injected
        ``_oanda_client``.
    2.  Honour idempotency on ``client_extension_id`` -- Oanda's
        ``clientExtensions.id`` field is the natural carrier; the
        adapter MUST de-duplicate before calling the v20 API.
    3.  Wire the constructed adapter into the execution-service stack
        in place of any prior shadow / paper adapter.
    4.  No call site changes -- consumers depend on the Protocol.

Why a separate Protocol from
:class:`libs.contracts.interfaces.broker_adapter.BrokerAdapterInterface`:
    The contracts-level adapter carries execution-service plumbing
    (timeout configs, fill events, diagnostics, paper/live flag) that
    higher-layer execution code needs but the strategy-IR layer must
    not depend on. The IR layer needs only the four operations
    declared here. Keeping the surfaces separate is what lets us swap
    to Oanda without dragging the contracts-level surface into the
    IR module's import graph.

==============================================================================

Responsibilities:
    - Define the value objects the IR layer uses to talk about orders
      (:class:`OrderRef`, :class:`Position`, :class:`AccountState`,
      :class:`OrderSide`, :class:`OrderType`).
    - Define :class:`BrokerAdapterInterface`, the Protocol every
      strategy-IR broker adapter satisfies.
    - Define :class:`OandaBrokerAdapter`, the abstract M4.E5
      placeholder whose concrete methods will be filled in during
      that milestone.

Does NOT:
    - Implement any concrete adapter. The mock implementation lives
      under :mod:`libs.strategy_ir.mocks.mock_broker_adapter`. The
      live Oanda implementation lives in this same file but its
      methods are abstract until M4.E5.
    - Make any HTTP call. The :class:`OandaBrokerAdapter` constructor
      accepts a pre-built ``_oanda_client`` so this module never
      imports an HTTP library.

Dependencies:
    - Pydantic v2 (BaseModel, ConfigDict, Field) for the value
      objects.
    - :mod:`libs.strategy_ir.oanda_creds` for the
      :class:`OandaCredsMissingError` re-export.
    - Standard library only otherwise.

Example::

    from libs.strategy_ir.interfaces.broker_adapter_interface import (
        BrokerAdapterInterface,
        OrderSide,
        OrderType,
    )

    def fire(adapter: BrokerAdapterInterface, *, symbol: str) -> None:
        adapter.place_order(
            symbol=symbol,
            side=OrderSide.BUY,
            units=10_000,
            order_type=OrderType.MARKET,
            client_extension_id="run-42-bar-1234-leg-A",
        )
"""

from __future__ import annotations

from abc import abstractmethod
from decimal import Decimal
from enum import Enum
from typing import Any, Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict, Field

from libs.strategy_ir.oanda_creds import OandaCredsMissingError

# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class OrderSide(str, Enum):  # noqa: UP042 -- per project convention (see ruff config)
    """
    Direction of an order.

    Values are lowercase strings to keep parity with what the Oanda
    v20 API expects on the wire, so the M4.E5 adapter can pass the
    enum value through directly without translation.
    """

    BUY = "buy"
    SELL = "sell"


class OrderType(str, Enum):  # noqa: UP042 -- per project convention
    """
    Supported order types in the IR layer.

    Kept narrow on purpose: market and limit cover every IR-driven
    strategy in the M4 buildout. Stop / take-profit handling is
    represented as separate orders rather than embedded fields so the
    Protocol stays simple.
    """

    MARKET = "market"
    LIMIT = "limit"


# ---------------------------------------------------------------------------
# Value objects
# ---------------------------------------------------------------------------


class OrderRef(BaseModel):
    """
    Immutable reference returned by :meth:`BrokerAdapterInterface.place_order`.

    Attributes:
        broker_order_id: Identifier assigned by the broker on accept.
            For Oanda v20 this is the order's ``id`` field.
        client_extension_id: The idempotency key the caller supplied.
            Echoed back so audit trails can correlate.
        symbol: Tradable instrument the order targets.
        side: Buy / sell direction.
        units: Order size in instrument units (positive integer).

    Why frozen:
        The reference is a record of what was placed; mutating it
        after the fact would corrupt the audit trail.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    broker_order_id: str = Field(..., min_length=1)
    client_extension_id: str = Field(..., min_length=1)
    symbol: str = Field(..., min_length=1)
    side: OrderSide
    units: int = Field(..., gt=0)


class Position(BaseModel):
    """
    Immutable snapshot of a held position.

    Attributes:
        symbol: Tradable instrument.
        units: Net position size. Positive for long, negative for
            short, never zero (callers receive ``None`` from
            :meth:`BrokerAdapterInterface.get_position` when there is
            no position).
        average_price: Volume-weighted entry price as a Decimal.

    Why frozen:
        Snapshots are immutable observations; refresh by calling
        :meth:`BrokerAdapterInterface.get_position` again rather than
        mutating in place.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    symbol: str = Field(..., min_length=1)
    units: int = Field(...)
    average_price: Decimal = Field(..., ge=0)


class AccountState(BaseModel):
    """
    Immutable snapshot of the broker account balance / margin state.

    Attributes:
        account_id: Broker-side account identifier.
        balance: Cash balance in account currency.
        unrealized_pl: Mark-to-market open P&L in account currency.
        margin_used: Margin currently held against open positions.
        margin_available: Margin still free for new positions.
        currency: ISO currency code of the account (``"USD"``, etc.).

    Why frozen:
        Snapshots are immutable observations.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    account_id: str = Field(..., min_length=1)
    balance: Decimal = Field(...)
    unrealized_pl: Decimal = Field(...)
    margin_used: Decimal = Field(..., ge=0)
    margin_available: Decimal = Field(..., ge=0)
    currency: str = Field(..., min_length=3, max_length=3)


# ---------------------------------------------------------------------------
# Protocol every broker adapter satisfies
# ---------------------------------------------------------------------------


@runtime_checkable
class BrokerAdapterInterface(Protocol):
    """
    Port for placing and managing orders against a broker.

    Implementations:
        - :class:`libs.strategy_ir.mocks.mock_broker_adapter.MockBrokerAdapter`
          (in-memory, deterministic; the canonical test double).
        - :class:`OandaBrokerAdapter` (abstract until M4.E5).

    Idempotency contract:
        :meth:`place_order` MUST be idempotent on
        ``client_extension_id``. Calling it a second time with the
        same key (regardless of the other arguments) MUST return the
        :class:`OrderRef` from the first call without re-submitting.
        This is how the IR layer survives at-least-once delivery in
        any retry loop above it.

    Methods:
        place_order: Submit a new order; returns an :class:`OrderRef`.
        cancel_order: Best-effort cancellation by :class:`OrderRef`.
        get_position: Snapshot for one symbol, or ``None`` if flat.
        get_account_state: Snapshot of the broker account.
    """

    def place_order(
        self,
        symbol: str,
        side: OrderSide,
        units: int,
        *,
        order_type: OrderType,
        client_extension_id: str,
    ) -> OrderRef:
        """
        Submit an order to the broker.

        Args:
            symbol: Tradable instrument.
            side: Buy or sell.
            units: Positive integer order size in instrument units.
            order_type: Market or limit.
            client_extension_id: Caller-supplied idempotency key.
                Re-submitting with the same key returns the existing
                :class:`OrderRef`.

        Returns:
            The accepted :class:`OrderRef`.
        """
        ...

    def cancel_order(self, order_ref: OrderRef) -> None:
        """
        Cancel a previously-placed order.

        Args:
            order_ref: The reference returned by :meth:`place_order`.

        Returns:
            ``None`` on success. Cancellation of an already-terminal
            order is a no-op (NOT an error) so callers can issue
            cancels defensively without risking spurious failures.
        """
        ...

    def get_position(self, symbol: str) -> Position | None:
        """
        Return the current position for ``symbol`` or ``None`` when flat.

        Args:
            symbol: Tradable instrument.

        Returns:
            :class:`Position` snapshot or ``None``.
        """
        ...

    def get_account_state(self) -> AccountState:
        """
        Return the current account snapshot.

        Returns:
            :class:`AccountState` value object.
        """
        ...


# ---------------------------------------------------------------------------
# M4.E5 placeholder -- abstract Oanda broker adapter
# ---------------------------------------------------------------------------


class OandaBrokerAdapter(BrokerAdapterInterface):
    """
    Abstract M4.E5 placeholder for the live Oanda v20 broker adapter.

    Why this class exists today:
        The codebase needs a stable import path
        (``libs.strategy_ir.interfaces.broker_adapter_interface``)
        where higher-layer code can already type its dependencies
        against the eventual Oanda implementation. By landing the
        class as an abstract subclass that REFUSES to construct
        without a working ``_oanda_client``, we get the import
        ergonomics without ever exposing a half-implemented method
        in a production code path (CLAUDE.md §0 forbids
        :class:`NotImplementedError` placeholders).

    M4.E5 must:
        - Drop the ``abstractmethod`` decorator from the four order
          operations and supply real implementations that delegate to
          ``self._oanda_client``.
        - Honour idempotency on ``client_extension_id`` via Oanda's
          ``clientExtensions.id`` field.
        - Translate Oanda v20 error responses into the project-typed
          exceptions (TransientError on 5xx / timeout, AuthError on
          401/403, ValidationError on 4xx with a structured body).

    Constructor:
        oanda_client: Pre-built v20 SDK client. The client itself is
            an M4.E5 dependency and is NOT imported by this module.
            Strict-typed as ``Any`` here so we do not pre-commit to a
            specific SDK shape.

    Raises:
        OandaCredsMissingError: At construction time if
            ``oanda_client`` is ``None`` or omitted.
    """

    def __init__(self, *, oanda_client: Any | None = None) -> None:
        if oanda_client is None:
            raise OandaCredsMissingError(
                "OandaBrokerAdapter requires a working _oanda_client "
                "constructed from valid OandaCreds. Until M4.E5 lands, this "
                "class is intentionally inert: the abstract methods will be "
                "filled in during that milestone. See the M4.E5 SWAP POINT "
                "banner in this module's docstring."
            )
        self._oanda_client = oanda_client

    @abstractmethod
    def place_order(
        self,
        symbol: str,
        side: OrderSide,
        units: int,
        *,
        order_type: OrderType,
        client_extension_id: str,
    ) -> OrderRef:
        """M4.E5 fills this in by calling ``self._oanda_client``."""

    @abstractmethod
    def cancel_order(self, order_ref: OrderRef) -> None:
        """M4.E5 fills this in via the Oanda v20 cancel endpoint."""

    @abstractmethod
    def get_position(self, symbol: str) -> Position | None:
        """M4.E5 fills this in via the Oanda v20 positions endpoint."""

    @abstractmethod
    def get_account_state(self) -> AccountState:
        """M4.E5 fills this in via the Oanda v20 account endpoint."""


__all__ = [
    "AccountState",
    "BrokerAdapterInterface",
    "OandaBrokerAdapter",
    "OandaCredsMissingError",
    "OrderRef",
    "OrderSide",
    "OrderType",
    "Position",
]
