# FXLab Phase 7 — Technical Indicators, Market Data Pipeline & Advanced Risk

**Version:** 1.0
**Created:** 2026-04-12
**Author:** Phase 7 Architecture Session
**Depends on:** Phase 6 (all 14 milestones DONE)
**Estimated milestones:** 16

---

## Revision History

| Version | Date | Changes |
|---------|------|---------|
| 1.0 | 2026-04-12 | Initial workplan: 16 milestones across 4 tracks |

---

```
MILESTONE INDEX
───────────────────────────────────────────────
Total milestones: 16
Tracks: Market Data Pipeline, Technical Indicators, Advanced Risk Management, Strategy Intelligence

Market Data Pipeline:       M0, M1, M2, M3
Technical Indicators:       M4, M5, M6, M7
Advanced Risk Management:   M8, M9, M10, M11
Strategy Intelligence:      M12, M13, M14, M15
───────────────────────────────────────────────
```

---

## Motivation

Phases 1–6 delivered a complete trading platform with strategy compilation,
backtesting, paper/live execution, governance, compliance, and real-time
dashboards. However, the platform currently lacks three foundational
capabilities that CLAUDE.md §1 identifies as core requirements:

1. **No technical indicator calculation engine.** The strategy DSL references
   indicators by name (e.g., `MACD > 0`) but no indicator library exists.
   Research runs and live strategies cannot compute indicators from market data.

2. **No market data ingestion pipeline.** Feed health monitoring exists, but
   no service collects, normalizes, or stores OHLCV candlestick data from
   broker APIs or third-party providers. Without ingested data, indicators
   cannot be calculated and backtests rely on externally provided datasets.

3. **No advanced risk management.** Pre-trade risk gates (position limits,
   daily loss limits) exist, but portfolio-level risk analytics (VaR, Greeks,
   correlation analysis, stress testing) are absent. For a platform managing
   live capital, this is a critical gap.

Phase 7 closes these gaps and connects them to the existing execution and
research infrastructure.

---

## Track: Market Data Pipeline

### M0 — Market Data Contracts, Interfaces & Storage Schema

**Objective:** Define the data model, repository interfaces, and database
schema for normalized OHLCV market data, enabling all downstream consumers
(indicators, backtests, live strategies) to work against a single canonical
data store.

**Context:** Feed registry (Phase 1 M5) tracks feed configurations and health.
This milestone adds the actual data storage layer — the registry knows *about*
feeds; this milestone stores what feeds *produce*.

**Deliverables:**

- `libs/contracts/market_data.py` — Pydantic contracts:
  - `Candle`: symbol, interval (1m/5m/15m/1h/1d), open, high, low, close,
    volume, vwap (optional), trade_count (optional), timestamp (UTC)
  - `CandleInterval` enum: `M1`, `M5`, `M15`, `H1`, `D1`
  - `MarketDataQuery`: symbol, interval, start, end, limit
  - `MarketDataPage`: candles list, total_count, has_more, next_cursor
  - `TickData`: symbol, price, size, timestamp, exchange (for future tick-level)
  - `DataGap`: symbol, interval, gap_start, gap_end, detected_at

- `libs/contracts/interfaces/market_data_repository.py` — Interface:
  - `upsert_candles(candles: list[Candle]) -> int` — bulk upsert, returns row count
  - `query_candles(query: MarketDataQuery) -> MarketDataPage` — paginated read
  - `get_latest_candle(symbol: str, interval: CandleInterval) -> Candle | None`
  - `detect_gaps(symbol: str, interval: CandleInterval, start: datetime, end: datetime) -> list[DataGap]`
  - `delete_candles(symbol: str, interval: CandleInterval, before: datetime) -> int`

- `libs/contracts/models.py` — ORM model:
  - `CandleRecord` table with composite unique index on (symbol, interval, timestamp)
  - `DataGapRecord` table for gap tracking

- Alembic migration for `candle_records` and `data_gap_records` tables

- `services/api/repositories/sql_market_data_repository.py` — SQL implementation:
  - Bulk upsert via `INSERT ... ON CONFLICT DO UPDATE`
  - Cursor-based pagination for large result sets
  - Gap detection via window functions comparing consecutive timestamps

- `services/api/repositories/mocks/mock_market_data_repository.py` — In-memory mock

- Tests:
  - Unit tests for mock repository
  - Integration tests for SQL repository (SAVEPOINT isolation)
  - Contract tests for Pydantic models

