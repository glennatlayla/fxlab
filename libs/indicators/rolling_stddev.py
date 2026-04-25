"""
Rolling sample standard deviation indicator (M1.B4).

Responsibilities:
- Provide RollingStddevCalculator: a rolling-window sample stddev (ddof=1)
  computed on close prices, registered as ROLLING_STDDEV in the default
  registry.
- Match numpy/pandas sample-stddev semantics to within 1e-12 for the
  acceptance test.

Does NOT:
- Mutate or persist any state. The calculator is stateless and pure.
- Perform I/O. All inputs are numpy arrays passed by the caller.
- Re-implement BollingerBands or other compound volatility indicators —
  this is the elementary primitive used by FX_SingleAsset_MeanReversion_H1.

Dependencies:
- numpy: vectorised cumulative-sum computation.
- libs.contracts.indicator: IndicatorInfo, IndicatorParam (metadata model).
- libs.indicators.registry (deferred): module-bottom registration into
  default_registry. Imported at module bottom to avoid a circular import
  at package init time.

Error conditions:
- Returns an all-NaN array (without raising) when the input is shorter than
  ``length_bars`` or when ``length_bars`` < 2 — sample stddev is undefined
  with fewer than 2 samples (denominator N-1 would be 0).

Example:
    from libs.indicators.rolling_stddev import RollingStddevCalculator

    calc = RollingStddevCalculator()
    result = calc.calculate(o, h, l, c, v, t, length_bars=20)
    info = calc.get_info()
"""

from __future__ import annotations

from typing import Any

import numpy as np

from libs.contracts.indicator import IndicatorInfo, IndicatorParam


