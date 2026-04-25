# FXLab Strategy Execution Buildout — Agent Orchestration Workplan

**Author:** Claude (with Glenn)
**Created:** 2026-04-25
**Status:** Draft for Glenn's review — no implementation begins until this document is approved.

---

## REVISION SUMMARY

- **v1.0 (2026-04-25)** — Initial decomposition. 5 agents, 25 milestones, ~12 working days of parallel effort.
- **v2.0 (2026-04-25)** — Autonomy revision per Glenn's directive: agents do NOT pause at decision gates during execution. Defaults baked in for every previously-named decision gate, with the rationale documented inline. The minimal set of questions that genuinely require Glenn's input before kickoff is consolidated into a new `kickoff` companion doc; agents read those answers at startup and never ask Glenn anything mid-run. Integration model tightened: per-agent feature branches, atomic per-tranche commits, append-only progress logs Glenn can scan at wake-time.
- **v2.1 (2026-04-25)** — Forex provider revision per Glenn's directive: NO manual CSV downloads. Verified Schwab's public Trader API does not expose FX programmatically (the existing `SchwabBrokerAdapter` is equities-only). Switched to **Oanda v20 REST API** as the single provider for both historical FX data AND live broker interface (paper via `fxpractice`, live via `fxtrade`). Track E grows by two tranches (M4.E5 OandaBrokerAdapter, M4.E6 broker registry) so a paper-trade smoke test is part of the M3.X2 hard floor. Total milestones: 27 (was 25).
- **v2.2 (2026-04-25)** — Orchestration revision: Glenn confirmed the run is launched as a single `claude` CLI session on the dev Mac, given this workplan as input. Replaces the previous "5 separate sessions, one per track" execution model with "one Claude Code orchestrator session that spawns Task subagents to parallelize tracks." Adds an ORCHESTRATOR PROTOCOL section that pins down: how to read this plan; how to spawn parallel Task subagents per round; how to resume from `progress.md` after a session interruption; how to commit atomically per tranche so context-fill or rate-limit hits don't lose work. Kickoff doc step 5 reduced to a single launch command.

---

## MILESTONE INDEX (per CLAUDE.md §16 Rule 1)

```
MILESTONE INDEX
───────────────────────────────────────────────────────────────
Total milestones: 27
Tracks: A (Schema/Compiler), B (Indicators), C (API), D (Frontend),
        E (Forex Data + Broker — Oanda v20)

Track A — Schema + Compiler   (critical-path):  M1.A1, M1.A2, M1.A3, M1.A4, M1.A5
Track B — Indicator coverage  (parallel after A1):
                                                  M1.B1, M1.B2, M1.B3, M1.B4, M1.B5, M1.B6
Track C — API + run plumbing  (after A3):       M2.C1, M2.C2, M2.C3, M2.C4
Track D — Frontend            (parallel after C contracts published):
                                                  M2.D1, M2.D2, M2.D3, M2.D4
Track E — Oanda data + broker (independent):    M4.E1, M4.E2, M4.E3, M4.E4, M4.E5, M4.E6

Cross-track integration milestones:             M3.X1 (single-strategy CLI backtest),
                                                M3.X2 (viable candidate via UI +
                                                       paper-trade smoke test)
───────────────────────────────────────────────────────────────
```

This block is the canonical source of truth for milestone scope. Any
distillation of this document MUST honour the integrity-header
discipline in CLAUDE.md §16 Rule 2.

---

## ORCHESTRATOR PROTOCOL (v2.2 — Claude Code single-session model)

The execution model is: **one Claude Code CLI session on the dev Mac
acts as the orchestrator**. It reads this document, dispatches work
to `Task`-tool subagents (which Claude Code spawns in-process for
parallel sub-jobs), commits atomically after each tranche, updates
the progress file, and either continues to the next round or stops
cleanly when context or token budget is exhausted.

If interrupted (rate limit, context full, operator Ctrl-C), the
operator relaunches `claude` with the same prompt; the new session
reads `docs/workplan/2026-04-25-strategy-execution-progress.md`,
finds the first NOT_STARTED milestone, and resumes from there.
Atomic per-tranche commits make the state persistent across
sessions.

### Orchestrator startup ritual (every session, including resumes)

1. **Verify `make verify` is green on `main`.** If not, fix is the
   first task — a broken main poisons every track.
2. **Read `docs/workplan/2026-04-25-strategy-execution-progress.md`**
   to determine which milestones are DONE and which are pending.
