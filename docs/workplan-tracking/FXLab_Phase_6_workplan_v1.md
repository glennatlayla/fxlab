# FXLab Phase 6 — Live Operations, Identity, Trader UX & Compliance

**Version:** 1.0
**Created:** 2026-04-12
**Author:** Phase 6 Architecture Session
**Depends on:** Phase 5 (all 18 milestones DONE)
**Estimated milestones:** 14

---

## Revision History

| Version | Date | Changes |
|---------|------|---------|
| 1.0 | 2026-04-12 | Initial workplan: 14 milestones across 4 tracks |

---

```
MILESTONE INDEX
───────────────────────────────────────────────
Total milestones: 14
Tracks: Identity & Auth, Live Trading, Trader UX, Compliance & Automation

Identity & Auth:       M0, M1, M2
Live Trading:          M3, M4, M5, M6
Trader UX:             M7, M8, M9, M10
Compliance & Automation: M11, M12, M13
───────────────────────────────────────────────
```

---

## Track: Identity & Auth

### M0 — Keycloak Token Validation and RS256 Migration

**Objective:** Replace self-rolled JWT HS256 token issuance with Keycloak RS256
token validation. The API becomes a resource server that validates tokens issued
by Keycloak, not an identity provider.

**Context:** Phase 1 bootstrapped JWT HS256 in `services/api/auth.py`. Phase 3
added OIDC-compatible discovery endpoints. Decision (2026-04-03): Keycloak is
the canonical IdP. This milestone executes that decision on the backend.

**Deliverables:**

- `services/api/infrastructure/keycloak_token_validator.py` — RS256 token validator:
  - Fetch Keycloak JWKS from `{KEYCLOAK_URL}/realms/{realm}/protocol/openid-connect/certs`
  - Cache JWKS with configurable TTL (default 5 min), refresh on cache miss
  - Validate: signature (RS256), issuer, audience, expiration, not-before
  - Extract claims: sub, email, roles, realm_access, resource_access
  - Thread-safe JWKS cache (Lock-protected)
  - Timeout on JWKS fetch (5s default), fail-closed on error

- `services/api/auth.py` — Modified:
  - New `AuthMode` enum: `LOCAL_JWT` | `KEYCLOAK`
  - `AUTH_MODE` env var selects mode (default: `LOCAL_JWT` for backward compat)
  - `KEYCLOAK` mode: validate via KeycloakTokenValidator
  - `LOCAL_JWT` mode: existing HS256 validation (unchanged)
  - `AuthenticatedUser` extended with `auth_mode` field
  - Role mapping: Keycloak realm_access.roles → FXLab role scopes

- `services/api/config.py` — Extended:
  - `KeycloakSettings`: keycloak_url, realm, client_id, jwks_ttl_seconds
  - Nested under AppSettings

- Tests:
  - Unit tests for KeycloakTokenValidator (mocked JWKS endpoint)
  - Unit tests for AuthMode switching (LOCAL_JWT vs KEYCLOAK)
  - Integration test with Keycloak container (docker-compose.test.yml)

**Acceptance criteria:**
- AUTH_MODE=KEYCLOAK: Keycloak-issued RS256 token grants access to protected endpoints
- AUTH_MODE=LOCAL_JWT: existing HS256 tokens continue to work (zero breaking changes)
- JWKS cache refreshes on key rotation without restart
- Invalid/expired Keycloak tokens return 401 with structured error
- All existing auth tests pass with AUTH_MODE=LOCAL_JWT

---

### M1 — Frontend OIDC Integration

**Objective:** Wire the React frontend to authenticate via Keycloak's OIDC flow
using `oidc-client-ts`, replacing the current local JWT login form.

**Context:** Frontend auth context (`frontend/src/context/AuthContext.tsx`) currently
POSTs to `/auth/token` for local JWT. This milestone adds the OIDC authorization
code flow with PKCE as the primary auth path.

**Deliverables:**

- `frontend/src/auth/OidcProvider.tsx` — OIDC provider using oidc-client-ts:
  - Authorization Code Flow with PKCE
  - Automatic silent token renewal (refresh_token grant)
  - Logout: RP-initiated logout → Keycloak end_session_endpoint
  - State persistence: in-memory only (no localStorage per security policy)
  - Configurable via `VITE_OIDC_AUTHORITY`, `VITE_OIDC_CLIENT_ID`, `VITE_OIDC_REDIRECT_URI`

