# FXLab v9 — Recommended Development Phasing

## Context / Objective

This package breaks FXLab v9 into four development phases that build in the right order for an LLM-assisted engineering workflow. The intent is to establish the operational spine first, then layer on research capability, then user-facing governance and analytics, and finally live/paper execution. Each phase file is written so it can stand alone as work context for an implementation agent while still dovetailing into the rest of the project.

The overall sequencing is deliberate:

1. **Phase 1 — Platform Foundation, Data Operations, and Containerized Runtime**
2. **Phase 2 — Strategy Compiler, Research Engine, and Optimization**
3. **Phase 3 — Web UX, Governance, and Results/Export Surfaces**
4. **Phase 4 — Broker Execution, Shadow/Paper/Live, and Production Hardening**

## Why this split

This is the cleanest way to reduce rework:

- **Phase 1** creates the substrate: Dockerized services, database schemas, artifact storage, feed registry, data certification, parity, observability, queueing, and base APIs.
- **Phase 2** builds the core product value on top of that substrate: Strategy IR, compiler, backtester, optimization, readiness scoring, and research artifacts.
- **Phase 3** turns the engine into an actual operator product: Strategy Studio, dashboards, readiness workflow, exports, approvals, and override visibility.
- **Phase 4** adds the most dangerous capability last: broker connectivity, shadow, paper, limited live, kill switches, reconciliation, and emergency controls.

## Cross-phase rules of engagement

These rules apply to every phase:

1. **Do not break lineage.** Every object must be versioned and traceable.
2. **No hidden contracts.** If one service depends on another, declare the interface explicitly in code and docs.
3. **APIs first, UI second.** The UI may not invent business logic that does not exist behind a stable API or service contract.
4. **Determinism wins.** Batch research must be reproducible; live paths must be explicitly marked as non-deterministic.
5. **Safe defaults only.** When state is uncertain, block, degrade, or halt rather than continue silently.
6. **Feature gating is mandatory.** Paper and live capabilities must remain disabled until earlier evidence gates exist and are passing.
7. **Every phase ends with a stable contract.** The next phase may assume those contracts exist, but may not rewrite them casually.

## Shared canonical contracts

These should be established early and extended carefully:

- `strategy`
- `strategy_version`
- `strategy_build`
- `dataset_version`
- `feed_config_version`
- `experiment_plan`
- `search_space`
- `run`
- `trial`
- `readiness_report`
- `promotion_decision`
- `paper_deployment`
- `live_deployment`
- `override_record`
- `feed_health_event`
- `parity_event`
- `audit_event`

## Recommended repository layout

```text
fxlab/
  services/
    api/
    orchestrator/
    scheduler/
    market_data_ingest/
    feed_verification/
    parity/
    research_worker/
    realtime_worker/
    broker_adapter/
    alerting/
  libs/
    contracts/
    strategy_ir/
    experiment_plan/
    event_ledger/
    data_quality/
    risk/
    charting/
  infra/
    docker/
    compose/
    migrations/
    observability/
  docs/
    phases/
```

## Deliverables in this package

- `phase_1_platform_foundation_v1.md`
- `phase_2_research_and_compiler_v1.md`
- `phase_3_web_governance_and_exports_v1.md`
- `phase_4_execution_and_live_operations_v1.md`
