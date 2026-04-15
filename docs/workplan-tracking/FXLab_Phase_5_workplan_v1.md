# FXLab Phase 5 — Production Hardening, Real Broker Integration, and Operational Maturity

**Version:** 1.0
**Created:** 2026-04-11
**Source:** `FXLab_Production_Readiness_Assessment.docx` (21 findings, F-01 through F-21)
**Phase 4 dependency:** All 11 milestones (M0–M10) DONE per progress file.
**CLAUDE.md §0 compliance:** Every milestone in this phase must satisfy the Absolute Law
directive. No in-memory stand-ins for durable storage. No deferred persistence. No partial
safety systems. No unprotected shared mutable state.

---

```
MILESTONE INDEX
───────────────────────────────────────────────
Total milestones: 18
Tracks: Execution Persistence, Broker Integration, Safety Hardening,
        Operational Maturity, Observability & Performance

Execution Persistence:        M0, M1, M2, M3
Broker Integration:           M4, M5, M6
Safety Hardening:             M7, M8, M9, M10
Operational Maturity:         M11, M12, M13, M14
Observability & Performance:  M15, M16, M17
───────────────────────────────────────────────
```

---

## Track: Execution Persistence

> Addresses findings: F-02 (execution state not persisted), F-03 (no thread
> synchronization), F-13 (login brute-force resets on restart).
>
> This track is prerequisite for ALL other tracks. No other milestone may begin
> until M0–M3 are DONE. The entire execution layer currently stores state in
> Python dicts. This track replaces every in-memory dict with durable SQL or
> Redis persistence and adds synchronization to all shared mutable state.

---

### M0 — Order, Fill, and Position SQL Repositories

**Objective:** Implement SQL repository classes for Order, OrderFill, and Position.
These tables already exist (migration 0009) and ORM models exist in models.py.
This milestone writes the repository implementations, wires them into services,
and replaces all in-memory order/fill/position storage.

**Deliverables:**

- `libs/contracts/interfaces/order_repository_interface.py` — Repository port:
  - `save(order: Order) -> Order`
  - `get_by_id(order_id: str) -> Order` (raises NotFoundError)
  - `get_by_client_order_id(client_order_id: str) -> Order | None`
  - `get_by_broker_order_id(broker_order_id: str) -> Order | None`
  - `list_by_deployment(deployment_id: str, status: OrderStatus | None = None) -> list[Order]`
  - `list_open_by_deployment(deployment_id: str) -> list[Order]`
  - `update_status(order_id: str, status: OrderStatus, **kwargs) -> Order`

- `libs/contracts/interfaces/order_fill_repository_interface.py` — Repository port:
  - `save(fill: OrderFill) -> OrderFill`
  - `list_by_order(order_id: str) -> list[OrderFill]`
  - `list_by_deployment(deployment_id: str) -> list[OrderFill]`

- `libs/contracts/interfaces/position_repository_interface.py` — Repository port:
  - `save(position: Position) -> Position`
  - `get_by_deployment_and_symbol(deployment_id: str, symbol: str) -> Position | None`
  - `list_by_deployment(deployment_id: str) -> list[Position]`
  - `update_position(position_id: str, **fields) -> Position`
  - `get_for_update(deployment_id: str, symbol: str) -> Position | None`
    (SELECT FOR UPDATE NOWAIT — pessimistic lock, addresses F-09)

- `services/api/repositories/sql_order_repository.py` — SQL implementation
- `services/api/repositories/sql_order_fill_repository.py` — SQL implementation
- `services/api/repositories/sql_position_repository.py` — SQL implementation
  - `get_for_update` uses `with_for_update(nowait=True)` on SQLAlchemy query

- `libs/contracts/mocks/mock_order_repository.py` — In-memory mock with introspection
- `libs/contracts/mocks/mock_order_fill_repository.py` — In-memory mock
- `libs/contracts/mocks/mock_position_repository.py` — In-memory mock

- `tests/unit/test_sql_order_repository.py` — CRUD, not-found, status filter, idempotency lookup
- `tests/unit/test_sql_order_fill_repository.py` — save, list by order, list by deployment
- `tests/unit/test_sql_position_repository.py` — save, get, update, for-update lock
- `tests/integration/test_order_position_persistence.py` — roundtrip through real DB session

**Acceptance criteria:**
- Order saved via repository survives session close and reopen
- get_by_client_order_id returns existing order (idempotency support)
- get_for_update acquires row-level lock (verify with concurrent test)
- list_open_by_deployment returns only non-terminal status orders
- All mocks implement same interface and raise same exceptions as SQL versions
- Zero in-memory order/fill/position dicts remain in any production service

---

### M1 — Execution Event, Kill Switch Event, and Reconciliation SQL Repositories

**Objective:** Implement SQL repositories for the remaining three execution tables:
execution_events, kill_switch_events, and reconciliation_reports. Also implement
the SqlRiskEventRepository (currently mock-only, no table exists — requires a new
migration).

**Deliverables:**

