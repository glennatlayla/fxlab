# FXLab Strategy Execution Buildout — Agent Orchestration Workplan

**Author:** Claude (with Glenn)
**Created:** 2026-04-25
**Status:** Draft for Glenn's review — no implementation begins until this document is approved.

---

## REVISION SUMMARY

- **v1.0 (2026-04-25)** — Initial decomposition. 5 agents, 25 milestones, ~12 working days of parallel effort.

---

## MILESTONE INDEX (per CLAUDE.md §16 Rule 1)

```
MILESTONE INDEX
───────────────────────────────────────────────────────────────
Total milestones: 25
Tracks: A (Schema/Compiler), B (Indicators), C (API), D (Frontend), E (Forex Data)

Track A — Schema + Compiler   (critical-path):  M1.A1, M1.A2, M1.A3, M1.A4, M1.A5
Track B — Indicator coverage  (parallel after A1):
                                                  M1.B1, M1.B2, M1.B3, M1.B4, M1.B5, M1.B6
Track C — API + run plumbing  (after A3):       M2.C1, M2.C2, M2.C3, M2.C4
Track D — Frontend            (parallel after C contracts published):
                                                  M2.D1, M2.D2, M2.D3, M2.D4
Track E — Forex market data   (independent):    M4.E1, M4.E2, M4.E3, M4.E4

Cross-track integration milestones:             M3.X1 (end-to-end backtest one strategy),
                                                M3.X2 (all-five-strategies backtest)
───────────────────────────────────────────────────────────────
```

This block is the canonical source of truth for milestone scope. Any
distillation of this document MUST honour the integrity-header
discipline in CLAUDE.md §16 Rule 2.

---

## EXECUTIVE SUMMARY

The user wants to (a) load strategy packs from `Strategy Repo/` via
Strategy Studio, (b) backtest them, (c) eventually paper-trade them
against configurable FX pairs.

**The honest scope:** 25 milestones, organised into five agent tracks.
A single agent working sequentially would take ~6 weeks. Five agents
working with the dependency graph below complete the backtesting path
(Tracks A + B + C + D + E1) in ~12 working days, with acceptance gate
at **M3.X2 — every strategy in the repo runs end-to-end through the UI**.

Paper trading (Phase 4 work) is explicitly **out of scope** for this
workplan. Adding it would double the timeline because of risk-gate
and reconciliation requirements. A separate workplan covers it.

**What ships at acceptance:**
- Pydantic schema for `strategy_ir.json`, validated against every
  IR file in `Strategy Repo/`.
- IR → `SignalStrategy` compiler that the existing `BacktestEngine`
  consumes unchanged.
- All indicators referenced by the five repo strategies, implemented
  in `libs/indicators/` and exercised by tests against real bars.
- Lookback-notation support (`_prev_1`, `_prev_2`, …) in the engine.
- Forex `MarketDataProvider` populating the existing
  `market_data` table for the six majors at the timeframes the
  strategies require (1h / 4h / 1d).
- API endpoints to import an IR, submit a run from IR + experiment
  plan, and read results.
- Strategy Studio UI: "Load from repo" panel, IR detail view, run
  submit form, results viewer (equity curve, drawdown, blotter,
  metrics).

---

## AGENT TOPOLOGY

```
                         ┌──────────────┐
                         │  Track E     │  ← independent, can start day 1
                         │  Forex Data  │
                         └──────────────┘
                                │
                                ▼ (FX bars in market_data table)
   ┌──────────────┐                   ┌──────────────┐
   │  Track A     │ M1.A1 IR schema   │  Track B     │
   │ Schema +     │ ───────────────►  │  Indicator   │ ← parallel after A1
   │ Compiler     │                   │  coverage    │
   └──────────────┘                   └──────────────┘
        │                                   │
        │ M1.A3 compiler                    │ M1.B6 derived_fields
        │ (consumes B's registry)           │
        ▼                                   ▼
        ┌─────────────────────────────────────┐
        │   M3.X1 — single-strategy backtest  │ ← integration gate
        │   (CLI, no UI, against real FX)     │
        └─────────────────────────────────────┘
                          │
        ┌──────────────┐  │  ┌──────────────┐
        │  Track C     │ ◄┴► │  Track D     │
        │  API endpts  │     │  Frontend    │ ← parallel via published contracts
        └──────────────┘     └──────────────┘
                          │
                          ▼
        ┌─────────────────────────────────────┐
        │   M3.X2 — all five strategies via   │ ← FINAL acceptance
        │   the UI, end-to-end                │
        └─────────────────────────────────────┘
```

