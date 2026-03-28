# FXLab Phase 3 — Milestone 13: Infrastructure Completion and Gap Fill
# Source: Audit of distilled M0–M12 against FXLab_Phase_3_workplan_v1_1.md
# Created: 2026-03-28
# Prerequisite: All distilled M0–M12 steps marked DONE in progress file

---

## AUDIT FINDINGS — M0–M12 vs Spec

This section records every gap discovered. M13 closes all of them before the
frontend track (M22–M31) may begin.

### M0 — Bootstrap: PARTIAL

| Item | Status | Evidence |
|---|---|---|
| docker-compose.yml with api, web, postgres, redis | ✅ | File exists, services wired |
| frontend/ directory and src stubs | ✅ | All 9 page stubs, router.tsx, App.tsx |
| services/api/Dockerfile | ❌ **MISSING** | Referenced in docker-compose; file does not exist |
| frontend/Dockerfile | ❌ **MISSING** | Referenced in docker-compose; file does not exist |
| exports.py registered in main.py | ❌ **MISSING** | Stub file exists; not in include_router list |
| research.py registered in main.py | ❌ **MISSING** | Stub file exists; not in include_router list |
| governance.py registered in main.py | ❌ **MISSING** | Stub file exists; not in include_router list |
| services/api/routes/charts.py stub exists | ✅ | Full implementation exists |
| services/api/routes/queues.py stub exists | ✅ | Full implementation exists |
| services/api/routes/feed_health.py stub exists | ✅ | Full implementation exists |

### M1 — Docker Runtime: BROKEN

| Item | Status | Evidence |
|---|---|---|
| Docker Compose brings up api service | ❌ **BROKEN** | services/api/Dockerfile missing — build fails |
| Docker Compose brings up web service | ❌ **BROKEN** | frontend/Dockerfile missing — build fails |
| postgres and redis services configured | ✅ | Defined in docker-compose.yml |
| Health checks on all services | ✅ | Defined in docker-compose.yml |
| FastAPI responds to GET /health | ✅ | /health endpoint in health.py |
| services/api restart policy | ✅ | `restart: unless-stopped` in compose |

**Docker cannot build without the two missing Dockerfiles. M1 is functionally broken.**

### M2 — DB Schema + Migrations + Audit Ledger: PARTIAL

| Item | Status | Evidence |
|---|---|---|
| libs/contracts/models.py (SQLAlchemy models) | ✅ | File exists |
| libs/contracts/audit.py (AuditEvent schema) | ✅ | File exists |
| libs/contracts/database.py | ✅ | File exists |
| Alembic migration files | ❌ **MISSING** | `find alembic/versions/*.py` → 0 files |
| services/api/db.py (engine, session, get_db) | ❌ **MISSING** | File does not exist anywhere in services/ |
| All tables support ULID PKs | ✅ | Models validated in test_m2_db_schema.py |
| Audit ledger table with JSONB metadata | ✅ | Defined in models.py |

**No Alembic migration files exist. The M2 spec required a migration-based schema management approach. Tests run against SQLite in-memory; no schema upgrade path exists for PostgreSQL.**

**db.py is missing: no engine factory, no get_db FastAPI dependency. SQL wiring (M13-T3) cannot proceed without it.**

### M3 — Auth + RBAC: PARTIAL

| Item | Status | Evidence |
|---|---|---|
| libs/authz/interfaces/rbac.py | ✅ | File exists |
| libs/authz/mocks/mock_rbac.py | ✅ | File exists |
| services/api/dependencies.py (mock RBAC DI) | ✅ | File exists, uses mock RBAC |
| Real JWT/OIDC implementation | ❌ **MISSING** | No jwt/oidc files in authz/ |
| POST /approvals/{id}/approve | ✅ | In approvals.py |
| POST /approvals/{id}/reject | ❌ **MISSING** | Not in approvals.py; only /approve exists |
| POST /overrides/request | ❌ **MISSING** | No overrides.py exists anywhere |
| GET /overrides/{id} | ❌ **MISSING** | No overrides.py exists anywhere |
| M3 spec referenced these endpoints as interface contracts | — | See distilled M3 §Interface Contracts |

### M4 — Jobs + Queue Classes + Compute Policy: PARTIAL

| Item | Status | Evidence |
|---|---|---|
| libs/jobs/interfaces/{job.py, queue.py} | ✅ | Files exist |
| libs/jobs/mocks/{mock_job_repository.py, mock_queue_service.py} | ✅ | Files exist |
| Celery worker configuration (celery_app.py) | ❌ **MISSING** | No celery_app.py anywhere |
| Compute policy implementation | ❌ **MISSING** | Interface only; no concrete policy class |
| Queue class definitions (research, optimize, etc.) | ⚠️ PARTIAL | Defined in contracts/enums.py; not wired to worker |