**Acceptance criteria:**
- Bulk upsert of 10,000 candles completes in < 2 seconds (SQLite benchmark)
- Gap detection correctly identifies missing 1-minute candles in a 1-hour window
- Cursor pagination returns consistent results across pages
- Composite unique index prevents duplicate candles for same (symbol, interval, timestamp)

---

### M1 — Alpaca Market Data Collector

**Objective:** Implement a background service that collects OHLCV candlestick
data from Alpaca's Market Data API and persists it via the market data
repository.

**Context:** Alpaca provides both historical bars (REST) and real-time bars
(WebSocket). This milestone implements historical bar collection with
scheduled backfill. Real-time streaming is M3.

**Deliverables:**

- `libs/contracts/interfaces/market_data_provider.py` — Provider interface:
  - `fetch_historical_bars(symbol: str, interval: CandleInterval, start: datetime, end: datetime) -> list[Candle]`
  - `get_supported_intervals() -> list[CandleInterval]`
  - `get_provider_name() -> str`

- `services/worker/collectors/alpaca_market_data_provider.py` — Alpaca implementation:
  - REST calls to `https://data.alpaca.markets/v2/stocks/{symbol}/bars`
  - Rate-limit aware: respects 200 req/min limit with adaptive backoff
  - Pagination handling for large date ranges (Alpaca page_token)
  - Maps Alpaca bar format → Candle contract
  - Timeout: 30s per request, retry on 429/5xx with exponential backoff
  - Configurable via `ALPACA_DATA_API_KEY`, `ALPACA_DATA_API_SECRET`,
    `ALPACA_DATA_BASE_URL` (default: `https://data.alpaca.markets`)

- `services/worker/collectors/market_data_collector.py` — Collector service:
  - `collect(symbols: list[str], interval: CandleInterval, start: datetime, end: datetime) -> CollectionResult`
  - Batch symbols into configurable chunk sizes (default: 10)
  - Log progress: symbols collected, candles persisted, gaps detected
  - Emit Prometheus counter: `market_data_candles_collected_total`
  - Emit gap detection events for monitoring

- `services/worker/tasks/market_data_tasks.py` — Celery tasks:
  - `collect_historical_bars`: scheduled task for daily backfill
  - `backfill_gaps`: on-demand task to fill detected data gaps
  - Configurable symbol watchlist via `MARKET_DATA_SYMBOLS` env var

- Tests:
  - Unit tests for Alpaca provider (mocked HTTP)
  - Unit tests for collector service (mocked provider + repo)
  - Integration test: provider → collector → SQL repo pipeline

**Acceptance criteria:**
- Collects 1 year of daily AAPL candles in a single invocation
- Rate limiter prevents 429 errors during multi-symbol batch collection
- Gaps detected after collection are reported in structured logs
- Celery task is idempotent: re-running does not create duplicates (upsert)

---

### M2 — Market Data API Endpoints

**Objective:** Expose market data through REST endpoints for frontend charts,
strategy research, and external consumers.

**Deliverables:**

- `services/api/routes/market_data.py` — Endpoints:
  - `GET /market-data/candles` — Query candles with symbol, interval, start, end,
    limit parameters. Returns `MarketDataPage`. LTTB downsampling applied when
    result exceeds threshold (reuse `libs/utils/lttb.py`).
  - `GET /market-data/candles/latest` — Latest candle per symbol/interval.
    Used by live dashboard for current price display.
  - `GET /market-data/gaps` — List detected data gaps for a symbol/interval range.
    Used by operators to monitor data quality.
  - `POST /market-data/backfill` — Trigger gap backfill task (operator scope).
    Returns Celery task ID for polling.

- Scope enforcement: `feeds:read` for candle queries, `operator:write` for backfill trigger

- Frontend integration:
  - `features/market-data/api.ts` — Typed API client
  - `features/market-data/useCandles.ts` — TanStack Query hook with caching

- Tests:
  - Unit tests for all endpoints (mocked repo)
  - Scope enforcement tests (feeds:read required, operator:write for backfill)
  - Frontend: API client tests, hook tests with MSW

**Acceptance criteria:**
- GET /market-data/candles returns paginated results with LTTB downsampling
- Unauthorized users receive 401; users without feeds:read receive 403
- Backfill trigger returns 202 Accepted with task_id
- Frontend hook caches results and invalidates on interval change

---

### M3 — Real-Time Market Data Streaming

**Objective:** Add WebSocket-based real-time candle streaming from Alpaca's
data stream, broadcasting updates to connected frontend clients.