**Critical path:** A1 → A3 → X1 → C2/D3 → X2.
**Maximum parallelism:** 5 agents, all five tracks running simultaneously
once A1's schema interface is published (typically end of day 1).

---

## AGENT BRIEFS

Each brief is **self-contained**: an agent given only this document
and the existing repo can execute the assigned tranches with no
verbal clarification. Every tranche follows the established rhythm:

1. Archive any files about to change (per CLAUDE.md §1).
2. Write the failing test (TDD red).
3. Implement the minimum to pass (green).
4. `make verify` clean (Tranche G).
5. Commit atomically with a message that names the tranche ID.

**No agent ships a stub** (CLAUDE.md §0). If a tranche cannot land
production-grade in the budgeted scope, the agent stops, reports the
blocker, and waits for guidance — exactly the rhythm we ran for
Tranches A–L.

---

### AGENT A — Schema + Compiler

**Mission:** Build the layer that turns a `strategy_ir.json` file into
something the existing `BacktestEngine` already consumes. This is the
critical path — every other agent eventually waits on Agent A.

**Dependencies:** None. Starts immediately.

**Hands off:**
- A typed Pydantic model `StrategyIR` (and child models) at
  `libs/contracts/strategy_ir.py`.
- A `StrategyIRParser` at `libs/strategy_ir/parser.py` that loads,
  validates, and version-checks any IR JSON.
- A `StrategyIRCompiler` at `libs/strategy_ir/compiler.py` that
  produces an instance implementing the existing
  `SignalStrategyInterface` from a parsed `StrategyIR`.

**Tranches:**

#### M1.A1 — Pydantic schema for strategy_ir.json
- Define `StrategyIR` root model + child models for every section
  observed in the repo: `Metadata`, `Universe`, `DataRequirements`,
  `Indicator` (discriminated union by `type`), `EntryLogic`,
  `ConditionTree`, `LeafCondition`, `ExitLogic` with all variants
  (`atr_multiple`, `risk_reward_multiple`, `mean_reversion_to_mid`,
  `channel_exit`, `calendar_exit`, `basket_atr_multiple`,
  `basket_open_loss_pct`, `opposite_inner_band_touch`,
  `middle_band_close_violation`), `RiskModel`, `ExecutionModel`,
  `Filter`, `BasketTemplate`, `BasketLeg`, `DerivedField`,
  `AmbiguitiesAndDefaults`.
- Validate `schema_version` is `"0.1-inferred"` (until promoted) and
  `artifact_type == "strategy_ir"`.
- **Acceptance:** parametrised pytest loads each of the 5 IR files in
  `Strategy Repo/` without ValidationError; rejects 5 hand-crafted
  malformed inputs (missing required field, wrong artifact_type,
  unknown indicator type, etc.).

#### M1.A2 — Reference resolver
- Resolve indicator IDs referenced in conditions to their definitions
  (e.g. `lhs: "ema_fast"` → the indicator with `id: "ema_fast"`).
- Resolve cross-timeframe references (`close_1h`, `close_1d`).
- Build a dependency DAG of indicators → derived_fields → conditions
  so the engine evaluates in topological order.
- **Acceptance:** unit tests parametrised over each repo strategy
  produce a closed dependency graph with no missing references; a
  hand-crafted IR with a dangling reference (`lhs: "missing_id"`)
  fails fast with a useful error.

#### M1.A3 — IR → SignalStrategy compiler (the linchpin)
- Implement a class that takes a `StrategyIR` and returns an instance
  satisfying `SignalStrategyInterface` (the contract `BacktestEngine`
  already consumes).