**No Celery worker exists. Queue contention endpoints (ISS-017) return mock data because no real Celery inspect integration has been built.**

### M5 — Artifact Registry + Storage Abstraction: DONE with open issues

| Item | Status | Evidence |
|---|---|---|
| GET /artifacts | ✅ | Implemented in artifacts.py |
| GET /artifacts/{artifact_id}/download | ✅ | Implemented with Content-Type negotiation |
| libs/contracts/interfaces/artifact_repository.py | ✅ | File exists |
| libs/contracts/mocks/mock_artifact_repository.py | ✅ | File exists |
| LocalArtifactStorage, MinIOArtifactStorage classes | ✅ | In libs/storage/ |
| SqlArtifactRepository | ❌ **ISS-011** | No SQL implementation; mock used in production |
| MinIOArtifactStorage wired to DI | ❌ **ISS-012** | LocalArtifactStorage stub wired instead |

### M6 — Feed Registry + Versioned Config + Connectivity Tests: DONE with open issues

| Item | Status | Evidence |
|---|---|---|
| GET /feeds | ✅ | Implemented in feeds.py |
| GET /feeds/{feed_id} | ✅ | Implemented in feeds.py |
| GET /feed-health | ✅ | Implemented in feed_health.py |
| SqlFeedRepository | ❌ **ISS-013** | Mock only in production |
| SqlFeedHealthRepository | ❌ **ISS-014** | Mock only in production |

### M7 — Chart + LTTB + Queue Backend APIs: DONE with open issues

| Item | Status | Evidence |
|---|---|---|
| GET /runs/{run_id}/charts | ✅ | Implemented in charts.py |
| GET /runs/{run_id}/charts/equity | ✅ | LTTB applied, sampling_applied flag set |
| GET /runs/{run_id}/charts/drawdown | ✅ | Implemented in charts.py |
| libs/utils/lttb.py | ✅ | File exists |
| GET /queues/ | ✅ | Implemented in queues.py |
| GET /queues/{queue_class}/contention | ✅ | Implemented in queues.py |
| chart_cache_entries table/migration | ❌ **ISS-016** | Migration file missing; no SQL impl |
| SqlChartRepository (write-through cache) | ❌ **ISS-016** | Mock only in production |
| CeleryQueueRepository | ❌ **ISS-017** | Mock only; no Celery inspect integration |

### M8 — Verification + Gaps + Anomalies + Certification: DONE with open issues

| Item | Status | Evidence |
|---|---|---|
| GET /data/certification | ✅ | Implemented in data_certification.py |
| GET /parity/events | ✅ | Implemented in parity.py |
| GET /parity/events/{parity_event_id} | ✅ | Implemented in parity.py |
| GET /parity/summary | ✅ | Implemented in parity.py |
| SqlCertificationRepository | ❌ **ISS-019** | Mock only in production |
| SqlParityRepository | ❌ **ISS-020** | Mock only in production |

### M9 — Symbol Lineage & Audit Explorer Backend: DONE with open issues

| Item | Status | Evidence |
|---|---|---|
| GET /audit | ✅ | Implemented in audit.py |
| GET /audit/{audit_event_id} | ✅ | Implemented in audit.py |
| GET /symbols/{symbol}/lineage | ✅ | Implemented in symbol_lineage.py |
| SqlAuditExplorerRepository | ❌ **ISS-021** | Mock only in production |
| SqlSymbolLineageRepository | ❌ **ISS-022** | Mock only in production |

### M10 — Parity Service Extended: DONE with open ISS-020 (same as M8)

### M11 — Alerting + Observability: DONE with open issues

| Item | Status | Evidence |
|---|---|---|
| GET /health/dependencies | ✅ | Implemented in observability.py |
| GET /health/diagnostics | ✅ | Implemented in observability.py |
| RealDependencyHealthRepository | ❌ **ISS-024** | Mock only in production |
| SqlDiagnosticsRepository | ❌ **ISS-025** | Mock only in production |

### M12 — Operator API Docs + Acceptance Pack: DONE

| Item | Status | Evidence |
|---|---|---|
| docs/api/ACCEPTANCE_PACK.md | ✅ | 733-line operator API reference |
| tests/acceptance/test_m12_acceptance_pack.py | ✅ | 40 acceptance tests, all passing |

---

## COMPLETE GAP SUMMARY

### Category 1 — Infrastructure (blocks Docker build and SQL wiring)
| ID | Gap | Severity |
|---|---|---|
| G-01 | services/api/Dockerfile missing | 🔴 CRITICAL — Docker cannot build |
| G-02 | frontend/Dockerfile missing | 🔴 CRITICAL — Docker cannot build |
| G-03 | Alembic migrations directory missing — 0 migration files | 🔴 CRITICAL — no schema management |
| G-04 | services/api/db.py missing — no engine/session/get_db | 🔴 CRITICAL — SQL wiring cannot proceed |

