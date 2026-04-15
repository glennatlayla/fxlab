# FXLab Phase 4 — Broker Execution, Shadow/Paper/Live, and Production Hardening

**Version:** 1.0
**Created:** 2026-04-11
**Source spec:** `User Spec/phase_4_execution_and_live_operations_v1.md`
**Phase 3 dependency:** All 11 milestones (M0, M22–M31) DONE per progress file.

---

```
MILESTONE INDEX
───────────────────────────────────────────────
Total milestones: 11
Tracks: Execution Foundation, Live Operations, Production Hardening

Execution Foundation: M0, M1, M2, M3, M4
Live Operations:      M5, M6, M7, M8
Production Hardening: M9, M10
───────────────────────────────────────────────
```

---

## Track: Execution Foundation

### M0 — Normalized Broker Adapter Contract & Diagnostics

**Objective:** Define the idempotent broker adapter interface, normalized order/event model,
and adapter diagnostics contract. This is the foundational abstraction that every execution
path (shadow, paper, live) depends on.

**Deliverables:**

- `libs/contracts/execution.py` — Pydantic schemas:
  - `OrderSide` enum (BUY, SELL)
  - `OrderType` enum (MARKET, LIMIT, STOP, STOP_LIMIT)
  - `TimeInForce` enum (DAY, GTC, IOC, FOK)
  - `OrderStatus` enum (pending, submitted, partial_fill, filled, cancelled, rejected, expired)
  - `ExecutionMode` enum (shadow, paper, live)
  - `OrderRequest` — normalized order submission payload
  - `OrderResponse` — normalized broker acknowledgment
  - `OrderFill` — individual fill event
  - `OrderEvent` — lifecycle event (submitted, partial, filled, cancelled, rejected)
  - `PositionSnapshot` — account position state
  - `AccountSnapshot` — account balance/margin state
  - `AdapterDiagnostics` — connection health, latency, error counts

- `libs/contracts/interfaces/broker_adapter_interface.py` — Abstract adapter port:
  - `submit_order(request: OrderRequest) -> OrderResponse` (idempotent via client_order_id)
  - `cancel_order(broker_order_id: str) -> OrderResponse`
  - `get_order(broker_order_id: str) -> OrderResponse`
  - `list_open_orders() -> list[OrderResponse]`
  - `get_positions() -> list[PositionSnapshot]`
  - `get_account() -> AccountSnapshot`
  - `get_diagnostics() -> AdapterDiagnostics`
  - `is_market_open() -> bool`

- `libs/contracts/mocks/mock_broker_adapter.py` — In-memory mock with:
  - Configurable fill simulation (instant, delayed, partial, reject)
  - Introspection: `get_submitted_orders()`, `get_fills()`, `clear()`
  - Market-hours simulation

- `libs/contracts/enums.py` — Extended with execution enums

- Unit tests for all schemas (validation, serialization roundtrip)
- Unit tests for mock adapter (all fill modes, idempotency check)

**Acceptance criteria:**
- All order lifecycle states representable via normalized model
- Mock adapter passes same interface tests as real adapter will
- Client order ID enforces idempotency (duplicate submission returns existing order)
- AdapterDiagnostics includes latency_ms, error_count, last_heartbeat, connection_status

---

### M1 — Execution Domain Models & Database Migration

**Objective:** Create SQLAlchemy ORM models for orders, fills, positions, and execution
events. Create Alembic migration to add these tables.

**Deliverables:**

- `libs/contracts/models.py` — New ORM models (appended):
  - `Order` — broker order record with client_order_id (unique), deployment_id FK,
    strategy_id FK, symbol, side, order_type, quantity, limit_price, stop_price,
    time_in_force, status, broker_order_id, submitted_at, filled_at, cancelled_at,
    average_fill_price, filled_quantity, correlation_id, execution_mode
  - `OrderFill` — individual fill events: order_id FK, fill_id (broker), price,
    quantity, commission, filled_at, broker_execution_id
  - `Position` — current position state: deployment_id FK, symbol, quantity,
    average_entry_price, market_value, unrealized_pnl, realized_pnl, updated_at
  - `ExecutionEvent` — append-only execution audit: order_id FK, event_type,
    timestamp, details JSON, correlation_id
  - `KillSwitchEvent` — kill switch activations: scope (global/strategy/symbol),
    target_id, activated_by, activated_at, deactivated_at, reason
  - `ReconciliationReport` — recon run results: deployment_id FK, started_at,
    completed_at, status, discrepancies JSON, resolved_count, unresolved_count

