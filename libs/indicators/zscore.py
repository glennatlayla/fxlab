"""
Z-score indicator — standardised deviation of a value series from a
reference mean / std-deviation series.

Responsibilities:
- Compute element-wise ``(value - mean_source) / std_source`` over numpy
  arrays where ``mean_source`` and ``std_source`` are series produced by
  other indicators (e.g. Bollinger middle band and rolling stddev) and
  passed in as keyword arguments at calculate-time.
- Return ``np.nan`` at any position where ``std_source`` is zero, and emit
  a structured WARN log AT MOST ONCE per calculator instance to surface
  the degenerate-volatility condition without flooding the log stream.
- Register itself into ``libs.indicators.default_registry`` under the
  canonical name ``"ZSCORE"`` at module import time.

Does NOT:
- Compute the mean or stddev itself — those are responsibilities of the
  Bollinger / SMA / rolling-stddev calculators referenced by the IR's
  ``mean_source`` and ``std_source`` fields. The strategy resolver
  (M1.A2) wires the upstream indicator outputs into this calculator's
  ``mean_source`` / ``std_source`` kwargs.
- Validate that ``mean_source`` and ``std_source`` align with ``value``;
  the caller is responsible for passing equal-length aligned arrays.
- Persist any state across calculator instances (each instance is the
  unit of "log once" semantics; the registry holds a single instance).

Dependencies:
- numpy: vectorised arithmetic, NaN sentinels, division-by-zero handling.
- structlog: structured logging for the std==0 warning, consistent with
  the rest of the libs/ tree (see libs/contracts/base.py).
- libs.contracts.indicator: IndicatorInfo, IndicatorParam metadata types.
- libs.indicators.registry: default_registry to self-register at module
  bottom.

Error conditions:
- Returns NaN at positions where ``std_source`` is zero (numpy convention
  for division by zero) and where any of ``value``, ``mean_source``,
  ``std_source`` is NaN.
- Raises ValueError if ``value``, ``mean_source``, ``std_source`` are not
  all the same length — this is a caller bug, not a runtime data issue.

Example:
    calc = ZScoreCalculator()
    z = calc.calculate(
        open=o, high=h, low=l, close=c, volume=v, timestamps=t,
        value=close,
        mean_source=bb_mid_series,
        std_source=bb_std_series,
    )
"""

from __future__ import annotations

from typing import Any

import numpy as np
import structlog

from libs.contracts.indicator import IndicatorInfo, IndicatorParam

logger = structlog.get_logger(__name__)


