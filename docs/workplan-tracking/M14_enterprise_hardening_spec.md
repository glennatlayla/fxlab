# M14 — Enterprise Hardening (Pre-Frontend Production Readiness)

**Created:** 2026-03-28
**Last revised:** 2026-03-28 (post-audit revision — fully comprehensive)
**Status:** IN_PROGRESS
**Prerequisite:** M13 Gap Fill DONE
**Blocks:** M22 Frontend Foundation

---

## Objective

Close every production-blocking and enterprise-readiness gap identified in
the post-M13 quality audit before the frontend track begins. M22 will rely
on authentication, rate limiting, and correlation IDs being present and
stable in the backend.

---

## MILESTONE INDEX

```
MILESTONE INDEX
────────────────────────────────────────────────────────────────
Total milestones: 9
Track: M14 Enterprise Hardening

M14: M14-T1, M14-T2, M14-T3, M14-T4, M14-T5, M14-T6, M14-T7, M14-T8, M14-T9
────────────────────────────────────────────────────────────────
```

---

## Issue-to-Track Mapping (all 17 audit issues)

| Issue | Priority | Track | Status |
|-------|----------|-------|--------|
| Health check doesn't test DB | P0 | T1 | **DONE** |
| No migration-on-startup | P0 | T1 | **DONE** |
| No request body size limit | P1 | T1 | **DONE** |
| No rate limiting | P1 | T1 | **DONE** |
| Correlation ID not propagated | P2 | T1 | **DONE** (middleware); routes still need log wiring |
| Zero authentication | P0 | T2 | **DONE** |
| X-User-ID trusted without verification | P0 | T2 | **DONE** |
| Separation of duties not enforced | P2 | T3 | NOT STARTED |
| No transactional integrity | P2 | T3 | NOT STARTED |
| Pydantic guards incomplete | P1 | T3 | PARTIAL (~60%) |
| Stub endpoints not wired | P1 | T6 | NOT STARTED |
| No SQL integration tests | P1 | T4 | NOT STARTED |
| Coverage < 80% | P1 | T4 | NOT STARTED |
| No CI/CD pipeline | P2 | T5 | **DONE** (mypy gap) |
| No HTTPS documentation | P3 | T7 | NOT STARTED |
| No secrets manager path | P3 | T7 | NOT STARTED |
| No connection pool validation | P3 | T7 | NOT STARTED |

---

## Track Specifications

### M14-T1 — Infrastructure Middleware Hardening  ✅ COMPLETE

All five deliverables are implemented and tested. Summary of completion:

1. **Real health check** (`services/api/routes/health.py`) — DONE
   - `GET /health` calls `check_db_connection()`, returns 200/503.
   - **Cleanup required:** Duplicate inline implementation exists in `main.py`
     (lines 247–300). Remove the inline version; keep `routes/health.py`.
   - Routes/health.py is the canonical implementation.

2. **Migration-on-startup** (`services/api/entrypoint.sh`) — DONE
   - Runs `alembic upgrade head` with `set -e` before uvicorn.
   - Wired in `services/api/Dockerfile` as `ENTRYPOINT`.
   - **Gap:** 30-second timeout guard not implemented (low priority — not a blocker).

3. **Request body size limit** (`services/api/middleware/body_size.py`) — DONE
   - `MAX_REQUEST_BODY_BYTES` env var, defaults to 512 KB. Returns 413.
   - `/health`, `/docs`, `/openapi.json` excluded.

4. **Rate limiting** (`services/api/middleware/rate_limit.py`) — DONE
   - Sliding-window: 20 req/min governance, 100 req/min others, per IP.
   - Returns 429 with `Retry-After` header.
   - **Gap:** Redis-backed path is documented but not implemented; in-memory
     singleton is sufficient for pre-frontend, but must be wired before
     horizontal scaling. Not a blocker for M14.

5. **Correlation ID middleware** (`services/api/middleware/correlation.py`) — DONE
   - Reads/generates UUID4 `X-Correlation-ID`. Attaches to response.
   - `correlation_id_var` ContextVar is set per request.
   - **Remaining work (wired under T3):** Route-level structured log calls must
     read `correlation_id_var.get()` and include `correlation_id` field. This
     is a log completeness gap, not a functionality gap.

