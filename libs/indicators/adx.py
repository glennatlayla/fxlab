"""
ADX indicator — Wilder's Average Directional Index.

Responsibilities:
- ADXCalculator: compute ADX, +DI, -DI using Wilder's smoothing recurrence.

Does NOT:
- Access databases, files, or external services.
- Manage registration of itself with any specific registry instance
  beyond the module-bottom default_registry registration.
- Hold any mutable state between calls.

Dependencies:
- numpy: all computation is vectorized where possible.
- libs.contracts.indicator: IndicatorInfo, IndicatorParam.
- libs.indicators.registry: default_registry is patched at module bottom
  via libs.indicators.__init__ wiring (the calculator class itself does
  not import the registry to avoid circular imports).

Error conditions:
- All outputs return NaN for positions with insufficient lookback.
- Division-by-zero in DI calculation produces NaN (Wilder convention).
- Output bounded [0, 100].

Example:
    calc = ADXCalculator()
    result = calc.calculate(o, h, l, c, v, t, length=14)
    # result is dict with "adx", "plus_di", "minus_di" keys
"""

from __future__ import annotations

from typing import Any

import numpy as np

from libs.contracts.indicator import IndicatorInfo, IndicatorParam


class ADXCalculator:
    """
    ADX — Average Directional Index (Wilder, 1978).

    Computes the strength of a trend (regardless of direction) along with
    the directional indicators +DI and -DI. ADX > 25 typically indicates
    a strong trend; ADX < 20 indicates a weak / non-trending market.

    Calculation chain (all using Wilder's smoothing, alpha = 1 / length):

        1. True Range (TR):
             TR = max(H - L, |H - prev_C|, |L - prev_C|)

        2. Directional Movement:
             up_move   = H[i] - H[i-1]
             down_move = L[i-1] - L[i]
             +DM = up_move   if up_move   > down_move and up_move   > 0 else 0
             -DM = down_move if down_move > up_move   and down_move > 0 else 0

        3. Wilder smoothing (length-period rolling sums):
             - Initial sum at index `length`: SUM of first `length` values
               (TR / +DM / -DM).
             - Subsequent: smoothed[i] = smoothed[i-1] - smoothed[i-1]/length + value[i]

        4. Directional Indicators (% form):
             +DI = 100 * smoothed_+DM / smoothed_TR
             -DI = 100 * smoothed_-DM / smoothed_TR
             (NaN when smoothed_TR == 0)

        5. DX:
             DX = 100 * |+DI - -DI| / (+DI + -DI)
             (NaN when (+DI + -DI) == 0)

        6. ADX = Wilder smoothing (SMA seed of length DX values, then
                 ADX[i] = (ADX[i-1] * (length - 1) + DX[i]) / length).

    Multi-output: returns dict with "adx", "plus_di", "minus_di".

    Warmup: the first `length` bars produce NaN +DI / -DI / DX; ADX
    requires an additional `length - 1` bars for its own SMA seed and
    one more recurrence step. Net first non-NaN ADX is at index
    `2 * length` (zero-based), matching standard reference implementations
    such as TA-Lib and pandas-ta.

    Example:
        calc = ADXCalculator()
        result = calc.calculate(o, h, l, c, v, t, length=14)
        adx_series = result["adx"]
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
    ) -> dict[str, np.ndarray]:
        """
        Compute Wilder ADX, +DI, -DI from OHLC arrays.

        Args:
            high: High prices (float64).
            low: Low prices (float64).
            close: Close prices (float64).
            **params: length (int, default 14).

        Returns:
            Dict with three np.ndarray outputs of the same length as
            the input close array:
              - "adx":      Average Directional Index (0-100).
              - "plus_di":  +DI line (0-100).
              - "minus_di": -DI line (0-100).
            All three arrays carry NaN for positions with insufficient
            lookback. Division-by-zero in the DI / DX steps yields NaN.
        """
        length: int = int(params.get("length", 14))
        n = len(close)

        adx = np.full(n, np.nan, dtype=np.float64)
        plus_di = np.full(n, np.nan, dtype=np.float64)
        minus_di = np.full(n, np.nan, dtype=np.float64)

        # Need enough bars for: 1 prev bar + length DM/TR sums + (length-1)
        # additional DX values to seed the ADX SMA.
        if length < 1 or n < 2 * length + 1:
            return {"adx": adx, "plus_di": plus_di, "minus_di": minus_di}

        # ------------------------------------------------------------------
        # Step 1 & 2: True Range and Directional Movement (per-bar values).
        # tr[0], plus_dm[0], minus_dm[0] are undefined (no prev bar) — left
        # as NaN; we begin accumulating from index 1.
        # ------------------------------------------------------------------
        tr = np.full(n, np.nan, dtype=np.float64)
        plus_dm = np.full(n, np.nan, dtype=np.float64)
        minus_dm = np.full(n, np.nan, dtype=np.float64)

        for i in range(1, n):
            hl = high[i] - low[i]
            hc = abs(high[i] - close[i - 1])
            lc = abs(low[i] - close[i - 1])
            tr[i] = max(hl, hc, lc)

            up_move = high[i] - high[i - 1]
            down_move = low[i - 1] - low[i]

            if up_move > down_move and up_move > 0.0:
                plus_dm[i] = up_move
            else:
                plus_dm[i] = 0.0

            if down_move > up_move and down_move > 0.0:
                minus_dm[i] = down_move
            else:
                minus_dm[i] = 0.0

        # ------------------------------------------------------------------
        # Step 3: Wilder-smoothed length-period sums of TR / +DM / -DM.
        # First sum at index `length` = sum of values[1..length].
        # Subsequent: smoothed[i] = smoothed[i-1] - smoothed[i-1]/length + value[i]
        # ------------------------------------------------------------------
        sm_tr = np.full(n, np.nan, dtype=np.float64)
        sm_plus_dm = np.full(n, np.nan, dtype=np.float64)
        sm_minus_dm = np.full(n, np.nan, dtype=np.float64)

        sm_tr[length] = float(np.sum(tr[1 : length + 1]))
        sm_plus_dm[length] = float(np.sum(plus_dm[1 : length + 1]))
        sm_minus_dm[length] = float(np.sum(minus_dm[1 : length + 1]))

        for i in range(length + 1, n):
            sm_tr[i] = sm_tr[i - 1] - (sm_tr[i - 1] / length) + tr[i]
            sm_plus_dm[i] = sm_plus_dm[i - 1] - (sm_plus_dm[i - 1] / length) + plus_dm[i]
            sm_minus_dm[i] = sm_minus_dm[i - 1] - (sm_minus_dm[i - 1] / length) + minus_dm[i]

        # ------------------------------------------------------------------
        # Step 4: +DI / -DI as percentages of smoothed TR.
        # Division-by-zero yields NaN (Wilder convention — undefined when
        # there has been no range over the smoothing window).
        # ------------------------------------------------------------------
        dx = np.full(n, np.nan, dtype=np.float64)
        for i in range(length, n):
            tr_smoothed = sm_tr[i]
            if tr_smoothed == 0.0 or not np.isfinite(tr_smoothed):
                continue  # leave plus_di / minus_di / dx as NaN
            pdi = 100.0 * sm_plus_dm[i] / tr_smoothed
            mdi = 100.0 * sm_minus_dm[i] / tr_smoothed
            plus_di[i] = pdi
            minus_di[i] = mdi

            denom = pdi + mdi
            if denom == 0.0:
                # No directional movement at all; DX is undefined.
                continue
            dx[i] = 100.0 * abs(pdi - mdi) / denom

        # ------------------------------------------------------------------
        # Step 6: ADX = Wilder smoothing of DX, seeded by SMA of the first
        # `length` valid DX values. First DX is at index `length`; the
        # seed therefore lands at index 2*length - 1 and incorporates DX
        # values from indices [length .. 2*length - 1].
        #
        # Then ADX[i] = (ADX[i-1] * (length - 1) + DX[i]) / length.
        # ------------------------------------------------------------------
        seed_start = length
        seed_end = 2 * length  # exclusive
        seed_window = dx[seed_start:seed_end]
        # If any DX in the seed window is NaN (degenerate input), the seed
        # is undefined and downstream ADX stays NaN until the next valid
        # window. For typical FX data this does not happen.
        if np.any(np.isnan(seed_window)):
            return {"adx": adx, "plus_di": plus_di, "minus_di": minus_di}

        seed_index = 2 * length - 1
        adx[seed_index] = float(np.mean(seed_window))

        for i in range(seed_index + 1, n):
            dx_i = dx[i]
            prev = adx[i - 1]
            if not np.isfinite(prev):
                # Recover from a NaN gap: re-seed when we again have
                # `length` consecutive valid DX values ending at i.
                window = dx[i - length + 1 : i + 1]
                if not np.any(np.isnan(window)):
                    adx[i] = float(np.mean(window))
                continue
            if not np.isfinite(dx_i):
                continue
            adx[i] = (prev * (length - 1) + dx_i) / length

        return {"adx": adx, "plus_di": plus_di, "minus_di": minus_di}

    def info(self) -> IndicatorInfo:
        """Return ADX metadata."""
        return IndicatorInfo(
            name="ADX",
            description="Average Directional Index — Wilder trend-strength oscillator (0-100)",
            category="momentum",
            output_names=["adx", "plus_di", "minus_di"],
            default_params={"length": 14},
            param_constraints=[
                IndicatorParam(
                    name="length",
                    default=14,
                    min_value=2,
                    max_value=200,
                    param_type="int",
                ),
            ],
        )


# ---------------------------------------------------------------------------
# Auto-registration into the package-level default registry.
#
# Imported lazily (inside the registration block) to avoid a circular import:
# libs.indicators.__init__ imports this module, and the registry singleton
# lives in libs.indicators.registry (no cycle), but the *default_registry*
# instance is constructed in libs.indicators.__init__ itself. We register
# against that shared instance only when it has already been built.
# ---------------------------------------------------------------------------

try:
    from libs.indicators import default_registry as _default_registry

    if not _default_registry.has("ADX"):
        _default_registry.register("ADX", ADXCalculator())
except ImportError:
    # libs.indicators.__init__ has not finished initialising yet
    # (this module is being imported during package init). The package
    # __init__ is responsible for registering ADXCalculator() in that
    # case — see the registration block at the bottom of
    # libs/indicators/__init__.py.
    pass
