"""
Contracts for the technical indicator calculation engine.

Responsibilities:
- Define the IndicatorCalculator protocol that all indicator implementations
  must satisfy (compute from OHLCV numpy arrays to result arrays).
- Define IndicatorInfo metadata for registry introspection.
- Define IndicatorResult as the canonical output container.
- Define IndicatorRequest as the canonical input for batch computation.
- Define IndicatorParam for parameter validation and documentation.

Does NOT:
- Contain indicator computation logic (see libs/indicators/).
- Manage indicator registration (see libs/indicators/registry.py).
- Depend on any I/O, framework, or infrastructure code.

Dependencies:
- numpy: Array types for indicator input/output.
- pydantic: Frozen model validation.

Error conditions:
- ValidationError (via Pydantic): Invalid parameter values or types.

Example:
    from libs.contracts.indicator import IndicatorRequest, IndicatorResult

    request = IndicatorRequest(indicator_name="SMA", params={"period": 20})
    # Engine computes and returns:
    result = IndicatorResult(
        indicator_name="SMA",
        values=np.array([...]),
        timestamps=np.array([...]),
        metadata={"period": 20},
    )
"""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

import numpy as np
from pydantic import BaseModel, Field

# ---------------------------------------------------------------------------
# IndicatorCalculator protocol — all indicator implementations satisfy this
# ---------------------------------------------------------------------------