- Translate AND/OR condition trees into deterministic Python
  evaluators that consume bar streams + indicator values.
- Inject `evaluation_timing` (`on_bar_close`) and `execution_timing`
  (`next_bar_open`) per the IR.
- Wire entry logic separately for long and short.
- Wire exit logic with `same_bar_priority` resolved at compile time.
- **Acceptance:** integration test feeds 30 days of synthetic bars
  through a compiled strategy and asserts the trade blotter matches a
  hand-computed expected blotter (e.g., "with these EMA crosses, we
  expect 3 trades at these timestamps with these P&Ls").

#### M1.A4 — Lookback notation handler
- Support `_prev_N` suffix on any indicator ID or price field
  (`bb_mid_prev_1`, `close_prev_2`).
- Engine maintains a per-indicator ring buffer sized to the maximum
  observed N across all IR conditions.
- **Acceptance:** the DoubleBollinger strategy compiles and produces
  signals only on the bar immediately after a `close < bb_upper_1`
  → `close >= bb_upper_1` transition, verified against synthetic data.

#### M1.A5 — Risk model + sizing translation
- Translate `risk_model.position_sizing.method == "fixed_fractional_risk"`
  into the engine's existing position-sizing pathway.
- Translate `daily_loss_limit_pct` and `max_drawdown_halt_pct` into
  pre-trade and post-trade gate checks consumed by `BacktestEngine`.
- Out of scope: `fixed_basket_risk` + `inverse_volatility_by_leg`
  (Turn-of-Month). That ships as a follow-up tranche M3.X2.5 once
  basket execution is wired.
- **Acceptance:** a strategy with `risk_pct_of_equity: 0.5` produces
  trades whose stop-distance × position size ≤ 0.5% of equity at
  entry, verified at every entry bar in the test trade blotter.

**Estimated tranches:** 5. **Estimated effort:** 4 working days for one
agent. **Critical path.**

---

### AGENT B — Indicator coverage

**Mission:** Implement every indicator referenced by the five repo
strategies that doesn't already exist in `libs/indicators/`.

**Dependencies:** Agent A's schema (M1.A1) — needs to know the
indicator-type discriminator vocabulary. Once A1 lands, Agent B runs
fully in parallel with the rest of A.

**Hands off:** Extended `IndicatorRegistry` covering every type
referenced by every IR in `Strategy Repo/`.

**Tranches:**

#### M1.B1 — ADX (Average Directional Index)
- Standard Wilder ADX with configurable `length`.
- Used by FX_TimeSeriesMomentum_Breakout_D1.
- **Acceptance:** numeric output matches a reference implementation
  (e.g., `pandas-ta`) within 1e-6 across 500 bars of EURUSD daily.

#### M1.B2 — z-score indicator
- Compute `(value - mean_source) / std_source` where
  `mean_source` and `std_source` are references to other indicator
  IDs (e.g. `bb_mid` and `bb_std`).
- Used by FX_SingleAsset_MeanReversion_H1.
- **Acceptance:** z-score across 500 bars matches manual numpy
  calculation within 1e-9; passes when `std_source == 0` by
  returning `nan` and logging once at WARN.

#### M1.B3 — Rolling extremes
- `rolling_high`, `rolling_low`, `rolling_max`, `rolling_min` with
  configurable `length_bars`.
- Used by FX_TimeSeriesMomentum_Breakout_D1 (Donchian),
  FX_MTF_DailyTrend_H1Pullback (swing high/low for Fib).
- **Acceptance:** rolling-window output matches `pandas.rolling().max()`
  / `.min()` exactly across edge cases (window larger than series,
  NaN at series start).

#### M1.B4 — Rolling stddev
- `rolling_stddev` with configurable `length_bars`. Population vs
  sample stddev: pick **sample** (denominator N-1) to match the
  Bollinger-Band convention used elsewhere in the repo, document the
  choice in the docstring.
- Used by FX_SingleAsset_MeanReversion_H1.
- **Acceptance:** matches `numpy.std(..., ddof=1)` to 1e-12.

#### M1.B5 — Calendar indicators
- `calendar_business_day_index` — emits the business-day index of the
  current bar's date within its month.
- `calendar_days_to_month_end` — emits the count of remaining
  business days in the bar's month.
- Used by FX_TurnOfMonth_USDSeasonality_D1.
- **Decision point for Glenn:** what calendar? FX trading is 24/5, so
  the relevant business calendar is "weekdays minus FX market
  holidays." Proposal: use `pandas_market_calendars` with the FX
  calendar; lock the choice in CLAUDE.md as the canonical FX
  calendar. **Agent must wait for Glenn's approval on this choice
  before implementing.**
- **Acceptance:** unit test against a hand-computed calendar for
  March/April/December (year-end edge case).

#### M1.B6 — Derived-fields formula evaluator
- Implement a safe expression evaluator that handles the formulas
  observed in the repo:
  `swing_high_h1 - ((swing_high_h1 - swing_low_h1) * 0.382)`
- Operators: `+ - * /`, parentheses, references to other indicator
  IDs. **No `eval()`.** Parse with `ast.parse` in `mode='eval'` and
  whitelist `ast.Add, Sub, Mult, Div, Name, Constant, BinOp,
  UnaryOp, USub`.
- **Acceptance:** parametrised tests over the 4 Fibonacci formulas
  in MTF Pullback produce numerically correct results; an injection
  attempt (`__import__('os').system('rm -rf /')`) is rejected with a
  `ValueError` at parse time, not at eval time.

**Estimated tranches:** 6. **Estimated effort:** 3 working days. Runs
in parallel with Agent A (after A1).

---

### AGENT C — API + run plumbing

**Mission:** Add the REST endpoints needed to import an IR file,
submit a backtest run from IR + experiment_plan, and read results.

**Dependencies:** Agent A's `StrategyIR` and `StrategyIRCompiler`
(M1.A3). Until those publish their public types, Agent C develops
against a mocked `StrategyIR` shape that mirrors the v1 schema.

**Hands off:**
- `POST /strategies/import-ir` — accepts a multipart upload of
  `strategy_ir.json` (and optionally the matching `search_space.json`
  + `experiment_plan.json`); validates; persists; returns the
  strategy ID.
- `POST /runs/from-ir` — accepts a `strategy_id` (from a prior
  import) plus an embedded or referenced `experiment_plan` and
  enqueues a `ResearchRun` with `run_type=BACKTEST`.
- `GET /runs/{run_id}/results/equity-curve`,
  `GET /runs/{run_id}/results/blotter`,
  `GET /runs/{run_id}/results/metrics` — already partially exist;
  audit and extend.

**Tranches:**

#### M2.C1 — POST /strategies/import-ir
- Multipart endpoint. Validates with `StrategyIRParser`. Persists via
  `StrategyService.create_from_ir(...)`.
- Authz: requires `strategies:write` scope (matches Tranche L).
- Audit log entry per CLAUDE.md §8: structured log
  `event=strategy_imported strategy_id=... source=ir_upload`.
- **Acceptance:** contract test posts each of the 5 repo IR files
  and gets a 201 with the new strategy_id; posting a malformed IR
  returns 400 with the validation error path.

#### M2.C2 — POST /runs/from-ir
- Endpoint accepts `{"strategy_id": "...", "experiment_plan": {...}}`.
- Validates the experiment plan against a Pydantic model
  (`ExperimentPlan` — Agent C owns this contract; mirrors the example
  in `User Spec/`).
- Resolves `dataset_ref` via the new `DatasetService` (Track E
  publishes this; until E1 lands, Agent C accepts a literal
  `dataset_ref` string and looks it up against an in-memory map).
- Builds a `ResearchRunConfig`, submits via `ResearchRunService`,
  returns the `run_id`.
- Authz: `runs:write`.
- **Acceptance:** integration test imports an IR, posts an
  experiment_plan, polls `GET /runs/{run_id}` until status=COMPLETED,
  reads metrics, asserts shape.

#### M2.C3 — Results endpoints expansion
- Audit existing `GET /runs/{run_id}/results` paths. Add the
  three sub-endpoints listed above if missing. Pagination on
  `/blotter` (default 100 trades/page).
- **Acceptance:** schema-locked contract tests; pagination tests
  with 1000-trade synthetic blotter.

#### M2.C4 — Strategy detail with parsed IR
- `GET /strategies/{id}` returns the parsed IR alongside the legacy
  draft fields, with a `source: "ir_upload" | "draft_form"` flag so
  the frontend renders the correct view.
- **Acceptance:** the 5 imported repo strategies each round-trip
  through this endpoint with deep-equal IR bodies.

**Estimated tranches:** 4. **Estimated effort:** 2.5 working days.

---

### AGENT D — Frontend Strategy Studio + Results

**Mission:** Make the user-facing flow real: import an IR, see it,
submit a backtest, see equity curves and a blotter.

**Dependencies:** Agent C's API contracts. Develops against the
OpenAPI spec C publishes after M2.C1; can mock until C ships.

**Hands off:** Functional Strategy Studio "Load from repo" flow plus
a results viewer page.

**Tranches:**

#### M2.D1 — "Load from repo" panel
- Add a new tab in Strategy Studio: "Import from file".
- File-drop zone or file picker accepting `*.strategy_ir.json`.
- POSTs to `/strategies/import-ir`.
- On success, navigates to `/strategy-studio/{id}`.
- **Acceptance:** vitest component test renders the panel, simulates
  a file drop, asserts the correct multipart POST body, asserts
  navigation on 201.

#### M2.D2 — IR detail view
- Read-only render of the parsed IR: indicators, entry/exit logic
  trees, risk model, ambiguities. Uses an opinionated layout that
  mirrors the spec doc's section ordering (A through J).
- **Acceptance:** snapshot tests for each of the 5 imported repo
  strategies; visual regression-style.

#### M2.D3 — "Run backtest" flow
- On the strategy detail page, an "Execute backtest" button opens a
  modal with the experiment plan (loaded from the matching
  `*.experiment_plan.json` if uploaded alongside, or hand-edited).
- Submit triggers `POST /runs/from-ir`. Page transitions to the run
  monitor with the new run_id pinned.
- **Acceptance:** vitest test for the modal; e2e test (Playwright)
  that imports an IR, runs a backtest, waits for completion, lands
  on results page.

#### M2.D4 — Results viewer page
- New route `/runs/{run_id}/results` (renders for any completed run).
- Three sections: metrics tile grid (return, Sharpe, max DD, win
  rate, profit factor, trade count), equity-curve + drawdown chart
  pair (recharts), trade blotter (sortable / paginated table).
- **Acceptance:** visual + functional tests; loads metrics from
  `/runs/{id}/results/metrics`; renders 100 trades from
  `/runs/{id}/results/blotter`.

**Estimated tranches:** 4. **Estimated effort:** 3 working days.

---

### AGENT E — Forex market data

**Mission:** Get FX bars into the existing `market_data` table for
the six majors at the timeframes the strategies need (1h, 4h, 1d).
Without this, even a perfectly-built backtest path runs against
empty data.

**Dependencies:** None. Independent. Starts day 1.

**Hands off:**
- A `ForexMarketDataProvider` implementing
  `MarketDataProviderInterface`.
- Backfilled historical FX bars in `market_data`, indexed by symbol
  + interval, covering the date ranges in each strategy's
  `experiment_plan.json` (2010-01-01 onward for the deepest splits).
- A `dataset_ref` resolution mechanism so `experiment_plan.dataset_ref`
  values like `fx-eurusd-15m-certified-v3` resolve to a versioned
  rows-set, not just "everything in the table."

**Tranches:**

#### M4.E1 — Forex provider selection (DECISION GATE)
- **Glenn must choose a forex data source before this tranche
  begins.** Options:

  | Option | Cost | Coverage | API quality | Real-time |
  |---|---|---|---|---|
  | **Oanda v20 REST** | free w/ live account | EOD + intraday | excellent | yes |
  | **Dukascopy historical CSV** | free | 2003+, tick & bar | manual download | no |
  | **TwelveData** | free tier 800 req/day | 1m+ | OK | limited |
  | **Polygon FX** | $99/mo+ | full intraday | excellent | yes |
  | **CSV import (manual)** | zero | whatever you load | none | no |

- **Recommendation:** start with **Dukascopy historical CSV** for
  backtesting (no API rate limits, no cost, deepest history). Add
  **Oanda v20** later for live/paper. Defer real-time decision to
  Phase 4.
- This is an infra choice per the operator memory; agent does not
  proceed without explicit Glenn approval.

#### M4.E2 — `ForexMarketDataProvider` adapter
- Implements `MarketDataProviderInterface` against the chosen source.
- Maps source bars to the canonical `Candle` contract.
- Error handling: rate-limit, retry-with-backoff, gap detection.
- Authz: read-only against the source.
- **Acceptance:** integration test fetches 30 days of EURUSD 1h
  bars from the source, asserts contiguous OHLC, asserts spread
  field populated when source provides it.

#### M4.E3 — Dataset versioning
- A `dataset` table with `(name, version, symbol, interval,
  start_date, end_date)` rows.
- A `DatasetService.resolve(dataset_ref) -> list[Candle]` that
  returns bars for the named, versioned dataset.
- An admin CLI tool (`python -m services.api.cli.import_dataset
  --name fx-eurusd-1h --version 2026.04.bootstrap --source dukascopy
  --symbol EURUSD --interval H1 --start 2010-01-01`) to ingest a
  versioned snapshot.
- **Acceptance:** CLI ingests 14 years of EURUSD H1 from the chosen
  source; `DatasetService.resolve("fx-eurusd-1h:2026.04.bootstrap")`
  returns the bars; a stale version reference returns a clear error.

#### M4.E4 — Backfill all six majors
- Orchestrate ingestion for EURUSD, GBPUSD, USDJPY, AUDUSD, NZDUSD,
  USDCAD at 1h, 4h, 1d timeframes from each strategy's earliest
  `splits.in_sample.start` (2010 for Turn-of-Month, 2021 for the
  example).
- Persist as one versioned dataset per (symbol, interval).
- **Acceptance:** smoke script `make verify-fx-data` queries each
  expected `(symbol, interval)` pair and asserts ≥99% bar coverage
  across the expected date range.

**Estimated tranches:** 4. **Estimated effort:** 3 working days
(mostly waiting on data downloads).

---

## INTEGRATION MILESTONES

### M3.X1 — Single-strategy end-to-end backtest (CLI)

**Trigger:** A1, A3, A4, A5, B1, B3, E2, E4 all green.

**Deliverable:** A repl session like:
```python
>>> from libs.strategy_ir.parser import StrategyIRParser
>>> from libs.strategy_ir.compiler import StrategyIRCompiler
>>> from services.worker.research.backtest_engine import BacktestEngine
>>> ir = StrategyIRParser.from_file("Strategy Repo/.../FX_TimeSeriesMomentum_Breakout_D1.strategy_ir.json")
>>> strategy = StrategyIRCompiler().compile(ir)
>>> result = BacktestEngine(...).run(strategy, symbols=["EURUSD"], start="2021-01-01", end="2023-12-31")
>>> result.metrics.sharpe_ratio
0.84
>>> len(result.trades)
167
```

**Acceptance test:** `tests/integration/test_strategy_ir_backtest_e2e.py`
runs this exact sequence and asserts non-empty trade list + metric
shape (no specific numeric thresholds — those depend on the data).

This gate proves the foundation works. Tracks C and D resume
parallel work after this point with confidence the underlying engine
is real.

### M3.X2 — Five-strategies via UI (final acceptance)

**Trigger:** all milestones complete.

**Deliverable:** an operator can:
1. Open Strategy Studio at `http://192.168.1.5/strategy-studio`.
2. Click "Import from file", upload one of the five
   `*.strategy_ir.json` files plus its experiment_plan.
3. See the IR rendered in the detail view.
4. Click "Execute backtest", confirm the experiment plan, submit.
5. Wait for the run to complete (poll the run-monitor page).
6. View metrics + equity curve + blotter on the results page.

**Acceptance test:** a Playwright e2e test runs all five strategies
in sequence and asserts each lands on a results page with at least
one trade. (The Turn-of-Month basket strategy may need M3.X2.5 for
basket execution if not done by then.)

---

## SEQUENCING & MILESTONE CALENDAR

```
Day  Track A           Track B          Track C            Track D            Track E
─────────────────────────────────────────────────────────────────────────────────────────
1    M1.A1 schema      ── (waits A1)    ── (waits A3)      ── (waits C1)      M4.E1 source choice → DECISION GATE
2    M1.A2 references  M1.B1 ADX        M2.C1 import-ir    M2.D1 file panel   M4.E2 provider adapter
3    M1.A3 compiler    M1.B2 z-score    M2.C2 from-ir      M2.D2 IR view      M4.E3 dataset svc
4    M1.A4 lookback    M1.B3 rolling    M2.C3 results API  M2.D3 backtest UI  M4.E4 backfill (running)
5    M1.A5 risk        M1.B4 stddev     M2.C4 detail GET   M2.D4 results view M4.E4 (continued)
6    ─────────────── INTEGRATION GATE: M3.X1 single-strategy CLI backtest ───────────────
7    (basket support) M1.B5 calendar   (cleanup)          (e2e tests)        (validation)
                                                                              DECISION GATE
8    (basket support) M1.B6 derived    (perf review)      (results polish)   (cleanup)
9    ─────────────── FINAL ACCEPTANCE: M3.X2 five-strategies via UI ─────────────────────
```

Five agents for nine working days plus integration gates. A single
agent doing the same work serially: ~28 working days.

---

## DECISION GATES requiring Glenn's approval

These are the points where the agent stops and waits, per the
operator memory `feedback_ask_before_infra_choices`:

1. **M4.E1 — Forex data source choice.** Five real options listed
   above; recommendation = Dukascopy CSV for now, Oanda later.
   Cost, coverage, latency tradeoffs.
2. **M1.B5 — FX business calendar choice.** Proposal: use
   `pandas_market_calendars` with the FX-24/5 schedule plus a
   curated holiday list. Document in CLAUDE.md as the canonical
   reference. Alternative: hand-roll a calendar in
   `libs/calendars/fx.py`.
3. **M2.C2 — `dataset_ref` syntax.** Proposed format
   `<name>:<version>` (e.g. `fx-eurusd-1h:2026.04.bootstrap`).
   Alternative: separate `name` and `version` fields in the
   experiment plan. Cleaner separation but requires updating every
   experiment_plan in `Strategy Repo/`.
4. **Out-of-band: Phase 4 paper-trading.** Not in this workplan.
   Open question: when to start? After M3.X2 acceptance is the
   recommendation.

Each agent's brief explicitly stops at its decision-gate tranche and
posts the question before proceeding.

---

## QUALITY GATES

Every tranche, every agent:

- [ ] TDD red → green → refactor cycle followed.
- [ ] `make verify` clean (format-check, lint, test-unit,
      compose-check) before commit.
- [ ] Atomic commit with `Tranche M<x>.<track><n> — <summary>` in
      the subject line.
- [ ] No stubs, no `pass`, no `NotImplementedError`, no commented-out
      code (CLAUDE.md §0).
- [ ] Docstring shape: Purpose / Responsibilities / Does NOT /
      Dependencies / Raises / Example (CLAUDE.md §7).
- [ ] Structured logging at component boundaries (CLAUDE.md §8).
- [ ] Mock implementations live alongside interfaces under
      `mocks/` (CLAUDE.md §10).

The whole workplan acceptance gate (M3.X2) requires:

- [ ] All 25 milestones DONE per the progress file.
- [ ] Aggregate ≥80% line coverage on touched code, ≥85% on new
      modules, ≥90% on `libs/strategy_ir/` and
      `libs/indicators/` additions (CLAUDE.md §5).
- [ ] No security findings ≥ medium.
- [ ] One end-to-end integration test that exercises every track
      simultaneously (`tests/integration/test_strategy_ir_e2e.py`).
- [ ] Updated CLAUDE.md §17 if any new operator workflows appear.

---

## OUT OF SCOPE — explicitly deferred

These are real, but not part of this workplan. Each gets its own
workplan when prioritised:

- **Paper trading** (`PaperBrokerAdapter` orchestration, live data,
  risk gates, reconciliation). Phase 4. Estimated 8–12 tranches.
- **Live trading** (Alpaca / Schwab / Oanda for real-money orders).
  Phase 4. Risk-gate work doubles the effort.
- **Walk-forward + Monte Carlo execution.** The `ResearchRunConfig`
  models `WalkForwardConfig` and `MonteCarloConfig` exist; the
  engine paths are stubs in this audit's findings. Adding them
  shifts the calendar by ~5 days.
- **Strategy authoring (visual editor) for net-new strategies.**
  Strategy Studio's existing draft form is preserved unchanged; this
  workplan only adds the import path. Visual editor for IR is a
  Phase 5+ concern.
- **Multi-strategy portfolio backtests.** The repo's strategies
  trade independently. Cross-strategy interactions, capital
  allocation, correlation gates: future work.
- **Promotion / governance flows for repo-imported strategies.**
  The Approvals page exists; integrating IR-imported strategies into
  the promotion workflow is a small extension but not in scope here.

---

## RISKS

| # | Risk | Mitigation |
|---|---|---|
| 1 | Repo IRs use a feature my Pydantic model didn't anticipate | M1.A1 acceptance test loads ALL 5 repo files. Fail fast on day 1. |
| 2 | Indicator numerics drift from reference impls | Every indicator tranche compares to `pandas-ta` or `numpy` to 1e-6+. |
| 3 | Dukascopy CSVs have data quality issues (gaps, weekend bars) | M4.E2 includes gap detection; M4.E4 acceptance asserts ≥99% coverage. |
| 4 | BacktestEngine `SignalStrategyInterface` doesn't admit our compiled output | Mitigate at M1.A3: spike-test the integration in 2 hours before completing the rest of A3; if mismatch, propose extending the interface as a separate small tranche. |
| 5 | Forex calendar holidays are subjective | Lock the choice in M1.B5 decision gate; document in CLAUDE.md so reviewers don't second-guess. |
| 6 | Five-agent coordination overhead exceeds the parallelism win | Each agent's brief is self-contained; integration only at X1 and X2 gates. |

---

## HANDOFF — what each agent gets

**A common operator launches each agent** with the exact assignment:

> *Read `docs/workplan/2026-04-25-strategy-execution-agent-orchestration.md` and execute Track <X> tranches in order. Do not start tranche N+1 until tranche N's commit has landed and `make verify` is green. At every DECISION GATE, stop and ask Glenn. After each tranche, post a one-paragraph summary linking to the commit.*

The workplan + the existing CLAUDE.md + the existing test patterns
are the entire context an agent needs. No further verbal
clarification should be required.

---

## STATUS TRACKING

A separate progress file at
`docs/workplan/2026-04-25-strategy-execution-progress.md` should be
seeded from this workplan's Milestone Index per CLAUDE.md §16 Rule
3, with every milestone listed as `NOT_STARTED`. Each agent
transitions its assigned milestones as they complete:

```
M1.A1   IR Pydantic schema                        DONE     <commit-sha>
M1.A2   Reference resolver                        IN_PROGRESS
M1.A3   IR → SignalStrategy compiler              NOT_STARTED
...
```

Phase completion (per §16 Rule 4) requires the assertion
`source_count == done_count + open_count` AND `open_count == 0`.

---

## END

This document is the canonical workplan for the strategy execution
buildout. Glenn approves it (or requests revisions) before any
implementation begins. After approval, Glenn's choice of agent
orchestration platform launches the five agents, each pointing at
its assigned track.

Estimated total effort with five agents: **9 working days to
M3.X2 acceptance**, two integration gates, four decision gates, no
stubs, no shortcuts.