class ZScoreCalculator:
    """
    Z-score — standardised distance of a series from an external mean.

    Computes ``(value - mean_source) / std_source`` element-wise. Both
    ``mean_source`` and ``std_source`` are pre-computed numpy arrays
    supplied via the ``calculate`` kwargs; the strategy resolver maps the
    IR's ``mean_source`` / ``std_source`` indicator-IDs to those arrays.

    Responsibilities:
    - Element-wise standardisation of an aligned numpy series.
    - One-time WARN log per instance when ``std_source`` contains zeros.

    Does NOT:
    - Compute the mean or the standard deviation itself.
    - Mutate the input arrays.

    Dependencies:
    - structlog logger ``libs.indicators.zscore`` for the std==0 warning.

    Error conditions:
    - Raises ``ValueError`` if input arrays have mismatched lengths.
    - Returns NaN at positions where ``std_source == 0`` or any input is
      NaN (numpy division-by-zero / NaN-propagation semantics).

    Example:
        calc = ZScoreCalculator()
        z = calc.calculate(
            open=o, high=h, low=l, close=c, volume=v, timestamps=t,
            value=close, mean_source=bb_mid, std_source=bb_std,
        )
    """

    def __init__(self) -> None:
        # Per-instance flag so the WARN log fires AT MOST ONCE for the
        # life of this calculator. The default registry holds a single
        # shared instance, so this gives one warning per process for the
        # entire ZSCORE indicator — exactly the spec.
        self._zero_std_warned: bool = False

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
        Compute z-score = (value - mean_source) / std_source element-wise.

        Args:
            open, high, low, close, volume, timestamps: standard OHLCV
                arrays — accepted for protocol conformance but not used
                directly. The actual inputs are passed via kwargs because
                the IR resolver wires upstream indicator outputs in.
            **params: must contain three same-length float64 numpy arrays:
                - ``value``: the series being standardised.
                - ``mean_source``: rolling-mean reference series.
                - ``std_source``: rolling-stddev reference series.

        Returns:
            np.ndarray of float64 z-scores aligned with ``value``. Any
            position where ``std_source == 0`` (or any input is NaN) is
            NaN in the output.

        Raises:
            ValueError: if ``value`` / ``mean_source`` / ``std_source``
                are missing from ``params`` or differ in length.

        Example:
            z = calc.calculate(
                open=o, high=h, low=l, close=c, volume=v, timestamps=t,
                value=close, mean_source=bb_mid, std_source=bb_std,
            )
        """
        try:
            value = np.asarray(params["value"], dtype=np.float64)
            mean_source = np.asarray(params["mean_source"], dtype=np.float64)
            std_source = np.asarray(params["std_source"], dtype=np.float64)
        except KeyError as exc:  # pragma: no cover - defensive; caller bug
            raise ValueError(
                f"ZScoreCalculator requires 'value', 'mean_source', and "
                f"'std_source' arrays in params; missing {exc.args[0]!r}"
            ) from exc

        if not (value.shape == mean_source.shape == std_source.shape):
            raise ValueError(
                f"ZScoreCalculator inputs must be the same shape; got "
                f"value={value.shape}, mean_source={mean_source.shape}, "
                f"std_source={std_source.shape}"
            )

        # Identify zero-std positions BEFORE the division so we can both
        # (a) substitute NaN deterministically, and (b) decide whether to
        # emit the one-time WARN. Use ``== 0.0`` rather than a tolerance
        # because the caller's stddev computation has its own numerical
        # contract and we should not silently mask a near-zero std as
        # zero (that is a separate decision for the caller to make).
        zero_mask = std_source == 0.0

        # Suppress numpy's "invalid value" / "divide by zero" warnings —
        # the NaN substitution below is the documented behaviour, not an
        # accidental floating-point issue.
        with np.errstate(divide="ignore", invalid="ignore"):
            result = (value - mean_source) / std_source

        # Force NaN at zero-std positions (covers both the +/- inf and
        # 0/0 = NaN cases produced by the division above).
        if zero_mask.any():
            result = np.where(zero_mask, np.nan, result)
            if not self._zero_std_warned:
                self._zero_std_warned = True
                logger.warning(
                    "ZScoreCalculator received std_source with zero values; "
                    "z-score is NaN at those positions",
                    operation="zscore_calculate",
                    component="ZScoreCalculator",
                    zero_count=int(zero_mask.sum()),
                    total=int(zero_mask.size),
                    result="partial",
                )

        return result

    def info(self) -> IndicatorInfo:
        """
        Return Z-score indicator metadata.

        Returns:
            IndicatorInfo describing the ZSCORE indicator. The
            ``param_constraints`` list documents that ``value``,
            ``mean_source``, and ``std_source`` are array-typed inputs —
            ``param_type='array'`` because there is no scalar default
            here; the IR resolver supplies the actual numpy arrays.
        """
        return IndicatorInfo(
            name="ZSCORE",
            description=(
                "Z-score — (value - mean_source) / std_source against "
                "external rolling-mean and rolling-stddev series"
            ),
            category="momentum",
            output_names=["value"],
            default_params={},
            param_constraints=[
                IndicatorParam(
                    name="value",
                    description="Series being standardised",
                    default=None,
                    param_type="array",
                ),
                IndicatorParam(
                    name="mean_source",
                    description="Rolling-mean reference series (e.g. bb_mid)",
                    default=None,
                    param_type="array",
                ),
                IndicatorParam(
                    name="std_source",
                    description="Rolling-stddev reference series (e.g. bb_std)",
                    default=None,
                    param_type="array",
                ),
            ],
        )


# ---------------------------------------------------------------------------
# Self-registration into the default registry
# ---------------------------------------------------------------------------
#
# This module-bottom registration only takes effect when the module is
# imported. ``libs/indicators/__init__.py`` does NOT currently import this
# module, so callers that need ZSCORE in the default_registry must either
# (a) ``import libs.indicators.zscore`` explicitly, or (b) the package
# ``__init__`` should be updated to import this module alongside the
# other built-ins. The latter is the conventional path; see the report
# accompanying this milestone.
from libs.indicators import default_registry  # noqa: E402  (intentional late import)

default_registry.register("ZSCORE", ZScoreCalculator())
