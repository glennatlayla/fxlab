# FXLab Phase 1 — Implementation Workplan v3

## Revision Summary

**v3 changes over v2:**
- Added §3A: Session Continuity and Knowledge Management Protocol (progress, issues,
  lessons-learned files; cross-workplan knowledge sharing; mandatory pre-session checks).
- All other content (milestone ordering, domain model, specs, acceptance criteria, coding
  standards, definition of done) is unchanged from v2.

---

## 1. Mission

Implement Phase 1: Platform Foundation, Data Operations, and Containerized Runtime for FXLab
as the operational spine of the platform. The result must be a backend stack that can:

- run locally via Docker Compose,
- expose stable versioned APIs,
- manage versioned feed configurations,
- ingest sample market data,
- detect gaps and anomalies,
- create dataset versions with certification state,
- run feed parity checks and persist parity events,
- store/retrieve artifacts with lineage metadata,
- emit immutable audit events for every state change,
- provide RBAC-protected operator APIs,
- expose health, metrics, logs, alerts, and queue visibility.

**Out of scope:** strategy compilation, backtesting, optimization, UI-heavy workflows, broker execution.

---

## 2. Non-Negotiable Rules

These are mandatory across every milestone and are not repeated per-milestone. Treat violations
as build failures.

1. **Version everything that changes over time.** Feed edits create new `feed_config_version`
   rows. Datasets are immutable `dataset_version` objects. Certification changes are append-only
   events.
2. **No hidden contracts.** Shared request/response schemas live in `libs/contracts`.
   Service-to-service payloads are typed and documented.
3. **Long-running work is always a job.** Connectivity tests, validation, backfill, parity runs,
   and gap scans enqueue jobs and return `202 Accepted` plus a `job_id`.
4. **Every mutation writes an immutable audit event.** Include actor, action, target object,
   before/after summaries, correlation ID, reason, and evidence refs where applicable.
5. **Safe defaults only.** Uncertain feed state, failed dataset validation, missing secrets, or
   unhealthy dependencies → block or degrade.
6. **Correlation IDs everywhere.** Accept `X-Correlation-ID`; generate if absent. Propagate
   through API, workers, logs, jobs, alerts, audit, and artifacts.
7. **No history rewrites.** Retiring or disabling a feed never erases lineage or prior data.
   Any data repair records its remediation method.
8. **Idempotency on mutating operator APIs.** Support `Idempotency-Key` header. Prevent
   duplicate feed creation or repeated promote/quarantine actions.

---

## 3. CLAUDE.md Compliance Protocol

Every milestone must follow the CLAUDE.md agentic execution protocol. This section maps the
protocol to this workplan so there is no ambiguity.

### Per-milestone execution order

```
1. Read milestone spec below (STEP 1 — UNDERSTAND)
2. Identify layers: which contracts, services, repositories, controllers are touched
3. Write/verify interfaces in libs/contracts or service interfaces/ (STEP 2 — INTERFACE FIRST)
4. Write failing tests covering happy path + error paths + dependency failures (STEP 3 — RED)
5. Write minimal implementation to pass tests (STEP 4 — GREEN)
6. Run quality gate: format → lint → type-check → test with coverage (STEP 5 — QUALITY GATE)
7. Refactor, re-run gate (STEP 6 — REFACTOR)
8. Integration tests if I/O involved (STEP 7 — INTEGRATION)
9. Review checklist (STEP 8 — REVIEW)
```

### Onion architecture mapping for this project

| Layer               | FXLab location              | Owns                                                              |
|---------------------|-----------------------------|-------------------------------------------------------------------|
| Domain / Contracts  | `libs/contracts/`           | Pydantic models, enums, value objects, schemas                    |
| Service interfaces  | `libs/*/interfaces/`        | Abstract base classes for all services                            |
| Services            | `libs/feeds/`, `libs/datasets/`, `libs/audit/`, etc. | Business logic, orchestration        |
| Repository interfaces | `libs/*/interfaces/`      | Port definitions for DB, storage, queue                           |
| Repositories        | `libs/db/`, `libs/storage/` | SQLAlchemy repos, S3 adapter, Redis adapter                       |
| Controllers         | `services/api/routes/`      | FastAPI route handlers — no business logic                        |
| Infrastructure      | `infra/`, service `main.py` files | DI wiring, config, logging bootstrap                        |

