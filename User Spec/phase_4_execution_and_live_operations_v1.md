# FXLab Phase 4 — Broker Execution, Shadow/Paper/Live, and Production Hardening

## Context / Objective

This phase introduces the most operationally dangerous capability in the platform: external execution. The purpose is to connect FXLab to brokers in a way that preserves the evidence, lineage, risk controls, and auditability created in the earlier phases. This phase must not behave like a clean-room greenfield build. It must plug into the existing data, governance, queueing, artifact, and observability systems without creating side channels.

This work must dovetail into the rest of the project by treating research evidence, approvals, and deployment policy as hard prerequisites. Live capability is the last phase because the platform must already be able to explain what a strategy is, why it is eligible, what data it depends on, who approved it, and how the system will stop it when things go wrong.

## Primary outcome

Build the controlled execution layer:

- broker adapters
- shadow mode
- paper trading
- limited live deployment controls
- reconciliation
- pre-trade risk checks
- kill switches
- emergency posture/flatten logic
- execution drift analysis
- deep traceability and replay
- production drill/runbook readiness

## In scope

### 1. Broker integration layer

- idempotent broker adapter contract
- normalized order/event model
- account/position/open-order snapshots
- order/fill/reject/cancel updates
- throttling and market-state awareness
- adapter diagnostics

### 2. Realtime execution modes

- shadow mode
- paper deployment
- limited live deployment
- deployment enable/disable/freeze controls
- promotion gating enforcement
- deployment state machine

### 3. Safety controls

- reconciliation on startup/reconnect/interval
- pre-trade risk checks
- kill switches
- daily loss halts
- regime halts
- data-state halts
- MTTH measurement
- emergency posture matrix
- flatten/cancel procedures

### 4. Debugging and observability

- per-order timeline
- correlation ID search
- request/response capture with sanitization
- live-vs-expected drift views
- replay of order/session context
- adapter diagnostics pages
- incident-linked artifacts and logs

### 5. Production hardening

- drills and failure injection
- recovery testing
- rollback validation
- runbooks
- on-call/operator procedures
- staging-to-production promotion criteria

## Explicitly out of scope

- speculative new research features
- major schema redesign of earlier phases
- bypassing approval or readiness controls for convenience

Phase 4 is about safe execution, not inventing a second product.

## Dependencies on earlier phases

Phase 4 assumes these are already in place:

- Phase 1 containerized runtime, feed health, parity, alerts, audit, and queues
- Phase 2 Strategy IR, readiness reports, regime baselines, and exportable evidence
- Phase 3 approvals, overrides, governance UI, and operator dashboards

No Phase 4 execution path may ignore earlier phase state.

## Required interface points

### Service boundaries

- `broker_adapter`
- `realtime_worker`
- `reconciliation_service`
- `risk_gate`
- `execution_analysis`
- `deployment_control`

### Canonical APIs to establish in this phase

#### Deployment control
- `POST /deployments/paper`
- `POST /deployments/live-limited`
- `POST /deployments/{id}/freeze`
- `POST /deployments/{id}/unfreeze`
- `POST /deployments/{id}/rollback`
- `GET /deployments/{id}`
- `GET /deployments/{id}/health`

#### Execution and reconciliation
- `GET /deployments/{id}/orders`
- `GET /deployments/{id}/positions`
- `GET /deployments/{id}/timeline`
- `POST /reconciliation/run`
- `GET /reconciliation/reports/{id}`
- `GET /execution-drift/{deployment_id}`

#### Safety controls
- `POST /kill-switch/global`
- `POST /kill-switch/strategy/{strategy_id}`
- `POST /kill-switch/symbol/{symbol}`
- `GET /kill-switch/status`
- `GET /risk-events`
- `GET /adapter-diagnostics/{broker}`

## API rules of engagement

1. No deployment endpoint may succeed without required readiness evidence and approvals.
2. All order submission must pass through a single risk gate and adapter boundary.
3. Every order lifecycle event must carry a stable correlation ID.
4. Reconciliation is not optional for paper/live modes.
5. Kill switches must revoke new-order permission at the adapter gate, not merely in UI state.
6. Emergency posture must be declared before deployment activation.
7. Execution logs must be structured, searchable, and linked to deployments and incidents.

## Operational rules of engagement

- When state is uncertain, halt and alert.
- No manual broker-side intervention may remain undocumented; imported state must be visible.
- Any policy bypass must use the override model from earlier phases.
- Staging drills are required before production live enablement.
- A deployment without tested rollback and emergency posture is not eligible for live use.

## Technical acceptance gate for Phase 4 exit

Phase 4 is complete only when all of the following are true:

- shadow mode can run continuously and preserve end-to-end traceability
- paper trading uses the same normalized order lifecycle and risk gate as live
- reconciliation can recover from restart/reconnect without duplicating orders
- kill-switch MTTH is measured and within declared budget
- every deployment has a declared emergency posture and decision matrix
- operators can reconstruct an order from strategy decision through broker response and reconciliation
- live-vs-expected drift can be viewed and used to trigger alerts or halts
- rollback drills have been executed and documented

## Suggested work breakdown

1. normalized adapter contract and diagnostics
2. deployment state machine and policy gates
3. shadow mode pipeline
4. paper deployment pipeline
5. risk gate and reconciliation
6. kill switches, MTTH, and emergency posture
7. drift analysis and replay
8. runbooks, drills, and production hardening
9. Phase 4 acceptance test pack

## Deliverables

- broker adapter framework
- shadow/paper/live deployment services
- reconciliation service
- risk gate service
- kill-switch and halt controls
- execution analysis and replay tooling
- operator runbooks and drill documentation
- Phase 4 acceptance test pack
