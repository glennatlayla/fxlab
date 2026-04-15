"""
Technical indicator library — registration and engine bootstrap.

Responsibilities:
- Create the default IndicatorRegistry instance.
- Auto-register all built-in indicators (trend, momentum, volatility, volume).
- Expose the default IndicatorEngine for convenient import.

Usage:
    from libs.indicators import default_engine, default_registry

    result = default_engine.compute("SMA", candles, period=20)
    available = default_registry.list_available()
"""

from libs.indicators.engine import IndicatorEngine
from libs.indicators.momentum import (
    CCICalculator,
    MACDCalculator,
    MOMCalculator,
    ROCCalculator,
    RSICalculator,
    StochasticCalculator,
    StochasticRSICalculator,
    WilliamsRCalculator,
)
from libs.indicators.registry import IndicatorRegistry
from libs.indicators.trend import (
    DEMACalculator,
    EMACalculator,
    SMACalculator,
    TEMACalculator,
    WMACalculator,
)
from libs.indicators.volatility import (
    ATRCalculator,
    BollingerBandsCalculator,
    DonchianChannelCalculator,
    HistoricalVolatilityCalculator,
    KeltnerCalculator,
    StandardDeviationCalculator,
)
from libs.indicators.volume import (
    ADLCalculator,
    CMFCalculator,
    MFICalculator,
    OBVCalculator,
    VWAPCalculator,
)

# ---------------------------------------------------------------------------
# Default registry — populated with all built-in indicators
# ---------------------------------------------------------------------------

default_registry = IndicatorRegistry()

# Trend indicators (M5)
default_registry.register("SMA", SMACalculator())
default_registry.register("EMA", EMACalculator())
default_registry.register("WMA", WMACalculator())
default_registry.register("DEMA", DEMACalculator())
default_registry.register("TEMA", TEMACalculator())

# Momentum indicators (M5)
default_registry.register("MACD", MACDCalculator())
default_registry.register("RSI", RSICalculator())
default_registry.register("STOCHASTIC", StochasticCalculator())
default_registry.register("STOCHASTIC_RSI", StochasticRSICalculator())
default_registry.register("ROC", ROCCalculator())
default_registry.register("MOM", MOMCalculator())
default_registry.register("WILLIAMS_R", WilliamsRCalculator())
default_registry.register("CCI", CCICalculator())

# Volatility indicators (M6)
default_registry.register("BOLLINGER_BANDS", BollingerBandsCalculator())
default_registry.register("ATR", ATRCalculator())
default_registry.register("KELTNER", KeltnerCalculator())
default_registry.register("DONCHIAN", DonchianChannelCalculator())
default_registry.register("STDDEV", StandardDeviationCalculator())
default_registry.register("HISTORICAL_VOLATILITY", HistoricalVolatilityCalculator())

# Volume indicators (M6)
default_registry.register("OBV", OBVCalculator())
default_registry.register("VWAP", VWAPCalculator())
default_registry.register("ADL", ADLCalculator())
default_registry.register("MFI", MFICalculator())
default_registry.register("CMF", CMFCalculator())

# ---------------------------------------------------------------------------
# Default engine — ready to use
# ---------------------------------------------------------------------------

default_engine = IndicatorEngine(default_registry)

__all__ = [
    "default_engine",
    "default_registry",
    "IndicatorEngine",
    "IndicatorRegistry",
]