**Dependency rule applies:** Controllers → Services (via interface) → Repositories (via
interface) → Domain. Never skip a layer. Never import concrete implementations into services.

---

## 3A. Session Continuity and Knowledge Management Protocol  ← NEW IN v3

This section is **mandatory for every development session**, whether automated or human-assisted.
Its purpose is to prevent repeated troubleshooting, lost context, and siloed knowledge across
milestones and across workplans (Phase 1 through Phase 4).

---

### 3A.1  Tracking File Naming Convention

Each workplan owns three companion tracking files. The `{workplan_name}` token is the
lower-kebab-case base name of the workplan file, without its `.md` extension.

| File                              | Purpose                              |
|-----------------------------------|--------------------------------------|
| `{workplan_name}.progress`        | Activity-level progress journal       |
| `{workplan_name}.issues`          | Numbered issue register               |
| `{workplan_name}.lessons-learned` | Numbered lessons-learned log          |

**Example** — for this workplan (`FXLab_Phase_1_workplan_v3.md`):

```
docs/workplan-tracking/
  FXLab_Phase_1_workplan_v3.progress
  FXLab_Phase_1_workplan_v3.issues
  FXLab_Phase_1_workplan_v3.lessons-learned
```

All three files live under `docs/workplan-tracking/` so the build menu system can discover them
without hardcoded paths. **Commit these files into version control** — they are project
artifacts, not ephemeral scratch space.

---

### 3A.2  Progress File — Format and Maintenance Rules

**Filename:** `{workplan_name}.progress`

**Purpose:** Single-source-of-truth for which milestone activities are complete, in-progress,
or not started. The build menu reads this file to resume from the last known position.

**Format:**

```
# Progress: FXLab Phase 1
# Workplan: FXLab_Phase_1_workplan_v3.md
# Last updated: 2025-01-15T14:32:00Z  (ISO-8601, UTC)
# Active milestone: M4
# Active step: STEP 4 — GREEN (implementing job lifecycle service)

[M0] Bootstrap                                            DONE
[M1] Docker Runtime                                       DONE
[M2] DB Schema + Migrations + Audit Ledger                DONE
[M3] Auth + RBAC                                          IN_PROGRESS
  [M3-S1] UNDERSTAND — reviewed auth spec                 DONE
  [M3-S2] INTERFACE FIRST — defined AuthService ABC      DONE
  [M3-S3] RED — wrote failing unit tests                  DONE
  [M3-S4] GREEN — writing JWT implementation              IN_PROGRESS  ← resume here
  [M3-S5] QUALITY GATE                                    NOT_STARTED
  [M3-S6] REFACTOR                                        NOT_STARTED
  [M3-S7] INTEGRATION                                     NOT_STARTED
  [M3-S8] REVIEW                                          NOT_STARTED
[M4] Jobs + Queue Classes + Compute Policy                NOT_STARTED
[M5] Artifact Registry + Storage Abstraction              NOT_STARTED
[M6] Feed Registry + Versioned Config + Connectivity      NOT_STARTED
[M7] Ingest Pipeline                                      NOT_STARTED
[M8] Verification + Gaps + Anomalies + Certification      NOT_STARTED
[M9] Symbol Lineage                                       NOT_STARTED
[M10] Parity Service                                      NOT_STARTED
[M11] Alerting + Observability Hardening                  NOT_STARTED
[M12] Operator API Docs + Acceptance Pack                 NOT_STARTED
```

**Valid status values:** `NOT_STARTED` | `IN_PROGRESS` | `DONE` | `BLOCKED` | `SKIPPED`

**Maintenance rules:**
- Update the progress file **at the end of every work step**, not just at the end of a milestone.
- `BLOCKED` must reference an open issue number from the issues file (e.g., `BLOCKED[ISS-003]`).
- The `# Active milestone` and `# Active step` header lines are what the build menu uses to
  resume execution. Keep them accurate.
- Never delete completed entries; the history of completion is part of the audit trail.

---

### 3A.3  Issues File — Format and Maintenance Rules

**Filename:** `{workplan_name}.issues`

**Purpose:** Numbered register of all outstanding and resolved problems encountered during
development. Prevents re-investigation of known problems and provides a quick escalation log.

**Format:**