**Context:** M7 (Phase 6) established the WebSocket infrastructure
(`WebSocketConnectionManager`). This milestone adds a market data stream
channel using the same pattern.

**Deliverables:**

- `services/worker/streams/alpaca_market_stream.py` — Alpaca WebSocket client:
  - Connects to `wss://stream.data.alpaca.markets/v2/iex` (or sip for paid plan)
  - Subscribes to bar updates for configured symbols
  - Reconnect with exponential backoff on disconnect
  - Heartbeat monitoring (expect ping every 30s, reconnect on timeout)
  - Maps real-time bars → Candle contract
  - Persists candles via market data repository
  - Broadcasts via WebSocketConnectionManager

- `services/api/routes/ws_market_data.py` — WebSocket endpoint:
  - `WS /ws/market-data/{symbol}` — Subscribe to real-time candle updates
  - Authentication via query parameter token (same pattern as ws_positions)
  - Message format: `WsMessage` envelope with `market_data_update` type

- Frontend:
  - `features/market-data/useMarketStream.ts` — WebSocket hook for real-time updates
  - Integration with existing chart components for live price overlay

- Tests:
  - Unit tests for Alpaca stream client (mocked WebSocket)
  - Unit tests for ws_market_data endpoint
  - Frontend: useMarketStream hook tests

**Acceptance criteria:**
- Real-time candle updates arrive within 2 seconds of Alpaca broadcast
- Reconnect logic recovers from network interruption within 30 seconds
- Multiple frontend clients receive the same broadcast (fan-out via manager)
- Candles are persisted to database as they arrive (no data loss on client disconnect)

---

## Track: Technical Indicators

### M4 — Indicator Calculation Engine (Core Library)

**Objective:** Build a vectorized technical indicator calculation library that
computes indicators from candle arrays, usable by both the research engine
(batch) and live strategies (incremental).

**Context:** The strategy DSL (`Phase 2`) references indicators by name
(e.g., `MACD(12,26,9) > 0`). Phase 2's research engine evaluates DSL rules
but delegates indicator computation to an indicator provider that does not yet
exist. This milestone creates that provider.

**Deliverables:**

- `libs/indicators/engine.py` — Indicator engine:
  - `IndicatorEngine` class with registration pattern
  - `compute(indicator_name: str, candles: list[Candle], **params) -> IndicatorResult`
  - `compute_batch(indicators: list[IndicatorRequest], candles: list[Candle]) -> dict[str, IndicatorResult]`
  - Vectorized computation using numpy arrays (not row-by-row Python loops)
  - `IndicatorResult`: values (np.ndarray), timestamps (np.ndarray), metadata (dict)
  - `IndicatorRequest`: name, params dict

- `libs/indicators/registry.py` — Indicator registry:
  - `register(name: str, calculator: IndicatorCalculator)` — register an indicator
  - `get(name: str) -> IndicatorCalculator` — retrieve by name
  - `list_available() -> list[IndicatorInfo]` — list all registered indicators
  - Built-in registration of all Phase 7 indicators on import

- `libs/contracts/indicator.py` — Contracts:
  - `IndicatorCalculator` protocol: `calculate(candles: np.ndarray, **params) -> np.ndarray`
  - `IndicatorInfo`: name, description, default_params, param_constraints
  - `IndicatorResult`: values, timestamps, metadata, indicator_name
  - `IndicatorRequest`: indicator_name, params

- Tests:
  - Unit tests for engine registration, dispatch, batch compute
  - Unit tests for IndicatorResult serialization
  - Property tests: indicator output length == input length (where applicable)

**Acceptance criteria:**
- Engine computes 10 indicators on 10,000 candles in < 100ms
- Unregistered indicator name raises `IndicatorNotFoundError`
- Batch compute returns all requested indicators in a single pass
- Engine is stateless — safe for concurrent use

---

### M5 — Trend and Momentum Indicators

**Objective:** Implement the most commonly used trend and momentum indicators
that CLAUDE.md §1 identifies: moving averages, MACD, RSI, and stochastic.

**Deliverables:**

- `libs/indicators/trend.py` — Trend indicators:
  - `SMA(period)` — Simple Moving Average
  - `EMA(period)` — Exponential Moving Average (Wilder smoothing)
  - `WMA(period)` — Weighted Moving Average
  - `DEMA(period)` — Double Exponential Moving Average
  - `TEMA(period)` — Triple Exponential Moving Average
  - All return np.ndarray with NaN for insufficient lookback periods
  - Vectorized: no Python loops in hot path