3. **Read `docs/workplan/agent_logs/BLOCKED.md`** if it exists.
   If non-empty, halt and surface the block to the operator —
   another session left an unresolved blocker. Do NOT attempt to
   re-execute a blocked tranche; the operator decides the unblock.
4. **Compute the next round of dispatchable tranches.** A tranche
   is dispatchable when every milestone listed in its
   `Dependencies` line is DONE in the progress file.
5. **Dispatch the round in parallel via the `Task` tool**, sending
   all parallel calls in a single message so Claude Code's tool
   harness runs them concurrently. Maximum recommended fan-out per
   round: 5 subagents (matches the documented "send them in a
   single message" pattern). For tranches with no parallelism
   available, dispatch one subagent.
6. **After the round returns**, review each subagent's commit (run
   `git log -1` on each agent branch), run `make verify`, and
   update the progress file.
7. **Decide next action**:
   - If milestones remain dispatchable → goto step 4.
   - If only blocked-on-dependency milestones remain → wait for
     prerequisite tranches, dispatch next round when unblocked.
   - If `M3.X2` hard-floor milestones are all DONE → run the
     M3.X2 acceptance test, mark integration.md, stop with
     success.
   - If context budget is approaching exhaustion → commit any
     pending state, append a `session_handoff` entry to each
     active track log naming the next dispatchable milestone, and
     stop. The operator's next session resumes from progress.md.

### Subagent dispatch contract

Each Task subagent dispatched by the orchestrator receives a
**self-contained brief** — the orchestrator does NOT assume the
subagent has read this document. The brief MUST include:

1. The exact tranche ID (e.g., `M1.A1`).
2. The tranche's full text from this document (copy-paste the
   tranche section).
3. The agent's track brief from the AGENT BRIEFS section.
4. The QUALITY GATES section (CLAUDE.md §0 / §5 / §6 / §7 / §8).
5. The AGENT COORDINATION PROTOCOL — specifically which files this
   tranche may touch and which it must not.
6. An explicit instruction: "When done, return the commit SHA, a
   one-paragraph summary, the test output, and the next
   recommended tranche on this track."

This removes the need for subagents to load the entire workplan into
their context — they get only what their tranche requires. Keeps
the orchestrator's token budget healthy across rounds.

### Atomicity contract

- Every tranche ends in exactly one commit on the agent's branch.
- Commit messages follow the convention in AGENT COORDINATION
  PROTOCOL > "Per-tranche commit convention".
- The orchestrator updates the progress file's status row in the
  SAME commit (or in a follow-up commit before the next dispatch
  round). Never leave a tranche DONE in code but NOT_STARTED in
  progress.md.

### Branching under one orchestrator

The v2.0 plan said "per-agent feature branches `agent/A` etc."
That still applies — even with one orchestrator session,
subagents work on per-track branches so an integration agent can
merge them in dependency order. However, with a single orchestrator
the branch creation is the orchestrator's responsibility on first
dispatch to a track, not the subagent's.

If a single orchestrator would prefer to work directly on `main`
(simpler — no merges needed), that's acceptable when **only one
track is in flight at a time** (i.e., no parallel dispatch). But the
default for multi-track parallel rounds is per-track branches.

### Rate-limit / context-limit handling

**Rate limit (HTTP 429 from Anthropic):** Claude Code's own retry
logic handles transient 429s. If the limit is the user's plan
ceiling (4-hour bucket exhausted), the session terminates. The
orchestrator's prior commits and progress.md updates persist. The
operator relaunches `claude` after the bucket resets.

**Context limit (orchestrator session approaches its window):**
the orchestrator commits any uncommitted work, appends
`session_handoff` entries to each active track log, and stops. No
auto-compaction; clean stop preferred over recovered state.

### What the orchestrator NEVER does

- Speculatively dispatch tranches whose dependencies are not yet
  DONE per progress.md.
- Edit files an agent does not own (per the file-ownership table).
- Skip the `make verify` gate before commit.
- Merge agent branches to `main` mid-run; merges happen only at
  M3.X1 / M3.X2 integration gates by an integration step the
  orchestrator runs as a single dedicated dispatch.
- Resume work from a `BLOCKED.md` entry without operator
  acknowledgement.

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
- **Default (decided 2026-04-25 v2):** use `pandas_market_calendars`
  with its built-in 24/5 schedule. The library is well-maintained,
  ships an FX-shaped calendar out of the box, and handles year-end
  / new-year edge cases consistently. Document the pin
  (`pandas_market_calendars==4.x`) in `requirements.txt`. If Glenn
  wants a hand-rolled calendar later, that's a one-tranche swap;
  no agent waits.
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

### AGENT E — Oanda data + broker (FX feed AND paper-trading interface)

