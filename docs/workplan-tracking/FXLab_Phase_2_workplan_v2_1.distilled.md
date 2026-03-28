<!-- FXLab distilled context
     Workplan: FXLab_Phase_2_workplan_v2_1
     Spec:     phase_2_research_and_compiler_v1.md
     Generated: 2026-03-16T22:53:49Z
     This file is machine-generated but human-editable.
     Re-run [d] to regenerate, or edit sections directly.
-->

## MILESTONE: M0 -- Bootstrap

### Spec Context
- This is Phase 2 of a multi-phase project building an analytical engine for FX strategy research
- Phase 1 already delivered: certified dataset versions, feed lineage, queue classes, compute policies, artifact storage, immutable audit events, correlation IDs, auth/RBAC, and containerized worker runtime
- Phase 2 must treat all Phase 1 contracts as authoritative — no bypassing existing storage or lineage controls
- Core Phase 2 outputs: strategy compiler, deterministic research engine, optimization workflows, and export-ready artifacts

### Key Constraints
- FastAPI app: services/api/main.py — never app.py or any other name
- Route handlers: services/api/routes/<name>.py
- Pydantic schemas/enums: libs/contracts/
- Typed exceptions: libs/contracts/errors.py
- All IDs are ULIDs — never UUID or auto-increment
- Test fixtures: tests/conftest.py (root), tests/unit/conftest.py, tests/integration/conftest.py — never create a second conftest.py
- No Phase 2 component may bypass Phase 1 storage or lineage controls
- All research runs, compiler outputs, and optimization results must plug into existing dataset registry, artifact store, audit ledger, queue classes, and compute policies

### Interface Contracts
- No new API endpoints or service interfaces defined for M0
- M0 establishes project structure only — execution logic comes in later milestones

### Acceptance Criteria
- (M0 workplan section not found — unable to extract acceptance criteria)

---

## MILESTONE: M1 -- Docker Runtime

### Spec Context
- Phase 2 requires "containerized services and worker runtime" as a dependency from Phase 1
- All services must integrate with Phase 1's queue classes, compute policies, artifact storage, and audit ledger
- Service boundaries include `strategy_compiler`, `research_worker`, `optimization_worker`, `readiness_service`, `results_artifact_service`

### Key Constraints
- All IDs are ULIDs — never UUID or auto-increment
- FastAPI app: services/api/main.py — never app.py or any other name
- No Phase 2 component may bypass Phase 1 storage or lineage controls
- Every mutation writes an immutable audit_event

### Interface Contracts
- Containerized runtime environment for all Phase 2 services
- Docker Compose orchestration for multi-service development and integration testing
- Worker runtime compatible with Phase 1 queue classes and compute policies

### Acceptance Criteria
- Docker Compose brings up all Phase 2 services with health checks passing
- Services can communicate through defined network and volume mounts
- Worker containers can consume jobs from Phase 1 queue infrastructure
- All containers use consistent base images and follow project conventions

---

## MILESTONE: M2 -- DB Schema + Migrations + Audit Ledger

### Spec Context
- This milestone must deliver the DB schema, migrations, and audit ledger infrastructure that Phase 2 analytical components will write to
- Phase 2 requires immutable audit events for all strategy compilation, research runs, optimization runs, and artifact registration operations
- The schema must support strategy versions, research/optimization runs, trials, artifacts, uncertainty ledger entries, and readiness scoring outputs
- All Phase 2 services (strategy_compiler, research_worker, optimization_worker, readiness_service, results_artifact_service) must log state changes to the audit ledger

### Key Constraints
- All IDs are ULIDs — never UUID or auto-increment
- FastAPI app: services/api/main.py — never app.py
- Every mutation writes an immutable audit_event — no direct state changes without audit trail
- No Phase 2 component may bypass Phase 1 storage or lineage controls — reuse existing artifact store and metadata registry
- Migrations must be versioned and deterministic — use Alembic or equivalent with explicit upgrade/downgrade paths

### Interface Contracts
- Database layer: services/api/db/ or libs/db/ — connection pooling, transaction context managers
- Migration scripts: migrations/ or alembic/versions/ — timestamped, single-direction SQL/Python migrations
- Audit ledger schema: audit_events table with entity_type, entity_id, event_type, payload, correlation_id columns
- Schema entities: strategies, strategy_versions, research_runs, optimization_runs, trials, uncertainty_entries, readiness_scores

