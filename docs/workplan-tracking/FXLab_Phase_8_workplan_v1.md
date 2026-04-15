# FXLab Phase 8 — Signal-to-Execution Pipeline, Advanced Backtesting & Portfolio Orchestration

**Version:** 1.0
**Created:** 2026-04-13
**Status:** ACTIVE

---

```
MILESTONE INDEX
───────────────────────────────────────────────
Total milestones: 16
Tracks: Data Quality, Signal Framework, Strategy Execution Engine, Advanced Backtesting, Portfolio & Multi-Strategy, Acceptance

Data Quality:               M0, M1, M2
Signal Framework:           M3, M4, M5
Strategy Execution Engine:  M6, M7, M8
Advanced Backtesting:       M9, M10, M11
Portfolio & Multi-Strategy: M12, M13, M14
Acceptance:                 M15
───────────────────────────────────────────────
```

---

## Phase Overview

Phase 8 closes the gap between FXLab's market data + indicators (Phase 7) and its
broker execution infrastructure (Phases 4–6) by building:

1. **Data quality scoring and anomaly detection** — ensure the data feeding strategies
   is trustworthy before trading on it.
2. **Signal generation framework** — typed contracts and evaluation engine that convert
   indicator output into actionable trading signals.
3. **Strategy execution engine** — event-driven loop that processes market data bars,
   evaluates signals through risk gates, and submits orders via broker adapters.
4. **Advanced backtesting** — walk-forward analysis, parameter optimization, and
   Monte Carlo simulation using the signal framework and real indicators.
5. **Portfolio orchestration** — multi-strategy allocation, rebalancing, and
   cross-strategy risk aggregation.

### Dependency Map

```
Phase 7 (Indicators, Market Data, Risk Analytics)
    │
    ├── Track A: Data Quality (M0–M2) ──────────────────────────┐
    │                                                             │
    ├── Track B: Signal Framework (M3–M5) ───────────────────────┤
    │       │                                                     │
    │       ├── Track C: Strategy Execution Engine (M6–M8) ──────┤
    │       │       │                                             │
    │       │       └── Track D: Advanced Backtesting (M9–M11) ──┤
    │       │                                                     │
    │       └── Track E: Portfolio & Multi-Strategy (M12–M14) ───┤
    │                                                             │
    └─────────────────────── M15: Acceptance Test Pack ──────────┘
```

### Existing Infrastructure Leveraged

| Component | Location | Phase |
|-----------|----------|-------|
| Candle, CandleInterval, MarketDataQuery | libs/contracts/market_data.py | P7 |
| MarketDataRepositoryInterface | libs/contracts/interfaces/market_data_repository.py | P7 |
| AlpacaBarStream (real-time) | services/worker/streams/alpaca_bar_stream.py | P7 |
| IndicatorEngine, IndicatorRegistry | libs/indicators/engine.py, registry.py | P7 |
| IndicatorResolverInterface | libs/contracts/interfaces/indicator_resolver.py | P7 |
| 24 indicators (SMA, EMA, RSI, MACD, BB, ATR, etc.) | libs/indicators/ | P7 |
| BrokerAdapterInterface | libs/contracts/interfaces/broker_adapter.py | P4 |
| OrderRequest, OrderResponse, PositionSnapshot | libs/contracts/execution.py | P4 |
| PaperBrokerAdapter | libs/broker/paper_broker_adapter.py | P4 |
| AlpacaBrokerAdapter | services/worker/brokers/alpaca_broker_adapter.py | P5 |
| DeploymentState, DeploymentService | libs/contracts/deployment.py | P4 |
| RiskGateInterface | libs/contracts/interfaces/risk_gate_interface.py | P4 |
| RiskAnalyticsService (VaR, correlation) | services/api/services/risk_analytics_service.py | P7 |
| PositionSizingService | services/api/services/position_sizing_service.py | P7 |
| KillSwitchService | services/api/services/kill_switch_service.py | P5 |
| ReconciliationService | services/api/services/reconciliation_service.py | P5 |
| BacktestConfig, BacktestResult | libs/contracts/backtest.py | P7 |
| IndicatorResolver | services/worker/research/indicator_resolver.py | P7 |

---

## Track A: Data Quality & Monitoring

### M0 — Data Quality Contracts, Interfaces & Storage Schema

**Objective:** Define the domain language for data quality — how quality is measured,
what anomalies look like, and where quality scores are persisted.

**Contracts (libs/contracts/data_quality.py):**