- `libs/contracts/interfaces/execution_event_repository_interface.py` — Repository port:
  - `save(event: ExecutionEvent) -> ExecutionEvent`
  - `list_by_order(order_id: str) -> list[ExecutionEvent]`
  - `search_by_correlation_id(correlation_id: str) -> list[ExecutionEvent]`
  - `list_by_deployment(deployment_id: str, limit: int = 100) -> list[ExecutionEvent]`

- `libs/contracts/interfaces/kill_switch_event_repository_interface.py` — Repository port:
  - `save(event: KillSwitchEvent) -> KillSwitchEvent`
  - `get_active(scope: str, target_id: str) -> KillSwitchEvent | None`
  - `list_active() -> list[KillSwitchEvent]`
  - `deactivate(event_id: str, deactivated_at: datetime) -> KillSwitchEvent`
  - `list_by_scope(scope: str, limit: int = 100) -> list[KillSwitchEvent]`

- `migrations/versions/20260411_0011_add_risk_events_table.py` — New migration:
  - `risk_events` table: id, deployment_id FK, order_id (nullable), check_name,
    passed (boolean), severity, message, details JSON, correlation_id, created_at
  - Indexes on deployment_id, severity, created_at

- `services/api/repositories/sql_execution_event_repository.py` — SQL implementation
- `services/api/repositories/sql_kill_switch_event_repository.py` — SQL implementation
- `services/api/repositories/sql_reconciliation_repository.py` — SQL implementation
- `services/api/repositories/sql_risk_event_repository.py` — SQL implementation

- Corresponding mock repositories for each (if not already existing)
- Unit tests for each SQL repository (CRUD, not-found, filter, ordering)
- Integration test: persist and retrieve across session boundaries

**Acceptance criteria:**
- Kill switch events survive restart — `list_active()` returns events persisted before restart
- Execution events are append-only, ordered by timestamp
- Reconciliation reports persist discrepancies as JSON, queryable by deployment
- Risk events table created by migration, SqlRiskEventRepository replaces mock in production
- All six execution tables (orders, order_fills, positions, execution_events,
  kill_switch_events, reconciliation_reports) plus risk_events have SQL repositories

---

### M2 — Service Layer Persistence Refactor

**Objective:** Refactor all seven execution services to use SQL repositories instead
of in-memory dicts. Add threading.Lock to all remaining shared mutable state. After
this milestone, `grep -r "self\._" services/api/services/` must show zero unprotected
in-memory dicts used for durable state.

**Deliverables:**

- `services/api/services/kill_switch_service.py` — Refactored:
  - Replace `self._active: dict` with KillSwitchEventRepository queries
  - Replace `self._events: list` with KillSwitchEventRepository.save()
  - `is_halted()` queries DB, not in-memory dict
  - `get_status()` queries DB, not in-memory dict
  - Add `threading.Lock` on adapter_registry mutations

- `services/api/services/paper_execution_service.py` — Refactored:
  - Persist orders via OrderRepository on submit_paper_order
  - Persist fills via OrderFillRepository on process_pending_orders
  - Persist position updates via PositionRepository on fill
  - Add `threading.Lock` on `self._adapters` dict
  - Recovery: on register_deployment, reload open orders from DB

- `services/api/services/shadow_execution_service.py` — Refactored:
  - Persist shadow orders via OrderRepository (execution_mode='shadow')
  - Persist decision timeline via ExecutionEventRepository
  - Add `threading.Lock` on `self._adapters` dict

- `services/api/services/execution_analysis_service.py` — Refactored:
  - Replace `self._expected_prices` with DB-backed storage (execution_events or new table)
  - Replace `self._events` and `self._all_events` with ExecutionEventRepository queries
  - `compute_drift()` queries DB for events, not in-memory list
  - `search_by_correlation_id()` delegates to ExecutionEventRepository

- `services/api/services/drill_service.py` — Refactored:
  - Persist drill results to new `drill_results` column/table (or use execution_events
    with event_type='drill_result' and details JSON)
  - `check_live_eligibility()` queries persisted results, not in-memory dict
  - Add `threading.Lock` on adapter_registry access

- `services/api/services/risk_gate_service.py` — Refactored:
  - Replace `self._limits: dict` with Deployment.risk_limits JSON column
    (already exists in deployment model)
  - `set_risk_limits()` writes to deployment record via DeploymentRepository
  - `get_risk_limits()` reads from deployment record
  - Risk events already persisted via RiskEventRepository (verify wired to SQL impl)

- `services/api/services/reconciliation_service.py` — Refactored:
  - Replace injected `internal_order_states` with OrderRepository queries
  - Replace injected `internal_positions` with PositionRepository queries
  - Run reconciliation against real DB state, not passed-in dicts
  - Persist reports via SqlReconciliationRepository (verify wired)

- Updated unit tests for all seven services with mock repositories injected
- Updated route DI wiring in `services/api/main.py` or route modules

**Acceptance criteria:**
- `grep -rn "self\._.*: dict" services/api/services/` returns ZERO hits for
  unprotected durable-state dicts (adapter registries with Lock are acceptable)
- All services recover state after simulated restart (test: create state, new
  service instance, verify state is present)
- All existing unit and acceptance tests still pass
- Thread safety: concurrent submit_paper_order calls do not corrupt state
  (test with threading.Thread)
- §0 compliance checklist passes for every modified service

---