### Acceptance Criteria
- Database schema supports all Phase 2 entities: strategies, versions, runs, trials, artifacts, uncertainty ledger, readiness scores
- Migration tooling in place with at least one migration applied successfully
- Audit ledger table exists and accepts writes for all entity types
- Schema enforces ULID primary keys and foreign key integrity
- Transaction rollback leaves no partial state in either operational or audit tables

---

## MILESTONE: M3 -- Auth + RBAC

### Spec Context
- Auth + RBAC was delivered in Phase 1 as a dependency for Phase 2
- Phase 2 assumes "auth/RBAC" already exists and enforces access control on all strategy, run, and artifact endpoints
- All APIs listed (strategy compilation, research/optimization, exports) require authenticated requests with role checks

### Key Constraints
- All IDs are ULIDs — never UUID or auto-increment
- FastAPI app: services/api/main.py — never app.py
- Route handlers: services/api/routes/<name>.py
- Typed exceptions: libs/contracts/errors.py
- Test fixtures: tests/conftest.py (root), tests/unit/conftest.py, tests/integration/conftest.py — never create a second conftest.py
- Every mutation writes an immutable audit_event
- No Phase 2 component may bypass Phase 1 storage or lineage controls

### Interface Contracts
- **AuthMiddleware** (services/api/middleware/auth.py) — validates JWT/session for all protected routes
- **RBACGuard** (services/api/dependencies/rbac.py) — enforces role/permission checks via FastAPI dependencies
- **User** schema (libs/contracts/user.py) — defines user_id (ULID), roles, permissions
- All route handlers in services/api/routes/ must inject current_user dependency

### Acceptance Criteria
- (M3 workplan section not found — no explicit acceptance criteria available for this milestone)
- Assumed: authenticated requests succeed with valid credentials; unauthorized requests return 401/403
- All strategy, run, and artifact endpoints enforce RBAC before execution

---

## MILESTONE: M4 -- Jobs + Queue Classes + Compute Policy

### Spec Context
- Create queue classes and compute policies that research/optimization jobs will use (foundation for later compiler, research_worker, optimization_worker services)
- Must integrate with Phase 1 artifact storage, metadata registry, and immutable audit events
- Jobs include: compile strategy, research run, optimization run, holdout verification, readiness report generation
- All outputs must register artifacts and support resumable/retry-safe execution

### Key Constraints
- All IDs are ULIDs
- Every job mutation writes an immutable audit_event
- Queue classes and compute policies were delivered in Phase 1 — reference those contracts, do not create parallel infrastructure
- Jobs must be resumable and retry-safe
- FastAPI app: services/api/main.py
- Pydantic schemas/enums: libs/contracts/
- Typed exceptions: libs/contracts/errors.py
- Test fixtures: tests/conftest.py (root), tests/unit/conftest.py, tests/integration/conftest.py — never create a second conftest.py

### Interface Contracts
- `QueueClass` enum in libs/contracts/ (defines COMPILER, RESEARCH, OPTIMIZATION, HOLDOUT, READINESS tiers)
- `ComputePolicy` schema in libs/contracts/ (memory_mb, timeout_sec, max_retries per queue class)
- `JobStatus` enum in libs/contracts/ (PENDING, RUNNING, COMPLETED, FAILED, RETRY)
- Job base schema in libs/contracts/ with queue_class, compute_policy_id, status, correlation_id, audit_event_id fields

### Acceptance Criteria
- Queue classes defined for all five job types (compile, research, optimize, holdout, readiness)
- Compute policies created with tier-appropriate resource limits and retry counts
- Job schemas enforce queue class assignment and link to audit events
- Integration test validates job creation writes audit event and respects compute policy timeout

---

## MILESTONE: M5 -- Artifact Registry + Storage Abstraction

### Spec Context
- M5 must create a `results_artifact_service` responsible for registering and retrieving all research outputs (trial summaries, equity curves, trade blotters, readiness reports, compiler manifests)
- Artifact storage must use the Phase 1 artifact store and metadata registry — no parallel infrastructure
- All artifacts must be registered with correlation_id and immutable audit events
- Endpoints: `GET /runs/{run_id}/artifacts`, `GET /runs/{run_id}/exports/trades`, `GET /runs/{run_id}/exports/equity`