```python
class DataQualityDimension(str, Enum):
    COMPLETENESS = "completeness"    # % of expected bars present
    TIMELINESS = "timeliness"        # latency from expected arrival
    CONSISTENCY = "consistency"      # cross-source agreement
    ACCURACY = "accuracy"            # OHLCV relationship validity
    VOLUME_PROFILE = "volume_profile"  # volume vs. historical norms

class AnomalyType(str, Enum):
    MISSING_BAR = "missing_bar"
    STALE_DATA = "stale_data"
    OHLCV_VIOLATION = "ohlcv_violation"  # e.g., high < low
    PRICE_SPIKE = "price_spike"          # % move exceeds threshold
    VOLUME_ANOMALY = "volume_anomaly"    # deviation from rolling mean
    TIMESTAMP_GAP = "timestamp_gap"
    DUPLICATE_BAR = "duplicate_bar"

class AnomalySeverity(str, Enum):
    INFO = "info"
    WARNING = "warning"
    CRITICAL = "critical"

class DataAnomaly(BaseModel):
    anomaly_id: str
    symbol: str
    interval: CandleInterval
    anomaly_type: AnomalyType
    severity: AnomalySeverity
    detected_at: datetime
    bar_timestamp: datetime | None
    details: dict[str, Any]
    resolved: bool = False

class QualityScore(BaseModel):
    symbol: str
    interval: CandleInterval
    window_start: datetime
    window_end: datetime
    completeness: float    # 0.0–1.0
    timeliness: float      # 0.0–1.0
    consistency: float     # 0.0–1.0
    accuracy: float        # 0.0–1.0
    composite_score: float # weighted average
    anomaly_count: int
    grade: QualityGrade    # A/B/C/D/F

class QualityGrade(str, Enum):
    A = "A"  # >= 0.95
    B = "B"  # >= 0.85
    C = "C"  # >= 0.70
    D = "D"  # >= 0.50
    F = "F"  # < 0.50

class QualityPolicy(BaseModel):
    """Defines minimum quality thresholds per execution mode."""
    execution_mode: ExecutionMode
    min_composite_score: float
    min_completeness: float
    max_anomaly_severity: AnomalySeverity
    lookback_window_minutes: int
```

**Interfaces:**

```python
class DataQualityRepositoryInterface(ABC):
    def save_anomaly(self, anomaly: DataAnomaly) -> DataAnomaly
    def save_quality_score(self, score: QualityScore) -> QualityScore
    def find_anomalies(self, symbol: str, interval: CandleInterval,
                       since: datetime, severity: AnomalySeverity | None) -> list[DataAnomaly]
    def get_latest_score(self, symbol: str, interval: CandleInterval) -> QualityScore | None
    def get_score_history(self, symbol: str, interval: CandleInterval,
                          since: datetime) -> list[QualityScore]

class DataQualityServiceInterface(ABC):
    def evaluate_quality(self, symbol: str, interval: CandleInterval,
                         window_minutes: int) -> QualityScore
    def check_trading_readiness(self, symbols: list[str],
                                 execution_mode: ExecutionMode) -> QualityReadinessResult
    def detect_anomalies(self, candles: list[Candle]) -> list[DataAnomaly]
```

**Database schema:**
- `data_anomalies` table: id, symbol, interval, anomaly_type, severity, detected_at,
  bar_timestamp, details (JSON), resolved, resolved_at
- `quality_scores` table: id, symbol, interval, window_start, window_end,
  completeness, timeliness, consistency, accuracy, composite_score, grade,
  anomaly_count, scored_at

**Mock:** MockDataQualityRepository with full introspection.

**Tests:** Contract validation (20+), mock behavioral parity, schema round-trip.

---

### M1 — Data Quality Engine & Anomaly Detection

**Objective:** Implement the anomaly detection algorithms and quality scoring engine.

**DataQualityService (services/api/services/data_quality_service.py):**

