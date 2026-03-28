# FXLab Phase 2 — Strategy Compiler, Research Engine, and Optimization
# Implementation Workplan v2.1

## Revision Summary

This v2.1 workplan is the recommended synthesis of workplan v1 and workplan v2.

Use v2 as the governing structure:
- formal compiler front-end contracts
- deterministic compiler output bundles
- mandatory preflight validation before run admission
- explicit PIT-safe multi-timeframe semantics
- deterministic candidate ranking and promotion lifecycle
- readiness policy versioning
- idempotency, retry, resume, and write-once artifact rules
- adversarial correctness testing as a definition-of-done gate

Use v1 as the implementation-detail source where precision matters:
- uncertainty dimensions and severity rules
- compiler stage-by-stage behavior
- walk-forward protocol
- readiness scoring dimensions and threshold defaults
- regime segmentation method
- exact stop/limit/gap-through fill rules
- missing-bar handling
- required sizing models
- concrete schema/API detail

This document keeps the v2 control model and milestone ordering, then folds in the strongest v1 mechanics so Claude has less room to make “reasonable but wrong” choices during implementation.

---

## 1. Mission

Implement Phase 2: Strategy Compiler, Research Engine, and Optimization on top of the Phase 1 operational substrate.

When this phase is complete, an operator must be able to:
- submit constrained strategy intent through APIs
- compile that intent into a deterministic, versioned Strategy IR and compiler bundle
- record uncertainty, assumptions, and compiler evidence as first-class artifacts
- run deterministic, PIT-safe backtests against certified datasets
- support PIT-safe multi-timeframe research behavior
- run resumable optimization sweeps
- promote ranked candidates into contamination-aware holdout evaluation
- generate evidence-backed readiness reports under explicit policy versions
- export lineage-linked artifacts without relying on notebooks or ad hoc outputs

Everything in this phase is headless and API-driven. Phase 3 may build UI on top of these APIs, but no Phase 2 capability depends on UI existing.

### Out of scope

- broker connectivity
- paper trading or live trading
- polished non-technical UI
- operator execution dashboards
- parallel storage or artifact systems outside Phase 1 controls

Basic internal review surfaces and API docs are allowed.

---

## 2. Non-Negotiable Rules

Treat violations as build failures, not warnings.

1. **Phase 1 contracts are immutable.** Do not modify Phase 1 database tables, queue classes, artifact conventions, lineage behavior, API envelopes, or audit mechanics. Extend only via new tables, new endpoints, and new versioned contracts.

2. **Every compile and run is reproducible.** Seeds, dataset version IDs, cost profile version IDs, strategy build IDs, policy version IDs, and effective parameters must be persisted before execution begins.

3. **PIT safety is mandatory.** No signal, feature, fill, derived field, or aggregation may observe data unavailable at the bar’s `as_of` boundary.

4. **Multi-timeframe safety is mandatory.** Lower-timeframe execution may not observe unfinished higher-timeframe bars. Cross-timeframe availability rules must be explicit, deterministic, and test-backed.

5. **Holdout contamination is irreversible.** Once a holdout window has been evaluated for a strategy build, that holdout designation is contaminated for that build and must be recorded append-only.

6. **Long-running work is always a job.** Compilation, preflight, research runs, optimization, holdout verification, and readiness generation must enqueue jobs and return `202 Accepted`.

7. **Every mutation writes an immutable audit event.** Include actor, action, target object, correlation ID, and evidence references where applicable.

8. **Material ambiguity blocks paper eligibility.** A strategy may compile to draft/blocked status, but unresolved material ambiguity may not advance to paper-eligible.

9. **Readiness is evidence, not a boolean.** Readiness reports are versioned, persisted entities with lineage, scoring evidence, and policy references.

10. **The simulation loop contains no I/O.** Load data before the loop. Persist outputs after the loop. No DB queries, artifact downloads, or network calls inside the hot loop.

11. **Artifacts are write-once.** Retries may register a new version only when content differs materially. They may never silently replace prior evidence.

12. **Duplicate submission must be safe.** Mutating endpoints must support `Idempotency-Key` and duplicate suppression.

13. **Cost models are conservative by default.** Defaults must not assume optimistic spread/slippage conditions.

14. **No notebook output counts as official evidence.** Official evidence must be registered through Phase 1 artifact and lineage controls.

---

## 3. Delivery Protocol

Every milestone follows the same execution discipline used in Phase 1.

### Per-milestone execution order

```text
1. Read the milestone contract
2. Identify contracts, services, repositories, routes, workers, and artifacts touched
3. Define or update interfaces first
4. Write failing tests for happy path, invalid inputs, edge cases, dependency failures, and retries
5. Implement minimum code to pass tests
6. Run quality gate: format -> lint -> type-check -> tests with coverage
7. Refactor and re-run quality gate
8. Add integration tests where orchestration or I/O exists
9. Review against milestone acceptance criteria and non-negotiable rules
```