- `migrations/versions/20260411_0009_add_execution_tables.py` — Alembic migration:
  - orders, order_fills, positions, execution_events, kill_switch_events,
    reconciliation_reports tables
  - Proper indexes on deployment_id, strategy_id, symbol, correlation_id, status
  - Check constraints on enum columns
  - Foreign key constraints with appropriate ON DELETE semantics

- Unit tests for model validation (ULID, enum constraints, FK integrity)

**Acceptance criteria:**
- Migration runs cleanly up and down (upgrade + downgrade)
- All models use TimestampMixin where appropriate
- Check constraints match enum values exactly
- Indexes support the query patterns: by deployment, by symbol, by status, by correlation_id

---

### M2 — Deployment State Machine & Policy Gates

**Objective:** Build the deployment control service with a formal state machine that
enforces promotion gating, readiness evidence, and approval requirements before any
execution mode can be activated.

**Deliverables:**

- `libs/contracts/deployment.py` — Deployment state machine schemas:
  - `DeploymentState` enum (created, pending_approval, approved, activating,
    active, frozen, deactivating, deactivated, rolled_back, failed)
  - `DeploymentTransition` — valid state transitions with guard conditions
  - `DeploymentCreateRequest` — creation payload (strategy_id, execution_mode,
    emergency_posture, risk_limits)
  - `DeploymentHealthResponse` — live health summary
  - `EmergencyPosture` — declared posture (flatten_all, cancel_open, hold, custom)

- `libs/contracts/interfaces/deployment_service_interface.py` — Service port:
  - `create_deployment(request: DeploymentCreateRequest) -> Deployment`
  - `activate_deployment(deployment_id: str) -> Deployment`
  - `freeze_deployment(deployment_id: str, reason: str) -> Deployment`
  - `unfreeze_deployment(deployment_id: str) -> Deployment`
  - `rollback_deployment(deployment_id: str) -> Deployment`
  - `get_deployment(deployment_id: str) -> Deployment`
  - `get_deployment_health(deployment_id: str) -> DeploymentHealthResponse`

- `services/api/services/deployment_service.py` — Implementation:
  - State machine with transition validation (illegal transitions → error)
  - Pre-activation gates: readiness check, approval check, emergency posture declared
  - Audit event on every state transition
  - Deployment cannot activate without declared emergency posture (spec rule 6)

- `libs/contracts/interfaces/deployment_repository_interface.py` — Repository port
- `services/api/repositories/sql_deployment_control_repository.py` — SQL implementation
- `libs/contracts/mocks/mock_deployment_repository.py` — In-memory mock

- `services/api/routes/deployments.py` — API routes:
  - `POST /deployments/paper`
  - `POST /deployments/live-limited`
  - `POST /deployments/{id}/freeze`
  - `POST /deployments/{id}/unfreeze`
  - `POST /deployments/{id}/rollback`
  - `GET /deployments/{id}`
  - `GET /deployments/{id}/health`

- Unit tests: all state transitions (valid + invalid), policy gate enforcement,
  audit event emission, API route validation
- Integration tests: full promotion → deploy → freeze → rollback lifecycle

**Acceptance criteria:**
- No deployment activates without readiness evidence + approval + emergency posture
- All transitions audited
- Invalid transitions return clear error with current state and attempted transition
- Frozen deployment rejects all order submissions

---

### M3 — Shadow Mode Pipeline

**Objective:** Implement shadow mode where the system records what it *would* have done
without touching the broker. Shadow mode uses the same order lifecycle and risk gate
as paper/live but routes to a no-op adapter that logs decisions.

**Deliverables:**

- `services/api/services/shadow_execution_service.py` — Shadow worker:
  - Receives strategy signals from the realtime worker
  - Runs pre-trade risk checks (same gate as live)
  - Submits to ShadowBrokerAdapter (logs, does not execute)
  - Records OrderEvent timeline with correlation_id
  - Tracks hypothetical positions and P&L

- `libs/contracts/mocks/shadow_broker_adapter.py` — Shadow adapter:
  - Implements BrokerAdapterInterface
  - Always "fills" at market price (from feed data)
  - Records full decision timeline
  - Produces AdapterDiagnostics with shadow-specific metrics

- `services/api/routes/shadow.py` — Shadow-specific query routes:
  - `GET /deployments/{id}/shadow-decisions` — recorded decisions
  - `GET /deployments/{id}/shadow-pnl` — hypothetical P&L

- Unit tests: signal → risk check → shadow fill → position update → audit trail
- Integration test: end-to-end shadow pipeline with mock feed data