**Acceptance criteria: ALL PASS.**

---

### M14-T2 — JWT Authentication Middleware  ✅ COMPLETE (2026-04-01)

**Current state:** `services/api/dependencies.py` uses X-User-ID header trust
(not JWT). No `auth.py` exists. Zero routes are protected. No TEST_TOKEN.

**Deliverables:**

1. **JWT verification dependency** (`services/api/auth.py`)
   - `get_current_user()` FastAPI dependency:
     - Reads `Authorization: Bearer <token>` header.
     - Validates signature using `JWT_SECRET_KEY` env var (HS256).
     - Extracts `sub` (user ULID), `role`, `email` from claims.
     - Raises `401 Unauthorized` on missing, expired, or invalid token.
   - Test bypass: when `ENVIRONMENT == "test"`, accepts a magic token
     `TEST_TOKEN` and returns a fixed test identity
     `{"user_id": "01HTESTUSER00000000000000", "role": "operator"}`.
   - `get_optional_user()` variant for public endpoints (returns None if no token).

2. **Token utility** (`services/api/auth.py`)
   - `create_access_token(user_id, role, expires_minutes)` — signs a JWT.
   - Used by test fixtures and the future `/auth/login` endpoint (M22).

3. **Apply auth to all protected endpoints**
   - All routes except `GET /health`, `GET /`, `GET /docs`, `GET /openapi.json`,
     and `OPTIONS *` require `Depends(get_current_user)`.
   - Remove `X-User-ID` header trust pattern from `dependencies.py`.
   - `submitter_id` is now taken from token claims, not from request body.
   - Routes that previously accepted `submitter_id` in body now read it
     from the authenticated identity.
   - Delete `services/api/dependencies.py` once all routes are migrated.

4. **Update tests**
   - All test clients updated to include a valid test token.
   - `conftest.py`: provide `auth_headers` fixture returning
     `{"Authorization": "Bearer TEST_TOKEN"}`.
   - All existing 738 tests must still pass after auth wiring.

5. **Clean up inline health route duplication**
   - Remove the inline `/health` implementation from `main.py` (lines 247–300).
   - Route from `routes/health.py` (included via router) is the canonical version.
   - Update `services/api/main.py` to import and include `health.router` with
     no prefix tag, same as other routers.

**Acceptance criteria:**
- `POST /overrides/request` without token → `401`.
- `POST /overrides/request` with invalid token → `401`.
- `POST /overrides/request` with valid token → `201`.
- `GET /health` without token → `200` (public).
- All 738 existing tests still pass after auth wiring.

---

### M14-T3 — Service Layer, SoD, Transactional Integrity, Pydantic Guards  ❌ NOT STARTED

**Current state:**
- `services/api/services/` directory does not exist.
- `POST /approvals/{id}/approve` is a hardcoded stub (`return {"status": "approved"}`).
- `POST /approvals/{id}/reject` is a partial stub (validates rationale but
  returns hardcoded response without writing to DB).
- No SoD enforcement anywhere in the codebase (zero 409 responses).
- Override submit creates only an Override row; no OverrideWatermark or AuditEvent.

**Deliverables:**

1. **Governance service layer** (`services/api/services/governance_service.py`)
   - `submit_override(submitter_id, payload) -> dict`: atomically creates
     Override row + OverrideWatermark + AuditEvent in one DB transaction.
   - `review_override(override_id, reviewer_id, decision, rationale) -> dict`:
     enforces SoD (raises 409 if `reviewer_id == submitter_id`), updates
     status, emits AuditEvent.
   - `approve_request(approval_id, reviewer_id) -> dict`: enforces SoD.
     Reads submission from DB, checks reviewer_id != submitter_id.
   - `reject_request(approval_id, reviewer_id, rationale) -> dict`: enforces SoD.

2. **Separation of duties enforcement**
   - Submitter cannot approve/reject their own override or approval request.
   - Returns `409 Conflict` with
     `detail: "Separation of duties violation: submitter and reviewer must be different users"`.
   - Service layer enforces this; route simply calls service.

