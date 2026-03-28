<!-- FXLab distilled context
     Workplan: FXLab_Phase_1_workplan_v3
     Spec:     phase_1_platform_foundation_v1.md
     Generated: 2026-03-14T20:20:06Z
     This file is machine-generated but human-editable.
     Re-run [d] to regenerate, or edit sections directly.
-->

## MILESTONE: M0 -- Bootstrap

### Spec Context
- Phase 1 establishes the "operational spine": containerized topology, metadata DB, artifact storage, feed registry, audit ledger, RBAC, observability, and API gateway
- M0 must bootstrap the minimal runtime so later milestones can build on stable deployment, persistence, and observability contracts
- No acceptance criteria provided for M0 in the workplan excerpt

### Key Constraints
- All first-party backend services must use Docker packaging
- Schema migrations and init jobs must run before application services start
- Health/readiness/liveness probes and graceful shutdown are mandatory for every service
- Immutable audit log and versioned artifact registry are non-negotiable substrates

### Interface Contracts
- Docker Compose environment defining service topology and dependency order
- Metadata database connection abstraction (relational or document store)
- Artifact/object storage abstraction
- Structured logging with correlation ID standard
- Health endpoints (`/health`, `/ready`, `/live`) on every service

### Acceptance Criteria
- (No explicit criteria in the provided workplan section for M0)
- Implied: local environment starts all core services with health checks passing
- Implied: metadata DB and artifact storage are initialized and accessible
- Implied: logging emits structured output with correlation IDs

---

## MILESTONE: M1 -- Docker Runtime

### Spec Context
- Phase 1 establishes containerized service topology with Docker packaging for all first-party backend services
- Docker Compose local environment required with startup ordering, dependency contracts, and health/readiness/liveness probes
- Services include: `api`, `orchestrator`, `scheduler`, `market_data_ingest`, `feed_verification`
- Persistent volume requirements, graceful shutdown contracts, and secrets injection via environment contract mandatory

### Key Constraints
- No later phase may bypass or replace this substrate—stable, versioned interfaces are non-negotiable
- Schema migration/init jobs must run before service startup
- Staging/prod deployment descriptors must be delivered alongside local environment
- Backup/restore policy required for all stateful stores

### Interface Contracts
- Health/readiness/liveness probe endpoints (all services)
- Secrets injection via environment variables (runtime contract)
- Service-to-service dependency declarations (Docker Compose)
- Graceful shutdown signal handlers (SIGTERM contract)

### Acceptance Criteria
- Docker Compose successfully orchestrates all Phase 1 services with correct startup order
- All services expose functional health/readiness/liveness endpoints
- Services shut down gracefully on SIGTERM without data loss
- Secrets are injected securely without hardcoding in images or compose files

---

## MILESTONE: M2 -- DB Schema + Migrations + Audit Ledger

### Spec Context
- Core persistent stores include: relational/document metadata store, artifact/object storage abstraction, event ledger/immutable audit log, feed-health and parity event storage, dataset version registry, feed configuration version registry
- Phase must deliver "immutable audit records" and "run/job records" as stable contracts for later phases
- All first-class objects stored in metadata store; artifact/object storage uses separate abstraction layer

### Key Constraints
- Event ledger must be immutable (every mutation writes an immutable audit_event)
- All IDs are ULIDs
- Schema migrations use dedicated init jobs with versioning
- Graceful shutdown and startup ordering contracts required for stateful stores
- Backup/restore policy mandatory for all stateful stores

### Interface Contracts
- `metadata_store` (persistence layer): relational or document database client for first-class objects
- `artifact_store` (persistence layer): object storage abstraction for versioned artifacts
- `audit_ledger` (persistence layer): append-only event log writer
- Migration runner: schema versioning and init job orchestration

### Acceptance Criteria
- Schema migration tooling in place with version tracking
- All metadata tables defined with ULID primary keys
- Audit event ledger accepts append-only writes with correlation IDs
- Feed registry, dataset registry, and feed-health tables created
- Backup/restore procedure documented for all persistent stores

