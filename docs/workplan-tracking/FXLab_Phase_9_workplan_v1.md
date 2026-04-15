# FXLab Phase 9 — Research Pipeline, Data Export & Platform Consolidation

## Revision Summary

| Rev | Date       | Description                                    |
|-----|------------|------------------------------------------------|
| 1.0 | 2026-04-13 | Initial workplan — research + exports + consolidation |

---

## MILESTONE INDEX

```
MILESTONE INDEX
───────────────────────────────────────────────
Total milestones: 14
Tracks: Research Pipeline, Data Export, Platform Consolidation, Acceptance

Research Pipeline:   M0, M1, M2, M3, M4
Data Export:         M5, M6, M7
Platform Consolidation: M8, M9, M10, M11, M12
Acceptance:          M13
───────────────────────────────────────────────
```

---

## Motivation

Phases 1–8 delivered a feature-complete algorithmic trading platform with:
strategy compilation, backtesting, walk-forward analysis, Monte Carlo simulation,
portfolio allocation, cross-strategy risk, signal generation, execution engines,
kill switches, reconciliation, compliance, audit trails, and a full React frontend.

Phase 9 closes three categories of gaps:

1. **Research Pipeline** — The frontend calls `POST /runs/research` and the
   `/research` route prefix exists but has zero endpoints. Research run
   submission, execution orchestration, and result retrieval are the core
   product loop that ties the backtesting/walk-forward/Monte Carlo engines
   to the operator's workflow.

2. **Data Export** — The frontend calls `POST /exports`, `GET /exports`,
   `GET /exports/{id}`, and `GET /exports/{id}/download`. The `/exports`
   route stub has zero endpoints. The audit export system exists but is
   separate. General-purpose data export (trades, runs, artifacts) is needed
   to satisfy the frontend contract.

3. **Platform Consolidation** — Deprecation warnings, code quality debt,
   and test hardening accumulated across 8 rapid phases. This track upgrades
   Pydantic models to V2 style, replaces deprecated SQLAlchemy patterns,
   adds missing Alembic migrations for any orphaned schema changes, and
   hardens flaky test isolation.

---

## Track A — Research Pipeline

### M0: Research Run Contracts, Interfaces & Storage Schema

**Objective:** Define the domain contracts for research run lifecycle — from
submission through execution to result retrieval.

**Inputs:**
- Frontend contract: `POST /runs/research` expects a `RunRecord` response
- Existing backtest/walk-forward/Monte Carlo engines in `services/worker/research/`
- Existing `libs/contracts/research.py` (ResearchRunResponse, RunCandidateResponse)

**Deliverables:**
- `libs/contracts/research_run.py`:
  - `ResearchRunType` enum: BACKTEST, WALK_FORWARD, MONTE_CARLO, COMPOSITE
  - `ResearchRunStatus` enum: PENDING, QUEUED, RUNNING, COMPLETED, FAILED, CANCELLED
  - `ResearchRunConfig` (frozen): run_type, strategy_id, strategy_version_id,
    symbols, date_range, backtest_config (optional), walk_forward_config (optional),
    monte_carlo_config (optional), initial_equity, execution_mode
  - `ResearchRunResult` (frozen): run_id, status, backtest_result (optional),
    walk_forward_result (optional), monte_carlo_result (optional), started_at,
    completed_at, error_message (optional)
  - `ResearchRunRecord` (frozen): id, config, status, result, created_by,
    created_at, updated_at
- `libs/contracts/interfaces/research_run_repository.py`:
  - `ResearchRunRepositoryInterface` ABC: create, get_by_id, update_status,
    save_result, list_by_strategy, list_by_user, count_by_status
- `libs/contracts/interfaces/research_run_service.py`:
  - `ResearchRunServiceInterface` ABC: submit_run, get_run, cancel_run,
    list_runs, get_run_result
- `libs/contracts/mocks/mock_research_run_repository.py`: full mock with introspection
- `libs/contracts/models.py`: ResearchRunRecord ORM model
- `migrations/versions/NNNN_add_research_runs_table.py`: Alembic migration
- Unit tests for all contracts, enums, validation, mock

**Acceptance criteria:**
- All contracts frozen, validated, import cleanly
- Mock repository passes behavioural parity tests
- ORM model creates/drops cleanly in SQLite
- Migration chain integrity preserved

---

### M1: Research Run Repository (SQL)

**Objective:** Implement the SQL-backed research run repository.

**Deliverables:**
- `services/api/repositories/sql_research_run_repository.py`:
  - Implements `ResearchRunRepositoryInterface`
  - CRUD with proper session management
  - List with pagination, filtering by strategy_id, user, status
  - Status transition validation
  - Structured logging per §8
- Integration tests: save, retrieve, update status, list, pagination,
  not-found, status transitions