- `frontend/src/auth/AuthGate.tsx` — Auth mode switch:
  - `VITE_AUTH_MODE=oidc`: render OidcProvider
  - `VITE_AUTH_MODE=local`: render existing local JWT provider
  - Default: `local` (backward compat)

- `frontend/src/context/AuthContext.tsx` — Modified:
  - Accept user identity from either OIDC or local provider
  - Expose unified `user`, `isAuthenticated`, `logout`, `getAccessToken` interface

- `frontend/.env.example` — Updated with OIDC config variables

- Tests:
  - Unit tests for OidcProvider (mocked oidc-client-ts)
  - Unit tests for AuthGate mode switching
  - Integration test: Keycloak → OIDC login → API access (docker-compose)

**Acceptance criteria:**
- OIDC login flow redirects to Keycloak, returns with valid token
- Silent renewal extends session without user interaction
- Logout terminates both frontend session and Keycloak session
- Local JWT mode continues to work when VITE_AUTH_MODE=local
- No localStorage usage (all token state in memory)

---

### M2 — Admin Panel: User Management and Secret Rotation UI

**Objective:** Build an admin panel in the React frontend for Keycloak user/role
management and secret rotation operations.

**Deliverables:**

- `frontend/src/pages/Admin/UserManagement.tsx` — Admin user management:
  - List users from Keycloak (via `/admin/users` API)
  - Create user (email, first_name, last_name, temporary_password, roles)
  - Update user roles
  - Reset password (sends Keycloak reset email)
  - Table with search/filter, pagination

- `frontend/src/pages/Admin/SecretManagement.tsx` — Secret rotation UI:
  - List secrets with metadata (key, source, is_set, last_rotated)
  - Expiring secrets highlighted (red/yellow based on days since rotation)
  - Trigger rotation button (calls `/admin/secrets/{key}/rotate`)
  - Rotation history log

- `frontend/src/pages/Admin/AdminLayout.tsx` — Admin navigation:
  - Sidebar with: Users, Secrets, System Health
  - Role-gated: only visible to users with `admin:manage` scope
  - Route: `/admin/*`

- API changes:
  - `GET /admin/secrets/expiring?threshold_days=90` — new endpoint
  - Wired to `EnvSecretProvider.list_expiring()`

- Tests:
  - Unit tests for Admin components (render, interaction, API calls)
  - API tests for new expiring endpoint

**Acceptance criteria:**
- Admin users can create/update/delete Keycloak users from the UI
- Secret rotation triggered from UI completes without service restart
- Non-admin users cannot access the admin panel (403)
- Expiring secrets surfaced with visual urgency indicators

---

## Track: Live Trading

### M3 — Live Execution Service and Broker Credential Wiring

**Objective:** Implement the live execution service that routes orders through real
broker adapters with full risk gate enforcement, order tracking, and position management.

**Context:** Paper and shadow execution services exist. The live execution service
follows the same pattern but with real broker adapters and stricter safety checks.

**Deliverables:**

- `services/api/services/live_execution_service.py` — Live execution service:
  - Implements same interface pattern as paper/shadow execution services
  - Mandatory pre-trade risk gate enforcement (no bypass)
  - Order submission through BrokerAdapterRegistry (real adapters only)
  - Position tracking: persist every fill to SqlPositionRepository
  - Execution event logging: all order lifecycle events persisted
  - Double-check kill switch state before every order submission
  - Structured logging at every decision point (submit, fill, reject, cancel)
  - Thread-safe: Lock on order state transitions

- `services/api/services/interfaces/live_execution_service_interface.py` — Interface

- `services/api/routes/live.py` — Live trading endpoints:
  - `POST /live/orders` — submit live order (requires `live:trade` scope)
  - `GET /live/orders` — list live orders
  - `GET /live/positions` — list live positions
  - `POST /live/orders/{id}/cancel` — cancel live order
  - `GET /live/pnl` — live P&L summary
  - All endpoints require elevated auth scope (`live:trade`)

- `services/api/auth.py` — Extended:
  - New scope: `live:trade` (separate from paper/shadow)
  - Role mapping: `live_trader` role → `live:trade` scope

- Tests:
  - Unit tests with MockBrokerAdapter (all order lifecycle paths)
  - Risk gate rejection tests (mandatory enforcement)
  - Kill switch pre-check tests
  - Thread safety tests for concurrent order submission

**Acceptance criteria:**
- Live orders route through real broker adapter (Alpaca in paper mode for testing)
- Every order persisted to database before broker submission
- Kill switch check happens before every submission — halts if active
- Risk gate rejection returns structured error with check details
- All existing paper/shadow tests unaffected