class RollingStddevCalculator:
    """
    Rolling sample standard deviation of close prices.

    ddof=1 (sample stddev) — chosen to match the convention used by
    ``numpy.std(..., ddof=1)``, ``pandas.Series(arr).rolling(N).std()``,
    and pandas-ta. The denominator is (N - 1) where N == ``length_bars``.

    Note: the in-tree ``BollingerBandsCalculator`` and
    ``StandardDeviationCalculator`` (in ``libs/indicators/volatility.py``)
    currently use population stddev (ddof=0). The M1.B4 workplan called
    for "matches BollingerBandsCalculator convention" but on inspection
    that convention diverges from numpy/pandas/pandas-ta. We follow the
    industry default (ddof=1) here so M1.B2 z-score (which references
    bb_std and is verified against numpy) stays consistent with the
    rest of the strategy execution stack. A future tranche can audit
    BollingerBandsCalculator's ddof=0 choice and either reconcile or
    document the asymmetry.

    The first ``length_bars - 1`` outputs are NaN (insufficient samples to
    compute a sample stddev with the full window). Thereafter every
    position holds the sample stddev of the trailing ``length_bars`` close
    prices.

    Multi-output: no — single ``np.ndarray`` of the same length as ``close``.

    Responsibilities:
    - Compute rolling sample stddev (ddof=1) over ``length_bars`` close prices.
    - Return an array aligned 1:1 with the input close array.

    Does NOT:
    - Mutate inputs.
    - Allocate any persistent state across calls.

    Example:
        calc = RollingStddevCalculator()
        std = calc.calculate(o, h, l, c, v, t, length_bars=20)
        # std[:19] are NaN; std[19:] are sample stddev of trailing 20 closes.
    """

    def calculate(
        self,
        open: np.ndarray,  # noqa: A002 — protocol-mandated parameter name
        high: np.ndarray,
        low: np.ndarray,
        close: np.ndarray,
        volume: np.ndarray,
        timestamps: np.ndarray,
        **params: Any,
    ) -> np.ndarray:
        """
        Compute rolling sample standard deviation of close prices.

        Args:
            close: Close prices (float64 array). Other OHLCV arrays accepted
                for protocol compliance but unused.
            **params: ``length_bars`` (int, default 20). Window size used as
                N in the (N - 1) denominator. Must be >= 2 for the result to
                be defined; smaller values yield an all-NaN array.

        Returns:
            np.ndarray of float64 with the same length as ``close``. The
            first ``length_bars - 1`` entries are NaN; subsequent entries
            hold the sample stddev (ddof=1) of the trailing ``length_bars``
            closes. If ``length_bars`` exceeds ``len(close)`` or is < 2 the
            entire output is NaN.

        Raises:
            (none) — invalid window sizes return all-NaN rather than raising,
            so a single bad parameter cannot abort a batch indicator
            computation.

        Example:
            calc = RollingStddevCalculator()
            std = calc.calculate(o, h, l, c, v, t, length_bars=3)
            # std[0] = NaN, std[1] = NaN, std[2] = sample-stddev of c[0..2], ...
        """
        length_bars: int = int(params.get("length_bars", 20))
        n = len(close)
        result = np.full(n, np.nan, dtype=np.float64)

        # Sample stddev requires N >= 2 (denominator N - 1 must be > 0).
        # If the series is shorter than the window, no full window exists.
        if length_bars < 2 or n < length_bars:
            return result

        # Numerical-stability note. The textbook one-pass formula
        # var = E[X^2] - E[X]^2 (cumulative-sum trick used by
        # BollingerBandsCalculator) suffers catastrophic cancellation when
        # the variance is small relative to the mean — exactly the FX
        # regime (closes ~ 1.10, deviations ~ 0.005). At length_bars=20 the
        # cancellation error reaches ~1e-12 of the price, blowing the
        # 1e-12 acceptance bar. We instead use the centred two-pass form
        # var = sum((x - mean)^2) / (N - 1) which is the accepted stable
        # algorithm and matches numpy.std(ddof=1) bit-for-bit on every
        # window we tested. Done vectorially via sliding_window_view so
        # cost stays modest for typical N (< ~200) without a Python loop.
        x = close.astype(np.float64, copy=False)
        windows = np.lib.stride_tricks.sliding_window_view(x, window_shape=length_bars)
        # windows.shape == (n - length_bars + 1, length_bars)

        # Per-window mean (axis=1) then per-window centred sum-of-squares.
        means = windows.mean(axis=1, keepdims=True)
        deviations = windows - means
        sum_sq = np.einsum("ij,ij->i", deviations, deviations)
        # Bessel-corrected sample variance — denominator N - 1.
        sample_var = sum_sq / (length_bars - 1)
        # Clamp tiny negative drift (cannot occur for centred form, but
        # cheap insurance against future refactors / weird inputs).
        sample_var = np.maximum(sample_var, 0.0)

        result[length_bars - 1 :] = np.sqrt(sample_var)
        return result

    def get_info(self) -> IndicatorInfo:
        """
        Return metadata describing this indicator.

        Returns:
            IndicatorInfo with name=ROLLING_STDDEV, single output "value",
            and a single parameter ``length_bars`` (default 20, range 2..5000).

        Example:
            info = RollingStddevCalculator().get_info()
            assert info.name == "ROLLING_STDDEV"
        """
        return IndicatorInfo(
            name="ROLLING_STDDEV",
            description=(
                "Rolling sample standard deviation (ddof=1) of close prices "
                "over length_bars window."
            ),
            category="volatility",
            output_names=["value"],
            default_params={"length_bars": 20},
            param_constraints=[
                IndicatorParam(
                    name="length_bars",
                    description=(
                        "Window size N. Sample stddev uses denominator N - 1 (Bessel's correction)."
                    ),
                    default=20,
                    min_value=2,
                    max_value=5000,
                    param_type="int",
                ),
            ],
        )

    # ------------------------------------------------------------------
    # IndicatorCalculator-protocol alias.
    #
    # The runtime-checked Protocol in libs.contracts.indicator requires an
    # ``info()`` method. The M1.B4 spec requires the public name to be
    # ``get_info()``. Keep both: ``get_info()`` is the canonical public API,
    # ``info()`` is a thin protocol-compatibility shim so this calculator
    # can be registered into IndicatorRegistry without further glue.
    # ------------------------------------------------------------------
    def info(self) -> IndicatorInfo:
        """Protocol-compatibility alias for ``get_info()``."""
        return self.get_info()


# ---------------------------------------------------------------------------
# Module-bottom registration into the default registry.
#
# Imported here (not at top of file) to avoid a circular import:
# ``libs.indicators.__init__`` imports concrete calculators to populate
# ``default_registry``, and that module is loaded before this one when
# the package is first imported. Deferring the import to module-execution
# end means by the time we touch ``default_registry`` the package init
# has finished (or, if this module is imported standalone, the init runs
# first as a side effect of ``from libs.indicators ...``).
# ---------------------------------------------------------------------------
from libs.indicators import default_registry  # noqa: E402

if not default_registry.has("ROLLING_STDDEV"):
    default_registry.register("ROLLING_STDDEV", RollingStddevCalculator())
