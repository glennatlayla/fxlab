"""
Calendar indicators — month-relative business-day positioning.

Responsibilities:
- CalendarBusinessDayIndexCalculator: emit the 1-based business-day index
  of each bar's date within its month (first business day = 1).
- CalendarDaysToMonthEndCalculator: emit the count of remaining business
  days in the bar's month, where the bar's own date counts as day-of (so
  the value on the last business day of the month is 0).

Both indicators are backed by ``pandas_market_calendars`` so that the
notion of "business day" honours the configured exchange/session schedule.
The default schedule is the 24/5 FX session (Mon-Fri, no holidays), which
matches the convention used by FX_TurnOfMonth_USDSeasonality_D1.

Does NOT:
- Access databases, files, or external services beyond importing the
  ``pandas_market_calendars`` library.
- Manage registration into the global registry — registration is performed
  by ``libs.indicators`` package init or by the helper ``register`` below.
- Hold any mutable state between calls; computation is purely functional.

Dependencies:
- numpy: input/output array contract.
- pandas: timestamp conversion (transitive via pandas_market_calendars).
- pandas_market_calendars (external, not bundled in venv by default):
  imported lazily-friendly at module top; ``calculate`` raises a clear
  RuntimeError if the library is missing at call time.
- libs.contracts.indicator: IndicatorInfo, IndicatorParam.

Error conditions:
- RuntimeError: if ``pandas_market_calendars`` is not importable when
  ``calculate`` is invoked.
- ValueError: if the configured calendar name is unknown.

Example:
    from libs.indicators.calendar import (
        CalendarBusinessDayIndexCalculator,
        CalendarDaysToMonthEndCalculator,
    )

    bdi = CalendarBusinessDayIndexCalculator()
    indices = bdi.calculate(o, h, l, c, v, ts)  # 1-based per bar

    dme = CalendarDaysToMonthEndCalculator()
    remaining = dme.calculate(o, h, l, c, v, ts)
"""

from __future__ import annotations

from typing import Any

import numpy as np

from libs.contracts.indicator import IndicatorInfo, IndicatorParam

# pandas_market_calendars depends on pandas; both are imported together so a
# missing pandas install is treated identically to a missing mcal install.
# Calculators raise a clear RuntimeError at .calculate() time when either is
# absent; .info() and module import remain safe for registry introspection.
try:  # pragma: no cover - exercised only when the dependency is absent
    import pandas as pd
    import pandas_market_calendars as mcal

    _MCAL_IMPORT_ERROR: ImportError | None = None
except ImportError as exc:  # pragma: no cover - exercised at runtime
    pd = None
    mcal = None
    _MCAL_IMPORT_ERROR = exc


_DEFAULT_CALENDAR = "24/5"


def _ensure_mcal_available() -> None:
    """Raise a clear error if pandas_market_calendars is missing."""
    if mcal is None:
        raise RuntimeError(
            "pandas_market_calendars is required for calendar indicators "
            "(calendar_business_day_index, calendar_days_to_month_end). "
            "Install with `pip install 'pandas_market_calendars==4.*'` and pin "
            "the dependency in requirements.txt. "
            f"Original ImportError: {_MCAL_IMPORT_ERROR!r}"
        )


def _bar_dates(timestamps: np.ndarray) -> pd.DatetimeIndex:
    """
    Convert a 1-D float64 unix-epoch-seconds array to a UTC DatetimeIndex
    of midnight-aligned bar dates (calendar-day granularity).

    The strategy timeframe is 1d, so we anchor every bar to its UTC date.
    """
    ts = timestamps.astype(np.float64, copy=False) if timestamps.dtype != np.float64 else timestamps
    # Timestamps are unix epoch seconds (per IndicatorCalculator contract).
    dt = pd.to_datetime(ts, unit="s", utc=True)
    # Normalize to date — drop intra-day component so bar membership in a
    # business-day schedule is unambiguous.
    return pd.DatetimeIndex(dt).normalize()