@runtime_checkable
class IndicatorCalculator(Protocol):
    """
    Protocol for a single indicator calculation function.

    Every indicator (SMA, EMA, MACD, RSI, etc.) implements this protocol.
    The engine dispatches to the appropriate calculator by name.

    The ``calculate`` method receives pre-extracted OHLCV numpy arrays so
    that the indicator does not need to know about the Candle model.

    Methods:
        calculate: Compute indicator values from OHLCV arrays.
        info: Return metadata about this indicator.
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
    ) -> np.ndarray | dict[str, np.ndarray]:
        """
        Compute indicator values from OHLCV numpy arrays.

        All arrays are 1-D float64 of equal length, ordered by ascending
        timestamp. Insufficient-lookback positions MUST be filled with NaN,
        never zero or error.

        Args:
            open: Open prices (float64).
            high: High prices (float64).
            low: Low prices (float64).
            close: Close prices (float64).
            volume: Trade volumes (float64).
            timestamps: Unix epoch timestamps (float64).
            **params: Indicator-specific parameters (e.g. period=20).

        Returns:
            Single np.ndarray for scalar indicators (e.g. SMA), or a dict
            mapping component names to arrays for multi-output indicators
            (e.g. MACD → {"macd_line": ..., "signal_line": ..., "histogram": ...}).
        """
        ...

    def info(self) -> IndicatorInfo:
        """
        Return metadata about this indicator.

        Returns:
            IndicatorInfo with name, description, default params, and
            parameter constraints.
        """
        ...


# ---------------------------------------------------------------------------
# Parameter descriptor — documents and constrains indicator parameters
# ---------------------------------------------------------------------------


class IndicatorParam(BaseModel, frozen=True):
    """
    Descriptor for a single indicator parameter.

    Used in IndicatorInfo.param_constraints to document valid ranges
    and default values for each parameter an indicator accepts.

    Attributes:
        name: Parameter name (must match the kwarg name in calculate()).
        description: Human-readable description of the parameter.
        default: Default value if not provided by caller.
        min_value: Minimum allowed value (inclusive), or None for no lower bound.
        max_value: Maximum allowed value (inclusive), or None for no upper bound.
        param_type: Python type name ("int", "float", "str").
    """

    name: str = Field(..., min_length=1, description="Parameter name")
    description: str = Field(default="", description="Human-readable description")
    default: Any = Field(..., description="Default value")
    min_value: float | None = Field(default=None, description="Minimum allowed value")
    max_value: float | None = Field(default=None, description="Maximum allowed value")
    param_type: str = Field(default="int", description="Python type name")


# ---------------------------------------------------------------------------
# IndicatorInfo — registry metadata for introspection
# ---------------------------------------------------------------------------


class IndicatorInfo(BaseModel, frozen=True):
    """
    Metadata for a registered indicator.

    Returned by ``IndicatorRegistry.list_available()`` and by each
    calculator's ``info()`` method. Provides enough information for
    API consumers to discover available indicators and their parameters.

    Attributes:
        name: Canonical uppercase name (e.g. "SMA", "MACD").
        description: One-line summary of what the indicator computes.
        category: Indicator category ("trend", "momentum", "volatility", "volume").
        output_names: Names of output arrays. Single-output indicators use
            ["value"]; multi-output use descriptive names (e.g. ["macd_line", ...]).
        default_params: Default parameter values as a dict.
        param_constraints: List of IndicatorParam descriptors.
    """

    name: str = Field(..., min_length=1, description="Canonical indicator name")
    description: str = Field(default="", description="One-line summary")
    category: str = Field(default="", description="Category: trend, momentum, volatility, volume")
    output_names: list[str] = Field(
        default_factory=lambda: ["value"],
        description="Output array names",
    )
    default_params: dict[str, Any] = Field(
        default_factory=dict,
        description="Default parameter values",
    )
    param_constraints: list[IndicatorParam] = Field(
        default_factory=list,
        description="Parameter validation constraints",
    )


# ---------------------------------------------------------------------------
# IndicatorResult — canonical output container
# ---------------------------------------------------------------------------


class IndicatorResult(BaseModel):
    """
    Result of an indicator computation.

    Wraps the raw numpy output with metadata for serialization, charting,
    and further computation. Mutable (not frozen) because numpy arrays
    cannot be hashed and Pydantic frozen models require hashable fields.

    Attributes:
        indicator_name: Name of the indicator that produced this result.
        values: Primary output array (for single-output indicators).
        components: Named output arrays (for multi-output indicators like MACD).
        timestamps: Aligned timestamp array (Unix epoch float64).
        metadata: Arbitrary metadata (parameters used, computation time, etc.).

    Example:
        result = IndicatorResult(
            indicator_name="SMA",
            values=np.array([NaN, NaN, 175.5, 176.2]),
            timestamps=np.array([1704067200, 1704153600, 1704240000, 1704326400]),
            metadata={"period": 20},
        )
    """

    indicator_name: str = Field(..., min_length=1)
    values: Any = Field(default=None, description="Primary output array (np.ndarray)")
    components: dict[str, Any] = Field(
        default_factory=dict,
        description="Named output arrays for multi-output indicators",
    )
    timestamps: Any = Field(default=None, description="Aligned timestamp array (np.ndarray)")
    metadata: dict[str, Any] = Field(
        default_factory=dict,
        description="Computation metadata (params, timing, etc.)",
    )

    model_config = {"arbitrary_types_allowed": True}

    @property
    def is_multi_output(self) -> bool:
        """True if this result has named components (multi-output indicator)."""
        return len(self.components) > 0

    def get_component(self, name: str) -> np.ndarray:
        """
        Retrieve a named component array.

        Args:
            name: Component name (e.g. "macd_line", "signal_line").

        Returns:
            The numpy array for the named component.

        Raises:
            KeyError: If the component name is not present.
        """
        if name not in self.components:
            available = list(self.components.keys())
            raise KeyError(
                f"Component '{name}' not found in {self.indicator_name} result. "
                f"Available: {available}"
            )
        return self.components[name]


# ---------------------------------------------------------------------------
# IndicatorRequest — batch computation input
# ---------------------------------------------------------------------------


class IndicatorRequest(BaseModel, frozen=True):
    """
    Request for a single indicator computation within a batch.

    Used by ``IndicatorEngine.compute_batch()`` to specify which indicators
    to compute and with what parameters in a single pass over the candle data.

    Attributes:
        indicator_name: Canonical indicator name (e.g. "SMA", "MACD").
        params: Indicator-specific parameters (e.g. {"period": 20}).

    Example:
        requests = [
            IndicatorRequest(indicator_name="SMA", params={"period": 20}),
            IndicatorRequest(indicator_name="RSI", params={"period": 14}),
        ]
    """

    indicator_name: str = Field(..., min_length=1)
    params: dict[str, Any] = Field(default_factory=dict)