---

### M4 — Multi-Broker Expansion: Schwab/TD Ameritrade Adapter

**Objective:** Add a second broker adapter (Schwab, formerly TD Ameritrade) to
validate the multi-broker architecture and provide broker diversity.

**Deliverables:**

- `services/api/infrastructure/schwab_broker_adapter.py` — Schwab adapter:
  - Implements BrokerAdapterInterface (all 12 methods)
  - OAuth 2.0 authentication flow (Schwab API requires OAuth)
  - Order mapping: FXLab OrderRequest → Schwab order format
  - Status mapping: Schwab statuses → FXLab OrderStatus enum
  - httpx.Client with BrokerTimeoutConfig-driven timeouts
  - Retry on 429/5xx with exponential backoff
  - Error mapping to FXLab exception hierarchy

- `services/api/infrastructure/schwab_config.py` — Schwab configuration:
  - SchwabConfig: Pydantic model with OAuth credentials, API URLs
  - Paper vs live URL selection

- `services/api/infrastructure/schwab_auth.py` — OAuth token management:
  - Authorization code flow (initial setup)
  - Refresh token auto-renewal
  - Token persistence via SecretProvider
  - Thread-safe token access

- Tests:
  - Unit tests with mocked HTTP responses (all 12 adapter methods)
  - OAuth flow tests (token refresh, expiration handling)
  - Integration tests (skipped unless SCHWAB_CLIENT_ID set)

**Acceptance criteria:**
- Schwab adapter passes same test suite structure as Alpaca adapter
- Both Alpaca and Schwab can be registered in BrokerAdapterRegistry simultaneously
- Deployments can specify preferred broker via configuration
- OAuth token refresh happens transparently (no user intervention)

---

### M5 — Live Integration Tests and Performance Validation

**Objective:** Create a comprehensive integration test suite that validates live
trading workflows against broker paper-trading APIs, and validate SLOs under
realistic load.

**Deliverables:**

- `tests/integration/test_live_execution_integration.py`:
  - Full order lifecycle: submit → fill → position update → P&L calculation
  - Order cancellation workflow
  - Concurrent order submission (10 simultaneous)
  - Kill switch activation during live orders
  - Broker disconnect + circuit breaker recovery
  - Risk gate enforcement under live conditions

- `tests/integration/test_multi_broker_integration.py`:
  - Same order on Alpaca and Schwab (parallel execution)
  - Broker failover: primary down → secondary accepts
  - Cross-broker position reconciliation

- `tests/load/locustfile_live.py` — Live-mode load tests:
  - Order submission throughput (target: 50 orders/sec live mode)
  - Kill switch MTTH under load with live orders
  - P&L calculation latency under concurrent queries

- SLO validation report: `docs/slo-validation-report.md`
  - Measured P50/P95/P99 for all SLOs
  - Pass/fail against defined thresholds
  - Recommendations for tuning

**Acceptance criteria:**
- All integration tests pass against Alpaca paper trading API
- Order P99 latency < 2s for live mode (SLO-1)
- Kill switch MTTH P99 < 5s with open live orders (SLO-2)
- No deadlocks under concurrent live execution
- Broker failover completes within circuit breaker recovery timeout

---

### M6 — MinIO Artifact Storage Wiring and Deployment Pipeline

**Objective:** Wire the MinIO artifact storage adapter into the lifespan DI
container (resolving TODO ISS-012) and create the deployment promotion pipeline
for staging → production.

**Deliverables:**

- `services/api/routes/artifacts.py` — Modified:
  - Remove TODO ISS-012
  - Wire MinIOArtifactStorage via app lifespan dependency injection
  - Configurable: `ARTIFACT_STORAGE_BACKEND=minio|local` env var
  - Local filesystem fallback for development

- `services/api/infrastructure/deployment_pipeline.py` — Deployment pipeline:
  - Staging validation: run acceptance tests against staging
  - Promotion gate: all checks green, manual approval required
  - Production deployment: K8s rolling update trigger
  - Rollback: automatic on health check failure

- `infra/k8s/api-deployment-staging.yaml` — Staging K8s manifest
- `infra/k8s/api-deployment-production.yaml` — Production K8s manifest

- `docs/runbooks/staging-to-production.md` — Updated:
  - Full promotion checklist with gate criteria
  - Canary deployment procedure
  - Rollback SOP