### M3 — Redis-Backed Login Tracking and Session State

**Objective:** Move LoginAttemptTracker from in-memory dict to Redis. Move any
remaining ephemeral-but-important state (rate limit counters in single-worker mode)
to Redis for multi-worker consistency.

**Deliverables:**

- `services/api/services/login_attempt_tracker.py` — Refactored:
  - Replace `self._store: dict` with Redis sorted sets (ZADD + ZRANGEBYSCORE)
  - TTL-based expiry replaces manual cleanup
  - Graceful fallback: if Redis unavailable, deny login (fail-closed, like rate limiter)

- `services/api/middleware/rate_limit.py` — Verify:
  - RedisRateLimitBackend is default when REDIS_URL configured
  - InMemoryRateLimitBackend only used when REDIS_URL absent (single-worker dev)

- Unit tests: Redis-backed tracker rejects after threshold, entries expire, survives restart
- Integration test: multiple simulated workers share lockout state via Redis

**Acceptance criteria:**
- Login lockout survives service restart
- Lockout state shared across multiple uvicorn workers
- Redis unavailability results in login denial (fail-closed), not bypass
- Rate limit backend auto-selects Redis when REDIS_URL is configured

---

## Track: Broker Integration

> Addresses findings: F-01 (no real broker adapter), F-06 (no request timeouts),
> F-08 (no real-time streaming).
>
> Prerequisites: M0–M3 (Execution Persistence) must be DONE.
> This track implements real broker communication starting with Alpaca, using
> a broker-agnostic adapter registry that supports future IBKR/Schwab additions.

---

### M4 — Broker Adapter Registry and Timeout Infrastructure

**Objective:** Build the multi-broker adapter registry pattern and request timeout
infrastructure. This is the plumbing that M5 (Alpaca) and future broker adapters
plug into.

**Deliverables:**

- `services/api/infrastructure/broker_registry.py` — BrokerAdapterRegistry:
  - Register/deregister adapters by deployment_id
  - Get adapter by deployment_id (raises NotFoundError)
  - List all registered deployments
  - Thread-safe (Lock-protected)
  - Persist registry state: deployment_id → broker_type mapping in DB

- `services/api/infrastructure/timeout_config.py` — Timeout configuration:
  - `BrokerTimeoutConfig` dataclass:
    - `connect_timeout_s: float = 5.0`
    - `read_timeout_s: float = 10.0`
    - `order_timeout_s: float = 30.0`
    - `cancel_timeout_s: float = 15.0`
    - `stream_heartbeat_s: float = 30.0`
  - Configurable via environment variables (BROKER_CONNECT_TIMEOUT, etc.)

- `libs/contracts/interfaces/broker_adapter.py` — Extended:
  - Add `connect() -> None` and `disconnect() -> None` lifecycle methods
  - Add `get_timeout_config() -> BrokerTimeoutConfig`
  - Add docstring requiring all implementations to enforce timeouts

- Update all existing adapters (Mock, Paper, Shadow) to implement new methods
- Unit tests for registry (register, get, not-found, thread-safety)
- Unit tests for timeout config (defaults, env override)

**Acceptance criteria:**
- Registry is thread-safe under concurrent access
- Timeout config is loaded from environment with sensible defaults
- All existing adapter implementations updated for new interface methods
- Registry state persists across restart (deployment-broker mapping in DB)

---

### M5 — Alpaca Broker Adapter (REST)

**Objective:** Implement AlpacaBrokerAdapter using Alpaca's Trading API v2 REST
endpoints. This is the first real broker adapter — it submits real orders, receives
real fills, and queries real positions.

**Deliverables:**

- `services/api/adapters/alpaca_broker_adapter.py` — AlpacaBrokerAdapter:
  - Implements BrokerAdapterInterface
  - Uses `httpx.Client` with configured timeouts (from BrokerTimeoutConfig)
  - OAuth2 authentication via API key + secret (from SecretProvider)
  - Endpoint: `https://paper-api.alpaca.markets/v2` (paper) or
    `https://api.alpaca.markets/v2` (live), configurable per deployment
  - All 9 interface methods implemented with real HTTP calls:
    - `submit_order` → POST /v2/orders (idempotent via client_order_id)
    - `cancel_order` → DELETE /v2/orders/{id}
    - `get_order` → GET /v2/orders/{id}
    - `list_open_orders` → GET /v2/orders?status=open
    - `get_fills` → GET /v2/orders/{id} (extract filled_qty, filled_avg_price)
    - `get_positions` → GET /v2/positions
    - `get_account` → GET /v2/account
    - `get_diagnostics` → GET /v2/clock + internal latency/error tracking
    - `is_market_open` → GET /v2/clock
  - Retry with exponential backoff on 429, 5xx (reuse task_retry.py pattern)
  - No retry on 400, 401, 403, 404, 422
  - Maps Alpaca order states to normalized OrderStatus enum
  - Maps Alpaca error codes to domain exceptions (NotFoundError, AuthError,
    ExternalServiceError, TransientError)

- `services/api/adapters/__init__.py`

- `libs/contracts/alpaca_config.py` — Pydantic config model:
  - `api_key: str`
  - `api_secret: str`
  - `base_url: str` (paper vs live)
  - `api_version: str = "v2"`

