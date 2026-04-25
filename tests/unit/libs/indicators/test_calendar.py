"""
Unit tests for libs.indicators.calendar.

Coverage:
- calendar_business_day_index for March 2026 (March 1 is a Sunday; first
  business day is Monday March 2 → index 1). Validates indices for every
  day of the month against a hand-computed weekday-only calendar.
- calendar_days_to_month_end for April 2026 (last business day Apr 30 → 0).
- Year-end edge: December 31, 2026 across the year boundary into January
  2027 — the indicator behaves sensibly month-by-month and does not span
  months.
- info() metadata + register() helper wires both names onto a registry.
- Non-business days (Sat/Sun) yield NaN under the 24/5 schedule.

Skips cleanly when ``pandas_market_calendars`` is not installed in the
venv (per M1.B5 ground rules — the orchestrator pins the dependency in
requirements.txt; this test must not fail in its absence).
"""

from __future__ import annotations

import datetime as dt

import numpy as np
import pytest

mcal = pytest.importorskip("pandas_market_calendars")

from libs.indicators.calendar import (  # noqa: E402  (import after skip guard)
    CalendarBusinessDayIndexCalculator,
    CalendarDaysToMonthEndCalculator,
    register,
)
from libs.indicators.registry import IndicatorRegistry  # noqa: E402


def _ts_for_dates(dates: list[dt.date]) -> np.ndarray:
    """Convert calendar dates → unix-epoch-seconds float64 (UTC midnight)."""
    return np.array(
        [dt.datetime(d.year, d.month, d.day, tzinfo=dt.UTC).timestamp() for d in dates],
        dtype=np.float64,
    )


def _empty_ohlcv(n: int) -> dict[str, np.ndarray]:
    """Zero-filled OHLCV arrays — calendar indicators ignore prices."""
    z = np.zeros(n, dtype=np.float64)
    return {"open": z, "high": z, "low": z, "close": z, "volume": z}


def _hand_business_days(year: int, month: int) -> list[dt.date]:
    """Hand-computed Mon-Fri set for the given (year, month)."""
    days: list[dt.date] = []
    d = dt.date(year, month, 1)
    while d.month == month:
        if d.weekday() < 5:  # 0=Mon .. 4=Fri
            days.append(d)
        d += dt.timedelta(days=1)
    return days


# ---------------------------------------------------------------------------
# calendar_business_day_index — March 2026
# ---------------------------------------------------------------------------


def test_business_day_index_march_2026_full_month_matches_hand_calendar() -> None:
    """Every day Mar 1-31, 2026 yields the expected 1-based index or NaN."""
    march_dates = [dt.date(2026, 3, d) for d in range(1, 32)]
    ts = _ts_for_dates(march_dates)
    ohlcv = _empty_ohlcv(len(march_dates))

    calc = CalendarBusinessDayIndexCalculator()
    result = calc.calculate(timestamps=ts, **ohlcv)

    expected_business_days = _hand_business_days(2026, 3)
    bday_to_index = {d: i + 1 for i, d in enumerate(expected_business_days)}

    # March 1, 2026 is a Sunday → first business day is March 2 → index 1.
    assert dt.date(2026, 3, 1) not in bday_to_index
    assert bday_to_index[dt.date(2026, 3, 2)] == 1
    assert bday_to_index[dt.date(2026, 3, 31)] == 22  # 22 weekdays in Mar 2026

    for i, day in enumerate(march_dates):
        if day in bday_to_index:
            assert result[i] == float(bday_to_index[day]), (
                f"index mismatch on {day}: got {result[i]}, expected {bday_to_index[day]}"
            )
        else:
            assert np.isnan(result[i]), f"weekend day {day} should be NaN, got {result[i]}"


def test_business_day_index_weekends_are_nan() -> None:
    """Saturdays and Sundays under the 24/5 schedule yield NaN."""
    dates = [dt.date(2026, 3, 7), dt.date(2026, 3, 8)]  # Sat, Sun
    ts = _ts_for_dates(dates)
    ohlcv = _empty_ohlcv(len(dates))

    calc = CalendarBusinessDayIndexCalculator()
    result = calc.calculate(timestamps=ts, **ohlcv)

    assert np.isnan(result).all()


# ---------------------------------------------------------------------------
# calendar_days_to_month_end — April 2026
# ---------------------------------------------------------------------------


def test_days_to_month_end_april_2026_last_business_day_is_zero() -> None:
    """April 30, 2026 is a Thursday → last business day → remaining = 0."""
    april_dates = [dt.date(2026, 4, d) for d in range(1, 31)]
    ts = _ts_for_dates(april_dates)
    ohlcv = _empty_ohlcv(len(april_dates))

    calc = CalendarDaysToMonthEndCalculator()
    result = calc.calculate(timestamps=ts, **ohlcv)

    business_days = _hand_business_days(2026, 4)
    assert business_days[-1] == dt.date(2026, 4, 30)
    expected = {d: len(business_days) - (i + 1) for i, d in enumerate(business_days)}

    for i, day in enumerate(april_dates):
        if day in expected:
            assert result[i] == float(expected[day]), (
                f"days_to_month_end mismatch on {day}: got {result[i]}, expected {expected[day]}"
            )
        else:
            assert np.isnan(result[i])

    # Spot check the contract: last business day → 0; second-to-last → 1.
    last_idx = april_dates.index(dt.date(2026, 4, 30))
    assert result[last_idx] == 0.0
    second_last = business_days[-2]
    second_last_idx = april_dates.index(second_last)
    assert result[second_last_idx] == 1.0