- **Completeness scoring:** Count actual bars vs. expected bars (based on market
  calendar for the symbol's exchange). Weekend/holiday gaps are not anomalies.
- **OHLCV validation:** high >= max(open, close), low <= min(open, close),
  high >= low, volume >= 0. Violations are CRITICAL anomalies.
- **Price spike detection:** Bar-to-bar % change exceeds configurable threshold
  (default: 10% for equities, 5% for futures). Uses rolling 20-bar standard
  deviation for adaptive thresholds.
- **Volume anomaly detection:** Volume deviates > 3σ from rolling 50-bar mean.
  Zero volume during market hours is WARNING; negative volume is CRITICAL.
- **Timestamp gap detection:** Gap between consecutive bars exceeds 2× expected
  interval (accounting for market hours). Weekends and holidays excluded.
- **Duplicate detection:** Multiple bars with identical (symbol, interval, timestamp).
- **Timeliness scoring:** For real-time data, measures lag from expected arrival
  time using AlpacaBarStream diagnostics (last_data_age_seconds).
- **Composite scoring:** Weighted average with configurable weights
  (default: completeness=0.35, timeliness=0.20, consistency=0.20, accuracy=0.25).
- **Grade assignment:** A ≥ 0.95, B ≥ 0.85, C ≥ 0.70, D ≥ 0.50, F < 0.50.

**Trading readiness check:**
- Queries latest QualityScore for each requested symbol.
- Compares against QualityPolicy for the target execution_mode.
- Returns QualityReadinessResult with per-symbol pass/fail and blocking reasons.
- LIVE mode: minimum composite_score 0.90, completeness 0.95, no CRITICAL anomalies.
- PAPER mode: minimum composite_score 0.70, completeness 0.80.
- SHADOW mode: no minimum (monitoring only).

**SQL repository:** Alembic migration, upsert with ON CONFLICT, indexed queries
by (symbol, interval, scored_at).

**Tests:** 30+ unit tests covering each anomaly type, edge cases (empty candles,
single bar, market hours), scoring math, grade boundaries, readiness policy.

---

### M2 — Data Quality API, Dashboard & Alerting Integration

**Objective:** Expose data quality through REST endpoints and wire anomaly alerts
into the existing notification/incident infrastructure.

**Endpoints (services/api/routes/data_quality.py):**

```
GET  /data-quality/score/{symbol}         — Latest quality score
GET  /data-quality/score/{symbol}/history  — Score time series
GET  /data-quality/anomalies/{symbol}      — Anomaly list with filters
POST /data-quality/evaluate                — Trigger on-demand evaluation
GET  /data-quality/readiness               — Trading readiness check
GET  /data-quality/summary                 — Multi-symbol quality dashboard
```

**Alerting integration:**
- New notification triggers: DATA_QUALITY_DEGRADED, DATA_ANOMALY_CRITICAL.
- Wire into IncidentManager for PagerDuty/Slack dispatch.
- Quality score evaluation runs on a schedule (configurable, default: every 5 min
  for active symbols).

**Scope enforcement:** feeds:read for queries, operator:write for evaluate trigger.

**Tests:** 15+ route tests (auth, serialization, error paths), alerting dispatch.

---

## Track B: Signal Framework

### M3 — Signal Contracts & Evaluation Types

**Objective:** Define the typed contract layer for trading signals — what a signal is,
how it's produced, and how it flows through the system.

**Contracts (libs/contracts/signal.py):**

```python
class SignalDirection(str, Enum):
    LONG = "long"
    SHORT = "short"
    FLAT = "flat"       # exit all positions

class SignalStrength(str, Enum):
    STRONG = "strong"
    MODERATE = "moderate"
    WEAK = "weak"

class SignalType(str, Enum):
    ENTRY = "entry"
    EXIT = "exit"
    SCALE_IN = "scale_in"
    SCALE_OUT = "scale_out"
    STOP_ADJUSTMENT = "stop_adjustment"

class Signal(BaseModel):
    """Immutable trading signal produced by a signal strategy."""
    signal_id: str                   # ULID
    strategy_id: str                 # originating strategy
    deployment_id: str               # deployment context
    symbol: str
    direction: SignalDirection
    signal_type: SignalType
    strength: SignalStrength
    suggested_entry: Decimal | None
    suggested_stop: Decimal | None
    suggested_target: Decimal | None
    confidence: float                # 0.0–1.0
    indicators_used: dict[str, float]  # indicator name → value at signal time
    bar_timestamp: datetime          # the bar that triggered the signal
    generated_at: datetime
    metadata: dict[str, Any] = {}
    correlation_id: str

class SignalEvaluation(BaseModel):
    """Result of running a signal through risk gates."""
    signal: Signal
    approved: bool
    risk_gate_results: list[RiskGateResult]
    position_size: Decimal | None    # from PositionSizingService
    adjusted_stop: Decimal | None    # risk-adjusted stop
    rejection_reason: str | None
    evaluated_at: datetime

class RiskGateResult(BaseModel):
    gate_name: str
    passed: bool
    details: dict[str, Any]
```

**Signal strategy interface (libs/contracts/interfaces/signal_strategy.py):**

```python
class SignalStrategyInterface(ABC):
    @abstractmethod
    def evaluate(self, symbol: str, candles: list[Candle],
                 indicators: dict[str, IndicatorResult],
                 current_position: PositionSnapshot | None) -> Signal | None:
        """Evaluate market data and indicators, optionally produce a signal."""

    @abstractmethod
    def required_indicators(self) -> list[IndicatorRequest]:
        """Declare which indicators this strategy needs computed."""

    @property
    @abstractmethod
    def strategy_id(self) -> str: ...

    @property
    @abstractmethod
    def name(self) -> str: ...

    @property
    @abstractmethod
    def supported_symbols(self) -> list[str]: ...
```

**Signal repository interface:**

```python
class SignalRepositoryInterface(ABC):
    def save_signal(self, signal: Signal) -> Signal
    def save_evaluation(self, evaluation: SignalEvaluation) -> SignalEvaluation
    def find_signals(self, strategy_id: str, symbol: str | None,
                     since: datetime | None, limit: int) -> list[Signal]
    def find_evaluations(self, signal_id: str) -> list[SignalEvaluation]
    def get_signal_stats(self, strategy_id: str, since: datetime) -> SignalStats
```

**Database schema:**
- `signals` table: all Signal fields, indexed by (strategy_id, symbol, generated_at)
- `signal_evaluations` table: evaluation fields with FK to signals

**Tests:** 25+ contract validation tests, mock repository behavioral parity.

---

### M4 — Built-In Signal Strategies

**Objective:** Implement a library of production-quality indicator-based signal
strategies that serve as both useful strategies and reference implementations.

**Strategies (services/worker/strategies/):**

1. **MovingAverageCrossover** — SMA/EMA crossover with configurable fast/slow periods.
   LONG when fast crosses above slow, SHORT when fast crosses below.
   Strength based on spread between MAs as % of price.

2. **RSIMeanReversion** — LONG when RSI crosses above oversold threshold (30),
   SHORT when RSI crosses below overbought (70). Requires minimum RSI swing
   magnitude for STRONG signal.

3. **MACDMomentum** — LONG on MACD histogram turning positive with MACD above
   signal line, SHORT on negative turn. Strength from histogram magnitude.

4. **BollingerBandBreakout** — LONG on close above upper band with volume
   confirmation (> 1.5× 20-bar average). SHORT on close below lower band.
   FLAT when price returns inside bands.

5. **StochasticMomentum** — Combines Stochastic %K/%D crossover with RSI filter.
   LONG: %K crosses above %D below 20 AND RSI < 40. SHORT: inverse.

6. **CompositeSignal** — Meta-strategy that aggregates signals from multiple
   sub-strategies with weighted voting. Configurable quorum and minimum
   confidence. Demonstrates strategy composition pattern.

Each strategy:
- Implements SignalStrategyInterface
- Declares required_indicators() returning exact IndicatorRequest specs
- Has configurable parameters via constructor
- Is fully documented with docstrings per §7
- Has 10+ unit tests covering crossover logic, edge cases, no-signal conditions

**Signal strategy registry:**

```python
class SignalStrategyRegistry:
    def register(self, strategy: SignalStrategyInterface) -> None
    def get(self, strategy_id: str) -> SignalStrategyInterface
    def list_available(self) -> list[str]
```

**Tests:** 60+ unit tests across all strategies.

---

### M5 — Signal Evaluation Service & Risk Gate Pipeline

**Objective:** Build the service that evaluates raw signals through risk gates,
position sizing, and data quality checks before approving them for execution.

**SignalEvaluationService (services/api/services/signal_evaluation_service.py):**

Pipeline per signal:
1. **Data quality gate** — check QualityScore for the signal's symbol. Reject if
   quality below policy threshold for the deployment's execution mode.
2. **Kill switch gate** — check if deployment or global kill switch is active.
3. **Risk gate** — delegate to existing RiskGateInterface (Phase 4). Includes
   max position size, max daily loss, max open orders, concentration limits.
4. **Position sizing** — delegate to PositionSizingService (Phase 7) using the
   signal's suggested_stop and configured method.
5. **VaR impact check** — estimate post-trade VaR using RiskAnalyticsService.
   Reject if projected VaR exceeds deployment-level threshold.
6. **Duplicate signal filter** — reject if identical signal (same strategy,
   symbol, direction, bar_timestamp) was evaluated within cooldown window.
7. **Assemble SignalEvaluation** with all gate results, approved/rejected status,
   position size, and adjusted stop.

**Interfaces:**
- SignalEvaluationServiceInterface (with evaluate() method)
- Depends on: DataQualityService, KillSwitchService, RiskGateInterface,
  PositionSizingService, RiskAnalyticsService, SignalRepository

**Tests:** 25+ unit tests covering each gate, gate ordering, partial rejection,
full approval pipeline, duplicate filter, concurrent evaluation.

---

## Track C: Strategy Execution Engine

### M6 — Execution Loop Contracts & State Machine

**Objective:** Define the execution loop lifecycle, state machine, and the contracts
that govern how a strategy runs continuously against live/paper market data.

**Contracts (libs/contracts/execution_loop.py):**

```python
class LoopState(str, Enum):
    INITIALIZING = "initializing"
    RUNNING = "running"
    PAUSED = "paused"          # manual pause or kill switch
    COOLDOWN = "cooldown"      # post-error cooldown before retry
    STOPPED = "stopped"        # graceful shutdown
    FAILED = "failed"          # unrecoverable error

class ExecutionLoopConfig(BaseModel):
    deployment_id: str
    strategy_id: str
    signal_strategy_id: str     # which SignalStrategy to use
    symbols: list[str]
    interval: CandleInterval
    execution_mode: ExecutionMode
    max_positions_per_symbol: int = 1
    cooldown_after_trade_s: int = 60
    max_consecutive_errors: int = 5
    health_check_interval_s: int = 30

class LoopDiagnostics(BaseModel):
    state: LoopState
    deployment_id: str
    bars_processed: int
    signals_generated: int
    signals_approved: int
    signals_rejected: int
    orders_submitted: int
    orders_filled: int
    errors: int
    last_bar_at: datetime | None
    last_signal_at: datetime | None
    last_order_at: datetime | None
    uptime_seconds: float
```

**ExecutionLoopInterface (libs/contracts/interfaces/execution_loop.py):**

```python
class ExecutionLoopInterface(ABC):
    def start(self, config: ExecutionLoopConfig) -> None
    def stop(self) -> None
    def pause(self) -> None
    def resume(self) -> None
    def diagnostics(self) -> LoopDiagnostics
    @property
    def state(self) -> LoopState
```

**State transitions:**
```
INITIALIZING → RUNNING → PAUSED → RUNNING (resume)
RUNNING → COOLDOWN → RUNNING (auto-resume after cooldown)
RUNNING → STOPPED (graceful)
RUNNING → FAILED (circuit breaker tripped)
PAUSED → STOPPED (stop while paused)
```

**Tests:** 20+ contract validation, state transition legality, config validation.

---

### M7 — Strategy Execution Engine Implementation

**Objective:** Implement the event-driven execution loop that ties together market data,
signal generation, evaluation, and order submission.

**StrategyExecutionEngine (services/worker/execution/strategy_execution_engine.py):**

Core loop (runs in a dedicated thread per deployment):
```
while state == RUNNING:
    1. Receive new bar(s) from AlpacaBarStream callback or poll MarketDataRepository
    2. Resolve required indicators via IndicatorResolver
    3. Evaluate signal via SignalStrategy.evaluate()
    4. If signal produced:
       a. Run through SignalEvaluationService (risk gates, sizing, quality)
       b. If approved: convert to OrderRequest and submit via BrokerAdapter
       c. Persist Signal and SignalEvaluation to repository
    5. Update LoopDiagnostics
    6. Check health: kill switch, circuit breaker, data quality
    7. Sleep until next bar or wake on real-time callback
```

**Key behaviors:**
- **Real-time mode:** Registers as AlpacaBarStream callback; processes bars as they
  arrive. No polling delay.
- **Backfill mode:** On startup, fetches historical bars from MarketDataRepository
  to warm up indicator buffers before processing live data.
- **Circuit breaker:** After `max_consecutive_errors`, transitions to FAILED state.
  Manual reset via execution loop API.
- **Kill switch integration:** Checks KillSwitchService on every iteration.
  If active, transitions to PAUSED and executes deployment emergency posture.
- **Graceful shutdown:** `stop()` sets cooperative event, waits for current bar
  processing to complete, closes open orders if configured.
- **Thread safety:** All shared state under threading.Lock. Diagnostics are
  atomic snapshots.
- **Structured logging:** Every bar processing cycle logs at DEBUG; signals at INFO;
  orders at INFO; errors at ERROR with correlation_id propagation.

**Dependencies (all injected):**
- SignalStrategyInterface (resolved from registry by signal_strategy_id)
- SignalEvaluationService
- BrokerAdapterInterface
- MarketDataRepositoryInterface
- IndicatorResolverInterface
- KillSwitchService
- SignalRepository

**Tests:** 35+ unit tests covering the full loop lifecycle, bar processing,
signal→order flow, error handling, circuit breaker, kill switch pause,
graceful shutdown, concurrent access.

---

### M8 — Execution Loop API & Monitoring

**Objective:** Expose execution loop management through REST endpoints and provide
real-time monitoring via WebSocket.

**Endpoints (services/api/routes/execution_loop.py):**

```
POST   /execution/loops                  — Start a new execution loop
DELETE /execution/loops/{deployment_id}   — Stop an execution loop
PUT    /execution/loops/{deployment_id}/pause   — Pause
PUT    /execution/loops/{deployment_id}/resume  — Resume
GET    /execution/loops/{deployment_id}/diagnostics — Loop diagnostics
GET    /execution/loops                  — List all active loops
GET    /execution/loops/{deployment_id}/signals — Recent signals with evaluations
GET    /execution/loops/{deployment_id}/orders  — Recent orders
```

**WebSocket endpoint:**
- `/ws/execution/{deployment_id}` — real-time stream of loop events (signals,
  orders, state changes, errors). Uses existing WebSocketConnectionManager.

**Execution loop manager (infrastructure):**
- Maintains registry of active ExecutionLoop instances per deployment_id.
- Enforces: one loop per deployment, max concurrent loops (configurable).
- Startup recovery: reads active deployments from database, restarts loops.
- Graceful shutdown: stops all loops on application shutdown.

**Tests:** 20+ route tests, WebSocket lifecycle, manager concurrency.

---

## Track D: Advanced Backtesting

### M9 — Event-Driven Backtesting Engine

**Objective:** Build a backtesting engine that uses the same SignalStrategy and
execution pipeline as live trading, ensuring backtest-live parity.

**BacktestEngine (services/worker/research/backtest_engine.py):**

- **Event-driven architecture:** Replays historical bars from MarketDataRepository
  through the same signal evaluation pipeline as live execution.
- **Uses real SignalStrategy implementations** — same code path as M7.
- **Simulated broker:** PaperBrokerAdapter (already exists) processes orders with
  configurable slippage and commission models.
- **Indicator computation:** IndicatorResolver with caching (already exists from M12).
- **Position tracking:** Tracks open positions, P&L, equity curve per bar.
- **Fill simulation:** Market orders fill at next bar open. Limit orders fill
  when bar's low ≤ limit (buy) or bar's high ≥ limit (sell). Stop orders
  trigger when price crosses stop level.

**BacktestResult extensions:**
- Extend existing BacktestResult (libs/contracts/backtest.py) with:
  - signals_generated, signals_approved, signals_rejected
  - per-signal attribution (which signal produced which trade)
  - equity_curve: list of (timestamp, equity) points
  - drawdown_curve: list of (timestamp, drawdown_pct) points
  - indicator_values_at_signals: snapshot of indicators at each signal

**Tests:** 30+ tests: known-outcome backtests (e.g., buy-and-hold on a known series),
signal→trade attribution, fill simulation accuracy, slippage modeling,
equity curve correctness.

---

### M10 — Walk-Forward Analysis & Parameter Optimization

**Objective:** Systematic parameter optimization with out-of-sample validation
to prevent overfitting.

**WalkForwardEngine (services/worker/research/walk_forward_engine.py):**

- **Walk-forward analysis:** Splits data into N rolling windows, each with
  in-sample (training) and out-of-sample (validation) periods.
  Runs optimization on in-sample, validates on out-of-sample.
- **Parameter grid search:** Enumerate parameter combinations for a SignalStrategy.
  Configurable: exhaustive grid, random search, or Bayesian optimization (scipy).
- **Optimization objective:** Configurable metric — Sharpe, Sortino, Calmar,
  profit factor, max drawdown. Supports multi-objective (Pareto front).
- **Walk-forward result:** Per-window results, aggregate out-of-sample performance,
  stability score (how consistent are optimal parameters across windows).

**Contracts (libs/contracts/walk_forward.py):**

```python
class WalkForwardConfig(BaseModel):
    strategy_id: str
    signal_strategy_id: str
    symbols: list[str]
    start_date: date
    end_date: date
    interval: BacktestInterval
    in_sample_bars: int
    out_of_sample_bars: int
    step_bars: int
    parameter_grid: dict[str, list[Any]]
    optimization_metric: str  # "sharpe", "sortino", "calmar", "profit_factor"
    initial_equity: Decimal

class WalkForwardWindowResult(BaseModel):
    window_index: int
    in_sample_start: date
    in_sample_end: date
    out_of_sample_start: date
    out_of_sample_end: date
    best_params: dict[str, Any]
    in_sample_metric: float
    out_of_sample_metric: float

class WalkForwardResult(BaseModel):
    config: WalkForwardConfig
    windows: list[WalkForwardWindowResult]
    aggregate_oos_metric: float
    stability_score: float  # 0–1, how consistent are optimal params
    best_consensus_params: dict[str, Any]
    completed_at: datetime
```

**Tests:** 25+ tests: window splitting, parameter enumeration, optimization
convergence on known data, stability scoring.

---

### M11 — Monte Carlo Simulation & Statistical Validation

**Objective:** Provide confidence intervals and risk metrics through Monte Carlo
simulation of backtest trade sequences.

**MonteCarloEngine (services/worker/research/monte_carlo_engine.py):**

- **Trade sequence resampling:** Shuffle the order of trades from a BacktestResult
  N times (default: 10,000) to generate a distribution of equity curves.
- **Return bootstrapping:** Resample daily/bar returns with replacement to generate
  alternative equity paths.
- **Metrics per simulation:** Final equity, max drawdown, Sharpe ratio, longest
  losing streak, time to recovery from max drawdown.
- **Confidence intervals:** Calculate percentile-based intervals (5th, 25th, 50th,
  75th, 95th) for each metric.
- **Probability of ruin:** % of simulations where equity drops below configurable
  threshold (e.g., 50% of initial equity).

**Contracts (libs/contracts/monte_carlo.py):**

```python
class MonteCarloConfig(BaseModel):
    num_simulations: int = 10000
    method: str = "trade_resample"  # or "return_bootstrap"
    confidence_levels: list[float] = [0.05, 0.25, 0.50, 0.75, 0.95]
    ruin_threshold: float = 0.50  # equity drops below 50%

class MonteCarloResult(BaseModel):
    config: MonteCarloConfig
    num_trades: int
    equity_percentiles: dict[str, float]  # "p5", "p25", etc.
    max_drawdown_percentiles: dict[str, float]
    sharpe_percentiles: dict[str, float]
    probability_of_ruin: float
    mean_final_equity: float
    median_final_equity: float
    completed_at: datetime
```

**API endpoints:**
```
POST /research/monte-carlo          — Run simulation on a BacktestResult
GET  /research/monte-carlo/{run_id} — Retrieve simulation results
```

**Tests:** 25+ tests: deterministic seed reproducibility, distribution shape
validation, edge cases (single trade, zero trades), ruin calculation,
confidence interval ordering.

---

## Track E: Portfolio & Multi-Strategy

### M12 — Portfolio Allocation Contracts & Engine

**Objective:** Define how capital is allocated across multiple strategies and
implement the allocation engine.

**Contracts (libs/contracts/portfolio.py):**

```python
class AllocationMethod(str, Enum):
    EQUAL_WEIGHT = "equal_weight"
    RISK_PARITY = "risk_parity"
    INVERSE_VOLATILITY = "inverse_volatility"
    KELLY_OPTIMAL = "kelly_optimal"
    FIXED = "fixed"

class StrategyAllocation(BaseModel):
    strategy_id: str
    deployment_id: str
    target_weight: float      # 0.0–1.0
    current_weight: float
    capital_allocated: Decimal
    max_drawdown_limit: float # per-strategy drawdown cap

class PortfolioConfig(BaseModel):
    portfolio_id: str
    name: str
    total_capital: Decimal
    allocation_method: AllocationMethod
    rebalance_frequency: str   # "daily", "weekly", "monthly", "on_threshold"
    rebalance_threshold: float # % drift before trigger (for on_threshold)
    strategy_configs: list[StrategyAllocationConfig]
    max_total_leverage: float = 1.0
    max_correlation_between_strategies: float = 0.80

class PortfolioSnapshot(BaseModel):
    portfolio_id: str
    timestamp: datetime
    total_equity: Decimal
    total_pnl: Decimal
    allocations: list[StrategyAllocation]
    strategy_correlations: dict[str, dict[str, float]]
```

**PortfolioAllocationService:**
- Equal weight: divide capital equally among active strategies.
- Risk parity: allocate inversely proportional to strategy volatility.
- Inverse volatility: similar to risk parity, uses rolling 20-day vol.
- Kelly optimal: uses per-strategy win rate and avg win/loss ratio.
- Fixed: user-specified weights.

**Repository:** SQL persistence for portfolio configs and snapshots.

**Tests:** 30+ tests: each allocation method, edge cases (single strategy,
zero volatility), constraint enforcement (leverage, correlation).

---

### M13 — Multi-Strategy Orchestration & Rebalancing

**Objective:** Build the orchestrator that manages multiple concurrent execution
loops and rebalances capital across them.

**PortfolioOrchestrator (services/worker/execution/portfolio_orchestrator.py):**

- Manages a set of StrategyExecutionEngine instances (one per deployment).
- Monitors per-strategy P&L and equity in real-time.
- **Rebalancing triggers:**
  - Time-based: daily/weekly/monthly at configurable time.
  - Threshold-based: when any strategy's weight drifts beyond threshold.
  - Manual: operator-triggered via API.
- **Rebalancing execution:**
  1. Pause all execution loops.
  2. Calculate target allocations using configured method.
  3. Determine required position adjustments per strategy.
  4. Submit rebalancing orders through each strategy's broker adapter.
  5. Wait for fills (with timeout).
  6. Resume execution loops with updated capital allocations.
- **Cross-strategy risk checks:**
  - Total portfolio VaR must not exceed configurable limit.
  - Correlation between strategy returns monitored; alert if exceeds threshold.
  - Total leverage must not exceed max_total_leverage.

**Endpoints (services/api/routes/portfolio.py):**
```
POST   /portfolios                           — Create portfolio config
GET    /portfolios/{id}                      — Get portfolio with current snapshot
PUT    /portfolios/{id}/allocations          — Update allocation weights
POST   /portfolios/{id}/rebalance            — Trigger manual rebalance
GET    /portfolios/{id}/history              — Equity/allocation history
GET    /portfolios/{id}/diagnostics          — Orchestrator diagnostics
DELETE /portfolios/{id}                      — Stop all loops, archive portfolio
```

**Tests:** 30+ tests: rebalancing math, pause/resume lifecycle, concurrent
loop management, drift detection, cross-strategy risk enforcement.

---

### M14 — Cross-Strategy Risk Aggregation & Capital Optimization

**Objective:** Aggregate risk metrics across all strategies in a portfolio and
optimize capital allocation based on realized performance.

**CrossStrategyRiskService (services/api/services/cross_strategy_risk_service.py):**

- **Portfolio-level VaR:** Aggregate positions across all strategies, compute
  portfolio VaR accounting for inter-strategy correlations.
- **Marginal VaR:** For each strategy, compute the portfolio VaR impact of
  adding/removing it. Identifies which strategies are the biggest risk contributors.
- **Strategy correlation tracking:** Rolling correlation matrix of strategy returns.
  Alert when correlation between strategies exceeds threshold (risk concentration).
- **Drawdown synchronization:** Detect when multiple strategies draw down
  simultaneously (correlated risk event). Trigger portfolio-level risk response.
- **Capital optimization:** Based on trailing N-day performance, suggest allocation
  adjustments using mean-variance optimization (Markowitz efficient frontier) or
  Black-Litterman with operator-provided views.

**Endpoints:**
```
GET  /portfolios/{id}/risk/var              — Portfolio-level VaR
GET  /portfolios/{id}/risk/marginal-var     — Per-strategy marginal VaR
GET  /portfolios/{id}/risk/correlation      — Strategy return correlations
GET  /portfolios/{id}/risk/optimization     — Suggested allocation adjustments
POST /portfolios/{id}/risk/stress-test      — Portfolio-level stress test
```

**Tests:** 25+ tests: portfolio VaR math, marginal VaR decomposition, correlation
tracking, drawdown sync detection, optimization constraints.

---

## Acceptance

### M15 — Phase 8 Acceptance Test Pack

**Objective:** End-to-end acceptance tests that verify the complete signal-to-execution
pipeline works as an integrated system.

**Acceptance scenarios:**

1. **Data quality → signal suppression:** Inject bad data (OHLCV violation),
   verify quality score drops, verify signal evaluation rejects due to data quality.

2. **Signal generation → order execution:** Set up MA crossover strategy with known
   data that will produce a crossover at a specific bar. Verify signal generated,
   risk gates passed, order submitted, fill recorded.

3. **Kill switch → execution pause:** Start execution loop, trigger kill switch,
   verify loop pauses and no new orders are submitted.

4. **Walk-forward → parameter selection:** Run walk-forward on known data with
   predictable optimal parameters. Verify optimization finds them.

5. **Monte Carlo → confidence intervals:** Run Monte Carlo on a known trade sequence.
   Verify percentiles are statistically reasonable (within expected bounds for N=10000).

6. **Portfolio rebalancing:** Set up 2-strategy portfolio, simulate drift past threshold,
   verify rebalance triggered and orders submitted.

7. **Cross-strategy risk:** Two strategies with correlated positions. Verify
   portfolio VaR is computed correctly (less than sum of individual VaRs due to
   imperfect correlation, or more if correlation > assumed).

8. **Full pipeline integration:** Market data → quality check → indicator computation →
   signal generation → risk evaluation → order submission → fill → P&L update →
   portfolio snapshot. Verify every link in the chain.

**Tests:** 15+ integration/acceptance tests.

**Documentation:** Update DEPLOYMENT.md with Phase 8 operational runbook entries
for the execution engine, data quality monitoring, and portfolio management.

---

## Implementation Order

The recommended implementation sequence accounts for dependencies:

```
M0  → M1  → M2   (Data Quality — no dependencies on other Phase 8 milestones)
M3  → M4  → M5   (Signal Framework — depends on Phase 7 indicators)
M6  → M7  → M8   (Execution Engine — depends on M3–M5 signals)
M9  → M10 → M11  (Backtesting — depends on M3–M5 signals, M6–M7 engine)
M12 → M13 → M14  (Portfolio — depends on M6–M8 execution engine)
M15               (Acceptance — depends on all above)
```

Tracks A and B can be developed in parallel. Track C depends on B.
Tracks D and E depend on C. M15 depends on all tracks.