- `.env.example` — Extended with:
  - `ALPACA_API_KEY=<your-api-key>`
  - `ALPACA_API_SECRET=<your-api-secret>`
  - `ALPACA_BASE_URL=https://paper-api.alpaca.markets`

- Unit tests with httpx mock transport (no real API calls in unit tests):
  - Happy path for all 9 methods
  - Timeout handling (connect, read)
  - Retry on 429 and 5xx
  - No retry on 4xx
  - Auth failure → AuthError
  - Order mapping: Alpaca states → normalized OrderStatus
  - Idempotency: duplicate client_order_id returns existing order

- Integration test (marked `@pytest.mark.alpaca`, skipped unless ALPACA_API_KEY set):
  - Connect to Alpaca paper API
  - Submit market order, verify fill
  - Cancel limit order, verify cancellation
  - Query positions and account

**Acceptance criteria:**
- All 9 BrokerAdapterInterface methods make real HTTP calls to Alpaca
- Every HTTP call has a configured timeout (no indefinite hangs)
- 429/5xx responses trigger retry with exponential backoff and jitter
- 4xx responses raise appropriate domain exceptions without retry
- Alpaca order states correctly mapped to normalized OrderStatus
- API credentials loaded from SecretProvider, never hardcoded
- Integration test passes against Alpaca paper trading API
- Adapter can be swapped in for MockBrokerAdapter via registry without service changes

---

### M6 — Real-Time Market Data and Order Update Streaming

**Objective:** Implement WebSocket clients for Alpaca's real-time market data stream
and order update stream. Feed market prices into paper/shadow adapters and order
updates into the execution event pipeline.

**Deliverables:**

- `services/api/adapters/alpaca_market_stream.py` — Market data WebSocket client:
  - Connects to `wss://stream.data.alpaca.markets/v2/{feed}` (iex or sip)
  - Subscribes to trades for configured symbols
  - Parses trade messages → normalized price updates
  - Reconnects on disconnect with exponential backoff
  - Heartbeat monitoring (alert if no message in stream_heartbeat_s)
  - Pushes price updates to registered callbacks (paper/shadow adapters)

- `services/api/adapters/alpaca_order_stream.py` — Order update WebSocket client:
  - Connects to `wss://paper-api.alpaca.markets/stream` or live equivalent
  - Authenticates via API key
  - Receives order update events (new, partial_fill, fill, canceled, etc.)
  - Maps to normalized OrderEvent, persists via ExecutionEventRepository
  - Updates order status in OrderRepository
  - Reconnects on disconnect with exponential backoff

- `services/api/infrastructure/stream_manager.py` — Lifecycle manager:
  - Start/stop streams per deployment
  - Register price update callbacks
  - Monitor stream health via diagnostics
  - Integrate with graceful shutdown (M11)

- Unit tests: message parsing, reconnect logic, callback dispatch
- Integration test (marked `@pytest.mark.alpaca`): connect to paper stream,
  receive at least one trade quote, verify parsed format

**Acceptance criteria:**
- Market data stream provides real-time prices to paper/shadow adapters
- Order updates automatically update order status in database
- WebSocket reconnects automatically on disconnect
- Stream health visible via adapter diagnostics
- Graceful disconnect on service shutdown

---

## Track: Safety Hardening

> Addresses findings: F-04 (kill switch unreliable), F-05 (no circuit breaker),
> F-07 (emergency posture unverified), F-09 (no position locking — addressed in M0
> via get_for_update), F-10 (risk gate advisory-only).
>
> Prerequisites: M0–M3 (Execution Persistence) must be DONE.
> Broker Integration (M4–M6) should be DONE or in progress.

---

### M7 — Circuit Breaker for External Service Calls

**Objective:** Implement a circuit breaker pattern that wraps all broker adapter calls.
When a broker becomes unresponsive, the circuit trips and fast-fails subsequent requests
instead of blocking the entire service.

**Deliverables:**

- `services/api/infrastructure/circuit_breaker.py` — CircuitBreaker:
  - Three states: CLOSED (normal), OPEN (fast-fail), HALF_OPEN (probe)
  - Configurable thresholds:
    - `failure_threshold: int = 5` — consecutive failures to trip
    - `recovery_timeout_s: float = 30.0` — time in OPEN before probing
    - `half_open_max_calls: int = 1` — probe calls allowed in HALF_OPEN
  - State transitions persisted to Redis (survives restart)
  - Raises `CircuitOpenError` when tripped (subclass of ExternalServiceError)
  - Metrics: trip count, recovery count, current state per adapter
  - Thread-safe

- `services/api/infrastructure/resilient_adapter.py` — ResilientBrokerAdapter:
  - Wraps any BrokerAdapterInterface with circuit breaker + retry + timeout
  - Composition: adapter → timeout → retry → circuit breaker → caller
  - Each method call passes through the full resilience stack
  - Configurable per-method timeouts (order operations longer than queries)

- `libs/contracts/exceptions.py` — Extended:
  - `CircuitOpenError(ExternalServiceError)` — broker circuit is open