3. **Transactional integrity**
   - All multi-step write operations (override submit, approval decide)
     use a single `async with db.begin():` block (or equivalent) for all mutations.
   - `db.rollback()` on any exception within the workflow.
   - Partial state (Override created but AuditEvent failed) must never persist.

4. **Wire routes to service layer**
   - `POST /overrides/request` → calls `governance_service.submit_override()`.
   - `POST /approvals/{id}/approve` → calls `governance_service.approve_request()`.
   - `POST /approvals/{id}/reject` → calls `governance_service.reject_request()`.
   - Replace all stubs. No `# Stub:` comments may remain in production paths.

5. **Correlation ID in structured logs**
   - All route files: update `logger.info(...)` calls to include
     `correlation_id=correlation_id_var.get("")` from
     `services.api.middleware.correlation`.
   - Ensures every log line is traceable to a request.

6. **Pydantic manual guards — complete coverage**
   - Audit every route file for fields with `min_length`, `max_length`,
     `pattern`, `ge`, or `le` in the corresponding contract.
   - `approve_request` route currently has zero guards — add them.
   - Add `require_*` calls for all uncovered constraints.
   - Target: every contract field with a constraint has a manual guard in the handler.

**Acceptance criteria:**
- `POST /approvals/{id}/approve` with `reviewer_id == submitter_id` → `409`.
- `POST /approvals/{id}/reject` with `reviewer_id == submitter_id` → `409`.
- Override submit creates Override + OverrideWatermark + AuditEvent atomically.
- DB failure mid-transaction does not leave partial records.
- All structured log lines in route handlers include `correlation_id` field.
- All manual guards tested with boundary values.

---

### M14-T4 — SQL Repository Integration Tests + ≥80% Coverage  ❌ NOT STARTED

**Current state:**
- `tests/integration/conftest.py` has the SQLite fixture infrastructure (ready to use).
- `tests/integration/test_sql_repositories.py` does not exist.
- 11 SQL repositories exist, zero have integration tests.
- Coverage is approximately 35% (observed in last pytest run output).

**Deliverables:**

1. **SQLite integration test fixture** — infrastructure already in `tests/integration/conftest.py`
   - In-process SQLite engine (`:memory:` or temp file).
   - `Base.metadata.create_all()` bootstraps all 20 tables.
   - Per-test session isolation via `SAVEPOINT`/rollback — already implemented.
   - **Action:** Verify `DATABASE_URL=sqlite:///./test.db` override works;
     add `sqlite+aiosqlite` fallback if needed.

2. **SQL repository integration tests** (`tests/integration/test_sql_repositories.py`)
   Tests for every SQL repository:
   - `SqlFeedRepository`: create, get_by_id, list, not_found.
   - `SqlArtifactRepository`: create, get_by_id, list_by_run.
   - `SqlOverrideRepository`: create, get_by_id.
   - `SqlDraftAutosaveRepository`: create, get_latest, delete.
   - `SqlChartRepository`: upsert, get_by_run_id.
   - `SqlFeedHealthRepository`: create, list_by_feed.
   - `SqlParityRepository`: create, list_by_feed.
   - `SqlCertificationRepository`: create, list, find_by_feed.
   - `SqlSymbolLineageRepository`: create, find_by_symbol.
   - `SqlAuditExplorerRepository`: create, find_by_id, list.
   - `SqlDiagnosticsRepository`: healthcheck.

3. **Coverage uplift tests** for routes currently at 0–40%
   - `routes/health.py`: DB-up path, DB-down path.
   - `routes/feeds.py`: create, list, get, not_found.
   - `routes/artifacts.py`: upload, get, not_found.
   - `routes/audit.py`: list, get_by_id.
   - `routes/approvals.py`: approve path, reject path, SoD violation path.
   - All other routes with uncovered branches.

**Acceptance criteria:**
- `pytest --cov --cov-fail-under=80` passes.
- All integration tests green against SQLite.
- No test uses production database.

---

### M14-T5 — CI/CD Pipeline  ✅ 90% COMPLETE