def _month_business_days(
    calendar_name: str,
    year: int,
    month: int,
) -> pd.DatetimeIndex:
    """
    Return the sorted DatetimeIndex of business days for the given month
    under the named pandas_market_calendars schedule.

    The result is timezone-naive UTC-midnight (matching ``_bar_dates``).
    """
    _ensure_mcal_available()
    cal = mcal.get_calendar(calendar_name)

    # Compute month start / end as plain dates.
    start = pd.Timestamp(year=year, month=month, day=1)
    if month == 12:
        end = pd.Timestamp(year=year + 1, month=1, day=1) - pd.Timedelta(days=1)
    else:
        end = pd.Timestamp(year=year, month=month + 1, day=1) - pd.Timedelta(days=1)

    schedule = cal.schedule(start_date=start, end_date=end)
    # schedule.index is the set of session dates (timezone-aware UTC). Normalize
    # to midnight UTC to align with _bar_dates().
    sessions = pd.DatetimeIndex(schedule.index)
    sessions = sessions.tz_localize("UTC") if sessions.tz is None else sessions.tz_convert("UTC")
    return sessions.normalize()


class CalendarBusinessDayIndexCalculator:
    """
    1-based business-day index within the bar's calendar month.

    For each input bar timestamp, computes the position of the bar's date
    within the ordered sequence of business days for that month. The first
    business day yields 1, the second yields 2, and so on. Bars that fall
    on a non-business day (under the configured schedule) yield NaN.

    Responsibilities:
    - Map each bar's date to its month's business-day calendar.
    - Emit a numeric index (1..N) per bar.

    Does NOT:
    - Mutate input arrays.
    - Cache schedules across calls (calendars are recomputed per call;
      caller can wrap if hot-path performance matters).

    Dependencies:
    - pandas_market_calendars (resolved at module import time).

    Raises:
    - RuntimeError: if pandas_market_calendars is not installed.

    Example:
        calc = CalendarBusinessDayIndexCalculator()
        result = calc.calculate(o, h, l, c, v, timestamps, calendar="24/5")
        # result is a float64 ndarray, NaN where the bar is outside the
        # configured business calendar.
    """

    def calculate(
        self,
        open: np.ndarray,
        high: np.ndarray,
        low: np.ndarray,
        close: np.ndarray,
        volume: np.ndarray,
        timestamps: np.ndarray,
        **params: Any,
    ) -> np.ndarray:
        """
        Compute the 1-based business-day-of-month index for each bar.

        Args:
            timestamps: Unix epoch seconds (float64), one per bar. Other
                OHLCV arrays are accepted but unused — calendar indicators
                are time-only.
            **params: Optional ``calendar`` (str, default "24/5") naming
                a pandas_market_calendars schedule.

        Returns:
            np.ndarray (float64) of length ``len(timestamps)``. Each value
            is the 1-based index of the bar's date within its month's
            business-day sequence, or NaN if the bar is not a business day
            under the configured schedule.

        Raises:
            RuntimeError: If pandas_market_calendars is not installed.
            ValueError: If the calendar name is unknown.

        Example:
            calc = CalendarBusinessDayIndexCalculator()
            result = calc.calculate(o, h, l, c, v, ts)
        """
        _ensure_mcal_available()
        calendar_name = str(params.get("calendar", _DEFAULT_CALENDAR))
        n = len(timestamps)
        out = np.full(n, np.nan, dtype=np.float64)
        if n == 0:
            return out

        bar_dates = _bar_dates(timestamps)

        # Group bars by (year, month) so we only build each month's schedule
        # once. Build a per-month index map: date -> 1-based index.
        month_keys = list(zip(bar_dates.year, bar_dates.month, strict=True))
        unique_months = sorted(set(month_keys))

        for year, month in unique_months:
            sessions = _month_business_days(calendar_name, year, month)
            session_to_index: dict[pd.Timestamp, int] = {ts: i + 1 for i, ts in enumerate(sessions)}
            for i, (y, m) in enumerate(month_keys):
                if y != year or m != month:
                    continue
                bar_ts = bar_dates[i]
                if bar_ts in session_to_index:
                    out[i] = float(session_to_index[bar_ts])
                # else: leave NaN (bar fell outside the business calendar)

        return out

    def info(self) -> IndicatorInfo:
        """Return calendar_business_day_index metadata."""
        return IndicatorInfo(
            name="CALENDAR_BUSINESS_DAY_INDEX",
            description=(
                "1-based business-day index within the bar's calendar month "
                "(first business day = 1)."
            ),
            category="calendar",
            output_names=["value"],
            default_params={"calendar": _DEFAULT_CALENDAR},
            param_constraints=[
                IndicatorParam(
                    name="calendar",
                    description=("pandas_market_calendars schedule name (e.g. '24/5', 'NYSE')."),
                    default=_DEFAULT_CALENDAR,
                    param_type="str",
                ),
            ],
        )


