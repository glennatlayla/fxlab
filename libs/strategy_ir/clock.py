"""
Clock abstraction injected into the IR-compiled SignalStrategy.

Purpose:
    Give the compiled signal strategy a single, replaceable source of
    "what time is it for the bar I'm currently evaluating" so the
    compiler never reaches for ``datetime.now()``, ``time.time()`` or
    any other wall-clock primitive. Same IR + same bar stream MUST
    produce byte-identical signal events on every invocation; that
    guarantee is impossible if any code path on the evaluation route
    reads a wall clock.

Responsibilities:
    - Define the :class:`Clock` Protocol every clock implementation
      satisfies (``def now(self) -> datetime``).
    - Provide :class:`BarClock`, the canonical implementation used by
      the compiled IRStrategy: it returns the timestamp of the bar
      currently being evaluated. Calling ``set_bar(timestamp)``
      advances the clock; ``now()`` returns whatever was last set.
    - Provide :class:`FixedClock` for tests that need a static value.

Does NOT:
    - Read the system clock under any circumstance.
    - Manage timezones or do any conversion. Callers pass timezone-
      aware ``datetime`` objects in; ``now()`` returns them unchanged.
    - Persist anything; clocks are pure in-process objects.

Dependencies:
    - Standard library only (``datetime``, ``typing``).

Raises:
    - :class:`RuntimeError`: if ``BarClock.now()`` is called before
      ``set_bar()`` has been called even once. Failing fast surfaces
      a wiring bug rather than returning a placeholder timestamp.

Example::

    from datetime import datetime, timezone
    from libs.strategy_ir.clock import BarClock

    clock = BarClock()
    clock.set_bar(datetime(2026, 4, 25, 14, 30, tzinfo=timezone.utc))
    assert clock.now().hour == 14
"""

from __future__ import annotations

from datetime import datetime
from typing import Protocol, runtime_checkable


@runtime_checkable
class Clock(Protocol):
    """
    Protocol every clock implementation must satisfy.

    Methods:
        now: return the current "wall" timestamp from this clock's
            perspective. The compiled IRStrategy never assumes the
            value reflects real wall-clock time -- it merely uses it
            to stamp ``Signal.generated_at``.
    """

    def now(self) -> datetime:
        """Return the current timestamp as observed by this clock."""
        ...


class BarClock:
    """
    Clock implementation that returns the timestamp of the bar
    currently being evaluated by the compiled strategy.

    Responsibilities:
    - Hold a single "current bar timestamp" value advanced by the
      strategy as it processes each bar.
    - Return that value on every ``now()`` call so signal stamping is
      a pure function of the input bar stream.

    Does NOT:
    - Reach for any wall-clock primitive. The whole point of this
      class is to keep ``datetime.now()`` and ``time.time()`` out of
      the compiled-strategy code path entirely.

    Dependencies:
    - Standard library only.

    Raises:
    - RuntimeError: when ``now()`` is called before ``set_bar()``.

    Example:
        clock = BarClock()
        clock.set_bar(candle.timestamp)
        signal_time = clock.now()
    """

    def __init__(self) -> None:
        """
        Initialise an unset BarClock.

        After construction, ``now()`` will raise until the first
        ``set_bar()`` call.
        """
        self._current: datetime | None = None

    def set_bar(self, timestamp: datetime) -> None:
        """
        Advance the clock to the supplied bar timestamp.

        Args:
            timestamp: the timestamp of the bar that the strategy is
                about to evaluate. Must be a timezone-aware
                ``datetime``; this class does not validate that, but
                downstream Signal validation will reject naive values.

        Example:
            clock.set_bar(candle.timestamp)
        """
        self._current = timestamp

    def now(self) -> datetime:
        """
        Return the timestamp of the bar currently being evaluated.

        Returns:
            The most recent value passed to :meth:`set_bar`.

        Raises:
            RuntimeError: if :meth:`set_bar` has not yet been called.

        Example:
            clock.set_bar(ts)
            assert clock.now() == ts
        """
        if self._current is None:
            raise RuntimeError(
                "BarClock.now() called before set_bar(); the compiled "
                "IRStrategy must call set_bar() with the current bar "
                "timestamp before evaluating any signal."
            )
        return self._current


class FixedClock:
    """
    Clock implementation that always returns a single fixed timestamp.

    Useful in tests where the bar timestamp does not need to advance
    or where a single deterministic stamp is desired across many calls.

    Responsibilities:
    - Hold one immutable timestamp.
    - Return that timestamp from every ``now()`` call.

    Does NOT:
    - Allow mutation. Construct a new FixedClock instead.

    Example:
        clock = FixedClock(datetime(2026, 1, 1, tzinfo=timezone.utc))
        assert clock.now() == datetime(2026, 1, 1, tzinfo=timezone.utc)
    """

    def __init__(self, value: datetime) -> None:
        """
        Initialise with the timestamp every ``now()`` call will return.

        Args:
            value: the timestamp to return on every call to
                :meth:`now`.
        """
        self._value = value

    def now(self) -> datetime:
        """
        Return the fixed timestamp this clock was constructed with.

        Returns:
            The constructor's ``value`` argument unchanged.

        Example:
            clock.now()  # always == constructor value
        """
        return self._value


__all__ = ["BarClock", "Clock", "FixedClock"]