### Category 2 — Missing Governance Endpoints (blocks M23 completion and M29 frontend)
| ID | Gap | Issue |
|---|---|---|
| G-05 | POST /approvals/{id}/reject missing | — |
| G-06 | POST /overrides/request missing (no overrides.py) | — |
| G-07 | GET /overrides/{id} missing | — |
| G-08 | POST /strategies/draft/autosave missing | — |
| G-09 | GET /strategies/draft/autosave/latest missing | — |
| G-10 | DELETE /strategies/draft/autosave/{id} missing | — |
| G-11 | evidence_link URI validation missing on override requests | — |
| G-12 | Separation-of-duties enforcement missing at service layer | — |
| G-13 | Override watermark creation on override approval missing | — |
| G-14 | draft_autosaves table + migration missing | — |

### Category 3 — SQL Repository Implementations (open issues)
| ID | Gap | Issue |
|---|---|---|
| G-15 | SqlArtifactRepository not implemented | ISS-011 |
| G-16 | MinIOArtifactStorage not wired to DI | ISS-012 |
| G-17 | SqlFeedRepository not implemented | ISS-013 |
| G-18 | SqlFeedHealthRepository not implemented | ISS-014 |
| G-19 | SqlChartRepository not implemented (incl. write-through cache) | ISS-016 |
| G-20 | CeleryQueueRepository not implemented | ISS-017 |
| G-21 | SqlCertificationRepository not implemented | ISS-019 |
| G-22 | SqlParityRepository not implemented | ISS-020 |
| G-23 | SqlAuditExplorerRepository not implemented | ISS-021 |
| G-24 | SqlSymbolLineageRepository not implemented | ISS-022 |
| G-25 | RealDependencyHealthRepository not implemented | ISS-024 |
| G-26 | SqlDiagnosticsRepository not implemented | ISS-025 |

### Category 4 — Router Registration and Stub Cleanup
| ID | Gap | Severity |
|---|---|---|
| G-27 | exports.py stub not registered in main.py | 🟡 MEDIUM |
| G-28 | research.py stub not registered in main.py | 🟡 MEDIUM |
| G-29 | governance.py stub not registered in main.py | 🟡 MEDIUM |
| G-30 | strategies.py is a stub (GET "/" only) — no real strategy endpoints | 🟡 MEDIUM |

---

## MILESTONE 13: Infrastructure Completion and Backend Gap Fill

### Objective

Bring the backend to a production-ready, fully-wired state before the frontend track begins.
Every mock repository must have a SQL-backed counterpart. Every governance endpoint specified
in the source workplan M23 must exist. Docker must build. The DB must have an Alembic-managed
schema. No frontend work (M22–M31) may begin until M13 acceptance criteria are all green.

### Dependency Order Within M13

```
T1 (Infrastructure) → T2 (Governance Endpoints) → T3 (SQL Repositories) → T4 (Router Cleanup)
     ↑
T1 must be complete before T3 (SQL wiring requires db.py and migration-managed schema).
T2 may develop in parallel with T1 (governance endpoints use mock repos initially).
T3 requires T1 and T2 (SQL repos replace mocks; governance tables need migrations).
T4 may run at any point but should be last before acceptance tests.
```

---

## M13 — Track 1: Infrastructure Completion (G-01 through G-04)

### Deliverables

#### 1. services/api/Dockerfile

```dockerfile
# Minimal reference spec — implementation must follow
FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY services/ ./services/
COPY libs/ ./libs/
EXPOSE 8000
CMD ["uvicorn", "services.api.main:app", "--host", "0.0.0.0", "--port", "8000"]
```

Requirements:
- Multi-stage build (builder + runtime) preferred for size
- Non-root user
- `HEALTHCHECK` directive matching docker-compose expectation (`GET /health`)
- `--reload` gated behind `ENVIRONMENT=development` env var

#### 2. frontend/Dockerfile

```dockerfile
# Reference spec — implementation must follow
FROM node:20-alpine AS builder
WORKDIR /app
COPY package*.json ./
RUN npm ci
COPY . .
RUN npm run build

FROM nginx:alpine
COPY --from=builder /app/dist /usr/share/nginx/html
EXPOSE 3000
```

Requirements:
- Two-stage: build then nginx serve
- Port 3000 (matches docker-compose)
- nginx.conf must proxy `/api/*` to `http://api:8000/*` for same-origin API calls

#### 3. Alembic migration scaffold + initial migration

Files required:
- `alembic.ini` at project root
- `migrations/env.py` — imports `libs.contracts.models.Base`
- `migrations/versions/` directory
- Initial migration `001_initial_schema.py` covering all tables currently in `libs/contracts/models.py`:
  - users, strategies, strategy_versions, runs, run_results, audit_events, feeds, feed_versions,
    feed_connectivity_tests, feed_health_snapshots, artifacts, parity_events, certification_events,
    symbol_lineage_entries, queue_snapshots, chart_cache_entries (placeholder — empty table OK)