**Current state:** Makefile, `.pre-commit-config.yaml`, and `.github/workflows/ci.yml`
all exist with correct targets. One gap: `mypy` is absent from the CI `quality` job
(it IS in pre-commit but not in GitHub Actions).

**Remaining work:**

1. **Add mypy to `.github/workflows/ci.yml` quality job**
   - After the ruff steps in the `quality` job, add:
     ```yaml
     - name: Type check
       run: .venv/bin/mypy services/ libs/ --ignore-missing-imports --no-strict-optional
     ```
   - This matches the pre-commit mypy hook and the spec requirement.

**All other T5 deliverables are complete:**
- `Makefile` with `make install-dev`, `make test`, `make quality`, `make format`, `make ci`, `make hooks`.
- `.pre-commit-config.yaml` with ruff (format + lint), mypy, and standard hooks.
- `.github/workflows/ci.yml` with quality → test → build jobs, 80% coverage gate.

**Acceptance criteria:**
- `make ci` runs to completion with 0 failures.
- `make quality` exits 0 on the current codebase.
- CI workflow YAML has mypy in quality job.

---

### M14-T6 — Wire Stub Endpoints to Real Repositories  ❌ NOT STARTED

**Current state:** Several endpoints return hardcoded stubs or empty collections
with no database interaction. These must be wired before the frontend can rely on them.

**Stub inventory (confirmed by code inspection):**

| Route | File | Current stub | Required action |
|-------|------|-------------|-----------------|
| `POST /approvals/{id}/approve` | routes/approvals.py:72 | `return {"status": "approved"}` | Wire to governance_service (T3) |
| `POST /approvals/{id}/reject` | routes/approvals.py:114 | Validates but returns stub | Wire to governance_service (T3) |
| `GET /governance/` | routes/governance.py | `return {"success": True, "data": []}` | Wire to repo or document as intentional |
| `GET /strategies/` | routes/strategies.py | Returns `[]` or similar | Wire to SqlDraftAutosaveRepository |
| `GET /runs/` | routes/runs.py | Returns stub | Assess: wire or document as deferred |
| `GET /candidates/` | (if exists) | Returns `[]` | Wire or document |
| `GET /deployments/` | (if exists) | Returns `[]` | Wire or document |

**Deliverables:**

1. **Wire approval endpoints to governance service** (done as part of T3 above, but
   tracked here for stub inventory completeness).

2. **Wire `GET /strategies/` to `SqlDraftAutosaveRepository`**
   - `GET /strategies/drafts` (or similar) → calls `repo.list_by_user(user_id)`.
   - Return actual autosaves from DB; remove `return []` stub.

3. **Audit and document remaining stubs**
   - For each remaining stub route, either:
     (a) Wire it to a repository, or
     (b) Add a `# DEFERRED: <reason>` comment with the milestone where it will be wired.
   - No silent stubs allowed — every endpoint must declare its intent.

4. **`GET /governance/`**
   - If this endpoint has a real purpose, define what it should return and wire it.
   - If it is a placeholder for a future list endpoint, document it explicitly and
     return `{"message": "Not yet implemented", "deferred": "M23"}` with 501.

**Acceptance criteria:**
- Zero routes return hardcoded empty collections `[]` or `{}` without a documented
  stub declaration.
- All stubs are either wired or carry a `# DEFERRED: <milestone>` comment.
- Approval endpoints call the real governance service (from T3).

---

### M14-T7 — Production Operations Documentation (P3)  ❌ NOT STARTED

**Current state:** No deployment guide, no secrets management path, no
connection pool validation documentation.

**Deliverables:**