---

## MILESTONE: M3 -- Auth + RBAC

### Spec Context
- Phase 1 establishes "authn/authz and RBAC" as a control-plane service requirement
- "operator-only admin endpoints" must be protected by the auth layer
- Secrets injection and environment contract must support credential management
- System must emit immutable audit records for all privileged actions

### Key Constraints
- Every mutation writes an immutable audit_event (from engineering protocol)
- All IDs are ULIDs (from engineering protocol)
- Secrets must be injected via environment contract, never hardcoded
- RBAC model must integrate with API gateway service boundary

### Interface Contracts
- `api` service (gateway layer) — enforces authentication and role checks
- `AuthMiddleware` or equivalent in gateway — validates tokens before routing
- Admin endpoints under `/admin/*` or similar path — require elevated permissions
- `audit_events` table or event ledger — records authentication and authorization decisions

### Acceptance Criteria
- (Milestone M3 not found in workplan; acceptance criteria unavailable)
- Operators can authenticate and access admin endpoints
- Non-operators receive 403 responses for privileged routes
- All auth decisions produce audit events with actor, resource, and outcome

---

## MILESTONE: M4 -- Jobs + Queue Classes + Compute Policy

### Spec Context
- **Queue classes**: spec implies scheduler/queue classes exist to route different job types (M4 scope)
- **Compute policy model**: Phase 1 control-plane services explicitly include "compute policy model" and "scheduler/queue classes" (§4)
- **Job records**: dovetail contract requires "run/job records and queue classes" for later phases to consume

### Key Constraints
- All IDs are ULIDs (engineering protocol)
- Every state change writes an immutable audit_event (engineering protocol)
- Jobs must be routable to queue classes; compute policy governs resource allocation
- Contracts must remain stable for Phase 2 integration

### Interface Contracts
- `scheduler` service (control-plane layer)
- `Job` model or table (persistence layer)
- `QueueClass` enumeration or table (persistence layer)
- `ComputePolicy` model (control-plane layer)
- API endpoints: `POST /jobs`, `GET /jobs/:id` (application API skeleton)

### Acceptance Criteria
*(Workplan section for M4 not found; inferred from spec requirements)*
- Job creation writes audit_event with ULID
- Job record links to queue_class
- Compute policy applied at job enqueue time
- Queue class determines scheduler routing

---

## MILESTONE: M5 -- Artifact Registry + Storage Abstraction

### Spec Context
- Artifact/object storage abstraction is a core persistent store required in Phase 1
- Storage must support dataset version registry and feed configuration version registry
- All first-party backend services run in Docker with persistent volume requirements
- Later phases must plug artifacts into stable retrieval contracts without changing their meaning

### Key Constraints
- Every service uses Docker packaging with health/readiness/liveness probes
- Secrets injection follows environment contract
- Versioned artifacts must be registered and retrievable via stable interface
- Backup/restore policy applies to all stateful stores including artifact storage

### Interface Contracts
- Artifact registration API (create, retrieve versioned objects)
- Storage abstraction layer (filesystem, S3-compatible, or blob interface)
- Volume mount contract for Docker Compose and staging/prod descriptors
- Dataset version registry schema and query interface

### Acceptance Criteria
- Artifact storage abstraction supports multiple backends (local volume, S3-compatible)
- Services can register and retrieve versioned artifacts by ID and version
- Docker Compose environment mounts persistent volumes correctly
- Backup/restore procedure documented and tested for artifact store

---

## MILESTONE: M6 -- Feed Registry + Versioned Config + Connectivity Tests

### Spec Context
- Feed provider registry with add/modify/disable/delete lifecycle and credential test/connectivity test endpoint
- Feed configuration versioning store with versioned feed configurations as a stable contract for later phases
- Connectivity test endpoint must validate feed credentials and provider reachability
- Feed-health and parity event storage required as part of core persistent stores