Migration must:
- Upgrade and downgrade cleanly on empty PostgreSQL database
- Run `alembic upgrade head` without error in a Docker environment
- Be idempotent (running twice does not fail)

#### 4. services/api/db.py

```python
# Required exports
engine: Engine               # SQLAlchemy engine from DATABASE_URL env var
SessionLocal: sessionmaker   # Session factory
Base: DeclarativeBase        # Re-exported from libs.contracts.models

def get_db() -> Generator[Session, None, None]:
    """FastAPI dependency that yields a database session and closes it after use."""
    ...
```

Requirements:
- Reads `DATABASE_URL` from environment (falls back to SQLite in-memory for tests)
- Session scoped to request (yield pattern)
- Connection pool configured for production (pool_size=5, max_overflow=10)
- `check_same_thread=False` for SQLite only

### Acceptance Criteria — Track 1

- [ ] `docker-compose build` exits 0 — no missing Dockerfile errors
- [ ] `docker-compose up --wait` brings all four services to healthy state
- [ ] `GET http://localhost:8000/health` returns 200 from within Docker network
- [ ] `GET http://localhost:3000` returns 200 (nginx serves frontend build)
- [ ] `alembic upgrade head` runs without error on empty PostgreSQL container
- [ ] `alembic downgrade base` runs without error after upgrade
- [ ] `from services.api.db import get_db, engine, SessionLocal` imports without error
- [ ] Integration test `test_m1_docker_runtime.py` passes (currently existing Docker tests)

---

## M13 — Track 2: Governance Endpoint Completion (G-05 through G-14)

### Deliverables

#### 1. POST /approvals/{id}/reject

File: `services/api/routes/approvals.py` (extend existing)

```
POST /approvals/{approval_id}/reject
Body: { "rationale": str (required, non-empty) }
Response: { "approval_id": str, "status": "rejected", "rationale": str }
```

- Validate `rationale` is non-empty string; return 422 if blank
- Emit audit event: `action="approval_rejected"`, `target_id=approval_id`
- Return 404 for unknown approval_id
- Test coverage: happy path, missing rationale (422), unknown ID (404)

#### 2. services/api/routes/overrides.py (new file)

```
POST /overrides/request
Body: OverrideRequest {
    governance_gate: str (required)
    target_object_id: str (ULID, required)
    target_object_type: str (required)
    rationale: str (required, non-empty)
    evidence_link: str (required, must be absolute HTTP/HTTPS URI with path)
}
Response: { "override_request_id": str, "status": "pending" }

GET /overrides/{override_id}
Response: OverrideDetail {
    override_request_id, governance_gate, target_object_id,
    status, rationale, evidence_link, submitter_id,
    watermark_id (if approved), decision_rationale (if decided),
    created_at, updated_at
}
```

**evidence_link validation rules (from source workplan M23):**
- Must be an absolute URL (starts with `http://` or `https://`)
- Must contain a non-root path (e.g. `https://jira.example.com/browse/TICKET-123`)
- `https://jira.example.com` alone (no path beyond `/`) → 422
- Missing or empty → 422 with field-level error
- Use Pydantic validator on `OverrideRequest.evidence_link`

**Separation-of-duties:**
- `POST /overrides/request` records `submitter_id` from auth context (use mock RBAC submitter)
- A future approve/reject endpoint must reject if `approver_id == submitter_id`
- Add `submitter_id` field to override request contract

**Override watermark:**
- When `POST /overrides/{id}/approve` is called (future endpoint, stub for now):
  create an `OverrideWatermark` record linking the override to the target object
- Stub the watermark in the mock implementation for now

#### 3. Draft autosave endpoints

File: `services/api/routes/strategies.py` (extend existing stub)

```
POST /strategies/draft/autosave
Body: { "draft_payload": dict, "strategy_id": str (optional ULID) }
Response: { "autosave_id": str (ULID), "created_at": str }

GET /strategies/draft/autosave/latest
Query params: none (user inferred from auth context)
Response: { "autosave_id": str, "draft_payload": dict, "created_at": str }
          OR { "autosave_id": null } if no draft within 30-day window

DELETE /strategies/draft/autosave/{autosave_id}
Response: { "success": true }
```

Contract: `libs/contracts/governance.py` — add `DraftAutosave`, `DraftAutosaveResponse` schemas

#### 4. libs/contracts/governance.py additions

Add to existing governance contracts:
- `OverrideRequest` Pydantic model with `evidence_link` validator
- `OverrideDetail` response model
- `DraftAutosave` model
- `DraftAutosaveResponse` model
- `ApprovalRejectRequest` model (rationale field)

#### 5. Register overrides.py in main.py

