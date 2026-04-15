"""
Built-in signal strategies for the FXLab trading platform.

This package contains production-quality indicator-based signal strategies
that implement SignalStrategyInterface. Each strategy encapsulates a
specific trading approach and produces Signal objects when market
conditions meet its criteria.

Available strategies:
- MovingAverageCrossoverStrategy: SMA/EMA crossover signals.
- RSIMeanReversionStrategy: RSI oversold/overbought mean reversion.
- MACDMomentumStrategy: MACD histogram momentum signals.
- BollingerBandBreakoutStrategy: Bollinger Band breakout with volume.
- StochasticMomentumStrategy: Stochastic + RSI filter signals.
- CompositeSignalStrategy: Meta-strategy aggregating sub-strategies.

Also provides SignalStrategyRegistry for strategy discovery and dispatch.
"""