- `libs/indicators/momentum.py` — Momentum indicators:
  - `MACD(fast_period=12, slow_period=26, signal_period=9)` → (macd_line, signal_line, histogram)
  - `RSI(period=14)` → RSI values (0–100 scale)
  - `Stochastic(k_period=14, d_period=3, smooth_k=3)` → (%K, %D)
  - `StochasticRSI(rsi_period=14, stoch_period=14, k_period=3, d_period=3)` → (%K, %D)
  - `ROC(period=12)` — Rate of Change
  - `MOM(period=10)` — Momentum (price difference)
  - `Williams_R(period=14)` — Williams %R
  - `CCI(period=20)` — Commodity Channel Index

- Registration: All indicators auto-register with IndicatorEngine on import

- Tests:
  - Unit tests for each indicator with known-good reference values
    (cross-validated against TA-Lib or pandas_ta output)
  - Edge cases: insufficient data, single candle, all-same-price candles
  - Numerical precision: results match reference within 1e-8 tolerance
  - Performance: 10,000 candles × each indicator < 10ms

**Acceptance criteria:**
- MACD(12,26,9) on SPY daily data matches TA-Lib output within 1e-8
- RSI(14) values are bounded [0, 100] for all inputs
- Stochastic %K and %D are bounded [0, 100]
- All indicators return NaN (not error) for insufficient lookback
- Zero Python for-loops in any indicator hot path (numpy only)

---

### M6 — Volatility and Volume Indicators

**Objective:** Implement volatility and volume indicators required for risk
assessment, position sizing, and strategy signals.

**Deliverables:**

- `libs/indicators/volatility.py` — Volatility indicators:
  - `BollingerBands(period=20, std_dev=2.0)` → (upper, middle, lower, bandwidth, %b)
  - `ATR(period=14)` — Average True Range
  - `Keltner(period=20, atr_period=10, multiplier=1.5)` → (upper, middle, lower)
  - `DonchianChannel(period=20)` → (upper, lower, middle)
  - `StandardDeviation(period=20)` — Rolling std dev of close prices
  - `HistoricalVolatility(period=20, annualize=True)` — Annualized log returns std dev

- `libs/indicators/volume.py` — Volume indicators:
  - `OBV()` — On-Balance Volume
  - `VWAP(anchor="session")` — Volume-Weighted Average Price
  - `ADL()` — Accumulation/Distribution Line
  - `MFI(period=14)` — Money Flow Index (0–100 scale)
  - `CMF(period=20)` — Chaikin Money Flow

- Registration: Auto-register on import

- Tests:
  - Unit tests with reference values for each indicator
  - Bollinger %b bounded [0, 1] for normal price action
  - ATR always non-negative
  - MFI bounded [0, 100]
  - VWAP requires volume data (raises `ValueError` if volume column is all-zero)

**Acceptance criteria:**
- Bollinger Bands width increases during high-volatility periods
- ATR(14) on known dataset matches TA-Lib within 1e-8
- VWAP resets at session boundary when anchor="session"
- All indicators handle zero-volume candles gracefully (NaN, not divide-by-zero)

---

### M7 — Indicator API, DSL Integration & Frontend Visualization

**Objective:** Wire the indicator engine into the API layer, connect it to
the strategy DSL evaluator, and add frontend chart overlays.

**Deliverables:**

- `services/api/routes/indicators.py` — Endpoints:
  - `GET /indicators` — List all available indicators with params and descriptions
  - `POST /indicators/compute` — Compute one or more indicators on specified
    candles (symbol, interval, date range, indicator list). Returns time-aligned
    indicator values. LTTB downsampled if result exceeds threshold.
  - `GET /indicators/{name}/info` — Detailed info for a single indicator

- `services/api/services/indicator_service.py` — Service layer:
  - Fetches candles from market data repository
  - Delegates to IndicatorEngine
  - Caches results via chart cache service (TTL-based)
  - Structured logging for compute requests

- Strategy DSL integration:
  - Update Phase 2 DSL evaluator to resolve indicator references via IndicatorEngine
  - `MACD(12,26,9).signal > 0` → fetches candles, computes MACD, evaluates condition
  - `RSI(14) < 30` → computes RSI, evaluates threshold

- Frontend:
  - `features/indicators/api.ts` — Typed API client
  - `features/indicators/IndicatorOverlay.tsx` — Chart overlay component
    that renders indicator lines on equity/price charts (Recharts + ECharts)
  - `features/indicators/IndicatorSelector.tsx` — Multi-select dropdown
    with parameter inputs for each indicator
  - Integration with EquityCurve and CandlestickChart components