### Key Constraints
- All first-class objects stored in relational or document metadata store
- Versioned feed configurations are a non-negotiable stable contract for Phase 2+
- Schema migration/init jobs manage database evolution
- Health/readiness/liveness probes required for all services

### Interface Contracts
- `market_data_ingest` service boundary must expose feed connectivity test
- Feed provider registry API endpoints for CRUD operations on feed definitions
- Feed configuration version registry stores and retrieves versioned configs
- Metadata store schema includes feed_providers, feed_configs, feed_health_events tables

### Acceptance Criteria
- Feed providers can be registered, modified, disabled, and deleted via API
- Feed configurations support versioning with immutable historical records
- Connectivity test endpoint successfully validates credentials against live feed provider
- Feed health events persist test results to support observability and diagnostics

---

## MILESTONE: M7 -- Ingest Pipeline

### Spec Context
- Service boundary: `market_data_ingest` (part of feed management and data operations substrate)
- Feed provider registry with versioning; add/modify/disable/delete lifecycle
- Gap detection, freshness/heartbeat tracking, anomaly capture, and quarantine workflow are in-scope data operations
- Feed configuration versioning and symbol lineage storage must be implemented

### Key Constraints
- All IDs are ULIDs (engineering protocol standard)
- Every mutation writes an immutable audit_event to the event ledger
- Versioned datasets and versioned feed configurations are stable contracts for later phases
- Correlation IDs must be generated per the platform standard

### Interface Contracts
- Service: `market_data_ingest` (runtime substrate layer)
- Service: `feed_verification` (data operations layer)
- Feed provider registry API (control-plane service)
- Credential test/connectivity test endpoint (admin API)
- Feed health events and parity events (persistent store contract)

### Acceptance Criteria
- (No acceptance criteria found in provided workplan section for M7)
- Feed configuration can be versioned, modified, and disabled
- Gap detection and freshness tracking emit feed health events
- Quarantine workflow prevents uncertified data propagation

---

## MILESTONE: M8 -- Verification + Gaps + Anomalies + Certification

### Spec Context
- Feed verification service must detect gaps, anomalies, and perform certification
- Certification states are part of the feed-health and parity event storage
- Anomaly capture and quarantine workflow are explicit in-scope deliverables
- Parity comparisons across multiple feeds must inform certification

### Key Constraints
- All feed-health and parity events stored in immutable audit ledger
- Every certification state transition writes an audit_event with correlation ID
- Feed configuration versioning must be immutable once certification occurs
- Gap detection and freshness tracking results must persist to feed-health storage

### Interface Contracts
- `feed_verification` service consumes feed-health events and produces certification state changes
- Feed health endpoints under operator-only admin endpoints in API gateway
- Anomaly and gap detection results stored in feed-health and parity event storage layer
- Quarantine workflow exposed via control-plane API

### Acceptance Criteria
- (criterion not found in provided workplan section for M8)

---

## MILESTONE: M9 -- Symbol Lineage

### Spec Context
- **Symbol lineage storage** is an in-scope deliverable under "Feed management and data operations."
- The spec requires **versioned datasets** and **versioned feed configurations** as stable contracts for later phases.
- Feed management includes **feed provider registry**, **feed configuration versioning**, and **add/modify/disable/delete lifecycle**.
- Symbol lineage must tie to **parity comparisons across multiple feeds** and **feed health events**.

### Key Constraints
- All IDs are ULIDs (from engineering protocol).
- Every mutation writes an immutable `audit_event` to the event ledger.
- **Versioned feed configurations** are first-class objects; symbol lineage must reference specific configuration versions.
- Symbol lineage is metadata; store in the **relational or document metadata store**, not artifact storage.

### Interface Contracts
- `FeedConfigurationVersion` (metadata layer): parent entity for symbol mappings.
- `SymbolLineage` (metadata layer): records symbol name, normalization rules, and parent feed config version ID.
- `GET /api/feed-configs/{id}/symbols` (application API): retrieves symbol lineage for a given feed configuration version.
- `market_data_ingest` service: consumes symbol lineage during normalization.