- Unit tests: state transitions, trip threshold, recovery, half-open probe
- Unit tests: resilient adapter wraps real adapter with full stack
- Integration test: simulate broker failure, verify circuit trips, verify recovery

**Acceptance criteria:**
- Circuit trips after N consecutive failures (configurable)
- Tripped circuit fast-fails with CircuitOpenError (no blocking)
- Circuit recovers after timeout by allowing probe calls
- Circuit state survives service restart (Redis-backed)
- All broker adapter calls go through resilient wrapper in production
- Metrics expose circuit state for monitoring

---

### M8 — Kill Switch Retry, Verification, and Escalation

**Objective:** Harden the kill switch so it retries failed cancellations, verifies
orders are actually cancelled, and escalates to emergency posture if cancellation
fails after max retries.

**Deliverables:**

- `services/api/services/kill_switch_service.py` — Enhanced:
  - `_cancel_open_orders()` refactored:
    - Retry each cancel_order call with exponential backoff (3 retries)
    - After all retries, verify each order status via get_order()
    - If order still open after retries + verification: add to failed list
    - If any cancellations failed: escalate to emergency posture automatically
    - Return detailed result: cancelled count, failed count, failed order IDs
  - `_flatten_positions()` refactored:
    - After submitting close orders, poll for fills (10s timeout, 1s interval)
    - If position not closed after timeout: log CRITICAL, add to failed list
    - Return detailed result: flattened count, failed count, failed symbols
  - `activate_kill_switch()` enhanced:
    - Persist activation to DB immediately (before attempting cancellations)
    - If cancellation partially fails: persist partial result, escalate
    - MTTH now includes retry time (total wall-clock to confirmed halt)
  - New method: `verify_halt(scope, target_id) -> HaltVerification`:
    - Re-checks all orders in scope are actually cancelled
    - Re-checks all positions in scope are actually flat
    - Returns verification result with any residual exposure

- Unit tests: retry on transient failure, escalation on persistent failure,
  verification after cancellation, partial failure handling
- Acceptance test: simulate broker that fails first 2 cancels then succeeds,
  verify all orders eventually cancelled

**Acceptance criteria:**
- Kill switch retries failed cancel_order calls (3 attempts with backoff)
- After retries, kill switch verifies each order is actually cancelled
- If verification fails, kill switch escalates to emergency posture
- Kill switch state persisted to DB before any cancellation attempts
- MTTH measurement includes total time from trigger to verified halt
- Partial failures are logged, persisted, and surfaced in response
- Zero silent discards of cancel failures

---

### M9 — Emergency Posture Verification Loop

**Objective:** Add post-execution verification to emergency posture operations.
After submitting close orders, the system must verify positions are actually closed
and escalate if they are not.

**Deliverables:**

- `services/api/services/kill_switch_service.py` — Enhanced `execute_emergency_posture()`:
  - After submitting close orders, enter verification loop:
    - Poll broker positions every 1s for up to 30s
    - If all positions flat: success
    - If positions remain after timeout: log CRITICAL with exact residual exposure
  - Verification result includes:
    - `positions_closed: int`
    - `positions_failed: list[PositionSnapshot]` (with current quantities)
    - `residual_exposure_usd: Decimal` (sum of abs(market_value) for failed)
  - If residual exposure exceeds threshold: trigger alert (structured log event
    at CRITICAL level with `operation=emergency_posture_residual_exposure`)

- `libs/contracts/execution.py` — New schema:
  - `EmergencyPostureVerification` — result of posture execution with verification

- Unit tests: all positions close → success, partial close → residual reported,
  timeout → CRITICAL logged
- Acceptance test: simulate position that fails to close, verify residual exposure
  is reported and logged at CRITICAL

**Acceptance criteria:**
- Emergency posture verifies positions actually closed after submitting orders
- Residual exposure calculated and reported if positions remain open
- CRITICAL log event emitted for any residual exposure
- Verification has configurable timeout (default 30s)
- Posture result includes full verification details, not just "success"

---

### M10 — Structural Risk Gate Enforcement

**Objective:** Make risk gate enforcement structural rather than advisory. Order
submission must be impossible without a passing risk gate check. A caller cannot
accidentally skip the risk gate.

**Deliverables:**

- `services/api/services/paper_execution_service.py` — Refactored:
  - `submit_paper_order()` calls risk gate internally (not optional)
  - If risk gate returns `passed=False`: raise `RiskGateRejectionError`
  - Order is NOT submitted to adapter if risk check fails
  - Risk check result persisted to risk_events before order submission

- `services/api/services/shadow_execution_service.py` — Same pattern

- `libs/contracts/exceptions.py` — Extended:
  - `RiskGateRejectionError(ValidationError)` — order blocked by risk gate
    - Includes: check_name, severity, message, deployment_id, order details

- `services/api/services/risk_gate_service.py` — Enhanced:
  - `check_order()` now required (not optional) in execution flow
  - Add `enforce_order(deployment_id, order, positions, account, correlation_id) -> None`:
    - Calls `check_order()` internally
    - If failed: persists event, raises RiskGateRejectionError
    - If passed: persists event, returns silently
  - Risk limits loaded from DB (already done in M2), not in-memory dict