### Onion architecture mapping

| Layer | FXLab location | Owns |
|---|---|---|
| Domain / Contracts | `libs/contracts/` | compiler input models, Strategy IR, experiment plan, runs, trials, readiness, exports |
| Compiler library | `libs/strategy_compiler/` | canonicalization, template binding, uncertainty extraction, bundle generation |
| Strategy IR library | `libs/strategy_ir/` | IR validation, static checks, PIT contract checks |
| Experiment plan library | `libs/experiment_plan/` | search space, walk-forward, trial generation, candidate ranking policy bindings |
| Risk library | `libs/risk/` | sizing, capital accounting, cost models, fill semantics, readiness scoring |
| Service interfaces | `libs/*/interfaces/` | abstract interfaces for services and repositories |
| Services | `services/research_worker/`, `services/optimization_worker/`, `services/readiness_service/`, `services/strategy_compiler/` | compile, run, optimize, holdout, report orchestration |
| Repositories | `libs/db/` | SQLAlchemy models, migrations, repos |
| Controllers | `services/api/routes/` | FastAPI handlers, no business logic |
| Infrastructure | `infra/`, service `main.py` | DI wiring, worker bootstrap, queue setup |

**Dependency rule:** Controllers -> Services -> Repositories -> Domain. Never skip a layer.

---

## 4. Default Technical Choices

Inherit all Phase 1 technical choices. Phase 2 additions:

| Concern | Choice |
|---|---|
| Compiler input models | Pydantic v2 with canonical JSON serialization |
| Strategy IR format | Pydantic v2 serialized to JSON / stored in JSONB |
| Compiler bundle | versioned JSON artifacts plus DB records |
| Search space format | Pydantic v2 with bounds, types, constraints, and policy refs |
| Experiment plan | Pydantic v2 referencing strategy build, search space, policies, and holdout inputs |
| Numerical operations | NumPy / Polars for bar-level computation |
| Optimization sampler | Optuna (TPE by default), behind interface |
| Monte Carlo / bootstrap | NumPy RNG with stored seeds |
| Checkpointing | Redis-backed worker state plus Postgres persistence |
| Parquet I/O | PyArrow for certified dataset artifacts |
| Idempotency | persisted endpoint idempotency keys in Postgres |

---

## 5. Repository Target Shape (Phase 2 additions)

```text
fxlab/
  services/
    api/
      routes/
        strategies.py
        runs.py
        readiness.py
        exports.py
    strategy_compiler/
      main.py
      tasks.py
      service.py
    research_worker/
      main.py
      tasks.py
      engine/
        core_loop.py
        pit_guard.py
        timeframe_alignment.py
        fills.py
        costs.py
        sizing.py
        capital.py
        walk_forward.py
      interfaces/
    optimization_worker/
      main.py
      tasks.py
      interfaces/
    readiness_service/
      main.py
      service.py
      interfaces/
  libs/
    contracts/
      compiler_input.py
      strategy_ir.py
      compiler_bundle.py
      search_space.py
      experiment_plan.py
      run_models.py
      readiness.py
      exports.py
      enums.py
    strategy_compiler/
      canonicalize.py
      template_binding.py
      uncertainty.py
      static_checks.py
      bundle_builder.py
    strategy_ir/
    experiment_plan/
    risk/
    db/
      models/
      repositories/
      migrations/
```

---

## 6. Phase 2 Domain Model

Add these first-class entities:

- `strategy_drafts`
- `strategy_versions`
- `strategy_builds`
- `compiler_manifests`
- `compiler_assumption_reports`
- `uncertainty_ledgers`
- `search_space_versions`
- `experiment_plans`
- `research_runs`
- `run_preflight_results`
- `run_trials`
- `candidate_rankings`
- `candidate_promotions`
- `holdout_designations`
- `holdout_evaluations`
- `readiness_policy_versions`
- `readiness_reports`
- `regime_baselines`
- `export_manifests`
- `idempotency_keys`

### Lifecycle definitions

- **Strategy draft:** pre-compiled user intent representation before deterministic normalization completes.
- **Strategy version:** user-facing logical version of a strategy.
- **Strategy build:** one deterministic compiled output of a specific strategy version under a specific compiler policy and template binding.
- **Research run:** top-level execution against one strategy build and one experiment plan.
- **Trial:** one parameterized execution unit inside a research or optimization run.
- **Holdout run:** specialized evaluation against an explicitly designated untouched holdout window.
- **Candidate promotion:** audited act of advancing ranked candidates into holdout or readiness evaluation.
- **Readiness report:** persisted evidence report generated under a specific readiness policy version.

---

## 7. Compiler Front-End and Strategy IR Contracts

### 7.1 Compiler front-end contracts

Define these input-side contracts explicitly before Strategy IR generation:

- `StrategyDraftInput`
- `TemplateBindingManifest`
- `CompilerAssumptions`
- `CompilerCanonicalizationResult`
- `UIBlueprintSeed`

`UIBlueprintSeed` is allowed only as a structural hook artifact for later phases. It must not create Phase 3 UI work in Phase 2.

### 7.2 Compiler front-end rules

1. Canonicalization must produce stable bytes for semantically identical input.
2. Template binding must be deterministic and versioned.
3. Unsupported freeform logic must fail with typed validation errors.
4. Material ambiguity extraction must happen before IR emission.
5. The compiler must separate assumptions, defaults, and inferred values explicitly.

### 7.3 Strategy IR minimum contract

The compiled Strategy IR must include, at minimum:

- instrument universe selector
- timeframe set
- session/calendar assumptions
- entry conditions
- exit conditions
- risk controls
- sizing model reference
- allowed parameterization fields
- data dependencies
- logging hooks and observability expectations
- compiler version
- template binding version
- build hash

### 7.4 Compiler output bundle

Compilation must emit a deterministic bundle containing:

- `strategy_ir.json`
- `compiler_manifest.json`
- `compiler_assumption_report.json`
- `uncertainty_ledger.json`
- `search_space_seed.json` if applicable
- `experiment_plan_seed.json` if applicable
- `ui_blueprint_seed.json` hook payload
- build hash and canonicalization evidence

---

## 8. Resolved Specification Gaps Adopted from v1

The following v1 clarifications are normative in v2.1. They are not optional implementation commentary.

### 8.1 Material ambiguity model

The compiler assesses each strategy against these uncertainty dimensions:

| Dimension | What is assessed | Material if... |
|---|---|---|
| `exit_latency` | how long after signal does the exit fire | not specified and position can be held overnight |
| `fill_model` | how fills are priced | strategy has non-trivial market impact assumptions unspecified |
| `data_dependency` | required symbols / timeframes / lookbacks | any required symbol or timeframe lacks certified data |
| `parameter_sensitivity` | sensitivity to small param changes | post-run dimension, not compiler-time gating |
| `cost_profile` | whether a cost profile version is specified | no cost profile version is referenced |
| `pit_dependency` | PIT safety of referenced data | any dependency is not PIT-safe by construction |
| `execution_model` | order types / priority rules | mixed order types with unspecified priority rules |
| `capital_model` | completeness of sizing model | sizing references parameters not present in the manifest |

Severity levels:
- `low` — resolved assumption with low impact
- `medium` — resolved assumption with moderate impact
- `high` — unresolved assumption with significant impact
- `material` — unresolved assumption that would materially change paper behavior and blocks paper eligibility

### 8.2 Compiler pipeline (normative)

```text
INPUT: StrategyDraftInput
  -> Stage 1: Schema validation
  -> Stage 2: Static contract checks
       - referenced symbols exist
       - required timeframes have certified datasets
       - lookback does not exceed available coverage
       - parameter references exist
       - no circular rule dependencies
  -> Stage 3: PIT contract check
       - all data refs include explicit timeframe and lookback
       - no "latest/current" semantics without explicit as_of handling
  -> Stage 4: Uncertainty assessment
       - create uncertainty entries
       - flag unresolved material entries
  -> Stage 5: IR generation and bundle build
       - normalize to canonical Strategy IR
       - compute build hash from canonical bytes
       - persist compiler version, template version, assumption report
OUTPUT:
  StrategyBuild + StrategyIR + CompilerManifest + UncertaintyLedger + CompilerAssumptionReport
```

### 8.3 Walk-forward protocol

```python
class WalkForwardConfig(BaseModel):
    method: Literal["anchored", "rolling"]
    n_folds: int
    oos_fraction: float
    min_is_bars: int
    min_oos_bars: int
    purge_bars: int
```

Rules:
- minimum `n_folds` is 3; recommended 5
- anchored: IS grows while OOS stays fixed
- rolling: IS and OOS both move forward
- fold windows are generated before the run starts
- folds failing minimum bar counts are skipped with explicit logging
- only completed folds count toward aggregated results

### 8.4 Readiness scoring methodology (Policy Version 1 defaults)

Readiness is scored across six dimensions. Each yields a 0-100 sub-score. The overall grade is determined by the **minimum** sub-score, not the average.

| Dimension | What is measured | Grade F threshold |
|---|---|---|
| `oos_stability` | OOS Sharpe / IS Sharpe ratio | `< 0.3` |
| `drawdown` | max drawdown as fraction of initial capital | `> 0.40` |
| `trade_count` | minimum trade count for statistical significance | `< 30` total OOS trades |
| `holdout_pass` | holdout positive and uncontaminated | Sharpe `<= 0` or not evaluated |
| `regime_consistency` | positive Sharpe in identified regimes | `< 2/3` regimes positive |
| `parameter_stability` | median OOS Sharpe across ±10% perturbation vs baseline | `< 0.5x` baseline Sharpe |