```
# Issues: FXLab Phase 1
# Workplan: FXLab_Phase_1_workplan_v3.md
# Last updated: 2025-01-15T14:32:00Z

---
ISS-001
Title:      Alembic migrations fail on fresh Docker volume when PostgreSQL is not yet ready
Status:     RESOLVED
Milestone:  M2
Discovered: 2025-01-10T09:15:00Z
Resolved:   2025-01-10T11:45:00Z
Symptoms:   `alembic upgrade head` raises `psycopg2.OperationalError: connection refused`
            when run as a Docker Compose init container before the DB health check passes.
Root cause: The init container started before the PostgreSQL readiness probe completed,
            despite `depends_on: condition: service_healthy`.
Fix:        Added a `wait-for-it.sh` wrapper and explicit `pg_isready` poll loop in the
            migration init container entrypoint.
Lesson:     SEE LL-001 in lessons-learned file.

---
ISS-002
Title:      Redis 7 RESP3 protocol causes Celery 5.2 connection errors
Status:     WORKING
Milestone:  M4
Discovered: 2025-01-14T16:00:00Z
Resolved:   —
Symptoms:   Celery workers log `RESP3 not supported` and fail to consume the queue.
Root cause: Under investigation — possibly a celery-redis version pin mismatch.
Fix:        TBD — trying `celery==5.3.6` and `redis==5.0.1` pin.
Lesson:     —

---
ISS-003
Title:      MinIO presigned URL expiry too short for large backfill artifacts
Status:     IDENTIFIED
Milestone:  M5
Discovered: 2025-01-15T13:00:00Z
Resolved:   —
Symptoms:   Backfill artifacts (>2GB) uploaded via presigned URL fail with 403 after 15 min.
Root cause: Default presigned URL TTL is 600 seconds; large uploads exceed this.
Fix:        TBD
Lesson:     —
```

**Valid status values:** `IDENTIFIED` | `WORKING` | `RESOLVED`

**Maintenance rules:**
- Assign sequential `ISS-NNN` numbers; never reuse a number.
- Set status to `RESOLVED` only after the fix is confirmed by a passing test.
- Cross-reference resolved issues in the lessons-learned file.
- When a milestone is blocked by an issue, mark the progress entry as `BLOCKED[ISS-NNN]`.
- Do not delete resolved issues; they are a searchable knowledge base.

---

### 3A.4  Lessons-Learned File — Format and Maintenance Rules

**Filename:** `{workplan_name}.lessons-learned`

**Purpose:** Numbered log of lessons derived from troubleshooting. Captures the pattern of
the problem broadly enough to be useful across milestones and phases — not just the narrow
fix for one specific bug.

**Format:**

```
# Lessons Learned: FXLab Phase 1
# Workplan: FXLab_Phase_1_workplan_v3.md
# Last updated: 2025-01-15T14:32:00Z

---
LL-001
Title:      Docker Compose `depends_on: service_healthy` is not sufficient for DB migrations
Milestone:  M2
Source:     ISS-001
Lesson:     `depends_on: condition: service_healthy` only waits for the health check to pass
            once. Migration init containers must independently poll for DB readiness using
            `pg_isready` or a wait-for-it loop before attempting Alembic commands. This
            pattern should be applied to every init container that targets PostgreSQL, Redis,
            or MinIO.
Apply to:   All future phases wherever init containers or migration jobs target external stores.

---
LL-002
Title:      Pin celery and redis client versions together; test on upgrade
Milestone:  M4
Source:     ISS-002
Lesson:     Celery version and the redis Python client version have interdependencies that
            break silently on minor version bumps. Lock both in requirements.txt with a
            comment explaining the constraint. Any upgrade of either library must be tested
            end-to-end against the local Redis container before merging.
Apply to:   All future phases that use Celery workers.
```

**Maintenance rules:**
- Assign sequential `LL-NNN` numbers; never reuse a number.
- Write lessons at a level of generality that makes them useful beyond the specific incident.
- Every resolved issue should yield at least one lesson if any non-trivial investigation occurred.
- Include an `Apply to` field so future phases know which milestones should review this lesson.

---

### 3A.5  Mandatory Pre-Session Checks (START OF EVERY SESSION)

**Before writing any code in a session**, execute the following checks in order. This is
enforced by the build menu (`build.py`) at the project root.

