# FXLab Phase 1 — Platform Foundation, Data Operations, and Containerized Runtime

## Context / Objective

This phase establishes the non-negotiable technical foundation for the entire FXLab platform. The purpose is to create the underlying runtime, persistence, feed-management, observability, and control-plane capabilities that every later phase depends on. No strategy feature, UI workflow, or broker path in later phases should be allowed to bypass or replace this substrate.

This phase must dovetail into the rest of the project by delivering stable, versioned interfaces for data, artifacts, auditability, queueing, health, and containerized deployment. Later phases may consume these contracts, but they should not have to redesign them. The design target is: **when Phase 1 finishes, the platform can ingest and certify data, manage feeds, run services in Docker, store versioned artifacts, emit audit logs, and expose operator-safe APIs even before research or execution logic is complete.**

## Primary outcome

Build the operational spine of FXLab:

- containerized service topology
- metadata database and schema migrations
- artifact/object storage
- feed registry and feed versioning
- feed verification and gap detection
- feed parity and certification workflow
- queueing/scheduling substrate
- audit/event ledger
- RBAC and secrets model
- health, metrics, logs, and alerts
- API gateway and service-to-service contracts

## In scope

### 1. Deployment/runtime substrate

- Docker packaging for all first-party backend services
- Docker Compose local environment
- staging/prod deployment descriptors
- startup ordering and dependency contracts
- health/readiness/liveness probes
- graceful shutdown contracts
- schema migration/init jobs
- secrets injection and environment contract
- persistent volume requirements
- backup/restore policy for stateful stores

### 2. Core persistent stores

- relational or document metadata store for first-class objects
- artifact/object storage abstraction
- event ledger / immutable audit log
- cache layer where justified
- feed-health and parity event storage
- dataset version registry
- feed configuration version registry

### 3. Feed management and data operations

- feed provider registry
- feed configuration versioning
- add/modify/disable/delete lifecycle
- credential test/connectivity test endpoint
- gap detection
- freshness/heartbeat tracking
- anomaly capture
- certification states
- quarantine workflow
- symbol lineage storage
- parity comparisons across multiple feeds

### 4. Control-plane services

- API gateway/application API skeleton
- orchestrator skeleton
- scheduler/queue classes
- compute policy model
- alerting/notification service
- authn/authz and RBAC
- operator-only admin endpoints

### 5. Observability

- structured logging baseline
- metrics emission
- alert routing
- correlation ID generation standard
- service health endpoints
- operator diagnostics for feeds, queues, and storage

## Explicitly out of scope

- full Strategy Studio UX
- AI compilation of trading ideas
- backtesting/optimization logic beyond smoke-test workers
- broker adapters and order submission
- shadow/paper/live deployment workflows

Small placeholders are allowed only if they exist to validate infrastructure contracts.

## Dovetail requirements for later phases

This phase must leave behind stable contracts for:

- versioned datasets
- versioned feed configurations
- feed health events
- parity events
- immutable audit records
- run/job records and queue classes
- artifact registration and retrieval
- authentication and permissions
- correlation IDs
- environment/runtime metadata

Phase 2 must be able to plug research runs and compiler artifacts into these contracts without changing their meaning.

## Required interface points

### Service boundaries

At minimum, create and document the following service boundaries:

- `api`
- `orchestrator`
- `scheduler`
- `market_data_ingest`
- `feed_verification`
- `feed_parity`
- `alerting`
- `artifact_registry`
- `auth`
- `observability`

### Canonical APIs to establish now

#### Feed management
- `POST /feeds`
- `PATCH /feeds/{feed_id}`
- `POST /feeds/{feed_id}/disable`
- `POST /feeds/{feed_id}/retire`
- `POST /feeds/{feed_id}/test_connectivity`
- `POST /feeds/{feed_id}/validate`
- `POST /feeds/{feed_id}/backfill`
- `GET /feeds`
- `GET /feeds/{feed_id}`
- `GET /feeds/{feed_id}/versions`

#### Data quality and certification
- `GET /data/coverage`
- `GET /data/anomalies`
- `GET /data/certifications`
- `POST /data/certifications/{dataset_version_id}/promote`
- `POST /data/certifications/{dataset_version_id}/quarantine`
- `GET /data/lineage/{symbol_or_id}`

#### Feed parity and health
- `GET /feed-health`
- `GET /feed-health/events`
- `GET /parity/events`
- `POST /parity/run`
- `GET /parity/policies`

#### Platform operations
- `GET /health`
- `GET /health/dependencies`
- `GET /queues`
- `GET /queues/contention`
- `GET /audit`
- `GET /artifacts/{artifact_id}`

## API rules of engagement

1. APIs must be versioned from day one.
2. No endpoint may return ambiguous IDs; every domain object gets a stable primary identifier plus version identifiers where needed.
3. Mutating operations must write immutable audit events.
4. Feed edits create new configuration versions; they do not rewrite history.
5. Certification changes must record actor, reason, and evidence.
6. Long-running work must run as jobs, not blocking requests.
7. Admin/operator endpoints must be permissioned separately from research-user endpoints.

## Data rules of engagement

- No raw feed should be treated as authoritative until it has a dataset version and certification state.
- No deleted feed may erase historical lineage.
- Any data repair must record its remediation method.
- Any parity disagreement above threshold must create a stored event.
- Symbol mapping lineage must be effective-dated.

## Technical acceptance gate for Phase 1 exit

Phase 1 is complete only when all of the following are true:

- a fresh developer machine can bring up the backend stack with Docker Compose
- services pass readiness checks and register dependencies correctly
- a user can create and version a feed configuration
- the platform can ingest sample data, detect gaps, and store certification state
- parity checks can compare two feeds and persist an event
- alerts fire for missing data and heartbeat failures
- every state-changing action is audit logged
- queue classes and compute policy objects exist, even if only Phase-1 jobs use them
- artifacts can be stored and retrieved with lineage metadata

## Suggested work breakdown

1. Runtime and infra skeleton
2. metadata store, migrations, and event ledger
3. auth/RBAC/secrets
4. feed registry and connectivity tests
5. ingest + verification + anomalies
6. certification + quarantine + lineage
7. parity service
8. alerts + observability
9. operator APIs and docs

## Deliverables

- running Dockerized backend stack
- platform environment contract document
- database schema/migrations
- feed registry service
- feed verification service
- feed parity service
- audit/event ledger implementation
- operator API reference
- observability baseline
- Phase 1 acceptance test pack