Grade mapping by minimum sub-score:

| Grade | Minimum sub-score | Interpretation |
|---|---|---|
| A | `>= 80` | proceed to paper with confidence |
| B | `>= 65` | proceed to paper with monitoring |
| C | `>= 50` | address weakest dimension before paper |
| D | `>= 35` | significant concerns; do not paper without remediation |
| F | `< 35` or `holdout_pass = false` | do not proceed |

These are the defaults for `readiness_policy_version = 1`. Later policy versions may change them, but historical reports must retain the policy version used.

### 8.5 Regime segmentation method

Default regime segmentation for Policy Version 1:
- Hidden Markov Model on rolling 20-day realized volatility of the primary symbol
- 2-3 states
- canonical labels: `low_vol`, `high_vol`, `trending` (optional third state)
- fit on IS data only
- apply to OOS and holdout data afterward
- persist regime labels per bar and summary metrics per regime

The implementation must be pluggable behind an interface, but this is the default required behavior for Phase 2.

### 8.6 Exact fill rules

These rules are normative.

| Order type | Normal bar | Gap-through bar |
|---|---|---|
| Market | fill at next bar open + slippage | fill at next bar open + slippage |
| Limit buy | fill at limit if `low <= limit` | fill at open if `open <= limit` |
| Limit sell | fill at limit if `high >= limit` | fill at open if `open >= limit` |
| Stop buy | fill at stop if `high >= stop` | fill at open if `open >= stop` |
| Stop sell | fill at stop if `low <= stop` | fill at open if `open <= stop` |

Gap detection:
```text
abs(open - prev_close) / prev_close > gap_threshold
```

Default `gap_threshold = 0.5%`.

Gap-through fills are priced at the open, not the order price.

### 8.7 Missing-bar handling

When a required bar is missing during simulation:

1. If the missing bar falls within a market-hours gap per the calendar, treat it as non-error and advance.
2. If the missing bar is inside market hours, emit `missing_bar_event`.
3. Apply policy from `ExperimentPlan` / persisted run record:

- `halt` (default): halt run with `status = data_error`
- `skip`: skip bar, hold positions, continue
- `forward_fill`: explicit opt-in only; use previous close as OHLCV surrogate

### 8.8 Required sizing models

All sizing models implement:

```text
compute_size(signal_strength, capital, price, atr, volatility) -> quantity
```

Required models:
- `FixedFractional(fraction)`
- `ATRBased(risk_fraction, atr_multiplier)`
- `KellyCapped(win_rate, avg_win, avg_loss, cap)`
- `FixedQuantity(quantity)`

`KellyCapped` inputs must be estimated from IS data and persisted in the experiment plan before OOS/holdout use.

---

## 9. Preflight Validation and Run Admission

Before any compile, research run, optimization run, or holdout evaluation is admitted to the queue, run preflight validation.

Preflight must verify:
- strategy build exists and is in an admissible status
- required datasets are certified and not quarantined
- required timeframes are available
- required lookback coverage exists
- cost profile version exists
- holdout designation is valid and not already contaminated for the relevant build
- search space constraints are valid
- seeds and reproducibility fields are present
- required policies and versions are resolvable

Preflight outputs:
- `run_preflight_results` persisted record
- explicit pass/fail status
- structured rejection reasons
- audit event
- queue admission allowed only on pass

---

## 10. Multi-Timeframe Semantics

These rules are mandatory.

1. Lower-timeframe execution may not observe unfinished higher-timeframe bars.
2. Higher-timeframe values become visible only after the higher-timeframe bar is finalized.
3. Aggregation boundaries must be session/calendar-aware.
4. Missing higher-timeframe bars must follow explicit missing-bar policy; never silent fallback.
5. Timeframe alignment decisions must be test-covered for:
   - session edges
   - calendar transitions
   - gaps
   - daylight savings or timezone boundary behavior if relevant to the instrument calendar

---

## 11. Concrete Database Schema

The schema below is the default implementation target. Where v2 added broader lifecycle entities, v2.1 keeps them, but the following v1-level tables and fields remain the baseline SQL shape unless a clearly better equivalent is documented in an ADR.