1. **`DEPLOYMENT.md`** (project root)
   - **HTTPS/TLS:** Document that the API must sit behind a reverse proxy
     (nginx/Caddy/ALB) that terminates TLS. FastAPI itself should bind to HTTP only.
     Provide example nginx upstream config.
   - **Secrets management:** Document that `JWT_SECRET_KEY`, `DATABASE_URL`,
     `REDIS_URL`, `CORS_ALLOWED_ORIGINS` must be injected via environment
     variables (not `.env` in production). Provide example docker-compose secrets
     block and AWS Secrets Manager path.
   - **Connection pool:** Document `DB_POOL_SIZE`, `DB_POOL_OVERFLOW`,
     `DB_POOL_TIMEOUT` env vars (add to `services/api/db.py` and `.env.example`).
     Recommended values: pool_size=5, max_overflow=10, pool_timeout=30.
   - **Pre-flight checklist** for production deployments:
     - `ENVIRONMENT=production` set in container.
     - `CORS_ALLOWED_ORIGINS` set to actual frontend domain.
     - `JWT_SECRET_KEY` is a 32+ byte random secret.
     - `DATABASE_URL` uses SSL mode (`sslmode=require`).
     - Health check endpoint responding before routing traffic.

2. **Add connection pool config to `services/api/db.py`**
   - Read `DB_POOL_SIZE`, `DB_POOL_OVERFLOW`, `DB_POOL_TIMEOUT` from env with
     documented defaults.
   - Validate at startup: log CRITICAL if any pool parameter is non-positive.

3. **Update `.env.example`**
   - Add all new variables: `JWT_SECRET_KEY`, `DB_POOL_SIZE`, `DB_POOL_OVERFLOW`,
     `DB_POOL_TIMEOUT` with documented expected values.

**Acceptance criteria:**
- `DEPLOYMENT.md` covers HTTPS, secrets, connection pool, and pre-flight checklist.
- `services/api/db.py` reads pool config from env vars with safe defaults.
- `.env.example` includes all production-required variables.

---

### M14-T8 — OIDC Auth Provider Integration (P1)  ❌ NOT STARTED

**Current state:** Phase 3 spec (line 243) requires "OIDC consuming Phase 1 auth
service; `@auth0/auth0-react` or equivalent". However:
- No OIDC provider exists anywhere in the codebase (no Keycloak, no Auth0, no custom IdP).
- Phase 1 workplan deferred OIDC ("JWT bearer; local bootstrap; replaceable with OIDC later").
- Current auth is self-rolled HS256 JWT in `services/api/auth.py`.
- Frontend `AuthProvider.tsx` is a fake stub (`setIsAuthenticated(true)`).
- No token endpoint, no discovery endpoint, no refresh token flow.

**Spec reference:** `User Spec/FXLab_Phase_3_workplan_v1_1.md` lines 243, 1024–1026, 1041–1043.

**Architecture decision required:** Choose an OIDC approach:
- **Option A:** Self-hosted Keycloak (docker-compose service) — full control, complex ops.
- **Option B:** Auth0 managed service — simpler, external dependency.
- **Option C:** Extend current JWT with OIDC-compatible endpoints — minimal IdP, custom token
  endpoint + discovery doc + refresh flow. Satisfies the spec's "Phase 1 auth service"
  language without external dependencies. M22 frontend consumes it via `@auth0/auth0-react`
  or `oidc-client-ts`.

**Deliverables (regardless of option chosen):**

1. **OIDC discovery endpoint** (`/.well-known/openid-configuration`)
   - Returns issuer, authorization_endpoint, token_endpoint, jwks_uri, supported scopes.
   - Required by any OIDC client library (auth0-react, oidc-client-ts).

2. **Token endpoint** (`POST /auth/token`)
   - Accepts `grant_type=password` (bootstrap) and `grant_type=refresh_token`.
   - Returns `{ access_token, refresh_token, token_type, expires_in, scope }`.
   - Access tokens: short-lived (15 min default, configurable via `JWT_EXPIRATION_MINUTES`).
   - Refresh tokens: long-lived (7 days), stored server-side, revocable.

3. **Refresh token storage** (`services/api/repositories/refresh_token_repository.py`)
   - SQL table `refresh_tokens`: id, user_id, token_hash (SHA-256), expires_at, revoked_at.
   - Alembic migration.
   - Interface + mock for testing.

4. **Token revocation endpoint** (`POST /auth/revoke`)
   - Revoke a specific refresh token (logout) or all tokens for a user (force logout).
   - Required for session management and security incident response.

5. **JWKS endpoint** (`GET /auth/jwks`) — *only if migrating to RS256*
   - Exposes public key for asymmetric token verification.
   - If staying with HS256 for now, this endpoint can return 501 with documentation.