- Tests:
  - API endpoint tests (mocked service)
  - Service tests (mocked repo + engine)
  - DSL integration tests (indicator resolution in strategy evaluation)
  - Frontend: overlay rendering tests, selector interaction tests

**Acceptance criteria:**
- POST /indicators/compute returns time-aligned indicator values with candle timestamps
- DSL expression `MACD(12,26,9) > 0` evaluates correctly against historical data
- Frontend overlay renders MACD histogram below price chart
- Indicator results are cached — second request for same params is a cache hit

---

## Track: Advanced Risk Management

### M8 — Portfolio Risk Analytics Engine

**Objective:** Build a portfolio-level risk analytics service that computes
Value-at-Risk (VaR), correlation matrices, and concentration analysis across
all active deployments.

**Deliverables:**

- `libs/contracts/risk_analytics.py` — Contracts:
  - `VaRResult`: var_95, var_99, cvar_95, cvar_99, method (historical/parametric),
    lookback_days, computed_at
  - `CorrelationEntry`: symbol_a, symbol_b, correlation, lookback_days
  - `CorrelationMatrix`: entries list, symbols list, matrix (2D), computed_at
  - `ConcentrationReport`: per_symbol (list of symbol, market_value, pct_of_portfolio),
    herfindahl_index, top_5_pct, computed_at
  - `PortfolioRiskSummary`: var, correlation, concentration, total_exposure,
    net_exposure, gross_exposure, long_exposure, short_exposure

- `libs/contracts/interfaces/risk_analytics_service.py` — Interface:
  - `compute_var(deployment_id: str, confidence: float, lookback_days: int) -> VaRResult`
  - `compute_correlation_matrix(deployment_id: str, lookback_days: int) -> CorrelationMatrix`
  - `compute_concentration(deployment_id: str) -> ConcentrationReport`
  - `get_portfolio_risk_summary(deployment_id: str) -> PortfolioRiskSummary`

- `services/api/services/risk_analytics_service.py` — Implementation:
  - Historical VaR: sort daily P&L returns, pick percentile
  - Parametric VaR: assume normal distribution, mean ± z × std
  - CVaR (Expected Shortfall): mean of returns beyond VaR threshold
  - Pearson correlation matrix from daily returns
  - Herfindahl-Hirschman Index for concentration
  - Uses market data repository for historical prices, position repo for current holdings
  - numpy/scipy for numerical computation

- `services/api/routes/risk_analytics.py` — Endpoints:
  - `GET /risk/var/{deployment_id}` — VaR and CVaR
  - `GET /risk/correlation/{deployment_id}` — Correlation matrix
  - `GET /risk/concentration/{deployment_id}` — Concentration report
  - `GET /risk/summary/{deployment_id}` — Full portfolio risk summary
  - Scope: `deployments:read`

- Tests:
  - Unit tests with known portfolios and expected VaR values
  - Correlation matrix is symmetric with 1.0 on diagonal
  - Concentration of single-stock portfolio → HHI = 10,000
  - Edge case: single position, no positions, insufficient history

**Acceptance criteria:**
- Historical VaR(95%) on 252-day lookback matches manual calculation
- Correlation matrix is positive semi-definite (eigenvalues ≥ 0)
- HHI = 10,000 for single-stock portfolio, decreases with diversification
- Computation completes in < 500ms for 50-position portfolio

---

### M9 — Stress Testing and Scenario Analysis

**Objective:** Enable operators to run predefined and custom stress scenarios
against their portfolio to assess tail-risk exposure.

**Deliverables:**

- `libs/contracts/stress_test.py` — Contracts:
  - `StressScenario`: name, description, shocks (dict of symbol → pct_change or
    sector → pct_change), is_predefined
  - `StressTestResult`: scenario_name, portfolio_pnl_impact, per_symbol_impact (list),
    margin_impact, would_trigger_halt (bool), computed_at
  - `ScenarioLibrary` enum: `FLASH_CRASH_2010`, `COVID_MARCH_2020`, `RATE_HIKE_2022`,
    `SECTOR_ROTATION`, `CUSTOM`

- `libs/contracts/interfaces/stress_test_service.py` — Interface:
  - `run_scenario(deployment_id: str, scenario: StressScenario) -> StressTestResult`
  - `run_predefined(deployment_id: str, scenario_name: ScenarioLibrary) -> StressTestResult`
  - `list_predefined_scenarios() -> list[StressScenario]`