```sql
strategies (
  strategy_id ULID PK,
  name TEXT NOT NULL,
  description TEXT,
  owner_id TEXT NOT NULL,
  created_at TIMESTAMPTZ NOT NULL,
  updated_at TIMESTAMPTZ NOT NULL
);

strategy_versions (
  strategy_version_id ULID PK,
  strategy_id ULID NOT NULL REFERENCES strategies,
  version_number INTEGER NOT NULL,
  ir_json JSONB NOT NULL,
  description_hash TEXT NOT NULL,
  created_by TEXT NOT NULL,
  created_at TIMESTAMPTZ NOT NULL,
  UNIQUE (strategy_id, version_number)
);

strategy_builds (
  strategy_build_id ULID PK,
  strategy_version_id ULID NOT NULL REFERENCES strategy_versions,
  build_hash TEXT NOT NULL,
  compiler_version TEXT NOT NULL,
  template_binding_version TEXT,
  status TEXT NOT NULL,
  blocks_paper BOOLEAN NOT NULL DEFAULT false,
  compiled_at TIMESTAMPTZ,
  error_message TEXT,
  created_at TIMESTAMPTZ NOT NULL
);

uncertainty_ledger_entries (
  entry_id ULID PK,
  strategy_build_id ULID NOT NULL REFERENCES strategy_builds,
  dimension TEXT NOT NULL,
  severity TEXT NOT NULL,
  description TEXT NOT NULL,
  resolution TEXT,
  resolved BOOLEAN NOT NULL DEFAULT false,
  blocks_paper BOOLEAN NOT NULL,
  created_at TIMESTAMPTZ NOT NULL
);

compiler_manifests (
  compiler_manifest_id ULID PK,
  strategy_build_id ULID NOT NULL REFERENCES strategy_builds,
  compiler_version TEXT NOT NULL,
  canonicalization_hash TEXT NOT NULL,
  template_binding_version TEXT NOT NULL,
  manifest_json JSONB NOT NULL,
  created_at TIMESTAMPTZ NOT NULL
);

experiment_plans (
  experiment_plan_id ULID PK,
  strategy_build_id ULID NOT NULL REFERENCES strategy_builds,
  dataset_version_ids JSONB NOT NULL,
  cost_profile_version_id ULID NOT NULL,
  holdout_designation_id ULID,
  search_space_json JSONB,
  walk_forward_config JSONB,
  monte_carlo_config JSONB,
  regime_config JSONB,
  sizing_model TEXT NOT NULL,
  sizing_params JSONB NOT NULL,
  created_by TEXT NOT NULL,
  created_at TIMESTAMPTZ NOT NULL
);

run_preflight_results (
  run_preflight_result_id ULID PK,
  experiment_plan_id ULID,
  strategy_build_id ULID,
  requested_run_type TEXT NOT NULL,
  passed BOOLEAN NOT NULL,
  reasons_json JSONB NOT NULL,
  created_by TEXT NOT NULL,
  created_at TIMESTAMPTZ NOT NULL
);

runs (
  run_id ULID PK,
  run_type TEXT NOT NULL,
  experiment_plan_id ULID NOT NULL REFERENCES experiment_plans,
  status TEXT NOT NULL,
  seeds JSONB NOT NULL,
  checkpoint_key TEXT,
  trial_count INTEGER NOT NULL DEFAULT 0,
  completed_trials INTEGER NOT NULL DEFAULT 0,
  ranking_policy_version TEXT,
  readiness_policy_version TEXT,
  started_at TIMESTAMPTZ,
  completed_at TIMESTAMPTZ,
  error_message TEXT,
  created_by TEXT NOT NULL,
  created_at TIMESTAMPTZ NOT NULL
);

trials (
  trial_id ULID PK,
  run_id ULID NOT NULL REFERENCES runs,
  trial_number INTEGER NOT NULL,
  parameters JSONB NOT NULL,
  seed INTEGER NOT NULL,
  status TEXT NOT NULL,
  metrics JSONB,
  fold_metrics JSONB,
  started_at TIMESTAMPTZ,
  completed_at TIMESTAMPTZ,
  UNIQUE (run_id, trial_number)
);

candidate_rankings (
  candidate_ranking_id ULID PK,
  run_id ULID NOT NULL REFERENCES runs,
  ranking_policy_version TEXT NOT NULL,
  ranking_json JSONB NOT NULL,
  created_at TIMESTAMPTZ NOT NULL
);

candidate_promotions (
  candidate_promotion_id ULID PK,
  run_id ULID NOT NULL REFERENCES runs,
  trial_id ULID REFERENCES trials,
  promotion_target TEXT NOT NULL,
  promotion_policy_version TEXT NOT NULL,
  promoted_by TEXT NOT NULL,
  promoted_at TIMESTAMPTZ NOT NULL
);

holdout_designations (
  holdout_designation_id ULID PK,
  dataset_version_id ULID NOT NULL,
  strategy_id ULID NOT NULL REFERENCES strategies,
  strategy_build_id ULID,
  holdout_start DATE NOT NULL,
  holdout_end DATE NOT NULL,
  designated_by TEXT NOT NULL,
  designated_at TIMESTAMPTZ NOT NULL,
  evaluated_at TIMESTAMPTZ,
  contaminated_run_id ULID
);

readiness_policy_versions (
  readiness_policy_version_id ULID PK,
  version_name TEXT NOT NULL,
  policy_json JSONB NOT NULL,
  created_at TIMESTAMPTZ NOT NULL
);

readiness_reports (
  readiness_report_id ULID PK,
  run_id ULID NOT NULL REFERENCES runs,
  strategy_build_id ULID NOT NULL REFERENCES strategy_builds,
  readiness_policy_version_id ULID NOT NULL REFERENCES readiness_policy_versions,
  grade TEXT NOT NULL,
  overall_score INTEGER NOT NULL,
  sub_scores_json JSONB NOT NULL,
  narrative TEXT,
  artifact_id ULID,
  generated_at TIMESTAMPTZ NOT NULL,
  created_at TIMESTAMPTZ NOT NULL
);

regime_baselines (
  regime_baseline_id ULID PK,
  run_id ULID NOT NULL REFERENCES runs,
  regime_config JSONB NOT NULL,
  regime_labels JSONB NOT NULL,
  regime_metrics JSONB NOT NULL,
  artifact_id ULID,
  created_at TIMESTAMPTZ NOT NULL
);

idempotency_keys (
  idempotency_key_id ULID PK,
  endpoint_name TEXT NOT NULL,
  idempotency_key TEXT NOT NULL,
  request_hash TEXT NOT NULL,
  response_json JSONB,
  created_at TIMESTAMPTZ NOT NULL,
  UNIQUE (endpoint_name, idempotency_key)
);
```