```
CHECK 1 — Load this workplan's progress file.
  → Identify active milestone and active step.
  → If status is BLOCKED, look up the blocking issue before proceeding.

CHECK 2 — Scan this workplan's issues file for IDENTIFIED or WORKING issues.
  → If any WORKING issue affects the current milestone, address it first.
  → Do not start new step work while a WORKING issue in the current milestone is unresolved.

CHECK 3 — Scan this workplan's lessons-learned file.
  → Search for lessons with `Apply to` fields that match the current milestone.
  → Apply all matching lessons before writing any implementation.

CHECK 4 — Cross-workplan scan (see §3A.6).
  → Search all sibling workplan tracking files for lessons and issues that apply
    to the current milestone's technology or domain area.
  → Document any cross-workplan findings as notes in the progress file before starting.
```

The build menu will print any relevant issues and lessons to the terminal at session start.
A human or agent **must acknowledge** these findings before the session proceeds.

---

### 3A.6  Cross-Workplan Knowledge Sharing

FXLab has four phases, each with its own workplan. Knowledge must not be siloed.

**Discovery rule:** The build menu and any agent session must scan **all** tracking files
under `docs/workplan-tracking/` — not just the active workplan's files.

**Cross-workplan search targets:**

| When working on…            | Also check issues/lessons for…                    |
|-----------------------------|---------------------------------------------------|
| Database migrations (any)   | All phases — M2 equivalent steps                 |
| Docker / container runtime  | All phases — M1 equivalent steps                 |
| Queue/job infrastructure    | All phases — M4 equivalent steps                 |
| Authentication/RBAC         | All phases — M3 equivalent steps                 |
| Storage (MinIO/S3 adapter)  | All phases — M5 equivalent steps                 |
| Any external dependency     | All phases — look for matching service name       |

**When to write a cross-workplan issue:**
If an issue in Phase 1 is structural (e.g., a Docker compose networking pattern) and is
likely to recur in Phase 2, 3, or 4, add a note in the issue's `Fix` field:
`Cross-phase note: This pattern applies to Phase N workplan, milestone MX.`

**Shared lessons registry:**
In addition to per-workplan files, maintain a single shared file:

```
docs/workplan-tracking/SHARED_LESSONS.md
```

Promote any lesson to `SHARED_LESSONS.md` when its `Apply to` field references more than
one phase. The build menu displays `SHARED_LESSONS.md` content at startup regardless of
which workplan is active.

---

### 3A.7  Tracking File Bootstrap (First Session Only)

On the very first session for a workplan:

1. Create `docs/workplan-tracking/` if it does not exist.
2. Create the three tracking files with correct headers and all milestones listed as
   `NOT_STARTED`.
3. Create `docs/workplan-tracking/SHARED_LESSONS.md` if it does not exist (singleton across
   all phases).
4. Commit all four files before writing any implementation code.

The build menu (`build.py`) automates this bootstrap.

---

## 4. Default Technical Choices

Use these unless the repository already has hard constraints. If the repo already uses a
different but equivalent stack, preserve the repo stack and keep the contracts identical.

| Concern          | Choice                                                                           |
|------------------|----------------------------------------------------------------------------------|
| Language         | Python 3.12                                                                      |
| HTTP framework   | FastAPI                                                                          |
| Schemas          | Pydantic v2                                                                      |
| ORM              | SQLAlchemy 2.x                                                                   |
| Migrations       | Alembic                                                                          |
| Metadata DB      | PostgreSQL 16                                                                    |
| Object storage   | MinIO locally, S3-compatible abstraction in code                                 |
| Cache/queue broker | Redis 7                                                                        |
| Async jobs       | Celery with Redis broker/backend                                                 |
| Scheduled jobs   | APScheduler in dedicated scheduler service                                       |
| Logging          | structlog (JSON)                                                                 |
| Metrics          | Prometheus client                                                                |
| Tracing          | OpenTelemetry                                                                    |
| Local observability | Grafana + Prometheus + Loki in compose                                        |
| Alert routing    | Alertmanager-compatible webhook or internal router                               |
| Auth             | JWT bearer; local bootstrap impl; replaceable with OIDC later                   |
| Data processing  | Polars or PyArrow                                                                |
| Dataset format   | Parquet for bars, JSON manifests for metadata                                    |

---

## 5. Repository Target Shape