**Acceptance criteria:**
- Shadow mode preserves end-to-end traceability (spec acceptance gate 1)
- Same risk gate as paper/live (spec acceptance gate 2)
- No broker side-effects
- All decisions recoverable by correlation_id

---

### M4 — Paper Deployment Pipeline

**Objective:** Build the paper trading pipeline using a simulated broker adapter that
maintains realistic order lifecycle (with configurable latency, partial fills, rejects).

**Deliverables:**

- `libs/broker/paper_broker_adapter.py` — Paper adapter:
  - Implements BrokerAdapterInterface
  - Simulated order book with configurable latency
  - Supports partial fills, market/limit order types
  - Realistic position tracking (margin, fees)
  - Reconciliation-compatible (startup recovery)

- `services/api/services/paper_execution_service.py` — Paper execution worker:
  - Same risk gate as live
  - Order lifecycle: submit → ack → fill/reject → position update
  - Reconciliation on startup/reconnect
  - All events carry correlation_id

- API routes reuse deployment routes from M2 (mode=paper)

- Unit tests: full order lifecycle, partial fills, rejects, reconnect reconciliation
- Integration test: strategy signal → risk gate → paper fill → position → recon

**Acceptance criteria:**
- Paper uses same normalized order lifecycle and risk gate as live (spec acceptance gate 2)
- Reconciliation recovers from restart without duplicating orders (spec gate 3)
- Paper positions and P&L track realistically

---

## Track: Live Operations

### M5 — Risk Gate & Pre-Trade Checks

**Objective:** Build the centralized risk gate that every order must pass through before
reaching any broker adapter. Implements position limits, daily loss limits, concentration
limits, and order-level validation.

**Deliverables:**

- `libs/contracts/risk.py` — Risk schemas:
  - `RiskCheckResult` — pass/fail with reason
  - `RiskLimits` — configurable limits per deployment (max_position_size,
    max_daily_loss, max_order_value, max_concentration_pct, max_open_orders)
  - `RiskEvent` — recorded risk check events (pass, fail, override)
  - `RiskEventSeverity` enum (info, warning, critical, halt)

- `libs/contracts/interfaces/risk_gate_interface.py` — Service port:
  - `check_order(order: OrderRequest, deployment: Deployment) -> RiskCheckResult`
  - `check_position_limits(deployment_id: str) -> RiskCheckResult`
  - `get_risk_events(deployment_id: str) -> list[RiskEvent]`

- `services/api/services/risk_gate_service.py` — Implementation:
  - Pre-trade checks: position limit, daily loss, order value, concentration
  - Checks are ordered: cheapest first, fail-fast on first violation
  - Risk events logged to risk_events table (append-only)
  - All checks use deployment-scoped limits (no global defaults bypass)

- `libs/contracts/interfaces/risk_event_repository_interface.py` — Repository port
- `services/api/repositories/sql_risk_event_repository.py` — SQL implementation
- `libs/contracts/mocks/mock_risk_event_repository.py` — In-memory mock

- `services/api/routes/risk.py` — API routes:
  - `GET /risk-events` (filterable by deployment, severity, time range)
  - `GET /deployments/{id}/risk-limits` — current limits

- Unit tests: each check type (pass + fail), fail-fast ordering, event recording
- Integration test: order submission → risk gate → accept/reject → audit

**Acceptance criteria:**
- Every order passes through risk gate before adapter (spec rule 2)
- Failed risk checks produce RiskEvent with severity and human-readable reason
- No order bypasses risk gate (enforced at service layer, not just API)

---

### M6 — Reconciliation Service

**Objective:** Build the reconciliation service that detects and reports discrepancies
between FXLab's internal state and broker state. Runs on startup, reconnect, and
configurable intervals.

**Deliverables:**

- `libs/contracts/reconciliation.py` — Reconciliation schemas:
  - `ReconciliationTrigger` enum (startup, reconnect, scheduled, manual)
  - `DiscrepancyType` enum (missing_order, extra_order, quantity_mismatch,
    price_mismatch, status_mismatch, missing_position, extra_position)
  - `Discrepancy` — individual discrepancy record
  - `ReconciliationRunRequest` — trigger a recon run
  - `ReconciliationRunResponse` — recon results summary

- `libs/contracts/interfaces/reconciliation_service_interface.py` — Service port:
  - `run_reconciliation(deployment_id: str, trigger: ReconciliationTrigger) -> ReconciliationReport`
  - `get_report(report_id: str) -> ReconciliationReport`
  - `list_reports(deployment_id: str) -> list[ReconciliationReport]`