---

## 12. Canonical API Surfaces

All mutating endpoints:
- use Phase 1 response envelope
- support `Idempotency-Key`
- return `202 Accepted` for heavy work
- persist correlation IDs and audit entries

### Strategy compilation

```text
POST /strategies/draft
POST /strategies/{strategy_id}/versions
POST /strategies/{strategy_id}/versions/{version}/compile
GET  /strategies/{strategy_id}/versions/{version}
GET  /strategies/{strategy_id}/versions/{version}/build
GET  /strategies/{strategy_id}/versions/{version}/uncertainty
PATCH /strategies/{strategy_id}/versions/{version}/uncertainty/{entry_id}
```

### Research / optimization / holdout

```text
POST /runs/research
POST /runs/optimize
POST /runs/{run_id}/verify_holdout
GET  /runs/{run_id}
GET  /runs/{run_id}/trials
GET  /runs/{run_id}/artifacts
GET  /runs/{run_id}/readiness
POST /runs/{run_id}/readiness
```

### Exports

```text
GET /runs/{run_id}/exports/trades?format=csv|parquet
GET /runs/{run_id}/exports/equity?format=csv|parquet
GET /runs/{run_id}/exports/summary
GET /runs/{run_id}/exports/readiness
```

Exports must include:
- stable schema version
- canonical ordering rules
- lineage metadata linking back to run/build/report

---

## 13. Milestone Dependency Graph

```text
M13  Compiler Input Contracts and First-Class Domain Schemas
  -> M14  Compiler Pipeline, Bundle Generation, and Safety Gates
    -> M15  Preflight Validation and Run Admission Control
      -> M16  Research Engine Core Loop and Timeframe Alignment
        -> M17  Cost, Sizing, Fills, Capital, and Walk-Forward Realism
          -> M18  Optimization, Candidate Promotion, and Holdout Workflows
            -> M19  Readiness Scoring, Policy Versioning, and Reports
              -> M20  Export Schemas, Artifact Registration, and API Surfaces
                -> M21  Reproducibility, Failure Semantics, and Adversarial Test Pack
```

No downstream milestone begins until predecessor acceptance criteria are green.

---

## 14. Ordered Milestone Sequence

### Milestone 13: Compiler Input Contracts and First-Class Domain Schemas

**Objective**

Define the compiler front-end contracts, foundational entities, enums, queues, and schema-bearing models before build logic starts.

**Deliverables**

- all compiler input-side contracts from Section 7
- Pydantic schemas for all new Phase 2 entities
- enums for build/run/trial/readiness/fill/sizing/policy states
- repository interfaces for every Phase 2 table
- queue class seed data
- Alembic migrations for baseline schema
- `libs/strategy_compiler/`, `libs/strategy_ir/`, `libs/experiment_plan/`, `libs/risk/` scaffolding

**Acceptance criteria**

- migrations upgrade/downgrade cleanly
- valid fixture payloads parse
- invalid payloads fail with typed validation errors
- queue classes are seeded correctly
- schema-bearing outputs are versioned from day one

---

### Milestone 14: Compiler Pipeline, Bundle Generation, and Safety Gates

**Objective**

Implement the deterministic compiler from front-end input through bundle output and blocking-gate enforcement.

**Deliverables**

- stage-by-stage compiler pipeline from Section 8.2
- canonicalization and template-binding modules
- uncertainty extractor using rules config, not hardcoded conditionals
- compiler bundle builder
- assumption report generation
- paper-eligibility gate
- strategy compilation endpoints

**Acceptance criteria**

- semantically identical drafts produce identical canonical bytes and build hashes
- unsupported freeform logic fails with typed validation errors
- unresolved material ambiguity blocks paper eligibility
- compiler bundle is persisted and artifact-linked
- compiler retries are idempotent and do not silently overwrite prior evidence