- `services/api/services/stress_test_service.py` — Implementation:
  - Apply percentage shocks to current positions' market values
  - Compute portfolio-level P&L impact
  - Check if result would breach daily loss limit (references risk gate config)
  - Predefined scenarios with historically calibrated shocks
  - Custom scenarios: operator provides symbol → shock mapping

- API endpoints: `POST /risk/stress-test`, `GET /risk/stress-test/scenarios`

- Frontend:
  - `features/risk/StressTestPanel.tsx` — Scenario selector with predefined library,
    custom shock editor, result display with P&L impact visualization
  - `features/risk/StressTestResult.tsx` — Per-symbol waterfall chart

- Tests:
  - Unit tests for each predefined scenario
  - Custom scenario with 100% drawdown → portfolio value = 0
  - Halt trigger detection when stress result exceeds daily loss limit
  - Frontend: panel interaction tests, result rendering tests

**Acceptance criteria:**
- Flash Crash scenario applies -8.7% to all equity positions
- Custom scenario with AAPL: -50% shows correct per-symbol and portfolio impact
- `would_trigger_halt` is true when stressed P&L exceeds configured daily loss limit
- Predefined scenario list matches ScenarioLibrary enum entries

---

### M10 — Dynamic Position Sizing

**Objective:** Replace static position size limits with volatility-aware
dynamic sizing that adjusts position sizes based on ATR, portfolio heat, and
Kelly criterion calculations.

**Deliverables:**

- `libs/contracts/position_sizing.py` — Contracts:
  - `SizingMethod` enum: `FIXED`, `ATR_BASED`, `KELLY`, `RISK_PARITY`, `EQUAL_WEIGHT`
  - `SizingRequest`: symbol, side, method, risk_per_trade_pct, account_equity,
    current_positions, atr_value (optional), win_rate (optional), avg_win_loss_ratio (optional)
  - `SizingResult`: recommended_quantity, recommended_value, stop_loss_price,
    risk_amount, method_used, reasoning (human-readable explanation)

- `libs/contracts/interfaces/position_sizing_service.py` — Interface:
  - `compute_size(request: SizingRequest) -> SizingResult`
  - `get_available_methods() -> list[SizingMethod]`

- `services/api/services/position_sizing_service.py` — Implementation:
  - `FIXED`: return configured max_position_size (existing behavior)
  - `ATR_BASED`: quantity = (account_equity × risk_pct) / (atr × multiplier)
  - `KELLY`: fraction = win_rate - (1 - win_rate) / avg_win_loss_ratio, with half-Kelly cap
  - `RISK_PARITY`: inverse-volatility weighting across positions
  - `EQUAL_WEIGHT`: equal dollar allocation across n positions
  - All methods respect existing risk gate maximums as hard caps

- Integration with live execution service:
  - `LiveExecutionService.submit_order()` calls sizing service before submission
  - Override: if strategy specifies exact quantity, skip dynamic sizing
  - Log sizing decision for audit trail

- API endpoint: `POST /risk/position-size` — compute recommended size without executing

- Tests:
  - Unit tests for each sizing method with known inputs/outputs
  - Kelly criterion: win_rate=0.6, ratio=2.0 → Kelly fraction = 0.30, half-Kelly = 0.15
  - ATR-based: high ATR reduces position size proportionally
  - Risk gate cap: recommended size never exceeds risk gate maximum
  - Integration: sizing service called before order submission

**Acceptance criteria:**
- ATR-based sizing reduces position size when volatility doubles
- Kelly fraction is capped at 0.5 (full Kelly) and recommended at half-Kelly
- Equal weight across 10 positions → each gets 10% of equity
- Existing risk gate limits are never exceeded regardless of sizing method

---

### M11 — Risk Dashboard and Alerting

**Objective:** Build a comprehensive risk dashboard that visualizes portfolio
risk metrics and triggers alerts when thresholds are breached.

**Deliverables:**

- Frontend:
  - `features/risk/RiskDashboard.tsx` — Main dashboard page at `/risk`:
    - Portfolio heat gauge (total risk as % of equity)
    - VaR display with confidence interval visualization
    - Correlation heatmap (d3 or recharts)
    - Concentration pie chart
    - Position sizing method selector per deployment
    - Stress test quick-run panel
  - `features/risk/VaRChart.tsx` — Historical VaR time series with breach highlights
  - `features/risk/CorrelationHeatmap.tsx` — Interactive correlation matrix
  - `features/risk/ConcentrationChart.tsx` — Treemap or pie chart of holdings