- Unit tests: order rejected when risk gate fails, order proceeds when passes,
  risk event always persisted regardless of outcome
- Acceptance test: submit order exceeding position limit, verify rejection with
  proper error message and persisted risk event

**Acceptance criteria:**
- Order submission is impossible without passing risk gate check
- RiskGateRejectionError raised (not just returned) on failure
- Risk events persisted for both pass and fail outcomes
- No code path exists that submits an order without risk check
- Risk gate is enforced inside the service, not at the route level

---

## Track: Operational Maturity

> Addresses findings: F-11 (no graceful shutdown), F-12 (SQLite-only tests),
> F-14 (scattered config), F-15 (no K8s), F-16 (no readiness probe),
> F-17 (no DR procedures), F-18 (8 broken tests).
>
> Prerequisites: M0–M3 (Execution Persistence) should be DONE.

---

### M11 — Graceful Shutdown and Startup Recovery

**Objective:** Implement graceful shutdown that drains in-flight orders and startup
recovery that detects and reconciles orphaned state from unclean shutdown.

**Deliverables:**

- `services/api/main.py` — Enhanced lifespan:
  - **Shutdown sequence:**
    1. Set accepting_requests flag to False
    2. Wait for in-flight requests to complete (configurable timeout, default 30s)
    3. For each active deployment: run reconciliation against broker state
    4. Persist final adapter state
    5. Disconnect all broker adapters (call adapter.disconnect())
    6. Dispose database connections
    7. Log shutdown summary with in-flight count, reconciliation results
  - **Startup sequence:**
    1. Run migrations (existing)
    2. Load active deployments from DB
    3. For each active deployment: reconnect broker adapter, run reconciliation
    4. If reconciliation finds discrepancies: log WARNING, do not auto-resolve
    5. Resume accepting requests

- `services/api/middleware/drain.py` — DrainMiddleware:
  - When accepting_requests is False: return 503 for new requests
  - Track in-flight request count via atomic counter
  - Expose `wait_for_drain(timeout_s)` for shutdown sequence

- Unit tests: drain middleware rejects new requests, tracks in-flight count
- Integration test: simulate shutdown during order processing, verify state persisted

**Acceptance criteria:**
- Service shutdown waits for in-flight requests before closing connections
- New requests receive 503 during drain period
- Active deployments are reconciled against broker on shutdown
- On startup, active deployments are reconnected and reconciled
- Unclean shutdown followed by restart results in consistent state

---

### M12 — PostgreSQL Integration Tests and Pre-Existing Test Fixes

**Objective:** Fix the 8 pre-existing test failures and add a PostgreSQL integration
test target. All tests must pass against real PostgreSQL, not just SQLite.

**Deliverables:**

- Fix 8 broken tests:
  - `test_api_bootstrap` (2 failures) — likely migration/fixture issue
  - `test_e2e_plan_document` (2 failures) — likely DB session issue
  - `test_global_exception_handlers` (1 failure) — likely middleware ordering
  - `test_m13_governance_endpoints` (3 failures) — likely schema/fixture issue

- `docker-compose.test.yml` — Test-specific compose with PostgreSQL:
  - PostgreSQL 15 with test database
  - Redis for integration tests
  - No Keycloak (mocked in tests)

- `tests/conftest.py` — Enhanced:
  - Auto-detect TEST_DATABASE_URL for PostgreSQL vs fallback to SQLite
  - PostgreSQL fixtures with proper transaction isolation
  - Redis fixtures with cleanup

- `Makefile` or `scripts/test-integration.sh` — Run integration tests against PostgreSQL:
  - `make test-pg` — start compose, run tests, stop compose
  - CI-compatible (docker-compose up -d, pytest, docker-compose down)

- All existing tests pass against both SQLite (fast, local) and PostgreSQL (CI)

**Acceptance criteria:**
- All 8 pre-existing test failures fixed
- Full test suite passes: 0 failures
- PostgreSQL integration test target available via docker-compose
- CI can run `make test-pg` for PostgreSQL-backed test suite
- Coverage does not decrease

---

### M13 — Centralized Configuration and Readiness Probe

**Objective:** Consolidate all scattered os.environ.get() calls into a centralized,
validated Pydantic Settings model. Add /ready endpoint for Kubernetes readiness probes.

**Deliverables:**

- `services/api/config.py` — Centralized Pydantic Settings:
  - `AppSettings(BaseSettings)` with all environment variables
  - Grouped: DatabaseSettings, RedisSettings, AuthSettings, BrokerSettings,
    RateLimitSettings, ObservabilitySettings
  - Validated at startup: missing required vars → immediate failure with clear message
  - Loaded once, injected via dependency injection
  - Replaces ALL direct os.environ.get() calls in production code

- `services/api/routes/health.py` — Extended:
  - `GET /ready` — Readiness probe (returns 503 until all dependencies confirmed):
    - Database: connection test
    - Redis: ping test
    - Broker adapters: all registered adapters report connected
    - Migrations: Alembic current matches head
  - `GET /health` — Liveness probe (existing, lighter check)

- Refactor all routes and services to use injected AppSettings instead of os.environ
- Unit tests: settings validation, missing required var raises, defaults applied
- Unit tests: readiness probe returns 503 when dependency down, 200 when all up