---

### Milestone 15: Preflight Validation and Run Admission Control

**Objective**

Prevent bad work from entering queues and ensure every compile/run request is admissible, reproducible, and policy-complete before execution starts.

**Deliverables**

- preflight validator service
- `run_preflight_results` repository and persistence
- queue admission gate
- structured rejection reasons
- audit event integration

**Acceptance criteria**

- uncertified or quarantined datasets are rejected
- missing lookback/timeframe coverage is rejected
- invalid search-space constraints are rejected
- missing reproducibility fields are rejected
- admissible requests persist preflight pass evidence before queue admission

---

### Milestone 16: Research Engine Core Loop and Timeframe Alignment

**Objective**

Implement the deterministic backtest loop with explicit PIT and multi-timeframe semantics.

**Deliverables**

- core bar/event loop
- PIT guard layer
- timeframe alignment module
- session/calendar-aware aggregation behavior
- state handling for signals, orders, fills, and exits
- deterministic replay hooks

**Acceptance criteria**

- same build + same dataset + same seed -> identical run outputs
- lower-timeframe execution cannot observe unfinished higher-timeframe bars
- aggregation boundaries are test-covered
- missing-bar policy is explicit and test-covered
- no I/O occurs in the hot loop

---

### Milestone 17: Cost, Sizing, Fills, Capital, and Walk-Forward Realism

**Objective**

Implement execution realism and accounting realism with explicit defaults and persisted policy references.

**Deliverables**

- spread/slippage/fees/swap models by versioned cost profile
- exact fill behavior from Section 8.6
- required sizing models from Section 8.8
- capital accounting and drawdown tracking
- walk-forward support from Section 8.3
- Monte Carlo / bootstrap scaffolding

**Acceptance criteria**

- cost profile version is persisted on every relevant run/trial
- fill rules are deterministic under fixed seed and dataset
- capital accounting reconciles across trade sequence and equity outputs
- walk-forward folds are lineage-linked and exportable
- conservative defaults are enforced where applicable

---

### Milestone 18: Optimization, Candidate Promotion, and Holdout Workflows

**Objective**

Implement resumable optimization, deterministic candidate ranking, audited promotion, and contamination-aware holdout evaluation.

**Deliverables**

- optimization worker with checkpointing
- trial orchestration and persistence
- candidate ranking service
- candidate promotion workflow
- holdout designation and contamination recording
- holdout evaluation flow

**Acceptance criteria**

- interrupted optimization resumes without losing completed trials
- each trial persists effective parameters, seed, and objective results
- candidate ranking uses an explicit ranking policy version
- promotion writes immutable audit evidence
- holdout evaluation contaminates the designation append-only
- top-N vs top-1 behavior is explicit and test-covered

---

### Milestone 19: Readiness Scoring, Policy Versioning, and Reports

**Objective**

Implement versioned readiness evaluation and evidence-backed report generation.

**Deliverables**

- readiness policy version model and repository
- scoring service implementing Policy Version 1 defaults
- regime baseline integration
- narrative report generation
- readiness report persistence and artifact registration

**Acceptance criteria**

- readiness reports persist policy version and narrative template version
- identical inputs under identical policy version produce identical grade/report payloads
- policy changes create new version IDs and do not rewrite history
- regime requirements are explicit: mandatory, conditional, or waived with rationale

---

### Milestone 20: Export Schemas, Artifact Registration, and API Surfaces

**Objective**

Expose all required Phase 2 artifacts through stable APIs and versioned export schemas.

**Deliverables**

- routes for strategy draft, compile, run submission, holdout verification, readiness generation, retrieval, and export
- export schemas for trial summaries, run summaries, equity curves, trade blotters, readiness reports, regime baselines, compiler assumption reports
- export manifests and artifact registration flows
- schema-versioned API responses

**Acceptance criteria**

- heavy operations return `202 Accepted` plus traceable job identity
- exports include stable schema versions and deterministic ordering rules
- CSV exports have canonical column order and sorting behavior
- artifact metadata links each export to run/build/report lineage
- OpenAPI docs cover route contracts, major errors, and idempotency behavior

---

### Milestone 21: Reproducibility, Failure Semantics, and Adversarial Test Pack

**Objective**

Close the phase with hardened reproducibility guarantees, explicit failure/retry semantics, and an adversarial correctness suite.

**Deliverables**

- failure-state model for compile/run/trial/report jobs
- retry policy definitions
- resume-versus-restart rules
- write-once artifact behavior tests
- reproducibility pack and golden fixtures
- adversarial test suite

**Acceptance criteria**

- retryable vs terminal failures are explicit and test-covered
- resume from checkpoint does not duplicate completed trials
- duplicate submit does not create duplicate official records
- same seed + same inputs + same policies produce byte-stable official exports where expected
- artifact overwrite attempts fail or explicitly version; they never silently replace evidence