class CalendarDaysToMonthEndCalculator:
    """
    Remaining business days in the bar's calendar month (today counts as 0).

    For each input bar timestamp, computes the number of business days that
    follow the bar's date within the same month under the configured
    schedule. The bar itself is not counted, so the value on the last
    business day of the month is 0; one business day earlier the value is
    1; and so on. Bars that fall on a non-business day yield NaN.

    Responsibilities:
    - Map each bar's date to its month's business-day calendar.
    - Emit (N - index) where N is the month's business-day count and index
      is the bar's 1-based position.

    Does NOT:
    - Span month boundaries (count is strictly within the bar's month).

    Dependencies:
    - pandas_market_calendars (resolved at module import time).

    Raises:
    - RuntimeError: if pandas_market_calendars is not installed.

    Example:
        calc = CalendarDaysToMonthEndCalculator()
        result = calc.calculate(o, h, l, c, v, ts)
        # result[i] == 0 on the last business day of month i.
    """

    def calculate(
        self,
        open: np.ndarray,
        high: np.ndarray,
        low: np.ndarray,
        close: np.ndarray,
        volume: np.ndarray,
        timestamps: np.ndarray,
        **params: Any,
    ) -> np.ndarray:
        """
        Compute remaining business days in the bar's month (today = 0).

        Args:
            timestamps: Unix epoch seconds (float64), one per bar.
            **params: Optional ``calendar`` (str, default "24/5").

        Returns:
            np.ndarray (float64) of length ``len(timestamps)``. Each value
            is the count of business days strictly after the bar's date
            within its calendar month, or NaN if the bar is not a business
            day under the configured schedule.

        Raises:
            RuntimeError: If pandas_market_calendars is not installed.
            ValueError: If the calendar name is unknown.

        Example:
            calc = CalendarDaysToMonthEndCalculator()
            result = calc.calculate(o, h, l, c, v, ts)
        """
        _ensure_mcal_available()
        calendar_name = str(params.get("calendar", _DEFAULT_CALENDAR))
        n = len(timestamps)
        out = np.full(n, np.nan, dtype=np.float64)
        if n == 0:
            return out

        bar_dates = _bar_dates(timestamps)
        month_keys = list(zip(bar_dates.year, bar_dates.month, strict=True))
        unique_months = sorted(set(month_keys))

        for year, month in unique_months:
            sessions = _month_business_days(calendar_name, year, month)
            total = len(sessions)
            session_to_index: dict[pd.Timestamp, int] = {ts: i + 1 for i, ts in enumerate(sessions)}
            for i, (y, m) in enumerate(month_keys):
                if y != year or m != month:
                    continue
                bar_ts = bar_dates[i]
                if bar_ts in session_to_index:
                    # remaining = total - position; last day → 0.
                    out[i] = float(total - session_to_index[bar_ts])

        return out

    def info(self) -> IndicatorInfo:
        """Return calendar_days_to_month_end metadata."""
        return IndicatorInfo(
            name="CALENDAR_DAYS_TO_MONTH_END",
            description=(
                "Remaining business days in the bar's calendar month "
                "(bar's own date counts as 0; last business day = 0)."
            ),
            category="calendar",
            output_names=["value"],
            default_params={"calendar": _DEFAULT_CALENDAR},
            param_constraints=[
                IndicatorParam(
                    name="calendar",
                    description=("pandas_market_calendars schedule name (e.g. '24/5', 'NYSE')."),
                    default=_DEFAULT_CALENDAR,
                    param_type="str",
                ),
            ],
        )


def register(registry: Any) -> None:
    """
    Register both calendar calculators on the supplied IndicatorRegistry.

    Wired by ``libs.indicators`` package init. Kept as a free function so
    the module can be imported (and unit-tested) without touching the
    global default registry.

    Registers:
    - CALENDAR_BUSINESS_DAY_INDEX → CalendarBusinessDayIndexCalculator
    - CALENDAR_DAYS_TO_MONTH_END  → CalendarDaysToMonthEndCalculator

    Args:
        registry: An object exposing ``register(name, calculator)``
            (e.g. ``IndicatorRegistry``).

    Example:
        from libs.indicators.registry import IndicatorRegistry
        from libs.indicators.calendar import register as register_calendar

        reg = IndicatorRegistry()
        register_calendar(reg)
    """
    registry.register(
        "CALENDAR_BUSINESS_DAY_INDEX",
        CalendarBusinessDayIndexCalculator(),
    )
    registry.register(
        "CALENDAR_DAYS_TO_MONTH_END",
        CalendarDaysToMonthEndCalculator(),
    )