```python
app.include_router(overrides.router, prefix="/overrides", tags=["overrides"])  # M13-T2
```

#### 6. Register strategies with updated router

Extend `strategies.py` with draft autosave endpoints and re-register properly.

### Acceptance Criteria — Track 2

- [ ] `POST /approvals/{id}/reject` returns 200 with `status: "rejected"` for valid payload
- [ ] `POST /approvals/{id}/reject` returns 422 when `rationale` is empty or missing
- [ ] `POST /approvals/{id}/reject` returns 404 for unknown approval_id
- [ ] `POST /overrides/request` returns 202 for valid payload with full-path evidence_link
- [ ] `POST /overrides/request` returns 422 when `evidence_link` is missing
- [ ] `POST /overrides/request` returns 422 when `evidence_link` is a root URL (no path)
- [ ] `POST /overrides/request` returns 422 when `evidence_link` is not HTTP/HTTPS
- [ ] `GET /overrides/{id}` returns 200 with full OverrideDetail for known override
- [ ] `GET /overrides/{id}` returns 404 for unknown override_id
- [ ] `POST /strategies/draft/autosave` returns 201 with autosave_id ULID
- [ ] `GET /strategies/draft/autosave/latest` returns most recent draft for user
- [ ] `GET /strategies/draft/autosave/latest` returns `{ autosave_id: null }` when no draft
- [ ] `DELETE /strategies/draft/autosave/{id}` returns 200 and removes draft
- [ ] `/overrides` prefix registered and visible in `GET /openapi.json`
- [ ] Unit tests: ≥ 25 tests covering all above behaviours
- [ ] Service layer coverage ≥ 90% for governance module

---

## M13 — Track 3: SQL Repository Implementations (ISS-011 through ISS-025)

### Prerequisites
- T1 complete (db.py exists, Alembic migrations exist, schema on PostgreSQL)
- Integration test environment can reach PostgreSQL (docker-compose up)

### Pattern for all SQL repositories

Each SQL repository must:
1. Extend the existing interface (e.g. `ArtifactRepositoryInterface`)
2. Accept a `Session` in `__init__` (injected by DI container)
3. Implement all abstract methods — no `pass` or `raise NotImplementedError`
4. Map domain models to SQLAlchemy ORM models via `_to_domain()` and `_from_domain()` helpers
5. Raise `NotFoundError` (from `libs/contracts/errors.py`) for missing records
6. Have an integration test file that runs against a real PostgreSQL session

### Deliverables by issue

#### ISS-011: SqlArtifactRepository

File: `services/api/repositories/sql_artifact_repository.py`

Implements: `ArtifactRepositoryInterface`
Operations: `find_by_id`, `save`, `list`, `delete`
ORM model: `libs.contracts.models.Artifact`

Wire: Update `get_artifact_repository()` DI provider in `artifacts.py` to instantiate
`SqlArtifactRepository(db=next(get_db()))` when `ENVIRONMENT != "test"`.

Integration test: `tests/integration/test_m13_sql_artifact_repository.py`

#### ISS-012: MinIOArtifactStorage DI Wiring

File: Update `get_artifact_storage()` in `artifacts.py`

Logic:
```python
def get_artifact_storage() -> ArtifactStorageBase:
    bucket = os.environ.get("ARTIFACT_BUCKET", "")
    endpoint = os.environ.get("MINIO_ENDPOINT", "")
    if bucket and endpoint:
        return MinIOArtifactStorage(bucket=bucket, endpoint=endpoint, ...)
    return LocalArtifactStorage(base_path=os.environ.get("ARTIFACT_LOCAL_PATH", "/tmp/fxlab"))
```

#### ISS-013: SqlFeedRepository

File: `services/api/repositories/sql_feed_repository.py`
Implements: `FeedRepositoryInterface`
Operations: `find_by_id`, `list`, `save`, `get_feed_detail`
Wire: Update `get_feed_repository()` in `feeds.py`

#### ISS-014: SqlFeedHealthRepository

File: `services/api/repositories/sql_feed_health_repository.py`
Implements: `FeedHealthRepositoryInterface`
Operations: `get_health_list`, `get_health_report`
Wire: Update `get_feed_health_repository()` in `feed_health.py`

#### ISS-016: SqlChartRepository (with write-through cache)

File: `services/api/repositories/sql_chart_repository.py`
Implements: `ChartRepositoryInterface`
Operations: `find_by_run_id`, `save_cache`, `get_cached`

Write-through caching logic (from source workplan M24):
- On first chart request for a completed run: compute charts, save to `chart_cache_entries`
- On subsequent requests: return cached entry
- Partial caches (run not complete): marked `is_partial: true`
- `chart_cache_entries` Alembic migration must be added to Track 1 migrations if not present

Wire: Update `get_chart_repository()` in `charts.py`

#### ISS-017: CeleryQueueRepository

