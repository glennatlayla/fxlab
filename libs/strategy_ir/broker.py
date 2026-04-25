"""
Broker abstraction injected into the IR-compiled SignalStrategy.

Purpose:
    Hold the (currently very small) interface the compiled
    :class:`IRStrategy` may consult about its broker at compile or
    evaluation time. The hard constraint from M1.A3 is that the
    compiler MUST NOT bake any FX-specific or broker-specific
    behaviour into the compiled strategy -- everything broker-shaped
    must come through this port.

Responsibilities:
    - Define the :class:`Broker` Protocol every broker implementation
      satisfies.
    - Provide :class:`NullBroker`, a deterministic no-op implementation
      used in tests and in any execution mode where the compiled
      strategy simply does not need broker-side knowledge (e.g. signal-
      stream-only verification, the M1.A3 acceptance test).

Does NOT:
    - Submit orders, query positions, or do any I/O. Order submission
      is the BacktestEngine's / live execution service's job; this
      port exists only so the compiled strategy can READ broker-
      provided constants (pip values, lot sizes, etc.) when it ever
      needs them. Today's compiler does not call any broker method,
      so :class:`NullBroker` is sufficient for every code path; the
      Protocol is published so future tranches can inject a richer
      implementation without changing the compiler signature.

Dependencies:
    - Standard library only.

Raises:
    - :class:`NotImplementedError` is intentionally NOT raised
      anywhere in this module; :class:`NullBroker` returns documented
      defaults so callers do not have to special-case its presence.

Example::

    from libs.strategy_ir.broker import NullBroker

    broker = NullBroker()
    pip_value = broker.get_pip_value("EURUSD")  # -> Decimal("0.0001")
"""

from __future__ import annotations

from decimal import Decimal
from typing import Protocol, runtime_checkable


@runtime_checkable
class Broker(Protocol):
    """
    Protocol every broker implementation injected into the compiled
    IRStrategy must satisfy.

    The interface is intentionally narrow: it covers ONLY the values
    the compiler / compiled strategy may need to read at compile time
    or per-bar evaluation time. Order submission lives elsewhere
    (see :mod:`libs.contracts.interfaces.broker_adapter`).

    Methods:
        get_pip_value: return the pip value for an FX symbol as a
            ``Decimal``. The compiled strategy uses this only when it
            has to convert a "spread <= 2 pips" leaf condition into a
            price-domain comparison.

    Example:
        class MyBroker:
            def get_pip_value(self, symbol: str) -> Decimal:
                return Decimal("0.0001")
    """

    def get_pip_value(self, symbol: str) -> Decimal:
        """Return the pip value for ``symbol`` as a Decimal."""
        ...


class NullBroker:
    """
    Deterministic no-op broker used in tests and any execution mode
    that needs no live broker interaction.

    Responsibilities:
    - Return documented constants for every method on the
      :class:`Broker` Protocol.

    Does NOT:
    - Do any I/O.
    - Reach for any global config, environment variable, or wall clock.
    - Hold any mutable state.

    Dependencies:
    - Standard library only.

    Example:
        broker = NullBroker()
        assert broker.get_pip_value("EURUSD") == Decimal("0.0001")
    """

    #: Default pip value for every symbol. JPY pairs would normally use
    #: ``0.01`` but the compiler today does not consume pip values, so
    #: we publish a single conservative default. Production deployments
    #: inject a richer broker that returns the correct per-symbol value.
    DEFAULT_PIP_VALUE: Decimal = Decimal("0.0001")

    def get_pip_value(self, symbol: str) -> Decimal:
        """
        Return :attr:`DEFAULT_PIP_VALUE` for every symbol.

        Args:
            symbol: ignored. Present so the signature satisfies the
                :class:`Broker` Protocol.

        Returns:
            ``Decimal("0.0001")``, the documented default.

        Example:
            NullBroker().get_pip_value("EURUSD")  # -> Decimal("0.0001")
        """
        # symbol is intentionally unused; the value is documented as a
        # constant so callers can see exactly what NullBroker returns.
        del symbol
        return self.DEFAULT_PIP_VALUE


__all__ = ["Broker", "NullBroker"]