- Tests:
  - Unit tests for artifact storage wiring
  - Unit tests for deployment pipeline stages

**Acceptance criteria:**
- Artifacts upload/download works with MinIO in docker-compose
- TODO ISS-012 resolved — no remaining TODOs in production code
- Staging → production promotion documented and tested
- Rollback procedure verified

---

## Track: Trader UX

### M7 — Real-Time Position Dashboard (WebSocket)

**Objective:** Build a real-time dashboard showing live positions, P&L, and order
status updates via WebSocket streaming.

**Deliverables:**

- `services/api/routes/ws_positions.py` — WebSocket endpoint:
  - `WS /ws/positions/{deployment_id}` — stream position updates
  - Authenticated (token in query param or first message)
  - Broadcasts: position changes, fill events, P&L updates
  - Heartbeat every 30s, auto-reconnect-friendly
  - Connection manager: track connected clients, fan-out updates

- `frontend/src/pages/Dashboard/LiveDashboard.tsx` — Real-time dashboard:
  - Position table with live P&L (unrealized, realized, total)
  - Color-coded: green (profit), red (loss), yellow (pending orders)
  - Order status timeline (recent orders with lifecycle events)
  - Account summary: total equity, buying power, daily P&L
  - Auto-reconnecting WebSocket with connection status indicator

- `frontend/src/hooks/useWebSocket.ts` — Reusable WebSocket hook:
  - Auto-reconnect with exponential backoff
  - Connection state management
  - Message parsing and dispatch

- Tests:
  - Unit tests for WebSocket endpoint (connection, auth, broadcast)
  - Frontend component tests (render, WebSocket message handling)
  - Integration test: order submission → WebSocket update received

**Acceptance criteria:**
- Position updates appear within 1s of fill event
- Dashboard handles 100+ simultaneous WebSocket connections
- Auto-reconnects within 5s of disconnection
- P&L calculations match backend reconciliation values

---

### M8 — Execution Reports and Order History

**Objective:** Build execution reporting pages that show trade history, fill
analysis, and execution quality metrics.

**Deliverables:**

- `frontend/src/pages/Execution/OrderHistory.tsx` — Order history table:
  - Filterable by: date range, symbol, side, status, execution mode
  - Sortable columns: time, symbol, quantity, price, status
  - Order detail expansion: fills, timeline, drift analysis
  - Export to CSV

- `frontend/src/pages/Execution/ExecutionReport.tsx` — Execution quality report:
  - Fill rate by strategy/symbol
  - Slippage analysis (expected vs actual fill price)
  - Execution latency distribution (P50/P95/P99)
  - Broker comparison (if multi-broker)
  - Date range selection with presets (today, this week, this month)

- API endpoints:
  - `GET /execution-analysis/report` — aggregate execution metrics
  - `GET /execution-analysis/export` — CSV export

- Tests:
  - Frontend component tests
  - API tests for report aggregation and export

**Acceptance criteria:**
- Order history loads within 2s for 10,000+ orders
- CSV export works for full date ranges
- Slippage and latency charts render correctly
- Filters apply without page reload

---

### M9 — Strategy P&L Tracking and Performance Attribution

**Objective:** Implement per-strategy P&L tracking with performance attribution
(which strategies/symbols contribute most to returns).

**Deliverables:**

- `services/api/services/pnl_attribution_service.py` — P&L attribution:
  - Per-strategy realized/unrealized P&L
  - Per-symbol contribution to strategy P&L
  - Daily/weekly/monthly P&L time series
  - Sharpe ratio, max drawdown, win rate per strategy
  - Commission and fee tracking

- `services/api/services/interfaces/pnl_attribution_service_interface.py` — Interface

- `services/api/repositories/pnl_snapshot_repository.py` — Daily P&L snapshots:
  - SqlPnlSnapshotRepository: persist daily P&L snapshots
  - Schema: deployment_id, snapshot_date, realized_pnl, unrealized_pnl,
    commission, fees, positions_count

- `services/api/routes/pnl.py` — P&L endpoints:
  - `GET /pnl/{deployment_id}/summary` — current P&L summary
  - `GET /pnl/{deployment_id}/timeseries` — P&L over time
  - `GET /pnl/{deployment_id}/attribution` — per-symbol breakdown
  - `GET /pnl/comparison` — compare strategies side by side

- `frontend/src/pages/PnL/StrategyPnL.tsx` — P&L dashboard:
  - Equity curve chart (Recharts)
  - Attribution table (symbol, contribution %, realized, unrealized)
  - Performance metrics cards (Sharpe, drawdown, win rate)
  - Strategy comparison view