File: `services/api/repositories/celery_queue_repository.py`
Implements: `QueueRepositoryInterface`
Operations: `get_queue_snapshot`, `get_contention`

Implementation notes:
- Use `celery.current_app.control.inspect()` for queue depth and active tasks
- Fall back gracefully if Celery/Redis is unreachable (return degraded status, do not raise)
- `CELERY_BROKER_URL` from environment

Wire: Update `get_queue_repository()` in `queues.py`

#### ISS-019: SqlCertificationRepository

File: `services/api/repositories/sql_certification_repository.py`
Implements: `CertificationRepositoryInterface`
Operations: `get_report`, `list_events`
Wire: Update `get_certification_repository()` in `data_certification.py`

#### ISS-020: SqlParityRepository

File: `services/api/repositories/sql_parity_repository.py`
Implements: `ParityRepositoryInterface`
Operations: `list` (with keyword-only filter args per LL-023 lesson), `find_by_id`,
            `get_summary`, `get_instrument_summary`
Wire: Update `get_parity_repository()` in `parity.py`

#### ISS-021: SqlAuditExplorerRepository

File: `services/api/repositories/sql_audit_explorer_repository.py`
Implements: `AuditExplorerRepositoryInterface`
Operations: `list` (with cursor pagination), `find_by_id`
Note: Cursor pagination — return `next_cursor` based on last event's `created_at` + `id`.
Wire: Update `get_audit_explorer_repository()` in `audit.py`

#### ISS-022: SqlSymbolLineageRepository

File: `services/api/repositories/sql_symbol_lineage_repository.py`
Implements: `SymbolLineageRepositoryInterface`
Operations: `get_lineage`
Wire: Update `get_symbol_lineage_repository()` in `symbol_lineage.py`

#### ISS-024: RealDependencyHealthRepository

File: `services/api/repositories/real_dependency_health_repository.py`
Implements: `DependencyHealthRepositoryInterface`

Checks to perform (each with timeout of 2 s, fail gracefully):
- `database`: attempt `SELECT 1` via `engine.connect()`
- `redis`: attempt `redis.ping()` via `REDIS_URL`
- `artifact_store`: attempt list on configured bucket/local path
- `feed_health_service`: check if feed_health table is queryable

Wire: Update `get_dependency_health_repository()` in `observability.py`

#### ISS-025: SqlDiagnosticsRepository

File: `services/api/repositories/sql_diagnostics_repository.py`
Implements: `DiagnosticsRepositoryInterface`

Aggregation queries (from source workplan M11):
- `queue_contention_alerts`: count queue snapshots with contention score > threshold
- `feed_health_degraded_feeds`: count feed health snapshots with `status != "healthy"`
- `parity_critical_events`: count parity events with `severity = "critical"` unresolved
- `certification_blocked_runs`: count certification events with `blocked = true`

Wire: Update `get_diagnostics_repository()` in `observability.py`

### Repository Directory Structure

```
services/api/repositories/
  __init__.py
  sql_artifact_repository.py       # ISS-011
  sql_feed_repository.py           # ISS-013
  sql_feed_health_repository.py    # ISS-014
  sql_chart_repository.py          # ISS-016
  celery_queue_repository.py       # ISS-017
  sql_certification_repository.py  # ISS-019
  sql_parity_repository.py         # ISS-020
  sql_audit_explorer_repository.py # ISS-021
  sql_symbol_lineage_repository.py # ISS-022
  real_dependency_health_repository.py  # ISS-024
  sql_diagnostics_repository.py    # ISS-025
```

### Acceptance Criteria — Track 3

- [ ] All 11 repository files exist in `services/api/repositories/`
- [ ] All 11 repositories implement their interface completely — no `pass` or `NotImplementedError`
- [ ] `get_artifact_repository()` returns `SqlArtifactRepository` when `ENVIRONMENT != "test"`
- [ ] `get_artifact_storage()` returns `MinIOArtifactStorage` when `MINIO_ENDPOINT` is set
- [ ] `get_feed_repository()` returns `SqlFeedRepository` when `ENVIRONMENT != "test"`
- [ ] `get_chart_repository()` returns `SqlChartRepository` with write-through cache
- [ ] Chart cache is populated on first request for a completed run; second request hits cache
- [ ] `get_queue_repository()` returns `CeleryQueueRepository`; falls back gracefully if broker unreachable
- [ ] `get_dependency_health_repository()` pings real database, Redis, and artifact store
- [ ] `GET /health/dependencies` reflects actual service state (not all-OK mock)
- [ ] `GET /health/diagnostics` returns real counts from DB queries
- [ ] Integration tests pass for all SQL repositories against PostgreSQL
- [ ] All ISS-011 through ISS-025 updated to `RESOLVED` in issues log

---

## M13 — Track 4: Router Registration and Stub Cleanup (G-27 through G-30)