**Mission:** Wire the project to **Oanda v20** as the single provider
for both (a) historical FX bars at the timeframes the strategies need
(1h, 4h, 1d) and (b) a live broker interface that supports paper
trading via `fxpractice` (and live trading later via `fxtrade`,
same API, different URL/credentials).

**Why Oanda (v2.1 lock-in):**
- One REST API for everything — historical candles, live quotes,
  order submission, position queries.
- FX-native (forex is Oanda's core product, not a side feature).
- Free demo account (`fxpractice`) — instant API access, fake money,
  realistic fills. Drop-in switch to `fxtrade` for live.
- Mature Python wrapper (`oandapyV20`) maintained on PyPI.
- Rejected by Glenn 2026-04-25: TwelveData / HistData (CSV, no
  paper-trading interface). Schwab (public Trader API does not
  expose FX programmatically — verified via the existing
  `services/api/adapters/schwab_broker_adapter.py` whose docstring
  scope is equities/options only).

**Dependencies:** None. Independent. Starts day 1. No other agent
waits for E to finish before its own tranches; only the M3.X1
integration gate blocks on E1–E4 being done.

**Hands off:**
- `OandaMarketDataProvider` implementing `MarketDataProviderInterface`.
- `OandaBrokerAdapter` implementing the existing
  `BrokerAdapterInterface` (the same one `AlpacaBrokerAdapter`,
  `SchwabBrokerAdapter`, and `PaperBrokerAdapter` already implement),
  with `fxpractice` as the default endpoint for paper trading.
- A broker-registry config layer (`BROKER_PROVIDER` env var) so
  the API selects which broker adapter to use at runtime.
- Backfilled historical FX bars in `market_data`, indexed by symbol
  + interval, covering the date ranges in each strategy's
  `experiment_plan.json` (2010-01-01 onward for the deepest splits
  in Turn-of-Month).
- A `dataset_ref` resolution layer.

**Tranches:**

#### M4.E1 — Oanda account + token verification
- **Locked default (v2.1):** Oanda v20 fxpractice (paper) for
  development; fxtrade (live) for future production. Single provider
  for both historical and live data, no fallback (per Glenn's
  "no manual CSV" directive).
- **Operator action required at kickoff:** sign up for an Oanda
  fxpractice (demo) account at <https://www.oanda.com/account/v20/>,
  generate an API token from the account dashboard, and put it in
  minitux's `.env`:
  ```
  OANDA_API_TOKEN=your-fxpractice-token-here
  OANDA_ACCOUNT_ID=your-fxpractice-account-id
  OANDA_ENVIRONMENT=fxpractice
  ```
  See the kickoff doc for step-by-step. Sign-up is free; KYC is
  minimal for demo accounts.
- **Agent's first step in M4.E1:** verify all three env vars are
  set, hit the `/v3/accounts` endpoint to confirm the token is
  valid, and confirm at least one account is reachable. If missing
  or invalid: fail fast with a clear error pointing at the kickoff
  doc; do not proceed to M4.E2.
- **Acceptance:** integration test asserts a real Oanda demo account
  is reachable with the configured token; the test is parametrised
  on `OANDA_ENVIRONMENT` so the same test will work later for
  fxtrade.

#### M4.E2 — `OandaMarketDataProvider` adapter
- Implements `MarketDataProviderInterface` against Oanda's
  `/v3/instruments/{instrument}/candles` endpoint.
- Maps Oanda bars (which have separate bid / ask / mid) to the
  canonical `Candle` contract; default to mid-bars; surface bid/ask
  spread in the `spread` field when both are present.
- Symbol mapping: EURUSD ↔ EUR_USD, GBPUSD ↔ GBP_USD, USDJPY ↔
  USD_JPY, AUDUSD ↔ AUD_USD, NZDUSD ↔ NZD_USD, USDCAD ↔ USD_CAD.
  Build a `_normalise_symbol` helper.
- Granularity mapping: `H1`, `H4`, `D` (Oanda) ↔ `H1`, `H4`, `D1`
  (canonical `CandleInterval`).
- Error handling: 401 → `AuthError`; 429 → `TransientError` with
  exponential backoff; 5xx → `TransientError`; gap detection across
  weekends (FX 24/5 — Oanda omits Saturday bars; agent's gap
  detector must understand this so it doesn't flag weekend gaps as
  data quality issues).
- **Acceptance:** integration test fetches 30 days of EUR_USD H1
  bars from fxpractice, asserts contiguous OHLC across weekday
  segments, asserts spread populated, asserts the
  `_normalise_symbol("EURUSD") == "EUR_USD"` round-trip.

#### M4.E3 — Dataset versioning + DatasetService
- A `dataset` table with `(name, version, symbol, interval,
  start_date, end_date, source)` rows.
- A `DatasetService.resolve(dataset_ref) -> list[Candle]` that
  returns bars for the named, versioned dataset.
- The interface (`libs/contracts/interfaces/dataset_service.py`) is
  published as the FIRST sub-step of this tranche so Track C's
  M2.C2 can consume it (in-memory stub if Track C reaches C2 before
  E3 completes).
- An admin CLI tool (`python -m services.api.cli.import_dataset
  --name fx-eurusd-1h --version 2026.04.bootstrap --source oanda
  --symbol EURUSD --interval H1 --start 2010-01-01`) to ingest a
  versioned snapshot.
- **Acceptance:** CLI ingests 1 year of EURUSD H1 from Oanda;
  `DatasetService.resolve("fx-eurusd-1h:2026.04.bootstrap")` returns
  the bars; a stale or unknown version reference raises a clear
  domain error.

#### M4.E4 — Backfill all six majors
- Orchestrate ingestion for EURUSD, GBPUSD, USDJPY, AUDUSD, NZDUSD,
  USDCAD at 1h, 4h, 1d timeframes from each strategy's earliest
  `splits.in_sample.start` (2010-01-01 for Turn-of-Month;
  2021-01-01 for the closest example).
- Sequential (per the v2 default), so 6 symbols × 3 timeframes × ~14
  years runs in ~4–6 hours of wall time. The agent paginates over
  Oanda's 5000-candle-per-request limit and persists one dataset
  per (symbol, interval).
- Versioned snapshot id: `fx-{symbol}-{interval}:2026.04.bootstrap`.
- **Acceptance:** smoke script `make verify-fx-data` queries each
  expected `(symbol, interval)` pair and asserts ≥99% bar coverage
  across the expected date range, accounting for the 24/5 schedule
  (no weekend bars expected).

#### M4.E5 — `OandaBrokerAdapter`
- Implements the existing `BrokerAdapterInterface` (same shape
  Alpaca and Schwab adapters use) against Oanda's order endpoints:
  - `POST /v3/accounts/{id}/orders` for submit
  - `PUT /v3/accounts/{id}/orders/{order_id}/cancel` for cancel
  - `GET /v3/accounts/{id}/openTrades` and `/positions` for query
  - `GET /v3/accounts/{id}/transactions` for fill confirmation
- Order types: market, limit, stop, stop-limit, trailing-stop.
- Order status mapping: `PENDING`, `FILLED`, `CANCELLED`, `REJECTED`,
  `EXPIRED` mapped to the canonical `OrderStatus` enum already used
  by Alpaca and Schwab adapters.
- Default endpoint: fxpractice (paper). Switching to fxtrade is a
  config change only — no code change.
- Reuses the OAuth-token-injection pattern from
  `SchwabBrokerAdapter`; Oanda uses bearer tokens (simpler than
  Schwab's refresh-token flow).
- **Acceptance:** integration test against fxpractice submits a
  small EUR_USD market order, polls until filled, queries position,
  closes the position, asserts the round-trip P&L is within slippage
  expectations. (Demo dollars, real API path. This test is the
  paper-trade smoke that satisfies M3.X2's hard floor.)

#### M4.E6 — Broker registry + selection
- A new `BROKER_PROVIDER` env var with values
  `paper_synthetic | alpaca | schwab | oanda_paper | oanda_live`.
- A `BrokerRegistry` factory at
  `services/api/services/broker_registry.py` that returns the right
  adapter for the configured value. Existing `PaperBrokerAdapter`
  remains the in-process synthetic broker (used by `BacktestEngine`);
  `oanda_paper` is a separate selection that hits real fxpractice.
- The runs subsystem reads the env var at startup and injects the
  selected adapter via dependency injection.
- **Acceptance:** unit test verifies each enum value resolves to the
  correct adapter class; an integration test with
  `BROKER_PROVIDER=oanda_paper` submits an order and gets a fill
  from fxpractice (proves the wiring end-to-end).

**Estimated tranches:** 6. **Estimated effort:** 4 working days
(M4.E4 backfill is the bulk; M4.E5/E6 add ~1 day of broker work).

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

### M3.X2 — Viable candidate for testing (final acceptance)

**Trigger:** all milestones complete OR M3.X2's hard floor met.

**Hard floor — "viable candidate" definition (v2.1 revision):**

The overnight run is considered SUCCESSFUL if Glenn at wake-time can:
1. Open Strategy Studio at `http://192.168.1.5/strategy-studio`.
2. Click "Import from file", upload one (1) of the five
   `*.strategy_ir.json` files plus its `*.experiment_plan.json`.
3. See the IR rendered in the detail view.
4. Click "Execute backtest", confirm the experiment plan, submit.
5. Wait for the run to complete (poll the run-monitor page).
6. View metrics + equity curve + blotter on the results page —
   non-empty trade list, sensible-looking equity curve.
7. **Submit one paper trade through Oanda fxpractice** via a
   `make oanda-paper-smoke` helper (or equivalent CLI shim that
   `OandaBrokerAdapter` exposes). Trade fills, position visible,
   round-trip closes cleanly. This proves the live broker
   interface Glenn requested actually works end-to-end against
   real (demo) infrastructure — not just an in-process synthetic.

The strategy that proves the backtest path is
**FX_TimeSeriesMomentum_Breakout_D1** — it uses only indicators in
the v2-completion set (ADX, Donchian / rolling-extremes, EMA, ATR),
runs on D1 bars (smallest data backfill), and has plenty of trades
over the 2010-2023 in-sample window (Donchian-55 breakouts trigger
frequently across 5 majors).

**Stretch — full success:**
All FIVE strategies importable and runnable end-to-end via the UI,
each producing a non-empty trade blotter. The Turn-of-Month basket
strategy may require additional basket-execution work
(M3.X2.5 — see below); if the agent budget runs out before basket
execution, single-position strategies (4 of 5) suffice for stretch.

**Acceptance test:** Playwright e2e test
`tests/e2e/test_strategy_import_to_results.spec.ts` runs the hard-floor
flow with FX_TimeSeriesMomentum_Breakout_D1. A second test
parametrises over the other 4 strategies and is marked `xfail` for
Turn-of-Month if M3.X2.5 hasn't landed.

### M3.X2.5 — Basket execution (stretch, opt-in)

**Trigger:** Turn-of-Month strategy fails M3.X2's per-strategy
parametrise unless this is built.

**Scope:** extend `BacktestEngine` (or wrap it) to support multi-leg
basket entries: enter all legs on the same bar with weighted sizes,
exit all legs on the same bar, basket-level P&L for stop checks.
Implement `basket_atr_multiple` and `basket_open_loss_pct` exit
types from FX_TurnOfMonth.

**Acceptance:** Turn-of-Month strategy completes a backtest, basket
entries appear as 6 simultaneous fills in the trade blotter, basket
P&L tracked per-month.

This tranche is opt-in. Agents move to it only after M3.X2 hard
floor is green AND Glenn's overnight time budget remains.

---

## SEQUENCING & MILESTONE CALENDAR

```
Day  Track A           Track B          Track C            Track D            Track E
─────────────────────────────────────────────────────────────────────────────────────────
1    M1.A1 schema      ── (waits A1)    ── (waits A3)      ── (waits C1)      M4.E1 token verify
2    M1.A2 references  M1.B1 ADX        M2.C1 import-ir    M2.D1 file panel   M4.E2 oanda candles
3    M1.A3 compiler    M1.B2 z-score    M2.C2 from-ir      M2.D2 IR view      M4.E3 dataset svc
4    M1.A4 lookback    M1.B3 rolling    M2.C3 results API  M2.D3 backtest UI  M4.E4 backfill (running)
5    M1.A5 risk        M1.B4 stddev     M2.C4 detail GET   M2.D4 results view M4.E4 (continued)
6    ─────────────── INTEGRATION GATE: M3.X1 single-strategy CLI backtest ───────────────
7    (basket support) M1.B5 calendar   (cleanup)          (e2e tests)        M4.E5 OandaBroker
8    (basket support) M1.B6 derived    (perf review)      (results polish)   M4.E6 broker registry
9    ─────────────── FINAL ACCEPTANCE: M3.X2 viable candidate + paper-trade smoke ──────
```

Five agents for nine working days plus integration gates. A single
agent doing the same work serially: ~28 working days.

---

## DEFAULTS LOCKED (v2 autonomy revision)

The v1 of this workplan named four decision gates where each agent
would pause for Glenn. Per Glenn's 2026-04-25 directive, each gate
is now resolved with a default the agent uses without waiting. The
underlying spec + project context made every one of these answerable
without a real cost-of-being-wrong. If Glenn objects to any of them
he edits this document BEFORE launching agents; once agents are
running, no agent pauses for any of these.

| # | Topic | Default | Rationale |
|---|---|---|---|
| 1 | Forex data source AND broker interface (M4.E1) | **Oanda v20 REST API** — fxpractice for paper, fxtrade for live | One provider for both historical FX bars and the live broker interface Glenn explicitly requested. FX-native, free demo accounts, mature Python wrapper. Glenn rejected CSV-based providers (TwelveData / HistData / Dukascopy) on 2026-04-25; verified Schwab's public Trader API does not support FX programmatically. Oanda's `fxpractice` env handles paper trading without any code change vs `fxtrade` (live). |
| 2 | FX business calendar (M1.B5) | `pandas_market_calendars` with 24/5 schedule | Library exists, well-maintained, ships an FX calendar out of the box. Hand-rolling a calendar adds a tranche of work for no quality gain. |
| 3 | `dataset_ref` syntax (M2.C2) | Keep the existing string format from the example experiment_plans (e.g. `fx-eurusd-15m-certified-v3`) | The format is already in every `*.experiment_plan.json` in `Strategy Repo/`. Changing the syntax forces 5 file rewrites for zero functional gain. |
| 4 | Phase 4 paper-trading start | Defer to a separate workplan, BUT — if all 25 milestones complete with budget remaining, agents may pick up M5 stretch tranches (PaperBrokerAdapter orchestration + risk gates) listed at the bottom of this doc. | Lets the overnight run produce more value if backtesting goes faster than estimated, without committing to paper trading as a hard requirement. |
| 5 | Coexistence with draft-form strategies (added v2) | Coexist via `source: "ir_upload" \| "draft_form"` flag on the strategy record | Preserves the existing Strategy Studio draft flow. IR-imported and hand-authored strategies live in the same `strategies` table. |
| 6 | Migration tooling (added v2) | Alembic, agent-owned per-tranche | Project already uses Alembic; each tranche that needs schema adds its own migration script under `migrations/versions/`. |
| 7 | Forex backfill concurrency (added v2) | Sequential | Trades 8 hours of wall time for zero rate-limit risk. Overnight runs prioritize safety over throughput. |

Each agent reads this table at startup. If a tranche references a
"decision gate" (legacy phrasing), the agent looks up the default
above and proceeds.

---

## AGENT COORDINATION PROTOCOL (v2 autonomy revision)

Five agents working on one repo can step on each other if not
coordinated. The protocol below avoids merge conflicts and gives
Glenn a clean wake-time review surface.

### Branching

- Each agent works on a feature branch named `agent/<track>` —
  `agent/A`, `agent/B`, `agent/C`, `agent/D`, `agent/E`.
- All branches are cut from the same `main` SHA at kickoff (call this
  the "kickoff SHA"; the orchestrator captures it in
  `docs/workplan/agent_logs/kickoff.md`).
- Per-tranche commits land on the agent's own branch. Atomic — one
  tranche, one commit, no force-pushes.
- At integration gate **M3.X1** (single-strategy CLI backtest), all
  branches merge to main in dependency order: A → B → E → C → D.
  Merges are fast-forward where possible, octopus or sequential merge
  commits where not. Conflicts are resolved by the agent that owns
  the more-recent commit (defined by commit timestamp).
- At **M3.X2** (final acceptance), the same procedure repeats for
  any post-X1 work.
- No agent rebases another agent's branch. No agent force-pushes
  anywhere.

### File-ownership boundaries

To prevent merge conflicts the tracks claim non-overlapping file
sets. Each agent's contract:

| Track | Owns (writes) | Reads but does not modify |
|---|---|---|
| A | `libs/contracts/strategy_ir.py` (NEW), `libs/strategy_ir/**` (NEW), `tests/unit/test_strategy_ir_*.py` (NEW), migrations for `strategies.ir_json` column | `libs/indicators/**` (read-only — uses registry) |
| B | `libs/indicators/<each-new-indicator>.py` (NEW per tranche), `libs/indicators/registry.py` (extends — see "shared file" rule below), `tests/unit/test_indicators_*.py` (NEW) | `libs/contracts/strategy_ir.py` (reads to know which types it must implement) |
| C | `services/api/routes/strategies.py` (extends — additive), `services/api/routes/runs.py` (extends — additive), `libs/contracts/experiment_plan.py` (NEW), `services/api/services/research_run_service.py` (extends — additive), `services/api/services/dataset_service.py` (NEW), `tests/unit/test_routes_*.py` (NEW), migrations | `libs/strategy_ir/**` (uses parser/compiler) |
| D | `frontend/src/pages/StrategyStudio.tsx` (extends), `frontend/src/pages/RunResults.tsx` (NEW), `frontend/src/components/strategy_import/**` (NEW), `frontend/src/api/strategies.ts` (extends), `frontend/src/api/runs.ts` (extends), `frontend/src/**/*.test.tsx` (NEW) | OpenAPI types from C |
| E | `services/worker/collectors/forex_*.py` (NEW), `services/worker/collectors/histdata_provider.py` (NEW), `services/api/services/dataset_service.py` (NEW — coordinated with C; see below), `services/api/cli/import_dataset.py` (NEW), migrations for `dataset` table, `tests/unit/test_forex_*.py` (NEW) | none |

**Shared-file rule for `libs/indicators/registry.py`:** Track B
appends new entries to the registry per tranche. Each commit
appends only at the bottom of the registration block — no edits to
existing entries. This avoids merge conflicts even if multiple
indicators are added in quick succession.

**Shared-file rule for `services/api/services/dataset_service.py`:**
Track E creates this file in M4.E3. Track C consumes it in M2.C2.
If C reaches M2.C2 before E reaches M4.E3, C uses an in-memory stub
of the dataset service (typed by the interface) and the real
implementation lands when E catches up. The interface is published
in `libs/contracts/interfaces/dataset_service.py` (Track E owns
the interface as the first sub-step of M4.E3).

**Shared-file rule for `Makefile` and `CLAUDE.md`:** if any track
needs to update either, the agent makes the edit on its own branch.
Conflicts are resolved at integration gate by appending — never
overwriting — in the order A, B, C, D, E.

### Per-tranche commit convention

Every commit subject:

```
<type>(<track>): Tranche M<x>.<track><n> — <one-line summary>
```

Examples:
```
feat(strategy-ir): Tranche M1.A1 — Pydantic schema for strategy_ir.json
feat(indicators): Tranche M1.B1 — ADX (Wilder's average directional index)
feat(api): Tranche M2.C1 — POST /strategies/import-ir
feat(forex-data): Tranche M4.E2 — TwelveData market-data provider
```

Body must include the tranche's acceptance test result, the file
list, and `Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>`.

### Progress logs (Glenn's wake-time view)

Every agent appends one entry per tranche to a track-specific log
file under `docs/workplan/agent_logs/`:

```
docs/workplan/agent_logs/A.md
docs/workplan/agent_logs/B.md
docs/workplan/agent_logs/C.md
docs/workplan/agent_logs/D.md
docs/workplan/agent_logs/E.md
docs/workplan/agent_logs/kickoff.md   ← captures kickoff SHA + agent assignments
docs/workplan/agent_logs/integration.md ← captures merge events at X1 / X2
docs/workplan/agent_logs/BLOCKED.md   ← created ONLY if an agent blocks
```

Each log entry is one fenced block:

```
## M1.A1 — Pydantic schema for strategy_ir.json
status:    DONE
commit:    abc1234
duration:  47m
notes:     5/5 repo IRs parse; 5 malformed inputs rejected at validation.
           Renamed StrategyIR to StrategyIRDocument to avoid clash with
           the existing 'strategy_ir' database column name; downstream
           tracks read from libs.contracts.strategy_ir.StrategyIRDocument.
```

**Glenn's wake-time ritual:** read `BLOCKED.md` first (empty = good
news); then `integration.md` (X1 / X2 status); then track logs in
order A, B, C, D, E for any decisions worth re-examining.

### Failure protocol

If an agent hits a blocker it cannot resolve from the workplan +
project context:

1. Commit any partial work that compiles and passes tests on its
   own branch.
2. Append the blocked tranche's entry to its track log with
   `status: BLOCKED` and a one-paragraph description of the
   ambiguity.
3. Append a one-line entry to `docs/workplan/agent_logs/BLOCKED.md`
   pointing at the track log entry.
4. Stop. Do NOT continue to the next tranche on the same track —
   downstream tranches likely depend on the blocked one.
5. Continue is not automatic; Glenn reviews `BLOCKED.md` in the
   morning, decides, edits the workplan if needed, restarts the
   agent.

### Self-checks at agent startup

Every agent's first action (before tranche 1) is a self-check
that fails fast if its environment isn't right:

1. `cd` to repo root; confirm on the kickoff SHA's history.
2. `git checkout -b agent/<track>` (or fast-forward if the branch
   already exists from a prior aborted run).
3. Run `make verify` — must be green. If not, the kickoff state
   itself is broken; agent stops and writes to `BLOCKED.md`.
4. Read `docs/workplan/2026-04-25-strategy-execution-agent-orchestration.md`
   AND `docs/workplan/2026-04-25-strategy-execution-kickoff.md`.
5. Confirm any agent-specific prerequisites listed in the kickoff
   doc (e.g. Track E confirms `TWELVEDATA_API_KEY` env var is set).
6. Begin tranche 1.


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

## M5 — STRETCH TRANCHES (opt-in, only after M3.X2 hard floor)

These tranches give the overnight run something to do if it finishes
early. None of them is required for the "viable candidate"
definition. Agents pick these up in the order listed below ONLY
after M3.X2 hard floor is green.

#### M5.S1 — Walk-forward execution path
- Wire the existing `WalkForwardConfig` into `BacktestEngine` via
  the IR compiler. Each strategy's `experiment_plan.json` already
  defines `walk_forward.train_window_months / test_window_months /
  step_months`.
- **Acceptance:** WF run produces a `walk_forward_summary` artifact
  with one row per (train, test) window.

#### M5.S2 — Monte Carlo trade-resampling
- Implement `monte_carlo.method == "trade_sequence_resampling"`
  using the existing trade blotter. 500 iterations.
- **Acceptance:** MC run produces P5/P50/P95 envelope around the
  equity curve.

#### M5.S3 — Basket execution (= M3.X2.5)
- See above. Promotes Turn-of-Month strategy from xfail to passing.

#### M5.S4 — Paper-trading orchestrator (continuous strategy execution)
- The single-shot paper-trade smoke (M4.E5) proves the
  `OandaBrokerAdapter` works. M5.S4 builds the
  `PaperDeploymentService` that runs a passed backtest's compiled
  strategy CONTINUOUSLY against live FX data, routing orders
  through `oanda_paper`. Risk gates from
  `risk_model.daily_loss_limit_pct` and `max_drawdown_halt_pct` are
  enforced pre-trade. Reconciliation loop checks broker state vs
  expected state every N minutes.
- **Acceptance:** an operator can click "Promote to paper" on a
  passed backtest and see live position state on a paper-trading
  page; the deployment survives a process restart and reconciles
  cleanly.
- **Note:** the broker interface (M4.E5/E6) is in M3.X2's hard
  floor; the orchestrator (M5.S4) is what turns "I can submit a
  paper trade" into "the strategy is live-paper-trading." Stretch
  because it adds significant code (deployment lifecycle, risk
  gates, reconciliation) that has its own quality bar.

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

## WAKE-TIME REVIEW PROTOCOL FOR GLENN

This is the morning checklist when the overnight run is done. The
intent is that Glenn can determine in <5 minutes whether the run
succeeded, partially-succeeded, or failed — without reading any
code.

1. **Open `docs/workplan/agent_logs/BLOCKED.md`** (created only if an
   agent blocked).
   - **Empty / file does not exist** → no agent hit a blocker. Best
     case.
   - **Has entries** → at least one agent stopped. Each entry points
     at the specific track log + tranche. Glenn opens those, reads
     the agent's notes, decides the unblock.

2. **Open `docs/workplan/agent_logs/integration.md`**.
   - Look for the "M3.X1" entry — single-strategy CLI backtest. If
     present and `status: DONE`, the foundation works.
   - Look for the "M3.X2" entry — viable candidate via UI. If
     present and `status: DONE`, the run hit the hard floor.

3. **Open `docs/workplan/2026-04-25-strategy-execution-progress.md`**
   and scan the status column. Count of DONE vs NOT_STARTED tells
   the overall arc.

4. **If hard floor is green:** open
   `http://192.168.1.5/strategy-studio` in a browser, run the
   acceptance flow manually
   (import FX_TimeSeriesMomentum_Breakout_D1, execute backtest, view
   results). One human-in-the-loop confirmation that the agents
   didn't fool themselves.

5. **If stretch tranches landed (M5.*):** check track logs for
   walk-forward / Monte Carlo / paper-trading status. These are
   gravy.

6. **`make verify`** on a fresh shell — final sanity that everything
   compiles, lints, and tests pass on `main` after integration
   merges.

If any of steps 1-6 surface a problem, Glenn either (a) restarts the
specific blocked agent with edited workplan instructions, or (b)
pauses the project and writes a remediation tranche in the rhythm
established by Tranches A-L.


## END

This document is the canonical workplan for the strategy execution
buildout. v2 (this revision) makes it autonomous: every previously-
named decision gate is resolved with a default agents use without
pausing. The minimal set of operator actions Glenn must take BEFORE
launching agents is documented in
`docs/workplan/2026-04-25-strategy-execution-kickoff.md`.

Estimated total effort with five agents: **9 working days serial
equivalent** compressed into one overnight run via parallelism. No
stubs, no shortcuts. Five-agent budget: ~50 agent-hours.