```
fxlab/
  services/
    api/                    # External HTTP API (controller layer)
    auth/                   # Auth token issuance, RBAC lookups
    orchestrator/           # Job creation, compute policy routing
    scheduler/              # Recurring task scheduling
    market_data_ingest/     # Feed adapter execution, normalization
    feed_verification/      # Validation, gap detection, anomaly detection
    feed_parity/            # Cross-feed comparison
    artifact_registry/      # Object storage registration and retrieval
    alerting/               # Alert evaluation, routing, delivery
    observability/          # Health probes, metrics, telemetry bootstrap
  libs/
    contracts/              # Pydantic models, enums, API schemas, error codes
    db/                     # SQLAlchemy models, base repo, session management
    authz/                  # Permission checking, JWT utilities
    storage/                # S3/MinIO abstraction
    feeds/                  # Feed management service logic
    datasets/               # Dataset version, certification, coverage logic
    audit/                  # Audit event writing, hash chaining
    jobs/                   # Job lifecycle, queue class, compute policy
    quality/                # Validation rules, gap detection, anomaly detection
    parity/                 # Parity comparison logic
    telemetry/              # Structured logging, correlation, metrics helpers
    utils/                  # Shared utilities (ULID generation, etc.)
  infra/
    compose/                # Docker Compose files
    docker/                 # Dockerfiles
    migrations/             # Alembic migrations
    observability/          # Grafana dashboards, Prometheus config, Loki config
  tests/
    unit/
    integration/
    acceptance/
    fixtures/               # Sample data files (clean, gapped, malformed, parity mismatch)
  docs/
    phases/
    api/
    adr/
    workplan-tracking/      # ← NEW: progress, issues, lessons-learned files for all workplans
      FXLab_Phase_1_workplan_v3.progress
      FXLab_Phase_1_workplan_v3.issues
      FXLab_Phase_1_workplan_v3.lessons-learned
      SHARED_LESSONS.md
```

---

## 6. Milestone Dependency Graph

```
M0: Bootstrap ──────────────────────────────────────────────────────────┐
  │                                                                     │
M1: Docker Runtime ─────────────────────────────────────────────────────┤
  │                                                                     │
M2: DB Schema + Migrations + Audit Ledger ──────────────────────────────┤
  │                                                                     │
M3: Auth + RBAC ────────────────────────────────────────────────────────┤
  │                                                                     │
M4: Jobs + Queue Classes + Compute Policy ──────────────────────────────┤  ← moved UP from M6
  │                                                                     │
M5: Artifact Registry + Storage Abstraction ────────────────────────────┤  ← moved DOWN from M4
  │                                                                     │
M6: Feed Registry + Versioned Config + Connectivity Tests ──────────────┤  ← was M5; now has jobs
  │                                                                     │
M7: Ingest Pipeline ────────────────────────────────────────────────────┤
  │                                                                     │
M8: Verification + Gaps + Anomalies + Certification ────────────────────┤
  │                                                                     │
M9: Symbol Lineage ─────────────────────────────────────────────────────┤
  │                                                                     │
M10: Parity Service ────────────────────────────────────────────────────┤
  │                                                                     │
M11: Alerting + Observability Hardening ────────────────────────────────┤
  │                                                                     │
M12: Operator API Docs + Acceptance Pack ───────────────────────────────┘
```

### Why jobs moved before artifacts and feeds

The original workplan placed "artifact registry" at M4 and "jobs/queues" at M6, but then M5
(feed registry) required connectivity tests that must run as jobs. In v2/v3:

- **M4 is jobs/queues/compute policy** — because feed connectivity tests, validation, backfill,
  parity, and ingest all require job infrastructure.
- **M5 is artifact registry** — because ingest (M7) needs to store raw and normalized artifacts.
- **M6 is feed registry** — because it can now use jobs for connectivity tests without a forward
  dependency.

### Parallel work opportunities

After M3 (auth) is complete, M4 (jobs) and M5 (artifacts) have no dependency on each other and
can be developed in parallel. M9 (symbol lineage) depends only on M2 and M7 and can be built
in parallel with M8 or M10.

---

## 7. Core Domain Model

Use ULIDs for all externally visible IDs.

### Tables/Entities