**Acceptance criteria:**
- Zero os.environ.get() calls in services/api/ (excluding test fixtures)
- Missing required configuration fails at startup, not at first request
- /ready endpoint checks all dependencies including broker connectivity
- /health remains lightweight (DB ping only)
- Settings model is the single source of truth for all configuration

---

### M14 — Kubernetes Manifests and Database DR Procedures

**Objective:** Create production Kubernetes manifests and database disaster recovery
runbooks.

**Deliverables:**

- `infra/k8s/api-deployment.yaml` — API Deployment:
  - Replicas: 2 (minimum)
  - Resource limits: CPU 500m/1000m, Memory 256Mi/512Mi
  - Liveness: /health, Readiness: /ready
  - Rolling update: maxSurge 1, maxUnavailable 0
  - Environment from ConfigMap + Secret refs

- `infra/k8s/api-service.yaml` — ClusterIP Service

- `infra/k8s/api-hpa.yaml` — HorizontalPodAutoscaler:
  - Min: 2, Max: 8
  - Target CPU: 70%

- `infra/k8s/api-pdb.yaml` — PodDisruptionBudget:
  - minAvailable: 1

- `infra/k8s/api-configmap.yaml` — Non-secret configuration
- `infra/k8s/api-secret.yaml` — Secret template (values from sealed-secrets or external)

- `infra/k8s/api-networkpolicy.yaml` — NetworkPolicy:
  - Ingress: only from ingress controller
  - Egress: only to postgres, redis, broker APIs

- `docs/runbooks/database-backup-restore.md` — PostgreSQL backup procedures:
  - pg_basebackup schedule (daily)
  - WAL archiving configuration
  - Retention policy (30 days)
  - Restore procedure (step-by-step)

- `docs/runbooks/point-in-time-recovery.md` — PITR procedure:
  - When to use PITR vs full restore
  - recovery_target_time configuration
  - Verification steps after recovery

- `docs/runbooks/migration-rollback.md` — Alembic rollback:
  - Pre-migration backup requirement
  - `alembic downgrade -1` procedure
  - Verification steps
  - When to escalate vs rollback

**Acceptance criteria:**
- Kubernetes manifests pass `kubectl apply --dry-run=client`
- HPA, PDB, and NetworkPolicy configured for production safety
- All three runbooks are complete with step-by-step procedures
- Resource limits prevent unbounded memory/CPU growth
- Rolling update strategy ensures zero-downtime deploys

---

## Track: Observability & Performance

> Addresses findings: F-19 (no load testing), F-20 (no distributed tracing),
> F-21 (no secret rotation).
>
> Prerequisites: Execution Persistence and Safety Hardening tracks should be DONE.

---

### M15 — Execution Metrics and Business SLOs

**Objective:** Add Prometheus metrics for the execution layer. Define and measure
business-level SLOs for order latency, fill rates, and system availability.

**Deliverables:**

- `services/api/metrics.py` — Extended with execution metrics:
  - `orders_submitted_total` (labels: execution_mode, symbol, side)
  - `orders_filled_total` (labels: execution_mode, symbol)
  - `orders_rejected_total` (labels: execution_mode, reason)
  - `order_latency_seconds` (Histogram, labels: execution_mode, order_type)
  - `kill_switch_activations_total` (labels: scope)
  - `kill_switch_mtth_seconds` (Histogram)
  - `reconciliation_runs_total` (labels: trigger, status)
  - `reconciliation_discrepancies_total` (labels: type)
  - `risk_gate_checks_total` (labels: check_name, result)
  - `circuit_breaker_state` (Gauge, labels: adapter_id, state)
  - `broker_request_duration_seconds` (Histogram, labels: adapter, method)
  - `positions_total` (Gauge, labels: deployment_id)

- Instrument all execution services to emit metrics at decision points
- Grafana dashboard JSON (importable): execution overview, risk gates, circuit breakers

- SLO definitions documented:
  - Order submission P99 latency < 500ms (paper), < 2s (live)
  - Kill switch MTTH P99 < 5s
  - Reconciliation discrepancy rate < 0.1%
  - API availability > 99.9%

**Acceptance criteria:**
- All execution metrics emitted and visible at /metrics
- Grafana dashboard displays execution health at a glance
- SLO thresholds documented and measurable from metrics

---

### M16 — Distributed Tracing (OpenTelemetry)

**Objective:** Integrate OpenTelemetry SDK for distributed tracing. Instrument broker
adapter calls, database queries, and cross-service operations as spans.

**Deliverables:**

- `services/api/infrastructure/tracing.py` — OpenTelemetry setup:
  - OTLP exporter (configurable endpoint via OTEL_EXPORTER_OTLP_ENDPOINT)
  - Service name: fxlab-api
  - Auto-instrumentation for FastAPI, SQLAlchemy, httpx
  - Manual spans for: broker adapter calls, risk gate checks, kill switch operations

- `docker-compose.yml` — Extended:
  - Jaeger all-in-one service (or Grafana Tempo)
  - OTEL collector (optional)