### Key Constraints
- All IDs are ULIDs — never UUID or auto-increment
- Every mutation writes an immutable audit_event
- FastAPI app: services/api/main.py — never app.py
- Route handlers: services/api/routes/<name>.py
- Pydantic schemas/enums: libs/contracts/
- No Phase 2 component may bypass Phase 1 storage or lineage controls
- Must use existing certified dataset versions, feed lineage, and artifact storage from Phase 1

### Interface Contracts
- `ArtifactService` (application layer): register_artifact, get_artifact_metadata, get_artifact_download_url
- `GET /runs/{run_id}/artifacts` (API): list all artifacts for a research run
- `GET /runs/{run_id}/exports/trades` (API): retrieve trade blotter artifact
- `GET /runs/{run_id}/exports/equity` (API): retrieve equity curve artifact
- `ArtifactMetadata` schema (libs/contracts/): artifact_id, run_id, artifact_type, storage_path, created_at
- `ArtifactType` enum (libs/contracts/): TRIAL_SUMMARY, EQUITY_CURVE, TRADE_BLOTTER, READINESS_REPORT, COMPILER_MANIFEST

### Acceptance Criteria
- (Acceptance criteria not found in provided workplan section)

---

## MILESTONE: M6 -- Feed Registry + Versioned Config + Connectivity Tests

### Spec Context
- Phase 2 depends on Phase 1 "certified dataset versions" and "feed lineage and parity evidence"
- No Phase 2 component may bypass Phase 1 storage or lineage controls
- Strategy compiler must perform "schema/static/PIT/logging contract checks"
- Research engine requires "PIT-safe multi-timeframe logic" and deterministic execution

### Key Constraints
- All IDs are ULIDs
- Every mutation writes an immutable audit_event
- FastAPI app: services/api/main.py
- Route handlers: services/api/routes/<name>.py
- Pydantic schemas/enums: libs/contracts/
- Must integrate Phase 1 dataset registry and artifact store — no parallel infrastructure

### Interface Contracts
- `GET /feeds` — list registered certified feed versions (Phase 1 dependency check)
- `GET /feeds/{feed_id}/versions` — verify feed lineage exists
- `GET /datasets/{dataset_id}/metadata` — confirm PIT-safe dataset availability
- Health check endpoint to verify Phase 1 substrate connectivity
- libs/contracts/ schema for feed version reference in strategy_ir.json

### Acceptance Criteria
- Feed registry API returns certified feed versions with lineage metadata
- Config schema supports versioned feed references with PIT timestamp boundaries
- Integration tests confirm connectivity to Phase 1 dataset and artifact services
- All feed and dataset IDs validated as ULIDs before acceptance

---

## MILESTONE: M7 -- Ingest Pipeline

### Spec Context
- Phase 2 assumes Phase 1 already provides: certified dataset versions, feed lineage and parity evidence, queue classes, artifact storage and metadata registry, immutable audit events
- No Phase 2 component may bypass Phase 1 storage or lineage controls
- Dependencies: dataset registry, artifact store, audit ledger, queue classes, compute policies from Phase 1 must be treated as authoritative

### Key Constraints
- All IDs are ULIDs — never UUID or auto-increment
- Every mutation writes an immutable audit_event
- Phase 1 contracts are authoritative — no parallel infrastructure
- FastAPI app: services/api/main.py — never app.py or any other name
- Route handlers: services/api/routes/<name>.py
- Pydantic schemas/enums: libs/contracts/
- Typed exceptions: libs/contracts/errors.py

### Interface Contracts
- Dataset registry integration (Phase 1 dependency)
- Artifact storage integration (Phase 1 dependency)
- Queue classes for async job submission (Phase 1 dependency)
- Audit ledger for all data ingestion events (Phase 1 dependency)
- Compute policies enforcement (Phase 1 dependency)

### Acceptance Criteria
- (No explicit M7 acceptance criteria found in provided workplan section)
- Must integrate with Phase 1 certified dataset versions
- Must respect Phase 1 lineage and storage controls
- Must emit immutable audit events for all operations