def test_days_to_month_end_first_business_day_april_2026_equals_count_minus_one() -> None:
    """April 1, 2026 is a Wednesday → first business day → remaining = N-1."""
    business_days = _hand_business_days(2026, 4)
    assert business_days[0] == dt.date(2026, 4, 1)
    expected_remaining = len(business_days) - 1  # 22 - 1 = 21

    ts = _ts_for_dates([dt.date(2026, 4, 1)])
    ohlcv = _empty_ohlcv(1)
    calc = CalendarDaysToMonthEndCalculator()
    result = calc.calculate(timestamps=ts, **ohlcv)
    assert result[0] == float(expected_remaining)


# ---------------------------------------------------------------------------
# Year-end edge — December 2026 → January 2027
# ---------------------------------------------------------------------------


def test_year_end_edge_dec_31_2026_is_last_business_day_of_december() -> None:
    """Dec 31, 2026 is a Thursday → last business day of December → both
    indicators take their boundary values; counting does not leak into
    January 2027."""
    dec_business = _hand_business_days(2026, 12)
    jan_business = _hand_business_days(2027, 1)

    assert dec_business[-1] == dt.date(2026, 12, 31)
    # 23 weekdays in Dec 2026 (Tue Dec 1 → Thu Dec 31).
    assert len(dec_business) == 23
    assert jan_business[0] == dt.date(2027, 1, 1)

    dates = [
        dt.date(2026, 12, 30),  # Wed — second-to-last Dec business day
        dt.date(2026, 12, 31),  # Thu — last Dec business day
        dt.date(2027, 1, 1),  # Fri — first Jan business day
        dt.date(2027, 1, 2),  # Sat — non-business
        dt.date(2027, 1, 4),  # Mon — second Jan business day
    ]
    ts = _ts_for_dates(dates)
    ohlcv = _empty_ohlcv(len(dates))

    bdi = CalendarBusinessDayIndexCalculator().calculate(timestamps=ts, **ohlcv)
    dme = CalendarDaysToMonthEndCalculator().calculate(timestamps=ts, **ohlcv)

    # Business-day indices reset at the month boundary.
    assert bdi[0] == float(len(dec_business) - 1)  # Dec 30 = 22nd of 23
    assert bdi[1] == float(len(dec_business))  # Dec 31 = 23rd / last
    assert bdi[2] == 1.0  # Jan 1, 2027 = first Jan business day
    assert np.isnan(bdi[3])  # Sat
    assert bdi[4] == 2.0  # Jan 4 = second Jan business day

    # days_to_month_end resets at the month boundary too.
    assert dme[0] == 1.0  # Dec 30 → one Dec business day remains (Dec 31)
    assert dme[1] == 0.0  # Dec 31 → zero remaining in December
    assert dme[2] == float(len(jan_business) - 1)  # Jan 1 → N-1 in January
    assert np.isnan(dme[3])
    assert dme[4] == float(len(jan_business) - 2)  # Jan 4 → N-2 in January


# ---------------------------------------------------------------------------
# info() metadata + register() helper
# ---------------------------------------------------------------------------


def test_info_metadata_for_business_day_index() -> None:
    info = CalendarBusinessDayIndexCalculator().info()
    assert info.name == "CALENDAR_BUSINESS_DAY_INDEX"
    assert info.category == "calendar"
    assert info.output_names == ["value"]
    assert info.default_params == {"calendar": "24/5"}


def test_info_metadata_for_days_to_month_end() -> None:
    info = CalendarDaysToMonthEndCalculator().info()
    assert info.name == "CALENDAR_DAYS_TO_MONTH_END"
    assert info.category == "calendar"
    assert info.output_names == ["value"]
    assert info.default_params == {"calendar": "24/5"}


def test_register_adds_both_calendars_to_registry() -> None:
    registry = IndicatorRegistry()
    register(registry)
    assert registry.has("CALENDAR_BUSINESS_DAY_INDEX")
    assert registry.has("CALENDAR_DAYS_TO_MONTH_END")
    # Sanity: the registered objects round-trip through the registry.
    bdi_calc = registry.get("CALENDAR_BUSINESS_DAY_INDEX")
    assert isinstance(bdi_calc, CalendarBusinessDayIndexCalculator)
    dme_calc = registry.get("CALENDAR_DAYS_TO_MONTH_END")
    assert isinstance(dme_calc, CalendarDaysToMonthEndCalculator)