- `services/api/services/reconciliation_service.py` — Implementation:
  - Compare internal orders/positions vs broker snapshot
  - Detect all DiscrepancyType variants
  - Auto-resolve safe discrepancies (e.g., status lag)
  - Flag unsafe discrepancies for operator review
  - Generate ReconciliationReport with resolved/unresolved counts

- `libs/contracts/interfaces/reconciliation_repository_interface.py` — Repository port
- `services/api/repositories/sql_reconciliation_repository.py` — SQL implementation
- `libs/contracts/mocks/mock_reconciliation_repository.py` — In-memory mock

- `services/api/routes/reconciliation.py` — API routes:
  - `POST /reconciliation/run`
  - `GET /reconciliation/reports/{id}`
  - `GET /reconciliation/reports?deployment_id=...`

- Unit tests: each discrepancy type, auto-resolve logic, report generation
- Integration test: inject discrepancies → recon → report → audit

**Acceptance criteria:**
- Reconciliation can recover from restart/reconnect without duplicating orders (spec gate 3)
- All discrepancy types detected and classified
- Unsafe discrepancies halt new order submission until resolved

---

### M7 — Kill Switches, MTTH & Emergency Posture

**Objective:** Build the kill switch system with global, per-strategy, and per-symbol
scopes. Measure Mean Time To Halt (MTTH). Implement emergency posture execution
(flatten, cancel, hold).

**Deliverables:**

- `libs/contracts/safety.py` — Safety control schemas:
  - `KillSwitchScope` enum (global, strategy, symbol)
  - `KillSwitchStatus` — current state per scope
  - `KillSwitchActivateRequest` — activation payload
  - `EmergencyPostureType` enum (flatten_all, cancel_open, hold, custom)
  - `EmergencyPostureDecision` — posture execution record
  - `HaltTrigger` enum (kill_switch, daily_loss, regime, data_state, manual)
  - `HaltEvent` — recorded halt with trigger, scope, MTTH measurement

- `libs/contracts/interfaces/kill_switch_service_interface.py` — Service port:
  - `activate_kill_switch(scope, target_id, reason) -> KillSwitchEvent`
  - `deactivate_kill_switch(scope, target_id) -> KillSwitchEvent`
  - `get_status() -> list[KillSwitchStatus]`
  - `execute_emergency_posture(deployment_id: str) -> EmergencyPostureDecision`

- `services/api/services/kill_switch_service.py` — Implementation:
  - Kill switch revokes order permission at adapter gate (spec rule 5)
  - MTTH measurement: time from trigger to all-orders-cancelled confirmation
  - Emergency posture execution: flatten (market sell all), cancel (cancel open), hold
  - Daily loss halt: triggered when realized + unrealized loss exceeds limit
  - Regime halt: triggered by external regime signal
  - Data-state halt: triggered when feed health degrades below threshold

- `services/api/routes/kill_switch.py` — API routes:
  - `POST /kill-switch/global`
  - `POST /kill-switch/strategy/{strategy_id}`
  - `POST /kill-switch/symbol/{symbol}`
  - `GET /kill-switch/status`

- Unit tests: each scope, MTTH calculation, posture execution, halt triggers
- Integration test: daily loss breach → kill switch → flatten → audit

**Acceptance criteria:**
- Kill switches revoke at adapter gate, not just UI (spec rule 5)
- Kill-switch MTTH measured and within declared budget (spec gate 4)
- Every deployment has declared emergency posture (spec rule 6, gate 5)
- Emergency posture tested in shadow and paper before live eligibility

---

### M8 — Execution Drift Analysis & Replay

**Objective:** Build the drift analysis engine that compares actual execution against
expected (shadow/backtest) execution, and the replay system that reconstructs order
context from strategy decision through broker response.

**Deliverables:**

- `libs/contracts/drift.py` — Drift analysis schemas:
  - `DriftMetric` — individual metric comparison (expected vs actual)
  - `DriftReport` — summary with categorized drift entries
  - `DriftSeverity` enum (negligible, minor, significant, critical)
  - `ReplayTimeline` — ordered event sequence for an order

- `libs/contracts/interfaces/execution_analysis_interface.py` — Service port:
  - `compute_drift(deployment_id: str, window: str) -> DriftReport`
  - `get_order_timeline(order_id: str) -> ReplayTimeline`
  - `search_by_correlation_id(correlation_id: str) -> list[ExecutionEvent]`