**Acceptance criteria:**
- All interface methods implemented with real SQL
- Integration tests pass against SQLite
- No bare except, no silent swallow

---

### M2: Research Run Service

**Objective:** Implement the research run service that orchestrates run
submission, delegates to the appropriate engine, and persists results.

**Deliverables:**
- `services/api/services/research_run_service.py`:
  - Implements `ResearchRunServiceInterface`
  - `submit_run`: validate config, create PENDING record, dispatch to engine
  - `get_run`: retrieve by ID with auth check
  - `cancel_run`: transition to CANCELLED if PENDING/QUEUED
  - `list_runs`: paginated list with filters
  - `get_run_result`: retrieve completed result
  - Engine delegation: route to BacktestEngine / WalkForwardEngine / MonteCarloEngine
    based on run_type
  - Error handling: catch engine failures, persist FAILED status with error_message
  - Thread-safe status transitions
- Unit tests: happy path for each run type, cancellation, failure handling,
  concurrent access, auth enforcement

**Acceptance criteria:**
- submit_run creates record and delegates to correct engine
- Results persisted on completion
- Failures captured with error_message
- ≥90% coverage on service layer

---

### M3: Research Run API Routes

**Objective:** Wire the research endpoints the frontend expects.

**Deliverables:**
- `services/api/routes/research.py` (replace empty stub):
  - `POST /research/runs` — submit a research run
  - `GET /research/runs` — list runs with pagination and filters
  - `GET /research/runs/{run_id}` — get run detail
  - `GET /research/runs/{run_id}/result` — get run result
  - `DELETE /research/runs/{run_id}` — cancel a pending/queued run
  - Auth enforcement: `require_scope("operator:write")` for mutations,
    `require_scope("operator:read")` for reads
  - Request/response schemas with Pydantic
  - Structured logging per §8
- Also update/add: `POST /runs/research` alias route for frontend compatibility
- Unit tests: happy path, auth, validation, 404, 409

**Acceptance criteria:**
- Frontend `POST /runs/research` returns RunRecord-compatible response
- All 5 endpoints functional with proper auth
- Error codes match spec (404, 409, 422)

---

### M4: Research Pipeline Integration

**Objective:** Wire end-to-end: frontend submits research run → backend
executes backtest/walk-forward/MC → result available via API.

**Deliverables:**
- Integration test: submit run, poll status, retrieve result
- Wire research routes into `services/api/main.py`
- DI wiring for research run service + repository in app bootstrap
- Structured logging across the full pipeline

**Acceptance criteria:**
- End-to-end integration test passes
- Research run lifecycle: PENDING → RUNNING → COMPLETED
- Result contains backtest metrics

---

## Track B — Data Export

### M5: Export Job Contracts & Repository

**Objective:** Implement the general-purpose export job system the frontend expects.

**Inputs:**
- Frontend contract: `ExportJobResponse` with id, export_type, object_id,
  status, artifact_uri, requested_by, created_at, updated_at, override_watermark
- Existing `libs/contracts/export.py` (ExportType, ExportStatus, ExportJobCreate,
  ExportJobResponse)

**Deliverables:**
- `libs/contracts/interfaces/export_repository.py`:
  - `ExportRepositoryInterface` ABC: create_job, get_job, update_job,
    list_jobs, list_by_object_id
- `libs/contracts/mocks/mock_export_repository.py`: full mock
- `libs/contracts/models.py`: ExportJobRecord ORM model
- `migrations/versions/NNNN_add_export_jobs_table.py`: Alembic migration
- `services/api/repositories/sql_export_repository.py`: SQL implementation
- Unit + integration tests for repository

**Acceptance criteria:**
- ORM model matches ExportJobResponse fields exactly
- CRUD operations work with real SQL
- Migration chain integrity preserved

---

### M6: Export Service

**Objective:** Implement export job orchestration — creating zip bundles of
trades, runs, and artifacts.

**Deliverables:**
- `libs/contracts/interfaces/export_service.py`:
  - `ExportServiceInterface` ABC: create_export, get_export, list_exports,
    download_export
- `services/api/services/export_service.py`:
  - `ExportService` implementing the interface
  - `create_export`: validate type + object_id, create PENDING job,
    generate export bundle (CSV + metadata JSON + README), store via
    ArtifactStorageBase, update job to COMPLETE with artifact_uri
  - Export types: TRADES (trade history CSV), RUNS (run result JSON),
    ARTIFACTS (artifact binary + metadata)
  - `download_export`: retrieve bytes from artifact storage
  - Override watermark injection per spec §8.2
  - Error handling: update to FAILED on exception
- Unit tests for each export type, error handling, watermark injection