- Alembic migration: `pnl_snapshots` table

- Tests:
  - Unit tests for attribution calculations
  - Repository tests for snapshot persistence
  - Frontend component tests

**Acceptance criteria:**
- P&L calculations match manual verification for test data
- Daily snapshots persisted automatically
- Attribution sums match total P&L (no unaccounted residual)
- Strategy comparison shows side-by-side metrics

---

### M10 — Enhanced Strategy Studio (Resolve TODO M26)

**Objective:** Complete the Strategy Studio by wiring the strategy creation API
call (TODO M26 in StrategyStudio.tsx) and adding live validation.

**Deliverables:**

- `frontend/src/pages/StrategyStudio.tsx` — Modified:
  - Remove TODO(M26)
  - Wire `POST /strategies` API call for strategy creation
  - Live DSL syntax validation as user types
  - Preview panel: simulated backtest results
  - Save/load strategy drafts

- `frontend/src/components/DslEditor.tsx` — DSL editor component:
  - Syntax highlighting for FXLab strategy DSL
  - Auto-completion for indicator names, symbols
  - Error markers on invalid lines
  - Line numbers and bracket matching

- Tests:
  - Frontend component tests for DslEditor
  - Integration test: create strategy → compile → validate → save

**Acceptance criteria:**
- Strategy creation from studio saves to database via API
- DSL validation errors shown inline in editor
- TODO(M26) removed from codebase
- Zero remaining TODOs in production code paths

---

## Track: Compliance & Automation

### M11 — Trade Execution Reports for Regulatory Compliance

**Objective:** Generate standardized trade execution reports suitable for
regulatory review (SEC Rule 606, MiFID II best execution).

**Deliverables:**

- `services/api/services/compliance_report_service.py` — Report generation:
  - Order execution report: all orders with fills, timestamps, venues
  - Best execution analysis: fill price vs NBBO at time of execution
  - Venue routing report: where orders were routed and why
  - Monthly summary: volumes, error rates, rejection reasons

- `services/api/routes/compliance.py` — Compliance endpoints:
  - `GET /compliance/execution-report` — generate execution report (date range)
  - `GET /compliance/best-execution` — best execution analysis
  - `GET /compliance/monthly-summary` — monthly aggregate
  - All require `compliance:read` scope

- Report output formats:
  - JSON (API response)
  - CSV export
  - PDF (for regulatory submission, via reportlab)

- Tests:
  - Unit tests for report generation logic
  - Data validation tests (report totals match order database)

**Acceptance criteria:**
- Execution report covers all orders in the specified date range
- Report totals reconcile with database order counts
- CSV and PDF exports render correctly
- Only compliance-scoped users can access endpoints

---

### M12 — Audit Trail Export and Retention Policy

**Objective:** Implement audit trail export for compliance archival and enforce
data retention policies for regulatory requirements.

**Deliverables:**

- `services/api/services/audit_export_service.py` — Audit export:
  - Export audit events by date range, user, action type
  - Formats: JSON, CSV, NDJSON (for log aggregators)
  - Signed exports (SHA-256 hash of content for tamper detection)
  - Compressed exports (gzip) for large date ranges

- `services/api/routes/audit.py` — Extended:
  - `POST /audit/export` — trigger audit export job
  - `GET /audit/export/{job_id}` — download export file
  - `GET /audit/retention-policy` — current retention settings

- `services/api/infrastructure/retention_job.py` — Data retention:
  - Configurable retention periods per entity type:
    - Audit events: 7 years (regulatory minimum)
    - Order history: 7 years
    - Execution events: 5 years
    - P&L snapshots: indefinite
  - Soft delete: mark expired records, move to archive table
  - Hard delete: purge archive after grace period (30 days)
  - Background job: runs daily at 02:00 UTC

- Alembic migration: archive tables for audit_events, orders

- Tests:
  - Unit tests for export formatting and signing
  - Unit tests for retention policy application
  - Integration test: create events → age past retention → verify archived

**Acceptance criteria:**
- Audit exports are complete and tamper-evident (SHA-256 hash)
- Retention policy correctly archives expired records
- No data loss: archived records recoverable during grace period
- Export handles 1M+ events without timeout

---

### M13 — Incident Automation: PagerDuty/Slack Integration

**Objective:** Automate incident notification and escalation via PagerDuty and Slack
when critical events occur (kill switch activation, circuit breaker trip, SLO breach).