- Backend alerting:
  - `services/api/services/risk_alert_service.py` — Alert rules:
    - VaR exceeds configured threshold → alert
    - Concentration (single position > X% of portfolio) → alert
    - Correlation spike (pairwise > 0.9) → alert
    - Dispatch via IncidentManager (Phase 6 M13)
  - Scheduled Celery task: `compute_risk_metrics` runs every 15 minutes,
    evaluates alert rules, dispatches notifications

- Route: `/risk` in frontend router with `deployments:read` scope guard

- Tests:
  - Frontend: dashboard rendering, heatmap interaction, gauge boundaries
  - Backend: alert rule evaluation, threshold breach detection
  - Integration: scheduled task → alert → incident manager dispatch

**Acceptance criteria:**
- Risk dashboard loads in < 3 seconds with all visualizations
- VaR breach triggers PagerDuty/Slack alert via IncidentManager
- Correlation heatmap correctly renders symmetric matrix with color scale
- Concentration chart updates when positions change

---

## Track: Strategy Intelligence

### M12 — Backtesting Engine Enhancement

**Objective:** Connect the technical indicator library to the research engine
so that backtests can evaluate indicator-based strategy rules against
historical market data from the market data repository.

**Context:** Phase 2 built the research engine that evaluates strategy DSL
rules. M4–M7 built the indicator library. This milestone wires them together
so that `MACD(12,26,9) > 0` in a strategy rule actually computes MACD from
historical candles during a backtest.

**Deliverables:**

- `services/worker/research/indicator_resolver.py` — Indicator resolver:
  - Parses indicator references from DSL rules
  - Fetches required candle data from market data repository
  - Computes indicators via IndicatorEngine
  - Caches computed indicators within a single backtest run
  - Handles lookback period requirements (fetches extra candles before start date)

- `services/worker/research/research_engine.py` — Modified:
  - Inject IndicatorResolver as dependency
  - DSL rule evaluation calls resolver for indicator values
  - Time-alignment: indicator values matched to backtest bar timestamps

- `libs/contracts/research.py` — Extended:
  - `BacktestConfig` extended with `indicator_cache_size` and `lookback_buffer_days`
  - `BacktestResult` extended with `indicators_computed` (list of indicator names used)

- Tests:
  - Unit tests for IndicatorResolver (mocked market data repo + engine)
  - Integration test: full backtest with MACD crossover strategy on real candle data
  - Verify: indicator lookback does not cause array index errors at backtest start

**Acceptance criteria:**
- Backtest with `MACD(12,26,9).signal > MACD(12,26,9).value` correctly identifies
  crossover signals matching manual calculation
- Lookback buffer fetches 26 extra candles (max slow period) before backtest start date
- Indicator cache prevents redundant computation of same indicator across multiple rules
- Backtest result includes list of indicators that were computed

---

### M13 — Strategy Performance Comparison and Ranking

**Objective:** Enable operators to compare multiple strategies side-by-side
across risk-adjusted performance metrics, enabling data-driven strategy
selection for live deployment.

**Deliverables:**

- `libs/contracts/strategy_comparison.py` — Contracts:
  - `StrategyRankingCriteria` enum: `SHARPE_RATIO`, `SORTINO_RATIO`, `CALMAR_RATIO`,
    `MAX_DRAWDOWN`, `WIN_RATE`, `PROFIT_FACTOR`, `NET_PNL`, `RISK_ADJUSTED_RETURN`
  - `StrategyComparisonRequest`: strategy_ids (list), date_range, ranking_criteria
  - `StrategyComparisonResult`: rankings (list of StrategyRank), comparison_matrix,
    computed_at
  - `StrategyRank`: strategy_id, strategy_name, rank, metric_values (dict)

- `services/api/services/strategy_comparison_service.py` — Implementation:
  - Fetch P&L timeseries for each strategy from PnlAttributionService
  - Compute additional metrics:
    - Sortino ratio (downside deviation only)
    - Calmar ratio (annualized return / max drawdown)
    - Profit factor (gross profit / gross loss)
    - Risk-adjusted return (Sharpe × sqrt(252))
  - Rank strategies by selected criteria
  - Comparison matrix: all strategies × all metrics

- API endpoints:
  - `POST /strategies/compare` — Compare strategies by criteria
  - `GET /strategies/{id}/metrics` — Per-strategy expanded metrics