- `services/api/services/execution_analysis_service.py` — Implementation:
  - Drift metrics: fill price vs expected, timing drift, slippage, fill rate
  - Drift severity classification (thresholds configurable per deployment)
  - Order timeline reconstruction from ExecutionEvent table
  - Correlation ID search across orders, fills, risk events, audit events

- `services/api/routes/execution_analysis.py` — API routes:
  - `GET /execution-drift/{deployment_id}`
  - `GET /deployments/{id}/orders`
  - `GET /deployments/{id}/positions`
  - `GET /deployments/{id}/timeline`

- `services/api/routes/adapter_diagnostics.py` — Adapter health:
  - `GET /adapter-diagnostics/{broker}`

- Unit tests: each drift metric, severity classification, timeline reconstruction
- Integration test: shadow vs paper comparison, correlation search

**Acceptance criteria:**
- Operators can reconstruct an order from strategy decision through broker response (spec gate 6)
- Live-vs-expected drift viewable and can trigger alerts/halts (spec gate 7)
- Correlation ID search returns complete event chain

---

## Track: Production Hardening

### M9 — Runbooks, Drills & Production Hardening

**Objective:** Create operator runbooks, execute rollback drills, validate recovery
procedures, and document staging-to-production promotion criteria.

**Deliverables:**

- `docs/runbooks/` — Operator runbooks:
  - `incident-response.md` — kill switch activation, escalation, post-incident review
  - `deployment-operations.md` — deploy, freeze, unfreeze, rollback procedures
  - `reconciliation-procedures.md` — scheduled recon, discrepancy resolution
  - `broker-failover.md` — adapter reconnection, manual position import
  - `staging-to-production.md` — promotion criteria checklist

- `services/api/services/drill_service.py` — Drill execution framework:
  - `execute_drill(drill_type: str, deployment_id: str) -> DrillResult`
  - Drill types: kill_switch_drill, rollback_drill, reconnect_drill, failover_drill
  - Drill results recorded as artifacts linked to deployments

- `libs/contracts/drill.py` — Drill schemas:
  - `DrillType` enum
  - `DrillResult` — pass/fail with MTTH, timeline, discrepancies found
  - `DrillRequirement` — prerequisite for live enablement

- Unit tests for drill service execution and result recording

**Acceptance criteria:**
- Rollback drills executed and documented (spec gate 8)
- Kill switch MTTH measured during drill
- Each drill produces an artifact linked to the deployment
- No deployment eligible for live without passing all drill types

---

### M10 — Phase 4 Acceptance Test Pack

**Objective:** Comprehensive acceptance test suite verifying all Phase 4 exit criteria
from the spec. This is the final gate before Phase 4 is declared complete.

**Deliverables:**

- `tests/acceptance/phase4/` — Acceptance tests:
  - `test_shadow_traceability.py` — Shadow mode end-to-end traceability
  - `test_paper_live_parity.py` — Paper uses same lifecycle and risk gate as live
  - `test_reconciliation_recovery.py` — Recon recovers from restart without duplicates
  - `test_kill_switch_mtth.py` — MTTH within budget
  - `test_emergency_posture.py` — Every deployment has posture + decision matrix
  - `test_order_reconstruction.py` — Full order timeline from decision to broker response
  - `test_drift_alerting.py` — Drift triggers alerts/halts
  - `test_rollback_drill.py` — Rollback drill executed and documented

- Coverage report for all Phase 4 code (≥85% new code, ≥80% overall)
- §16 Rule 4 reconciliation: source_count == done_count + open_count

**Acceptance criteria:**
- All 8 spec acceptance gates pass
- All unit + integration + acceptance tests green
- Coverage thresholds met
- Phase declared complete via §16 Rule 4 reconciliation

---

## Cross-Cutting Concerns (Apply to Every Milestone)

### Correlation ID propagation
Every order, fill, risk event, audit event, and execution event carries a correlation_id
originating from the strategy signal. The middleware already propagates X-Correlation-Id
via `services/api/middleware/correlation.py` — execution layer must thread it through
the adapter boundary.

### Audit trail
Every mutation (order submit, cancel, fill, position update, risk check, kill switch,
recon) produces an AuditEvent via `services/api/services/audit_writer.py`.

### Structured logging
Per CLAUDE.md §8: all execution events logged with operation, correlation_id, component,
duration_ms, result.

### Error handling
Per CLAUDE.md §9: transient errors (broker timeout, rate limit) → retry with backoff.
Permanent errors (auth, validation, insufficient funds) → fail fast.

### No side channels
Per spec: "No Phase 4 execution path may ignore earlier phase state." Every deployment
checks readiness, approvals, and governance state from Phase 3 services.