---

## 15. Queue Classes

Seed at minimum:

| Queue class | Used for | Max concurrency |
|---|---|---|
| `compiler.default` | strategy compilation jobs | 8 |
| `research.default` | research runs | 4 |
| `research.batch` | optimization sweep trials | 16 |
| `research.holdout` | holdout evaluation | 2 |
| `readiness.default` | readiness generation | 4 |

---

## 16. Observability

Every service emits Phase 1 structured log fields plus:

| Field | When present |
|---|---|
| `strategy_build_id` | compile and run contexts |
| `run_id` | run context |
| `trial_id` | trial context |
| `simulation_date` | inside engine loop events |
| `pit_violation` | PIT violation events |
| `fold_number` | walk-forward context |
| `policy_version` | ranking/readiness policy context |

Recommended metrics:
- `compiler_builds_total{status}`
- `research_runs_total{run_type,status}`
- `trial_duration_seconds{run_type}`
- `pit_violations_total`
- `optimization_trials_total{run_id}`
- `readiness_grade_total{grade}`

---

## 17. Acceptance Test Pack

Minimum end-to-end and adversarial tests:

1. compile deterministic happy path
2. compile rejects unsupported freeform logic
3. compile emits blocked status on unresolved material ambiguity
4. preflight rejects uncertified dataset
5. preflight rejects missing lookback or timeframe coverage
6. preflight rejects invalid search-space constraints
7. duplicate compile submit suppresses duplicate work
8. single-timeframe PIT-safe research run
9. multi-timeframe PIT contamination test
10. stop/limit/gap-through execution realism test
11. missing-bar policy test for `halt`, `skip`, and `forward_fill`
12. capital accounting reconciliation test
13. walk-forward fold generation / purge behavior test
14. optimization resume after interruption
15. candidate ranking determinism test
16. candidate promotion audit-trail test
17. holdout contamination lifecycle test
18. readiness report reproducibility under same policy version
19. regime baseline generation test
20. retry-safe artifact registration test
21. canonical CSV export ordering test
22. byte-stable export test for identical inputs where applicable

---

## 18. Test Fixtures to Seed

Seed at minimum:

- certified single-timeframe dataset
- certified multi-timeframe dataset with known aggregation edges
- dataset with missing bars
- uncertified / quarantined dataset fixture
- cost profile fixtures with multiple versions
- holdout window and contamination fixture
- canonical strategy drafts showing deterministic compiler behavior
- ambiguous strategy draft fixture
- optimization fixture with resumable checkpoint state

---

## 19. Coding Standards

- no stubs or placeholder implementations in committed code
- no business logic in route handlers
- no direct DB access from controllers
- no hidden randomness; all randomness is seeded and persisted
- no silent fallback for missing timeframe bars or uncertified data
- all schema-bearing outputs are versioned
- all long-running flows are resumable or explicitly documented as non-resumable by rule
- no implicit candidate promotion inside ranking code
- no live-config inference of policy versions at read time; persist policy version at write time

---

## 20. What Not To Do

- do not build parallel storage, audit, or artifact systems outside Phase 1
- do not run heavy work synchronously in API handlers
- do not treat readiness as a single boolean field
- do not allow holdout verification without contamination recording
- do not let retries silently overwrite evidence artifacts
- do not implement multi-timeframe logic without explicit availability semantics
- do not leave fill rules, missing-bar rules, or sizing semantics to “reasonable defaults”
- do not let schema or policy drift occur without a new version and ADR

---

## 21. Phase 2 Definition of Done

Phase 2 is done only when all of the following are true:

1. strategy drafts compile deterministically into versioned build bundles
2. unresolved material ambiguity blocks paper-eligible progression
3. all compile/run requests pass mandatory preflight before queue admission
4. research runs are deterministic, PIT-safe, and multi-timeframe-safe
5. execution realism and capital accounting are credible and test-backed
6. optimization is resumable and trial lineage is complete
7. candidate ranking, promotion, and holdout verification are deterministic and audited
8. holdout contamination is recorded append-only
9. readiness reports are generated under explicit readiness policy versions
10. regime baselines are generated or explicitly waived under recorded rationale
11. all required exports are versioned, lineage-linked, and deterministic where applicable
12. retries, resumes, and duplicate submissions are safe and test-covered
13. the full adversarial test pack is green
14. API surfaces are documented and operationally traceable
15. a new developer can reproduce a fixture run from stored evidence without hand repair

---

## 22. Final Guidance for Claude

If there is tension between “keeping options open” and “making Phase 2 deterministic,” choose determinism.

If there is tension between “abstract architecture purity” and “explicit mechanics that prevent hidden bugs,” choose explicit mechanics.

If there is tension between “faster coding” and “lineage/reproducibility correctness,” choose lineage and reproducibility correctness.

That is the governing spirit of this merged workplan.