---

## MILESTONE: M8 -- Verification + Gaps + Anomalies + Certification

### Spec Context
- M8 ("Verification + Gaps + Anomalies + Certification") not found in Phase 2 workplan
- Phase 2 includes `holdout verification job` and `readiness report generation job` as orchestrated batch workflows
- `POST /runs/{run_id}/verify_holdout` and `GET /runs/{run_id}/readiness` endpoints are required interface points
- Readiness scoring and holdout evaluation outputs must register as artifacts in Phase 1's artifact store

### Key Constraints
- All IDs are ULIDs — never UUID or auto-increment
- FastAPI app: services/api/main.py — never app.py
- Pydantic schemas/enums: libs/contracts/
- Every Phase 2 component must use Phase 1's artifact storage, audit ledger, and dataset registry — no parallel infrastructure
- All research/optimization outputs must emit immutable audit_events with correlation IDs
- PIT (point-in-time) safety is non-negotiable for all backtest/holdout logic

### Interface Contracts
- `POST /runs/{run_id}/verify_holdout` — services/api/routes/runs.py — triggers holdout verification job
- `GET /runs/{run_id}/readiness` — services/api/routes/runs.py — retrieves readiness report artifact
- `readiness_service` module — application layer — computes readiness score from holdout and optimization outputs
- `results_artifact_service` module — application layer — registers run outputs (equity curve, trade blotter, readiness report) in artifact store

### Acceptance Criteria
- (No acceptance criteria found for M8 in workplan — milestone may be misnamed or out of scope for Phase 2)
- If M8 refers to holdout verification: holdout dataset remains untouched during optimization, verification job runs deterministically on holdout period, and readiness report artifact is generated with certification evidence

---

## MILESTONE: M9 -- Symbol Lineage

### Spec Context
- M9 not explicitly named in workplan; symbol lineage likely falls under "feed lineage and parity evidence" dependency from Phase 1
- Phase 2 requires "PIT-safe multi-timeframe logic" and must not bypass "Phase 1 storage or lineage controls"
- Compiler must perform "schema/static/PIT/logging contract checks" — PIT = point-in-time correctness

### Key Constraints
- All IDs are ULIDs
- Every mutation writes an immutable audit_event
- FastAPI app: services/api/main.py
- Route handlers: services/api/routes/<name>.py
- Pydantic schemas/enums: libs/contracts/
- No Phase 2 component may bypass Phase 1 storage or lineage controls
- Research runs must plug into existing dataset registry, artifact store, audit ledger

### Interface Contracts
- Dataset registry service (Phase 1 dependency) — certifies dataset versions
- Feed lineage service (Phase 1 dependency) — tracks data provenance
- Artifact storage service (Phase 1 dependency) — stores all outputs
- `libs/contracts/lineage.py` — symbol lineage schemas (if not already defined in Phase 1)

### Acceptance Criteria
- (M9 workplan section not found — cannot provide exact acceptance criteria)
- Likely: symbol metadata and transformations traceable from raw feed to compiled strategy harness
- All symbol references validate against certified dataset registry
- Lineage chain supports PIT-correctness verification

---

## MILESTONE: M10 -- Parity Service

### Spec Context
- Phase 2 depends on Phase 1's certified dataset versions, feed lineage, parity evidence, and artifact storage.
- "No Phase 2 component may bypass Phase 1 storage or lineage controls."
- M10 (Parity Service) not explicitly defined in the workplan excerpt provided; inferring from Phase 1 dependency: parity evidence must exist before research runs can execute.
- Parity evidence = proof that datasets match broker/vendor truth at certification time.

### Key Constraints
- FastAPI app: services/api/main.py — never app.py
- Route handlers: services/api/routes/<name>.py
- Pydantic schemas/enums: libs/contracts/
- All IDs are ULIDs — never UUID or auto-increment
- Every mutation writes an immutable audit_event
- Phase 2 must consume Phase 1 lineage/artifact storage — no parallel infrastructure