6. **Scope enforcement** on protected routes
   - Phase 3 spec defines 10 scopes: `strategies:write`, `runs:write`,
     `promotions:request`, `approvals:write`, `overrides:request`,
     `overrides:approve`, `exports:read`, `feeds:read`, `operator:read`, `audit:read`.
   - `get_current_user` already extracts `role`; need a `require_scope("scope_name")`
     dependency that checks token claims against required scope.
   - Routes that require specific scopes must use `Depends(require_scope("..."))`.

7. **Update `services/api/auth.py`** to include `scope` claim in tokens.

8. **Update frontend `AuthProvider.tsx`** to use real token endpoint.
   - Wire `@auth0/auth0-react` or `oidc-client-ts` to the OIDC discovery endpoint.
   - Implement silent refresh via refresh token.
   - Implement session persistence (store refresh token in httpOnly cookie or secure storage).
   - Implement logout (call revoke endpoint, clear session).

**Acceptance criteria:**
- `GET /.well-known/openid-configuration` returns valid OIDC discovery document.
- `POST /auth/token` with valid credentials returns access + refresh token.
- `POST /auth/token` with `grant_type=refresh_token` returns new access token.
- Access token expires after configured minutes; refresh token extends session.
- `POST /auth/revoke` invalidates refresh token; subsequent refresh fails.
- Frontend `AuthProvider` completes full auth flow against running backend (E2E).
- Authenticated routes redirect to login when session is absent.
- `hasScope("scope")` correctly reflects RBAC scopes from token claims.
- Silent refresh succeeds without user interaction when access token expires.

---

### M14-T9 — Spec-Workplan Gap Closure (P2)  ❌ NOT STARTED

**Purpose:** Address Phase 3 spec requirements that have no corresponding workplan
task. Identified during 2026-04-01 audit comparing spec vs workplan.

**Gap 1: Route-level scope enforcement**
- Spec §7.7 defines 10 scopes and 4 default roles.
- No route currently checks scopes — only checks for a valid token (authentication
  without authorization).
- Deliverable: `require_scope(scope_name)` FastAPI dependency; wire to routes per spec.
- Blocked by: M14-T8 (scope claim in tokens).

**Gap 2: Observability metrics**
- Spec §15 requires Prometheus counters: `approval_requests_total`,
  `override_requests_total`, `chart_cache_hits_total`, `lttb_applied_total`,
  `export_requests_total`.
- No metrics instrumentation exists.
- Deliverable: `services/api/metrics.py` with `prometheus_client` counters;
  `/metrics` endpoint for Prometheus scraping.

**Gap 3: Draft autosave cleanup job**
- Spec §7.5 requires purging autosaves older than 30 days.
- No scheduled cleanup exists.
- Deliverable: Management command or Celery beat task for `draft_autosaves` cleanup.

**Gap 4: Chart cache eviction**
- Spec §7.3 specifies write-once caching for completed runs, partial cache flagging.
- Write-through cache not wired to SQL; no eviction policy documented.
- Deliverable: Wire chart cache to SQL; document eviction policy.

**Gap 5: mypy in GitHub Actions CI**
- mypy runs in pre-commit but NOT in `.github/workflows/ci.yml` quality job.
- Type errors can slip through if pre-commit is bypassed.
- Deliverable: Add mypy step to CI quality job.

**Gap 6: Governance structured log wiring**
- Correlation ID middleware is DONE (T1), but route handlers do not include
  `correlation_id` in their structured log calls yet.
- Deliverable: Update all 17 route files to pass `correlation_id_var.get()` in log extras.
- Note: Partially overlaps with M14-T3 (service layer).

**Gap 7: Override watermark propagation to all 5 surfaces**
- Spec §8.2 requires watermark visible on: run card, readiness page, export metadata,
  strategy version page, approval detail.
- Backend watermark model exists but propagation to all response payloads not confirmed.
- Deliverable: Verify and wire watermark inclusion in all 5 API response shapes.

**Gap 8: Evidence link bare-domain validation**
- Spec M23 acceptance criteria require rejecting bare domains like `https://jira.example.com`
  (must have a path component).