### Acceptance Criteria
- Symbol lineage records link each normalized symbol to its source feed configuration version.
- API exposes symbol lineage per feed configuration version.
- Audit log captures all symbol lineage modifications with feed config version ID and correlation ID.

---

## MILESTONE: M10 -- Parity Service

### Spec Context
- Feed parity service compares multiple feeds for the same symbol to detect divergence and certification readiness
- Parity events must be stored persistently with feed health and certification states
- Service fits within the feed verification and data operations control plane
- Symbol lineage storage tracks which feeds provide which symbols for parity comparison

### Key Constraints
- All events are immutable audit records with correlation IDs
- Service must expose health/readiness/liveness probes and graceful shutdown
- Docker packaging required; runs under orchestrator scheduling contracts
- Parity results must integrate with certification states and quarantine workflow

### Interface Contracts
- `feed_verification` service boundary (control-plane layer)
- Consumes feed configuration version registry and feed provider registry
- Writes to parity event storage and feed health event storage
- Exposes operator diagnostic endpoints for parity analysis

### Acceptance Criteria
- Parity service can compare two or more feeds for a given symbol and timestamp range
- Divergence detection triggers parity events stored in the event ledger
- Parity results update certification state for feeds under evaluation
- Operator diagnostics expose current parity status and historical divergence patterns

---

## MILESTONE: M11 -- Alerting + Observability Hardening

### Spec Context
- Phase 1 must deliver "health, metrics, logs, and alerts" as part of the operational spine
- Observability scope includes: structured logging baseline, metrics emission, alert routing, correlation ID generation standard, service health endpoints, operator diagnostics for feeds/queues/storage
- Service boundaries include api, orchestrator, scheduler, market_data_ingest, feed_verification (all require health/readiness/liveness probes)

### Key Constraints
- All services must expose health/readiness/liveness probe endpoints
- Correlation IDs must be generated and propagated across service boundaries
- Immutable audit events must be written for state transitions affecting feeds, certification, or quarantine
- Structured logging must be baseline across all first-party services

### Interface Contracts
- `/health`, `/ready`, `/live` endpoints on every containerized service
- Metrics emission interface (e.g. Prometheus exporter or push gateway)
- Alert routing service (component name TBD, consumes feed-health events, parity events, anomaly captures)
- Logging sink configuration in Docker Compose and deployment descriptors

### Acceptance Criteria
- All Phase 1 services emit structured logs with correlation IDs
- Alerts fire on feed freshness violations, gap detection, and parity failures
- Operator dashboards show service health, queue depth, and feed status
- Graceful shutdown does not lose in-flight metric or log records

---

## MILESTONE: M12 -- Operator API Docs + Acceptance Pack

### Spec Context
- Phase 1 deliverable: "stable, versioned interfaces" and "operator-safe APIs" before research/execution logic complete
- Required interface points include documented service boundaries: `api`, `orchestrator`, `scheduler`, `market_data_ingest`, `feed_verification`
- Control-plane services must include "operator-only admin endpoints"
- Observability must provide "operator diagnostics for feeds, queues, and storage"

### Key Constraints
- All first-class objects stored in metadata database must follow schema migration contracts
- Every service must expose health/readiness/liveness probe endpoints
- All API endpoints require authn/authz via RBAC model
- Correlation IDs must follow platform-wide generation standard

### Interface Contracts
- `api` gateway service exposes application API and admin endpoints (HTTP)
- `orchestrator` service handles queue management and compute policy
- `market_data_ingest` service provides feed connectivity test endpoint
- `feed_verification` service exposes gap detection and parity comparison endpoints
- Operator diagnostics endpoints accessible via `api` service admin routes

### Acceptance Criteria
- (No explicit acceptance criterion found in provided workplan section for M12)
- Complete API documentation covering all operator-accessible endpoints across service boundaries
- Documentation includes authentication requirements, correlation ID usage, and health probe contracts
- Acceptance pack validates API contracts against Phase 1 dovetail requirements for later phases

<!-- distilled -->