- Frontend:
  - `features/strategy/StrategyComparison.tsx` — Multi-strategy comparison table
    with sortable columns, rank badges, sparkline equity curves
  - `features/strategy/StrategyMetrics.tsx` — Expanded single-strategy metrics card

- Tests:
  - Unit tests for each metric calculation
  - Sortino ratio: penalizes downside volatility more than Sharpe
  - Calmar ratio with zero drawdown → infinity (capped at configurable max)
  - Ranking is stable for tied values (deterministic tiebreaker)

**Acceptance criteria:**
- Strategy with highest Sharpe ratio ranks #1 when criteria = SHARPE_RATIO
- Sortino ratio ≥ Sharpe ratio when downside volatility < total volatility
- Comparison of 10 strategies returns in < 2 seconds
- Frontend table supports sorting by any metric column

---

### M14 — Candlestick Chart Component and Technical Analysis View

**Objective:** Build a production-quality candlestick chart component that
renders OHLCV data with indicator overlays, enabling visual technical analysis
directly in the FXLab frontend.

**Deliverables:**

- Frontend:
  - `features/charts/CandlestickChart.tsx` — Core chart component:
    - Renders OHLCV candles with green/red coloring
    - Volume bars below price chart
    - Crosshair with price/time display on hover
    - Zoom and pan (mouse wheel, drag)
    - Adaptive rendering: Recharts for < 500 candles, ECharts Canvas for ≥ 500
    - Responsive to container width
    - ARIA labels for accessibility

  - `features/charts/IndicatorPanel.tsx` — Overlay and sub-chart indicators:
    - Overlays (on price chart): SMA, EMA, Bollinger Bands, Keltner
    - Sub-charts (below price): MACD histogram, RSI, Stochastic, OBV, MFI
    - Indicator selector: add/remove indicators with parameter configuration
    - Color coding per indicator (configurable)

  - `features/charts/ChartToolbar.tsx` — Toolbar:
    - Interval selector (1m, 5m, 15m, 1h, 1d)
    - Date range picker
    - Indicator add/remove
    - Fullscreen toggle
    - Screenshot/export

  - Route: `/charts/{symbol}` or embedded in strategy detail pages

- Tests:
  - Rendering tests for candle chart with various data shapes
  - Indicator overlay positioning relative to price axis
  - Zoom/pan state management
  - Accessibility: ARIA labels, keyboard navigation

**Acceptance criteria:**
- 500 daily candles render in < 500ms initial paint
- Indicator overlays align correctly with candle timestamps
- Zoom preserves indicator alignment (no drift)
- Volume bars scale independently from price axis
- Green candle when close > open, red when close < open

---

### M15 — Phase 7 Acceptance Test Pack and Documentation

**Objective:** Comprehensive acceptance testing across all Phase 7 deliverables,
documentation update, and quality gate verification.

**Deliverables:**

- Acceptance test suite:
  - End-to-end: Alpaca data collection → candle storage → indicator computation →
    backtest execution → strategy comparison → risk analytics
  - Market data pipeline: collect → store → query → stream round-trip
  - Indicator accuracy: cross-validation against TA-Lib reference for all indicators
  - Risk analytics: VaR computation with known historical data → expected result
  - Frontend: Candlestick chart with indicators renders correctly from API data

- Documentation updates:
  - `DEPLOYMENT.md` updated with market data pipeline configuration
  - `DEPLOYMENT.md` updated with indicator engine configuration
  - `DEPLOYMENT.md` updated with risk analytics alert thresholds
  - API documentation for all new endpoints
  - Operator guide: how to set up market data collection, configure indicators,
    interpret risk dashboard

- Quality gates:
  - Backend: ≥ 85% coverage on new code
  - Frontend: all new components have Vitest tests
  - Zero linting, type, or security findings
  - CI pipeline green with all Phase 7 tests included

- Performance benchmarks:
  - Market data collection: 10,000 candles/batch in < 5 seconds
  - Indicator computation: 20 indicators on 10,000 candles in < 1 second
  - VaR computation: 50-position portfolio in < 500ms
  - Candlestick chart: 1,000 candles with 3 overlays in < 1 second render

- Tests:
  - All acceptance criteria from M0–M14 verified in automated tests
  - Regression: existing Phase 1–6 tests continue to pass
  - Load tests for market data and indicator endpoints

**Acceptance criteria:**
- All 15 prior milestone acceptance criteria pass in automated test suite
- Zero regression in existing Phase 1–6 test suites
- Documentation covers all new operational procedures
- Performance benchmarks meet or exceed targets
- CI pipeline completes in < 10 minutes including Phase 7 tests