### Deliverables

#### 1. Register exports.py in main.py

The exports stub exists but is not registered. Register it and implement minimum viable endpoints:

```
GET /exports/runs/{run_id}/csv       → stub returning { "download_url": null, "status": "not_implemented" }
GET /exports/runs/{run_id}/json      → stub returning same shape
GET /exports/runs/{run_id}/parquet   → stub returning same shape
```

These are deliberate stubs with a documented `not_implemented` status. They are not empty
files — they return a valid schema response that the frontend M31 ExportCenter can detect
and handle. Full export implementation is in M31.

#### 2. Register research.py in main.py

Minimum viable research endpoints (stubs with `not_implemented` status):

```
POST /research/runs     → { "run_id": null, "status": "not_implemented" }
GET  /research/runs     → { "runs": [], "status": "not_implemented" }
```

#### 3. Register governance.py in main.py with prefix

The governance.py stub (GET "/") should be registered at `/governance` prefix and updated
to list available governance sub-resources:

```python
app.include_router(governance.router, prefix="/governance", tags=["governance"])
```

Update `GET /governance/` to return:
```json
{
  "success": true,
  "data": {
    "resources": ["approvals", "overrides", "promotions", "draft_autosaves"]
  }
}
```

#### 4. strategies.py extension

The strategies stub (GET "/" only) should be extended to include at minimum:

```
GET /strategies/         → list strategies (mock data)
GET /strategies/{id}     → get strategy by ID (mock data)
GET /strategies/{id}/versions → list versions (mock data)
```

Draft autosave endpoints are covered in Track 2.

### Acceptance Criteria — Track 4

- [ ] `GET /openapi.json` includes `/exports/*`, `/research/*`, `/governance/*` paths
- [ ] `GET /exports/runs/{run_id}/csv` returns 200 with `status: "not_implemented"` shape
- [ ] `GET /research/runs` returns 200 with `runs: []`
- [ ] `GET /governance/` returns 200 with resources list
- [ ] `GET /strategies/` returns 200 with strategies list (mock data)
- [ ] All 4 routers visible in OpenAPI docs at `GET /docs`

---

## M13 — Acceptance Test Pack

File: `tests/acceptance/test_m13_gap_fill.py`

This acceptance test file validates M13 is complete. It must pass before M22 begins.

### Tests to include

**Infrastructure (T1)**
- `test_api_dockerfile_buildable` — Dockerfile syntax validation (import check)
- `test_alembic_upgrade_downgrade` — run against test DB
- `test_db_module_importable` — `from services.api.db import get_db, engine`

**Governance Endpoints (T2)**
- `test_approve_endpoint_returns_approved`
- `test_reject_endpoint_returns_rejected`
- `test_reject_endpoint_rejects_empty_rationale`
- `test_override_request_accepts_valid_evidence_link`
- `test_override_request_rejects_missing_evidence_link`
- `test_override_request_rejects_root_url_evidence_link`
- `test_override_request_rejects_non_http_evidence_link`
- `test_get_override_returns_detail`
- `test_get_override_returns_404_for_unknown`
- `test_draft_autosave_post_returns_autosave_id`
- `test_draft_autosave_get_latest_returns_most_recent`
- `test_draft_autosave_delete_removes_draft`

**Router Registration (T4)**
- `test_exports_router_registered` — openapi.json contains /exports path
- `test_research_router_registered` — openapi.json contains /research path
- `test_governance_router_registered` — openapi.json contains /governance path
- `test_strategies_list_endpoint_responds`

**Open Issues Resolved (T3)**
- `test_artifact_repository_is_sql_backed_in_non_test_env`
- `test_feed_repository_is_sql_backed_in_non_test_env`
- `test_dependency_health_reflects_real_db_state`
- `test_diagnostics_returns_real_counts`

---

## M13 DEFINITION OF DONE

M13 is complete when ALL of the following are true:

- [ ] G-01 through G-30 all addressed (see gap table above)
- [ ] `docker-compose build && docker-compose up --wait` exits 0
- [ ] `alembic upgrade head` and `alembic downgrade base` both succeed on PostgreSQL
- [ ] `from services.api.db import get_db` imports without error
- [ ] All 6 governance endpoints (reject, overrides CRUD, draft autosave) return correct status codes
- [ ] evidence_link validation rejects root-only URLs and non-URI values
- [ ] All 12 open issues (ISS-011 through ISS-025) marked RESOLVED
- [ ] All SQL repositories exist in `services/api/repositories/` and implement their interfaces
- [ ] `GET /health/dependencies` reflects real service connectivity (not all-OK mock)
- [ ] `GET /health/diagnostics` returns real DB-sourced counts
- [ ] All 4 stub routers registered in main.py and visible in OpenAPI docs
- [ ] `tests/acceptance/test_m13_gap_fill.py` passes (all tests)
- [ ] Unit test coverage ≥ 85% on new code (per CLAUDE.md §5)
- [ ] Service layer coverage ≥ 90% for governance module
- [ ] Zero linting errors, zero type errors
- [ ] Progress file updated: M13 all steps DONE
- [ ] Issues log: ISS-011 through ISS-025 all marked RESOLVED