- `.env.example` — Extended:
  - `OTEL_EXPORTER_OTLP_ENDPOINT=http://jaeger:4317`
  - `OTEL_SERVICE_NAME=fxlab-api`
  - `OTEL_TRACES_SAMPLER=parentbased_traceidalgo`
  - `OTEL_TRACES_SAMPLER_ARG=0.1` (10% sampling in production)

- Correlation ID propagated as trace baggage (link structured logs to traces)

- Unit tests: tracing setup does not fail when exporter unavailable
- Integration test: submit order, verify trace with spans for route → service → adapter

**Acceptance criteria:**
- Traces visible in Jaeger/Tempo UI
- Each order submission produces a trace with: HTTP → service → risk gate → adapter spans
- Correlation ID linked to trace ID in structured logs
- Tracing is opt-in (no failure when OTEL endpoint not configured)
- Sampling rate configurable for production (avoid overhead)

---

### M17 — Load Testing and Secret Rotation

**Objective:** Create load test suite to establish performance baselines. Implement
automated secret rotation support in the secret provider.

**Deliverables:**

- `tests/load/locustfile.py` — Locust load test suite:
  - Scenarios:
    - Order submission throughput (target: 100 orders/sec paper mode)
    - Concurrent reconciliation (target: 10 concurrent, no deadlocks)
    - Kill switch under load (target: < 5s MTTH with 1000 open orders)
    - Mixed read/write (70% queries, 30% order submissions)
  - Configurable user count, ramp-up, duration
  - Results exported as CSV for regression tracking

- `tests/load/docker-compose.load.yml` — Load test infrastructure:
  - API service with 4 workers
  - PostgreSQL with realistic config
  - Redis
  - Locust master + workers

- `services/api/infrastructure/env_secret_provider.py` — Enhanced:
  - `rotate_secret(key)` implemented:
    - Read new value from environment (key + "_NEW" suffix)
    - Swap: current → old, new → current
    - Both old and new valid during rotation window
  - `list_expiring(threshold_days)` → secrets approaching expiry

- `services/api/infrastructure/secret_rotation_job.py` — Background job:
  - Periodically checks for _NEW suffixed env vars
  - Executes rotation when found
  - Logs rotation events at INFO level

- Documentation: `docs/runbooks/secret-rotation.md`
  - JWT key rotation procedure (zero-downtime)
  - Database credential rotation
  - Broker API key rotation
  - Verification steps after rotation

**Acceptance criteria:**
- Load test establishes baseline: orders/sec, P50/P95/P99 latency, error rate
- No deadlocks under concurrent load
- Kill switch MTTH < 5s with 1000 open orders in load test
- Secret rotation works without service restart
- JWT key rotation maintains session validity during rotation window
- Rotation runbook tested end-to-end

---

## Cross-Cutting Requirements

The following requirements apply to EVERY milestone in this phase:

1. **§0 Compliance:** Every milestone must pass the §0 verification checklist before
   being marked DONE. No in-memory dicts for durable state. No unprotected shared
   mutable state. No partial safety systems.

2. **TDD:** All implementation follows RED → GREEN → REFACTOR. No code without tests.

3. **Coverage:** Overall ≥ 85%. New code ≥ 90%. Core safety services ≥ 95%.

4. **Quality Gate:** format → lint → type-check → unit tests → integration tests
   must all pass before marking any milestone DONE.

5. **Logging:** All new operations emit structured log events per §8 standards.

6. **Error Handling:** All new external calls follow §9 retry/no-retry policy.

7. **Documentation:** All new public APIs have complete docstrings per §7 standards.

8. **Backward Compatibility:** No existing API contracts broken. New endpoints only.

---

## Finding-to-Milestone Traceability Matrix

| Finding | Severity | Addressed By | Milestone |
|---------|----------|-------------|-----------|
| F-01 | CRITICAL | Real Alpaca adapter | M5 |
| F-02 | CRITICAL | SQL repositories + service refactor | M0, M1, M2 |
| F-03 | CRITICAL | threading.Lock on all services | M2 |
| F-04 | CRITICAL | Kill switch retry + verification | M8 |
| F-05 | HIGH | Circuit breaker | M7 |
| F-06 | HIGH | Timeout infrastructure | M4 |
| F-07 | HIGH | Emergency posture verification | M9 |
| F-08 | HIGH | WebSocket streaming | M6 |
| F-09 | HIGH | SELECT FOR UPDATE on positions | M0 |
| F-10 | HIGH | Structural risk gate enforcement | M10 |
| F-11 | MEDIUM | Graceful shutdown + startup recovery | M11 |
| F-12 | MEDIUM | PostgreSQL integration tests | M12 |
| F-13 | MEDIUM | Redis-backed login tracking | M3 |
| F-14 | MEDIUM | Centralized Pydantic Settings | M13 |
| F-15 | MEDIUM | Kubernetes manifests | M14 |
| F-16 | MEDIUM | Readiness probe | M13 |
| F-17 | MEDIUM | DR runbooks | M14 |
| F-18 | MEDIUM | Fix 8 broken tests | M12 |
| F-19 | LOW | Load testing | M17 |
| F-20 | LOW | OpenTelemetry tracing | M16 |
| F-21 | LOW | Secret rotation | M17 |
