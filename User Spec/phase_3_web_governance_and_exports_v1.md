# FXLab Phase 3 — Web UX, Governance, and Results/Export Surfaces

## Context / Objective

This phase turns the Phase 1 and Phase 2 services into a usable product for non-technical users, approvers, and operators. The purpose is to expose research results, governance controls, approvals, overrides, feed health, and export workflows through a coherent web experience without moving business logic into the UI.

This work must dovetail into the rest of the project by consuming only established APIs and contracts from the earlier phases. The UI is a client of the platform, not the source of truth. Every action taken through the UI must map cleanly to an auditable backend mutation or job request. By the end of this phase, a user should be able to define a strategy, monitor optimization, inspect evidence, understand blockers, export data, and move through governance workflows without reading code.

## Primary outcome

Build the product-facing control surfaces:

- Strategy Studio
- optimization/results explorer
- readiness reports
- feed operations dashboard
- approvals and override visibility
- export UX
- operator health views
- queue/contention visibility
- permissioned deployment controls (without full live execution yet)

## In scope

### 1. Non-technical product UX

- describe strategy page
- blueprint review page
- parameter tuning page
- run monitor
- candidate comparison views
- readiness report viewer
- explanation surfaces for ambiguity, overfitting, data blockers, and risk blockers

### 2. Governance UX

- approval requests and status
- promotion history
- override request/review surfaces
- watermark visibility wherever override exists
- separation-of-duties UI affordances
- audit history explorer

### 3. Data and operations UX

- feed registry pages
- feed health dashboard
- anomaly and certification viewer
- parity dashboard
- queue health / compute contention dashboard
- artifact browser
- operator diagnostics shell for non-execution components

### 4. Export and analytics UX

- equity curve
- drawdown curve
- trade blotter
- segmented performance views
- trial summary tables
- CSV/JSON/parquet export entry points
- human-readable readiness artifact export

## Explicitly out of scope

- real broker order routing
- live/paper execution management beyond placeholder controls or mock states
- emergency flatten actions
- reconciliation against external brokers

Those arrive in Phase 4.

## Dependencies on earlier phases

Phase 3 assumes the following are already stable:

- Phase 1 operational APIs and RBAC
- Phase 2 research/compiler/readiness APIs
- artifact storage and export payloads
- audit trail and object lineage
- queue status and health endpoints

If an interaction is not supported by a backend API, the UI may not invent it.

## Required interface points

### Frontend domains/pages

- `/strategy-studio`
- `/strategies/{id}/versions/{version}`
- `/runs/{run_id}`
- `/runs/{run_id}/results`
- `/runs/{run_id}/readiness`
- `/feeds`
- `/feeds/{feed_id}`
- `/data/certification`
- `/parity`
- `/approvals`
- `/overrides`
- `/audit`
- `/queues`
- `/artifacts`

### Backend APIs this phase depends on or extends

- `GET /runs/{run_id}/results`
- `GET /runs/{run_id}/charts`
- `GET /runs/{run_id}/readiness`
- `POST /promotions/request`
- `POST /approvals/{id}/approve`
- `POST /approvals/{id}/reject`
- `POST /overrides/request`
- `GET /overrides/{id}`
- `GET /audit`
- `GET /queues/contention`
- `GET /feeds`
- `GET /feed-health`
- `GET /parity/events`

## UI/API rules of engagement

1. The UI may not compute official readiness or governance state locally.
2. All action buttons must map to permission-checked backend actions.
3. Override state must be visible everywhere a candidate or deployment appears.
4. Exports must preserve lineage metadata and not strip identifiers.
5. The UI must explain blockers in plain language, but the canonical blocker reason comes from backend state.
6. Charts are views over exported data, not a substitute for exportability.

## Design rules of engagement

- Default to conservative presentation: blocked means blocked.
- Surface evidence, not just verdicts.
- Show lineage and version identifiers where decisions matter.
- Distinguish operator surfaces from end-user research surfaces.
- Do not hide degraded data quality, override status, or holdout contamination.

## Technical acceptance gate for Phase 3 exit

Phase 3 is complete only when all of the following are true:

- a non-technical user can create a draft strategy and launch research/optimization through the UI
- a user can understand why a candidate is blocked for paper eligibility
- approvers can see evidence, audit history, and override state in one place
- feed health, anomalies, and parity issues are visible in the UI
- authorized users can export trade-level and run-level data from the product
- queue contention and job state are visible to operators
- every UI mutation is auditable and backed by a stable API

## Suggested work breakdown

1. shell app, auth integration, and navigation
2. Strategy Studio and run monitor
3. results explorer and charting
4. readiness and governance views
5. feed operations and parity views
6. export UX and artifact browser
7. operator dashboards and audit explorer
8. Phase 3 usability and permissions test pack

## Deliverables

- web UI application
- design system for research/operator/governance states
- strategy and results pages
- readiness/governance workflow pages
- feed operations dashboards
- export UX and artifact browsing
- operator dashboards
- Phase 3 acceptance test pack