| Entity | Mutability | Key relationships |
|--------|-----------|-------------------|
| `users` | mutable (profile only) | has many `user_roles` |
| `roles` | seed data | has many `permissions` |
| `permissions` | seed data | — |
| `user_roles` | mutable | references `users`, `roles` |
| `service_accounts` | mutable | has role assignment |
| `feeds` | stable entity; lifecycle: draft → active → disabled → retired | has many `feed_config_versions` |
| `feed_config_versions` | append-only | references `feed_id`; stores provider type, symbol universe, cadence, market hours, connection metadata, validation policy, active flag |
| `dataset_versions` | immutable | references `feed_id`, `feed_config_version_id`; contains storage URI, checksum, row count, schema version, temporal coverage, status |
| `dataset_certification_events` | append-only; states: pending → certified → quarantined → superseded | references `dataset_version_id` |
| `dataset_coverage_segments` | derived | normalized coverage windows per symbol/timeframe/date range |
| `data_gap_events` | append-only | — |
| `data_anomaly_events` | append-only | — |
| `symbol_lineage` | effective-dated | source_symbol → canonical_symbol with effective_from/to, provenance, reason |
| `parity_policies` | mutable | left_feed_id, right_feed_id, tolerances, schedule |
| `parity_runs` | append-only | references policy |
| `parity_events` | append-only | references run |
| `artifacts` | metadata only | storage URI, content hash, media type, artifact type, lineage refs |
| `audit_events` | append-only, immutable; includes prev_hash and event_hash for tamper evidence | — |
| `jobs` | mutable (lifecycle states) | — |
| `job_attempts` | append-only | references `job_id` |
| `queue_classes` | seed data | — |
| `compute_policies` | mutable | references `queue_class` |
| `feed_health_events` | append-only | — |
| `service_health_snapshots` | append-only | — |
| `alerts` | mutable (ack/resolve) | — |
| `alert_deliveries` | append-only | references `alert_id` |
| `outbox_events` | transactional outbox for reliable async side effects | — |

### Enums (centralized in `libs/contracts/enums.py`)

`FeedLifecycleStatus`, `FeedConfigStatus`, `DatasetStatus`, `CertificationState`,
`GapSeverity`, `AnomalySeverity`, `ParityStatus`, `AlertSeverity`, `JobStatus`,
`QueueClass`, `PermissionCode`

---

## 8. Shared Contracts (libs/contracts)

Treat this package as a stable API boundary for later phases.

### Must-have schema families

`Feed`, `FeedConfigVersion`, `DatasetVersion`, `CertificationEvent`, `GapEvent`,
`AnomalyEvent`, `ParityRun`, `ParityEvent`, `ArtifactRecord`, `AuditEvent`, `JobRecord`,
`QueueClassRecord`, `ComputePolicy`, `HealthDependencyStatus`, `APIError`

### API response envelope

```python
# Success
{"data": ..., "meta": {"correlation_id": "...", "api_version": "v1"}, "error": null}

# Failure
{"data": null, "meta": {"correlation_id": "...", "api_version": "v1"},
 "error": {"code": "FEED_CONFIG_INVALID", "message": "Human readable", "details": {...}}}
```

---

## 9. Feed Adapter Contract

```python
class FeedProviderAdapter(Protocol):
    def test_connectivity(self, config: FeedConfigVersion) -> ConnectivityResult: ...
    def validate_config(self, config: FeedConfigVersion) -> ValidationResult: ...
    def heartbeat(self, config: FeedConfigVersion) -> HeartbeatResult: ...
    def backfill(self, request: BackfillRequest) -> BackfillResult: ...
    def fetch_sample(self, request: FetchSampleRequest) -> SampleResult: ...
    def normalize_batch(self, raw_object_uri: str) -> NormalizedDatasetResult: ...
```

### Phase 1 adapters

| Adapter | Purpose |
|---------|---------|
| `LocalFileFeedAdapter` | Reads CSV/JSON/Parquet fixtures for deterministic acceptance testing |
| `HTTPPollingFeedAdapter` | Minimal skeleton with connectivity test and request plumbing |

---

## 10. Market Data Normalization Contract

### Canonical bar schema

`canonical_symbol`, `source_symbol`, `venue`, `asset_class`, `timeframe`, `ts`, `open`,
`high`, `low`, `close`, `volume`, `trade_count` (nullable), `vwap` (nullable), `feed_id`,
`feed_config_version_id`, `ingest_run_id`

### Validation rules (reject or quarantine)

Null timestamps, duplicate `(canonical_symbol, timeframe, ts)`, `high < low`, `open` or
`close` outside `[low, high]`, negative volume, out-of-order timestamps within a partition,
unsupported timeframe, schema mismatch, empty batch where data was expected.

---

## 11. Artifact and Dataset Storage Conventions