### Interface Contracts
- **libs/contracts/parity.py** — `ParityEvidence` schema (dataset_id, comparison_hash, certified_at, metadata)
- **services/api/routes/parity.py** — `GET /datasets/{dataset_id}/parity` endpoint
- **services/parity_worker/** — job handler that compares dataset artifact against reference feed, emits ParityEvidence record
- Called by Phase 2 research_worker before run execution to validate dataset integrity

### Acceptance Criteria
- Parity evidence record created for every certified dataset version
- Evidence includes comparison hash, timestamp, and certification authority
- Research/optimization runs reject datasets lacking valid parity evidence
- GET /datasets/{dataset_id}/parity returns current parity status with audit trail

---

## MILESTONE: M11 -- Alerting + Observability Hardening

### Spec Context
- Phase 2 assumes Phase 1 provides: certified datasets, feed lineage evidence, queue classes, compute policies, artifact storage, metadata registry, immutable audit events, correlation IDs, auth/RBAC, containerized services and worker runtime
- M11 is not explicitly defined in the provided workplan or spec — appears to be a post-implementation hardening milestone for alerting and observability
- Canonical service boundaries include: strategy_compiler, research_worker, optimization_worker, readiness_service, results_artifact_service
- All Phase 2 components must use Phase 1 storage and lineage controls — no bypassing allowed

### Key Constraints
- All IDs are ULIDs — never UUID or auto-increment
- Every mutation writes an immutable audit_event
- FastAPI app: services/api/main.py — never app.py
- Pydantic schemas/enums: libs/contracts/
- Typed exceptions: libs/contracts/errors.py
- Test fixtures: tests/conftest.py (root), tests/unit/conftest.py, tests/integration/conftest.py — never create a second conftest.py
- Must preserve correlation IDs across all async worker jobs and API boundaries

### Interface Contracts
- Monitoring endpoints: `services/api/routes/health.py` — GET /health, GET /metrics
- Correlation middleware: libs/observability/correlation.py — injects correlation_id into logs and headers
- Structured logger: libs/observability/logger.py — configured for JSON output with correlation context
- Worker health checks: services/workers/<worker_name>/health.py — heartbeat and queue depth metrics
- Alerting rules config: infra/monitoring/alerts.yaml — Prometheus/Grafana alert definitions

### Acceptance Criteria
- All critical paths (compilation, research, optimization jobs) emit structured logs with correlation_id, duration, and outcome
- Health endpoints return 200 with service metadata; degraded dependencies return 503
- Prometheus metrics exposed for: queue depth, job success/failure rates, compilation time, backtest duration
- Alert rules configured for: queue saturation, worker crash loops, excessive job failures, dataset staleness

---

## MILESTONE: M12 -- Operator API Docs + Acceptance Pack

### Spec Context
- M12 not defined in workplan; inferring from Phase 2 context: "Basic internal review surfaces or API docs are allowed"
- Phase 2 delivers a "headless but fully credible research system" driven by APIs before polished UI exists
- Canonical APIs listed: strategy compilation (5 endpoints), research/optimization (6 endpoints), exports/artifacts (3+ endpoints)
- All Phase 2 services must plug into Phase 1 contracts: dataset registry, artifact store, audit ledger, queue classes

### Key Constraints
- FastAPI app: services/api/main.py (never app.py)
- Route handlers: services/api/routes/<name>.py
- Pydantic schemas/enums: libs/contracts/
- All IDs are ULIDs (never UUID)
- Every mutation writes an immutable audit_event
- No Phase 2 component may bypass Phase 1 storage or lineage controls

### Interface Contracts
- **POST /strategies/draft** — services/api/routes/strategies.py
- **POST /strategies/{strategy_id}/compile** — services/api/routes/strategies.py
- **GET /strategies/{strategy_id}/versions/{version}** — services/api/routes/strategies.py
- **POST /runs/research** — services/api/routes/runs.py
- **POST /runs/optimize** — services/api/routes/runs.py
- **GET /runs/{run_id}/readiness** — services/api/routes/runs.py
- **GET /runs/{run_id}/exports/trades** — services/api/routes/runs.py
- OpenAPI schema auto-generated by FastAPI for operator review

### Acceptance Criteria
- All 14+ canonical Phase 2 API endpoints documented in OpenAPI schema
- Operator-facing API documentation accessible via /docs (Swagger UI)
- Internal acceptance pack includes example cURL/Postman calls for each endpoint

<!-- distilled -->