**Deliverables:**

- `services/api/infrastructure/notification_service.py` — Notification dispatch:
  - NotificationProviderInterface: abstract interface
  - SlackNotificationProvider: webhook-based Slack notifications
  - PagerDutyNotificationProvider: Events API v2 integration
  - Configurable: which events trigger which channels

- `services/api/infrastructure/notification_config.py` — Alert rules:
  - Kill switch activation → PagerDuty P1 + Slack #incidents
  - Circuit breaker OPEN → PagerDuty P2 + Slack #alerts
  - SLO breach → Slack #alerts
  - Secret expiring (< 14 days) → Slack #ops
  - Reconciliation discrepancy → Slack #alerts

- `services/api/infrastructure/incident_manager.py` — Incident lifecycle:
  - Create incident with metadata (trigger, affected services, timestamp)
  - Track acknowledgment and resolution
  - Auto-escalate if not acknowledged within SLA (15 min P1, 1 hour P2)

- Integration with existing services:
  - KillSwitchService: emit notification on activation
  - CircuitBreaker: emit notification on OPEN transition
  - SecretRotationJob: emit notification for expiring secrets

- Tests:
  - Unit tests for notification dispatch (mocked HTTP)
  - Unit tests for alert rule matching
  - Unit tests for escalation timing

**Acceptance criteria:**
- Kill switch activation triggers PagerDuty alert within 10s
- Slack notification includes structured incident details
- Auto-escalation fires if not acknowledged within SLA
- Notification failures logged but do not block the triggering operation

---

## Cross-Cutting Requirements

The following requirements apply to EVERY milestone in this phase:

1. **§0 Compliance:** Every milestone must pass the §0 verification checklist before
   being marked DONE. No in-memory dicts for durable state. No unprotected shared
   mutable state. No partial safety systems.

2. **TDD:** All implementation follows RED → GREEN → REFACTOR. No code without tests.

3. **Coverage:** Overall ≥ 83%. New code ≥ 90%. Core safety services ≥ 95%.

4. **Quality Gate:** format → lint → type-check → unit tests → integration tests
   must all pass before marking any milestone DONE.

5. **Logging:** All new operations emit structured log events per §8 standards.

6. **Error Handling:** All new external calls follow §9 retry/no-retry policy.

7. **Documentation:** All new public APIs have complete docstrings per §7 standards.

8. **Backward Compatibility:** No existing API contracts broken. New endpoints only.

9. **Shared Lessons:** Apply all lessons from SHARED_LESSONS.md, especially:
   - LL-S007: Use JSONResponse + model_dump() for FastAPI routes (cross-arch safety)
   - LL-S009: Explicit int() casts on numeric query parameters
   - LL-S012: Update BOTH unit AND integration tests on endpoint changes

---

## Milestone Dependency Graph

```
         M0 (Keycloak Validation)
         ├── M1 (Frontend OIDC)
         │   └── M2 (Admin Panel)
         │
M3 (Live Execution) ──── M4 (Schwab Adapter)
         │                    │
         └──── M5 (Live Integration Tests) ────┘
               │
         M6 (MinIO + Deploy Pipeline)
         │
M7 (WebSocket Dashboard)
         │
M8 (Execution Reports)
         │
M9 (P&L Attribution) ── M10 (Strategy Studio)
         │
M11 (Compliance Reports) ── M12 (Audit Export)
         │
M13 (Incident Automation)
```

### Suggested execution order (parallelism opportunities):

**Wave 1 (can run in parallel):**
- M0 (Keycloak) — backend auth, no frontend dependency
- M3 (Live Execution) — backend service, depends on Phase 5

**Wave 2 (depends on Wave 1):**
- M1 (Frontend OIDC) — depends on M0
- M4 (Schwab Adapter) — depends on M3 architecture
- M7 (WebSocket Dashboard) — can start once M3 exists

**Wave 3 (depends on Wave 2):**
- M2 (Admin Panel) — depends on M1
- M5 (Live Integration Tests) — depends on M3, M4
- M8 (Execution Reports) — depends on M3 order data
- M11 (Compliance Reports) — depends on M3 order data

**Wave 4 (depends on Wave 3):**
- M6 (MinIO + Deploy) — can run anytime, low dependency
- M9 (P&L Attribution) — depends on M3 for live data
- M10 (Strategy Studio) — can run anytime, low dependency
- M12 (Audit Export) — depends on M11

**Wave 5 (final):**
- M13 (Incident Automation) — integrates with all services