### Raw landing objects
```
raw/{feed_id}/{feed_config_version_id}/{ingest_run_id}/payload.jsonl.gz
```

### Normalized dataset objects
```
datasets/{dataset_version_id}/manifest.json
datasets/{dataset_version_id}/bars/part-000.parquet
datasets/{dataset_version_id}/quality_report.json
```

### Artifact keys
```
artifacts/{artifact_type}/{artifact_id}/{sha256}.{ext}
```

### Required artifact metadata fields

`artifact_id`, `artifact_type`, `storage_uri`, `media_type`, `sha256`, `size_bytes`,
`created_at`, `created_by`, `source_object_type`, `source_object_id`, `source_version_id`,
`correlation_id`, `tags`, `metadata_json`

---

## 12. Parity Model

### parity_policies fields

`policy_id`, `name`, `left_feed_id`, `right_feed_id`, `timeframe`, `symbol_scope`,
`lookback_window`, per-field tolerances (`open_tolerance`, `high_tolerance`,
`low_tolerance`, `close_tolerance`, `volume_tolerance_pct`), `breach_threshold_pct`,
`schedule_cron` (nullable), `enabled`

### Parity execution logic

Compare overlapping normalized bars → compute absolute and percentage deltas → summarize
missing-on-left/missing-on-right counts → persist sampled mismatches → if breach threshold
exceeded, create `parity_event` → route alert for critical breaches.

---

## 13. Auth, Secrets, and RBAC

### Roles to seed

`platform_admin`, `operator`, `research_user`, `viewer`, `service_account`

### Permission groups

`feed.read`, `feed.write`, `feed.disable`, `feed.retire`, `feed.test_connectivity`,
`feed.validate`, `feed.backfill`, `data.read`, `data.certify`, `data.quarantine`,
`data.lineage.read`, `parity.read`, `parity.run`, `queue.read`, `audit.read`,
`artifact.read`, `platform.health.read`, `admin.manage`

### Secrets rules

- Never store raw credentials in plaintext DB fields.
- Use environment-injected master key to encrypt secret payloads at rest.
- Separate feed config metadata from credential material.
- Redact secrets from logs, audit records, and API responses.

---

## 14. Observability Baseline

### Structured log fields (every line)

`timestamp`, `level`, `service`, `environment`, `correlation_id`, `job_id` (nullable),
`actor_id` (nullable), `feed_id` (nullable), `dataset_version_id` (nullable), `event_type`

### Prometheus metrics to expose

Request count/latency/error rate, job queue depth, job duration, dataset ingest count,
gap/anomaly counts, parity run count and breach count, heartbeat lag, alert count,
dependency health state.

### Health endpoints

`GET /health` (local service status), `GET /health/dependencies` (checks DB, Redis, MinIO,
and service-specific deps).

### Alerts to implement in Phase 1

Feed heartbeat stale, dataset validation failed, data gap above threshold, parity breach
above threshold, dependency unhealthy, artifact store unavailable.

---

## 15. Required API Surface

All endpoints under `/api/v1`.

### Feed management
`POST /feeds`, `PATCH /feeds/{feed_id}`, `POST /feeds/{feed_id}/disable`,
`POST /feeds/{feed_id}/retire`, `POST /feeds/{feed_id}/test_connectivity`,
`POST /feeds/{feed_id}/validate`, `POST /feeds/{feed_id}/backfill`,
`GET /feeds`, `GET /feeds/{feed_id}`, `GET /feeds/{feed_id}/versions`

### Data quality and certification
`GET /data/coverage`, `GET /data/anomalies`, `GET /data/certifications`,
`POST /data/certifications/{dataset_version_id}/promote`,
`POST /data/certifications/{dataset_version_id}/quarantine`,
`GET /data/lineage/{symbol_or_id}`

### Feed parity and health
`GET /feed-health`, `GET /feed-health/events`, `GET /parity/events`,
`POST /parity/run`, `GET /parity/policies`

### Platform operations
`GET /health`, `GET /health/dependencies`, `GET /queues`, `GET /queues/contention`,
`GET /audit`, `GET /artifacts/{artifact_id}`

### Supporting endpoints
`GET /jobs/{job_id}`, `GET /jobs`, `POST /auth/login`, `GET /auth/me`

---

## 16–18. [Milestone Specifications M0–M12 — unchanged from v2]