**Acceptance criteria:**
- Each export type produces a valid zip bundle
- Status lifecycle: PENDING → PROCESSING → COMPLETE (or FAILED)
- Watermark metadata attached when overrides are active

---

### M7: Export API Routes

**Objective:** Wire the export endpoints the frontend expects.

**Deliverables:**
- `services/api/routes/exports.py` (replace empty stub):
  - `POST /exports` — create export job
  - `GET /exports` — list exports with pagination + object_id filter
  - `GET /exports/{id}` — get export detail
  - `GET /exports/{id}/download` — download export content (streaming)
  - Auth enforcement: `require_scope("exports:read")` for reads,
    `require_scope("operator:write")` for create
  - Structured logging per §8
- Wire into `services/api/main.py`
- Unit tests: happy path, auth, 404, download streaming

**Acceptance criteria:**
- Frontend export API calls succeed
- Download endpoint streams binary content with correct Content-Type
- All error codes match spec

---

## Track C — Platform Consolidation

### M8: Pydantic V2 Deprecation Cleanup

**Objective:** Replace all `class Config` usage in Pydantic models with
`model_config = ConfigDict(...)` to eliminate PydanticDeprecatedSince20 warnings.

**Deliverables:**
- Update all Pydantic models using `class Config` to use `ConfigDict`
- Verify zero PydanticDeprecatedSince20 warnings in test output
- All existing tests pass unchanged

**Acceptance criteria:**
- `pytest ... -W error::DeprecationWarning` passes for Pydantic warnings
- Zero `class Config` in Pydantic models

---

### M9: SQLAlchemy Legacy API Cleanup

**Objective:** Replace deprecated `Query.get()` with `Session.get()` to
eliminate LegacyAPIWarning.

**Deliverables:**
- Update all `self._db.query(Model).get(id)` to `self._db.get(Model, id)`
- Verify zero LegacyAPIWarning in test output
- All existing tests pass unchanged

**Acceptance criteria:**
- Zero SQLAlchemy LegacyAPIWarning in test output
- All repository tests still pass

---

### M10: HTTP Status Code Deprecation Cleanup

**Objective:** Replace deprecated `HTTP_422_UNPROCESSABLE_ENTITY` with
`HTTP_422_UNPROCESSABLE_CONTENT`.

**Deliverables:**
- Update all references to the deprecated constant
- Zero DeprecationWarning for HTTP status codes in test output

**Acceptance criteria:**
- No deprecation warnings related to HTTP status codes

---

### M11: Test Isolation Hardening

**Objective:** Audit all route test modules for dependency override leaks
and ensure the autouse fixture in conftest.py covers all edge cases.

**Deliverables:**
- Audit all test modules that set `app.dependency_overrides`
- Ensure each module's fixtures properly clean up overrides
- Add defensive per-module cleanup where missing
- Verify full suite passes with pytest-randomly (random test ordering)
- Document test isolation patterns in tests/README.md

**Acceptance criteria:**
- `pytest tests/ -p randomly --count=3` (3 random orderings) all pass
- Zero ordering-dependent failures

---

### M12: Coverage Uplift & Dead Code Removal

**Objective:** Identify and remove unreachable code, increase coverage on
under-tested modules, remove empty stub service directories.

**Deliverables:**
- Run coverage with `--cov-report=term-missing` to identify uncovered lines
- Add tests for critical uncovered paths (especially error handlers)
- Remove empty `__init__.py`-only service directories that are unused stubs
- Overall coverage ≥ 88% (up from 86.82%)

**Acceptance criteria:**
- Coverage ≥ 88%
- No empty stub directories remain
- All new tests follow TDD per §5

---

## Track D — Acceptance

### M13: Phase 9 Acceptance Test Pack

**Objective:** End-to-end acceptance tests covering all Phase 9 deliverables.

**Deliverables:**
- `tests/acceptance/test_phase9_acceptance.py`:
  1. Research run submission → execution → result retrieval
  2. Research run cancellation
  3. Walk-forward research run
  4. Monte Carlo research run
  5. Export creation → download (trades)
  6. Export creation → download (runs)
  7. Export list with pagination
  8. Pydantic V2 zero-warning verification
  9. Full pipeline: submit research → export result → download bundle

**Acceptance criteria:**
- All 9 acceptance tests pass
- Zero deprecation warnings in test output
- Full suite (unit + integration + acceptance) green

---

## Dependencies

```
M0 ─→ M1 ─→ M2 ─→ M3 ─→ M4
                              ↘
M5 ─→ M6 ─→ M7 ─────────────→ M13
                              ↗
M8, M9, M10 (parallel) ─→ M11 ─→ M12
```

Tracks A, B, C are largely independent. Track D (M13) depends on all three.
Within each track, milestones are sequential.
M8, M9, M10 can be done in parallel.
