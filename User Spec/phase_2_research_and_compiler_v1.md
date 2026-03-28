# FXLab Phase 2 — Strategy Compiler, Research Engine, and Optimization

## Context / Objective

This phase builds the analytical core of FXLab on top of the operational substrate delivered in Phase 1. The purpose is to convert user strategy intent into a constrained runtime representation, execute robust backtests and optimization workflows against certified datasets, and emit evidence artifacts that later governance, UI, and deployment phases can trust.

This work must dovetail into the rest of the project by treating Phase 1 contracts as authoritative. Research runs, compiler outputs, and optimization results must plug into the existing dataset registry, artifact store, audit ledger, queue classes, and compute policies instead of introducing parallel infrastructure. The result should be a **headless but fully credible research system** that can be driven by APIs before a polished UI exists.

## Primary outcome

Build the product’s analytical engine:

- Strategy IR and schema validation
- uncertainty ledger and confidence scoring
- constrained compiler pipeline
- deterministic research/backtest engine
- optimization sweeps
- holdout evaluation
- readiness scoring
- results artifacts and export-ready schemas

## In scope

### 1. Strategy representation and compiler

- `strategy_ir.json` schema
- `search_space.json`
- `experiment_plan.json`
- `ui_blueprint.json` generation hooks
- uncertainty ledger
- material ambiguity blocking logic
- deterministic template-bound harness generation
- compiler manifest and build hashes
- schema/static/PIT/logging contract checks

### 2. Research engine

- PIT-safe multi-timeframe logic
- swap/financing modeling
- spread/slippage/fees modeling
- partial fill and rejection simulation
- stop/limit/gap-through semantics
- position sizing models
- capital accounting
- walk-forward support
- untouched holdout evaluation
- Monte Carlo/bootstrap support
- regime segmentation and baselines
- candidate ranking and readiness scoring

### 3. Orchestrated batch workflows

- compile strategy job
- research run job
- optimization run job
- holdout verification job
- readiness report generation job
- artifact registration for all outputs
- resumable/retry-safe long-running jobs

### 4. Exportable artifacts

- trial-level summaries
- run summaries
- equity curve data
- trade blotter data
- readiness report payload
- regime baseline payload
- compiler assumption/confidence report

## Explicitly out of scope

- polished non-technical UI pages
- paper/live order submission
- broker adapters
- operator execution dashboards

Basic internal review surfaces or API docs are allowed, but the main output of this phase is service/API completeness.

## Dependencies on Phase 1

Phase 2 assumes Phase 1 already provides:

- certified dataset versions
- feed lineage and parity evidence
- queue classes and compute policies
- artifact storage and metadata registry
- immutable audit events
- correlation IDs
- auth/RBAC
- containerized services and worker runtime

No Phase 2 component may bypass Phase 1 storage or lineage controls.

## Required interface points

### Service boundaries

At minimum, create and document these services or modules:

- `strategy_compiler`
- `research_worker`
- `optimization_worker`
- `readiness_service`
- `results_artifact_service`

### Canonical APIs to establish in this phase

#### Strategy compilation
- `POST /strategies/draft`
- `POST /strategies/{strategy_id}/compile`
- `GET /strategies/{strategy_id}/versions/{version}`
- `GET /strategies/{strategy_id}/versions/{version}/uncertainty`
- `GET /strategies/{strategy_id}/versions/{version}/build`

#### Research and optimization
- `POST /runs/research`
- `POST /runs/optimize`
- `POST /runs/{run_id}/verify_holdout`
- `GET /runs/{run_id}`
- `GET /runs/{run_id}/trials`
- `GET /runs/{run_id}/artifacts`
- `GET /runs/{run_id}/readiness`

#### Exports and artifacts
- `GET /runs/{run_id}/exports/trades`
- `GET /runs/{run_id}/exports/equity`
- `GET /runs/{run_id}/exports/summary`
- `GET /runs/{run_id}/exports/readiness`

## API rules of engagement

1. Research requests must identify exact dataset versions or approved selectors that resolve deterministically.
2. Any compile or run request that depends on uncertified or quarantined data must fail by default.
3. Material ambiguity blocks paper-eligible compilation regardless of confidence score.
4. Long-running workflows must expose resumable job status rather than monolithic synchronous execution.
5. Every run artifact must include strategy version, dataset version, cost profile version, and seeds.
6. Readiness is an evidence object, not a boolean flag hidden in code.

## Data and computation rules of engagement

- Use Phase 1 queue classes; heavy optimization and Monte Carlo work must stay in batch-oriented classes.
- Preserve deterministic seeds for research and optimization.
- Every candidate score must be reproducible from stored artifacts.
- Holdout contamination must be explicit and irreversible in lineage until a new holdout is designated.
- No ad hoc notebook output counts as official evidence unless it is registered as an artifact with lineage metadata.

## Technical acceptance gate for Phase 2 exit

Phase 2 is complete only when all of the following are true:

- the compiler can produce a validated Strategy IR and uncertainty ledger from a constrained strategy description
- materially ambiguous strategies are blocked from paper-eligible progression
- the research engine can run deterministic backtests against certified data
- optimization sweeps can resume after interruption
- holdout verification is explicit and contamination-aware
- results include exportable trade-level and equity-curve data
- readiness scoring is persisted as a first-class artifact
- all jobs run through the orchestrator/scheduler rather than side channels

## Suggested work breakdown

1. schemas and first-class contracts
2. compiler pipeline and safety gates
3. research engine core loop
4. cost/sizing/capital realism
5. optimization and holdout workflows
6. readiness scoring and reports
7. export schemas and artifact registration
8. Phase 2 test harness and reproducibility pack

## Deliverables

- Strategy IR schemas and validators
- compiler service with manifest output
- deterministic research engine
- optimization worker
- holdout verification logic
- readiness scoring/report service
- exportable artifact schemas and endpoints
- Phase 2 acceptance test pack