> The milestone-by-milestone specifications (M0 through M12) are structurally identical to
> v2. Reproduce them verbatim from `FXLab_Phase_1_workplan_v2.md` §§ milestone sections.
> Each milestone spec now has one additional **pre-work step** prepended:
>
> **PRE: Run §3A.5 pre-session checks. Confirm no BLOCKING issues and no unread lessons
> that apply to this milestone before writing any code.**

---

## 19. Acceptance Test Pack

Implement as automated integration/acceptance tests, not manual steps.

**A.** `docker compose up` from clean state; migrations run; health endpoints green.
**B.** Create feed → patch → assert new version → disable → retire → assert no history loss.
**C.** Connectivity test job → validate config → assert stored results and audit events.
**D.** Backfill sample feed → assert raw artifact → normalized dataset → dataset version.
**E.** Ingest gapped sample → assert gap event. Ingest malformed sample → assert anomaly event.
**F.** Promote clean dataset → quarantine bad dataset → assert actor/reason/evidence/audit.
**G.** Ingest two mismatched datasets → parity run → assert breach event.
**H.** Simulate stale heartbeat → assert alert. Simulate dependency failure → assert alert.
**I.** Retrieve artifact metadata by ID → verify checksum and lineage fields.
**J.** Unauthorized → 401. Insufficient role → 403. Admin separation enforced.

---

## 20. Test Fixtures to Seed

| Fixture                      | Purpose                                                        |
|------------------------------|----------------------------------------------------------------|
| `clean_ohlcv.csv`            | Normal well-formed OHLCV data for happy-path ingest            |
| `gapped_ohlcv.csv`           | Data with intentional time gaps for gap detection tests        |
| `malformed_ohlcv.csv`        | Data with `high < low`, negative volume, null timestamps       |
| `parity_left.csv`            | First feed for parity comparison                               |
| `parity_right_mismatch.csv`  | Second feed with controlled price/volume differences           |
| `parity_right_clean.csv`     | Second feed identical to left for clean parity test            |

---

## 21. Coding Standards

- Prefer small, composable service methods.
- Keep business logic out of route handlers.
- Put all schema definitions in `libs/contracts`.
- Put all DB writes behind repositories/services with transaction boundaries.
- Use typed exceptions and map them to stable API error codes.
- Add structured debug logs at: job start/end, external dependency calls, state transitions,
  failure paths.
- Make jobs idempotent where possible.
- Use retry only for transient failures, never for validation errors.
- Redact secrets from logs and traces.
- Write tests alongside each milestone, not afterward.

---

## 22. What Not To Do

- Do not collapse all services into one monolithic module without preserving service boundaries.
- Do not store datasets only in memory or only as local files.
- Do not use mutable feed configs (always append new versions).
- Do not perform parity/validation inline in HTTP requests (always jobs).
- Do not skip audit logging because "it's just Phase 1."
- Do not hardcode vendor-specific assumptions into the core feed abstraction.
- Do not build Phase 2 strategy features early.
- Do not expose admin endpoints without permission checks.
- Do not use Celery's default retry behavior — always use the compute policy model.
- **Do not start a new session without running §3A.5 pre-session checks.** ← NEW in v3
- **Do not resolve an issue without writing a lesson-learned entry.** ← NEW in v3

---

## 23. Phase 1 Definition of Done

Phase 1 is done only when **all** of the following are true:

1. Fresh local environment starts with `docker compose up`.
2. Services report readiness and dependency health.
3. Feed configs are versioned (edits create new versions, history preserved).
4. Sample data ingest works end to end (raw → normalized → dataset_version).
5. Gap/anomaly detection persists events.
6. Certification promote/quarantine works with full audit lineage.
7. Parity runs persist results and events.
8. Alerts fire for stale heartbeat and missing data.
9. Artifacts are stored and retrievable with lineage metadata.
10. Queue classes and compute policies exist and are visible.
11. Every mutation is audit logged with hash-chained tamper evidence.
12. Operator APIs are documented and covered by automated acceptance tests.
13. **All milestones show `DONE` in the `.progress` file.** ← NEW in v3
14. **All `IDENTIFIED` and `WORKING` issues are `RESOLVED`.** ← NEW in v3
15. **Every resolved issue has a corresponding lessons-learned entry.** ← NEW in v3

This definition comes directly from the Phase 1 exit gate in the spec and is release-blocking.
