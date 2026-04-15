"""
Unit tests for indicator contracts (IndicatorInfo, IndicatorResult,
IndicatorRequest, IndicatorParam).

Validates Pydantic model construction, immutability, serialization,
and field constraints.

Naming convention: test_<unit>_<scenario>_<expected_outcome>
"""

from __future__ import annotations

from typing import Any

import numpy as np
import pytest
from pydantic import ValidationError

from libs.contracts.indicator import (
    IndicatorCalculator,
    IndicatorInfo,
    IndicatorParam,
    IndicatorRequest,
    IndicatorResult,
)

# ---------------------------------------------------------------------------
# IndicatorParam
# ---------------------------------------------------------------------------


class TestIndicatorParam:
    """Tests for IndicatorParam frozen model."""

    def test_param_construction_with_defaults(self) -> None:
        param = IndicatorParam(name="period", default=20)
        assert param.name == "period"
        assert param.default == 20
        assert param.min_value is None
        assert param.max_value is None
        assert param.param_type == "int"
        assert param.description == ""

    def test_param_construction_with_all_fields(self) -> None:
        param = IndicatorParam(
            name="std_dev",
            description="Standard deviation multiplier",
            default=2.0,
            min_value=0.1,
            max_value=5.0,
            param_type="float",
        )
        assert param.name == "std_dev"
        assert param.min_value == 0.1
        assert param.max_value == 5.0
        assert param.param_type == "float"

    def test_param_is_frozen(self) -> None:
        param = IndicatorParam(name="period", default=20)
        with pytest.raises(ValidationError):
            param.name = "other"  # type: ignore[misc]

    def test_param_empty_name_rejected(self) -> None:
        with pytest.raises(ValidationError):
            IndicatorParam(name="", default=20)


# ---------------------------------------------------------------------------
# IndicatorInfo
# ---------------------------------------------------------------------------


class TestIndicatorInfo:
    """Tests for IndicatorInfo frozen model."""

    def test_info_construction_minimal(self) -> None:
        info = IndicatorInfo(name="SMA")
        assert info.name == "SMA"
        assert info.description == ""
        assert info.category == ""
        assert info.output_names == ["value"]
        assert info.default_params == {}
        assert info.param_constraints == []

    def test_info_construction_full(self) -> None:
        info = IndicatorInfo(
            name="MACD",
            description="Moving Average Convergence Divergence",
            category="momentum",
            output_names=["macd_line", "signal_line", "histogram"],
            default_params={"fast_period": 12, "slow_period": 26, "signal_period": 9},
            param_constraints=[
                IndicatorParam(name="fast_period", default=12, min_value=2, max_value=100),
            ],
        )
        assert info.name == "MACD"
        assert len(info.output_names) == 3
        assert info.default_params["fast_period"] == 12
        assert len(info.param_constraints) == 1

    def test_info_is_frozen(self) -> None:
        info = IndicatorInfo(name="RSI")
        with pytest.raises(ValidationError):
            info.name = "OTHER"  # type: ignore[misc]

    def test_info_empty_name_rejected(self) -> None:
        with pytest.raises(ValidationError):
            IndicatorInfo(name="")

    def test_info_serialization_roundtrip(self) -> None:
        info = IndicatorInfo(
            name="EMA",
            description="Exponential Moving Average",
            category="trend",
            default_params={"period": 20},
        )
        data = info.model_dump()
        restored = IndicatorInfo.model_validate(data)
        assert restored.name == info.name
        assert restored.default_params == info.default_params


# ---------------------------------------------------------------------------
# IndicatorResult
# ---------------------------------------------------------------------------


class TestIndicatorResult:
    """Tests for IndicatorResult model."""

    def test_result_single_output(self) -> None:
        values = np.array([1.0, 2.0, 3.0])
        ts = np.array([100.0, 200.0, 300.0])
        result = IndicatorResult(
            indicator_name="SMA",
            values=values,
            timestamps=ts,
            metadata={"period": 20},
        )
        assert result.indicator_name == "SMA"
        assert result.is_multi_output is False
        np.testing.assert_array_equal(result.values, values)
        assert result.metadata["period"] == 20

    def test_result_multi_output(self) -> None:
        components = {
            "macd_line": np.array([0.1, 0.2]),
            "signal_line": np.array([0.05, 0.15]),
            "histogram": np.array([0.05, 0.05]),
        }
        result = IndicatorResult(
            indicator_name="MACD",
            components=components,
            timestamps=np.array([100.0, 200.0]),
        )
        assert result.is_multi_output is True
        assert result.values is None
        np.testing.assert_array_equal(result.get_component("macd_line"), components["macd_line"])

    def test_result_get_component_missing_raises_key_error(self) -> None:
        result = IndicatorResult(
            indicator_name="MACD",
            components={"macd_line": np.array([1.0])},
        )
        with pytest.raises(KeyError, match="signal_line"):
            result.get_component("signal_line")

    def test_result_empty_name_rejected(self) -> None:
        with pytest.raises(ValidationError):
            IndicatorResult(indicator_name="")


# ---------------------------------------------------------------------------
# IndicatorRequest
# ---------------------------------------------------------------------------


class TestIndicatorRequest:
    """Tests for IndicatorRequest frozen model."""

    def test_request_construction(self) -> None:
        req = IndicatorRequest(indicator_name="SMA", params={"period": 20})
        assert req.indicator_name == "SMA"
        assert req.params["period"] == 20

    def test_request_default_params(self) -> None:
        req = IndicatorRequest(indicator_name="RSI")
        assert req.params == {}

    def test_request_is_frozen(self) -> None:
        req = IndicatorRequest(indicator_name="SMA")
        with pytest.raises(ValidationError):
            req.indicator_name = "OTHER"  # type: ignore[misc]

    def test_request_empty_name_rejected(self) -> None:
        with pytest.raises(ValidationError):
            IndicatorRequest(indicator_name="")


# ---------------------------------------------------------------------------
# IndicatorCalculator protocol
# ---------------------------------------------------------------------------


class TestIndicatorCalculatorProtocol:
    """Tests for IndicatorCalculator protocol conformance checking."""

    def test_conforming_class_is_instance(self) -> None:
        class GoodCalc:
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
                return close

            def info(self) -> IndicatorInfo:
                return IndicatorInfo(name="GOOD")

        assert isinstance(GoodCalc(), IndicatorCalculator)

    def test_non_conforming_class_not_instance(self) -> None:
        class BadCalc:
            pass

        assert not isinstance(BadCalc(), IndicatorCalculator)