---

## EXECUTION SEQUENCE (for implementing agent)

```
STEP 1 — UNDERSTAND
  Read this file.
  Read FXLab_Phase_3_workplan_v1_1.md §12 M23 and M24 for governance and chart spec.
  Read libs/contracts/models.py to understand existing schema.
  Read libs/contracts/interfaces/*.py to understand all interfaces.
  Confirm M0–M12 DONE in progress file.

STEP 2 — INTERFACE FIRST (T1)
  Define Alembic env.py that imports Base from libs.contracts.models.
  Define services/api/db.py interface (engine, SessionLocal, get_db).

STEP 3 — RED (T1)
  Write failing tests: test_m13_infrastructure.py.
  Verify they fail for the right reason.

STEP 4 — GREEN (T1)
  Create services/api/Dockerfile.
  Create frontend/Dockerfile.
  Create alembic.ini and migrations/env.py.
  Create migrations/versions/001_initial_schema.py.
  Create services/api/db.py.

STEP 5 — QUALITY GATE (T1)
  Verify docker-compose build succeeds.
  Verify alembic upgrade/downgrade succeeds.

STEP 6 — RED/GREEN/QUALITY (T2)
  Add governance contracts to libs/contracts/governance.py.
  Write failing tests for reject, overrides, and draft autosave endpoints.
  Implement endpoints. Run quality gate.

STEP 7 — RED/GREEN/QUALITY (T3)
  For each SQL repository (ISS-011 through ISS-025):
    Write failing integration test.
    Implement repository class.
    Update DI provider function.
    Run quality gate.
    Mark issue RESOLVED.

STEP 8 — RED/GREEN/QUALITY (T4)
  Register missing routers. Extend stubs to minimum viable endpoints.
  Run quality gate.

STEP 9 — ACCEPTANCE
  Run tests/acceptance/test_m13_gap_fill.py.
  All must pass.

STEP 10 — REVIEW CHECKLIST
  □ All G-01 through G-30 addressed.
  □ ISS-011 through ISS-025 RESOLVED.
  □ Coverage thresholds met.
  □ Docker builds.
  □ Alembic runs.
  □ Progress file updated.
  □ Issues log updated.
  □ M13 marked DONE in progress file.
  □ Active milestone updated to M22 (frontend track begins).
```

---

## PROGRESS TRACKING

Add the following to `FXLab_Phase_3_workplan_v1_1.progress` after M12:

```
[M13] Infrastructure Completion and Backend Gap Fill                    NOT_STARTED
  [M13-T1-S1] UNDERSTAND -- review audit findings, read interfaces      NOT_STARTED
  [M13-T1-S2] INTERFACE FIRST -- db.py and alembic env.py contracts     NOT_STARTED
  [M13-T1-S3] RED -- write failing infrastructure tests                 NOT_STARTED
  [M13-T1-S4] GREEN -- Dockerfiles, alembic, db.py                      NOT_STARTED
  [M13-T1-S5] QUALITY GATE -- docker build, alembic verify              NOT_STARTED
  [M13-T2-S1] UNDERSTAND -- read M23 governance spec                    NOT_STARTED
  [M13-T2-S2] INTERFACE FIRST -- governance contract additions          NOT_STARTED
  [M13-T2-S3] RED -- write failing governance endpoint tests            NOT_STARTED
  [M13-T2-S4] GREEN -- reject, overrides, draft autosave endpoints      NOT_STARTED
  [M13-T2-S5] QUALITY GATE -- format/lint/type/coverage                 NOT_STARTED
  [M13-T3-S1] UNDERSTAND -- review all interface contracts              NOT_STARTED
  [M13-T3-S2] RED -- write failing integration tests per repository     NOT_STARTED
  [M13-T3-S3] GREEN -- implement all 12 SQL repositories                NOT_STARTED
  [M13-T3-S4] QUALITY GATE -- integration tests against PostgreSQL      NOT_STARTED
  [M13-T3-S5] RESOLVE -- mark ISS-011 through ISS-025 RESOLVED          NOT_STARTED
  [M13-T4-S1] GREEN -- register missing routers, extend stubs           NOT_STARTED
  [M13-T4-S2] QUALITY GATE -- openapi.json verification                 NOT_STARTED
  [M13-S6] REFACTOR                                                      NOT_STARTED
  [M13-S7] INTEGRATION -- full integration test suite                   NOT_STARTED
  [M13-S8] REVIEW -- checklist sign-off, update progress + issues log   NOT_STARTED
```