- Current validation allows bare domains.
- Deliverable: Update evidence_link validation to require path component.

**Gap 9: Frontend acceptance test pack**
- Spec §16 defines 28 Playwright E2E test scenarios.
- No frontend tests exist.
- Deliverable: Playwright test infrastructure + test scenarios (M31 scope, documented here
  for tracking).

**Acceptance criteria:**
- Each gap has a corresponding implementation or explicit `# DEFERRED: <milestone>` comment.
- mypy passes in GitHub Actions CI.
- Correlation ID present in all route handler log lines.
- Scope enforcement present on at least one route as proof-of-concept.

---

## Definition of Done

M14 is DONE when ALL of the following are true:

### T1 (Infrastructure) — COMPLETE
- [x] `GET /health` tests DB connectivity and returns 503 on DB failure.
- [x] Migration entrypoint script exists and is wired in Dockerfile.
- [x] POST to any endpoint with body > 512 KB returns 413.
- [x] Governance endpoints rate-limited at 20 req/min.
- [x] Every response carries `X-Correlation-ID`.
- [x] Inline `/health` duplicate removed from `main.py`.

### T2 (Authentication)
- [ ] `services/api/auth.py` exists with `get_current_user()`, `get_optional_user()`, `create_access_token()`.
- [ ] TEST_TOKEN bypass works when `ENVIRONMENT == "test"`.
- [ ] Unauthenticated requests to protected endpoints return 401.
- [ ] Invalid/expired JWT returns 401.
- [ ] `Depends(get_current_user)` wired on all non-public routes.
- [ ] `auth_headers` fixture in `conftest.py`.
- [ ] All 738 existing tests still pass.

### T3 (Service Layer)
- [ ] `services/api/services/governance_service.py` exists with all four methods.
- [ ] `submitter == reviewer` returns 409 on approve/reject endpoints.
- [ ] Override submit is atomic (Override + Watermark + AuditEvent in one transaction).
- [ ] All structured log lines in route handlers include `correlation_id` field.
- [ ] All Pydantic field constraints have manual guards in route handlers.
- [ ] Zero `# Stub:` comments remain in production code paths.

### T4 (Testing & Coverage)
- [ ] `tests/integration/test_sql_repositories.py` exists with tests for all 11 SQL repos.
- [ ] `pytest --cov-fail-under=80` passes.
- [ ] No test uses production database.

### T5 (CI/CD)
- [x] GitHub Actions CI workflow is present and valid.
- [x] `.pre-commit-config.yaml` is present and valid.
- [x] `Makefile` with `make ci` target is present.
- [ ] `mypy` step present in GitHub Actions `quality` job.

### T6 (Stub Wiring)
- [ ] All approval routes call governance service (no hardcoded stubs).
- [ ] `GET /strategies/` wired or explicitly deferred with documented milestone.
- [ ] All remaining stub routes carry `# DEFERRED: <milestone>` comments.

### T7 (Operations Docs)
- [ ] `DEPLOYMENT.md` present with HTTPS, secrets, pool, and pre-flight checklist.
- [ ] `services/api/db.py` reads pool config from env vars.
- [ ] `.env.example` includes all production-required variables.

### T8 (OIDC Auth Provider)
- [ ] OIDC discovery endpoint at `/.well-known/openid-configuration`.
- [ ] Token endpoint (`POST /auth/token`) returns access + refresh tokens.
- [ ] Refresh token flow works (silent refresh without user interaction).
- [ ] Token revocation endpoint (`POST /auth/revoke`) invalidates refresh tokens.
- [ ] `scope` claim included in access tokens.
- [ ] `require_scope()` dependency enforces scope checks on routes.
- [ ] Frontend `AuthProvider.tsx` wired to real OIDC endpoints.
- [ ] Auth E2E test passes against running backend.

### T9 (Spec-Workplan Gap Closure)
- [ ] mypy step added to GitHub Actions CI quality job.
- [ ] Correlation ID present in all route handler structured logs.
- [ ] Scope enforcement on at least one route (proof-of-concept).
- [ ] All gaps documented with implementation or `# DEFERRED: <milestone>` comment.
