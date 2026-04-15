# E2E Test Plan: FXLab Phase 3 Frontend Acceptance

**Status:** Specification only (M14-T9). Implementation deferred to M31.
**Test Framework:** Playwright + pytest-playwright
**Milestone:** M31 (Export UX, Artifact Browser, Acceptance Test Pack)
**Last Updated:** 2026-04-03

---

## 1. Overview

### Purpose
The E2E test suite validates the entire Phase 3 frontend user journey, from authentication through strategy lifecycle, results exploration, governance workflows, and feed monitoring. Tests confirm that:

1. All frontend routes render without errors
2. User interactions trigger correct API calls
3. Data flows correctly from backend APIs to UI
4. Permission boundaries are enforced (RBAC validation)
5. Accessibility requirements are met (keyboard navigation, ARIA labels)
6. Exports preserve lineage metadata
7. Error states are handled gracefully

### Execution Context

**When tests run:**
- **Local development:** `make test-e2e` (optional, requires Playwright browser)
- **CI pipeline:** Mandatory pre-merge gate (blocking)
- **Pre-deploy:** Mandatory smoke test in staging environment before production rollout

**Success criteria:**
- All test scenarios pass (100% pass rate)
- All primary user journeys covered
- No accessibility violations detected
- Coverage includes both happy path and error cases

---

## 2. Technology Stack

### Dependencies
- **Playwright** 1.40+ — Browser automation (Chrome, Firefox, WebKit)
- **pytest-playwright** — Pytest plugin for Playwright integration
- **pytest** — Test runner and assertion framework
- **pydantic** — Response validation against contracts

### Configuration
- **Test timeout:** 30 seconds per test (page interactions only; no artificial delays)
- **Retry policy:** No automatic retries in local runs; 2-retry policy in CI (flake detection)
- **Parallelism:** 4 worker processes in CI; serial in local development
- **Headless mode:** True in CI; False optional in local dev for debugging
- **Trace recording:** Enabled on test failure for debugging

### Environment Setup
- FastAPI backend running at `http://localhost:8000` (or `FXLAB_API_BASE_URL`)
- Frontend dev server or static build at `http://localhost:3000` (or `FXLAB_WEB_BASE_URL`)
- Docker Compose test stack providing postgres, redis, queues
- Seed data factory: fixtures/seed_data.py

### File Organization
```
tests/
  e2e/
    conftest.py                    ← Shared E2E fixtures, API client
    fixtures/
      auth_fixtures.py             ← Login flows, token generation
      api_fixtures.py              ← Backend API mocking / stubbing
      seed_data.py                 ← Test data factories
    test_auth_flow.py              ← Authentication journey (M14-T9 scope)
    test_strategy_lifecycle.py      ← Strategy CRUD and promotion (defer to M31)
    test_results_exploration.py     ← Run results, charts, export (defer to M31)
    test_governance_workflow.py     ← Approvals, overrides, audit (defer to M31)
    test_feed_monitoring.py         ← Feed health, parity, anomalies (defer to M31)
    test_admin_panel.py             ← Admin operations, user management (defer to M31)
    test_accessibility.py           ← Keyboard nav, ARIA labels (defer to M31)
    test_permissions.py             ← RBAC smoke tests (defer to M31)
```

---

## 3. Test Categories & Journeys

### 3a. Authentication Flow (Test First: Local Dev / M14-T9)

**Journey:** Public user → login form → credential validation → token grant → protected route

#### TC-Auth-001: Login with Valid Credentials
- **Description:** User navigates to login, enters valid credentials, receives JWT token
- **Preconditions:**
  - Backend running at `http://localhost:8000`
  - User `test_researcher@fxlab.local` with password `test_password_123` pre-seeded
  - No prior session/token in localStorage
- **Steps:**
  1. Navigate to `/login` (or redirect from protected `/strategy-studio`)
  2. Enter email: `test_researcher@fxlab.local`
  3. Enter password: `test_password_123`
  4. Click "Sign In"
  5. Wait for redirect to `/strategy-studio`
- **Expected Result:**
  - POST `/auth/login` called with correct payload
  - Response includes `access_token`, `token_type: Bearer`, `expires_in`
  - Token stored in localStorage as `fxlab_auth_token`
  - User profile fetched via GET `/auth/profile` (scopes included)
  - Page redirects to `/strategy-studio`
  - No console errors

#### TC-Auth-002: Login with Invalid Credentials
- **Description:** Incorrect password triggers error message, no token issued
- **Preconditions:** Same as TC-Auth-001
- **Steps:**
  1. Navigate to `/login`
  2. Enter email: `test_researcher@fxlab.local`
  3. Enter password: `wrong_password`
  4. Click "Sign In"
  5. Wait for error message
- **Expected Result:**
  - POST `/auth/login` called
  - Response status 401 (Unauthorized)
  - Error banner displayed: "Invalid email or password"
  - No token stored in localStorage
  - User remains on login page

#### TC-Auth-003: Session Expiration & Refresh
- **Description:** Expired token triggers transparent refresh; stale token triggers re-login
- **Preconditions:**
  - Authenticated session with access_token (60 sec TTL for test)
  - refresh_token stored in localStorage
- **Steps:**
  1. Wait 65 seconds (or mock time advance)
  2. Attempt to fetch protected resource (GET `/runs`)
  3. Observe automatic refresh attempt
  4. Verify request succeeds after refresh
- **Expected Result:**
  - First request returns 401
  - Client detects 401, calls POST `/auth/refresh` with refresh_token
  - New access_token issued
  - Original request retried automatically
  - User sees no interruption

#### TC-Auth-004: Logout
- **Description:** Logout clears token and redirects to login
- **Preconditions:** Authenticated session at `/strategy-studio`
- **Steps:**
  1. Click "Sign Out" button (top-right menu)
  2. Confirm logout dialog (if present)
- **Expected Result:**
  - POST `/auth/logout` called (if applicable)
  - localStorage cleared (tokens, session data)
  - User redirected to `/login`
  - Visiting `/strategy-studio` redirects to login

#### TC-Auth-005: Protected Route Access Control
- **Description:** Unauthenticated user cannot access protected route
- **Preconditions:** No token in localStorage
- **Steps:**
  1. Clear localStorage
  2. Attempt to navigate directly to `/strategy-studio`
  3. Observe redirect
- **Expected Result:**
  - User redirected to `/login`
  - Query param `returnTo=/strategy-studio` preserved (optional, for UX)

#### TC-Auth-006: RBAC Scope Validation
- **Description:** User without required scope sees "403 Forbidden" instead of resource
- **Preconditions:**
  - Authenticated as `viewer@fxlab.local` (scope: `read:runs` only, no `write:strategies`)
- **Steps:**
  1. Login with `viewer@fxlab.local`
  2. Navigate to `/strategy-studio`
  3. Attempt to create new strategy
- **Expected Result:**
  - `/strategy-studio` page loads (read-only view)
  - "Create Strategy" button absent from DOM (not disabled, not present)
  - User profile shows scope: `["read:runs"]`
  - Attempting direct POST to `/strategies` returns 403 Forbidden

---

### 3b. Strategy Lifecycle (Defer to M31)

**Journey:** Draft → autosave → preview → promote → approve → live

#### TC-Strategy-001: Create New Draft Strategy
- **Description:** User creates blank strategy, auto-saves as draft
- **Preconditions:**
  - Authenticated with scope `write:strategies`
  - On `/strategy-studio`
- **Steps:**
  1. Click "New Strategy"
  2. Enter name: "Test Strategy A"
  3. Select strategy type: "Mean Reversion"
  4. Observe autosave activity
  5. Leave form for 30 seconds
- **Expected Result:**
  - Draft created with ID (ULID)
  - POST `/strategies/draft/autosave` called every 10 seconds
  - Draft stored in backend (persisted across page reload)
  - No validation errors shown

#### TC-Strategy-002: Autosave Recovery on Reconnect
- **Description:** User regains connection; draft is restored
- **Preconditions:**
  - Draft exists in backend (TC-Strategy-001 completed)
  - User session disconnected (simulated)
- **Steps:**
  1. Simulate network offline
  2. Edit strategy form (changes queued locally)
  3. Simulate network online
  4. Observe recovery flow
- **Expected Result:**
  - Recovery banner shown: "We found an unsaved draft. Restore or discard?"
  - Click "Restore" → form populated with draft data + local changes
  - Click "Discard" → form cleared, only backend draft used

#### TC-Strategy-003: Promote Draft to Research
- **Description:** User submits draft for research optimization
- **Preconditions:**
  - Draft exists with valid spec (TC-Strategy-001)
  - Scope: `write:strategies`
- **Steps:**
  1. Open draft detail page
  2. Click "Promote to Research"
  3. Optional: add notes, select parameters
  4. Click "Submit"
  5. Observe job submission flow
- **Expected Result:**
  - POST `/promotions/request` called with draft_id, parameters, notes
  - Promotion created with status: `PENDING_APPROVAL`
  - User shown confirmation: "Promotion submitted"
  - Page redirects to promotion detail page

#### TC-Strategy-004: Promotion Approval
- **Description:** Approver reviews and approves promotion
- **Preconditions:**
  - Promotion exists (status: PENDING_APPROVAL) from TC-Strategy-003
  - Authenticated as `approver@fxlab.local` (scope: `approve:strategies`)
- **Steps:**
  1. Navigate to `/approvals`
  2. Find promotion in list
  3. Click to open detail
  4. Review strategy spec, parameter choices
  5. Click "Approve"
  6. Confirm action
- **Expected Result:**
  - GET `/approvals/{promotion_id}` returns full spec
  - POST `/approvals/{promotion_id}/approve` called
  - Status updated to `APPROVED`
  - Research job enqueued (visible in `/queues`)
  - Original requester notified (audit trail visible)

#### TC-Strategy-005: Override Request During Research
- **Description:** User requests override of research results
- **Preconditions:**
  - Run exists in status `COMPLETED` (from approved promotion)
  - Authenticated with scope `request:overrides`
- **Steps:**
  1. Navigate to `/runs/{run_id}/results`
  2. Observe candidate recommendations
  3. Click "Request Override" on non-preferred candidate
  4. Fill form: reason, evidence link, justification
  5. Click "Submit Override Request"
- **Expected Result:**
  - POST `/overrides/request` called with run_id, candidate_id, reason, evidence_link
  - Override created with status: `PENDING_APPROVAL`
  - User redirected to `/overrides/{override_id}`
  - Watermark begins showing on run results

#### TC-Strategy-006: Override Approval & Deployment
- **Description:** Approver reviews override; deployment proceeds with watermark
- **Preconditions:**
  - Override exists (status: PENDING_APPROVAL) from TC-Strategy-005
  - Authenticated as `approver@fxlab.local`
- **Steps:**
  1. Navigate to `/approvals`
  2. Find override in list
  3. Click to review evidence_link
  4. Click "Approve Override"
  5. Confirm
- **Expected Result:**
  - GET `/overrides/{override_id}` returns all fields
  - POST `/approvals/{override_id}/approve` called
  - Status updated to `APPROVED`
  - Watermark persists: "Deployed with override ID: <id>"
  - Audit trail includes approver, timestamp, evidence_link

---

### 3c. Results Exploration (Defer to M31)

**Journey:** View run → inspect charts → check readiness → export data

#### TC-Results-001: View Run Results Page
- **Description:** User navigates to completed run, sees charts, metrics, recommendations
- **Preconditions:**
  - Run exists with status `COMPLETED`
  - Run has equity curve data (1000+ bars)
  - Authenticated with scope `read:runs`
- **Steps:**
  1. Navigate to `/runs/{run_id}/results`
  2. Observe page load and chart rendering
  3. Scroll through charts (equity, drawdown, trade blotter)
- **Expected Result:**
  - GET `/runs/{run_id}/results` called
  - GET `/runs/{run_id}/charts` called (includes sampling_applied flag)
  - Equity curve rendered (downsampled to ≤2000 points via LTTB)
  - sampling_applied: true shown as notice if applicable
  - Trade blotter table paginated (≤50 rows per page)
  - Readiness status badge shows pass/fail/warnings

#### TC-Results-002: Chart Downsampling
- **Description:** High-frequency run returns downsampled chart data
- **Preconditions:**
  - Run has 10,000+ equity curve bars
- **Steps:**
  1. Fetch `/runs/{run_id}/charts/equity`
  2. Inspect response envelope
  3. Verify point count ≤ 2000
- **Expected Result:**
  - Response includes `sampling_applied: true`
  - First and last bars preserved
  - Peak-to-trough accuracy maintained (max value in output ≥ max in input)
  - No visible gaps or artifacts in chart

#### TC-Results-003: Export Run Data
- **Description:** User downloads results as CSV zip with metadata
- **Preconditions:**
  - Run exists with results
  - Authenticated with scope `read:runs`
- **Steps:**
  1. Click "Export Results" button
  2. Select format: "CSV (with metadata)"
  3. Observe download button enable
  4. Click "Download"
  5. Unzip file locally (simulated in test)
- **Expected Result:**
  - POST `/exports` called with run_id, format
  - Export queued with status `PENDING`
  - GET `/exports/{export_id}` polled until status: `COMPLETED`
  - Zip file downloaded: `results_<run_id>_<timestamp>.zip`
  - Zip contains:
    - `data.csv` (no comment rows)
    - `metadata.json` (includes run_id, export_schema_version, override_watermarks)
    - `README.txt` (lineage explanation)

#### TC-Results-004: Export with Active Override
- **Description:** Export includes override watermark metadata
- **Preconditions:**
  - Run has approved override (status: `APPROVED`)
  - Export triggered
- **Steps:**
  1. Click "Export Results"
  2. Observe metadata preview before download
  3. Download and inspect `metadata.json`
- **Expected Result:**
  - `metadata.json` includes: `override_watermarks: [{id, approver, timestamp, reason}]`
  - CSV data unchanged (no additional columns)
  - README explicitly notes override used

#### TC-Results-005: Readiness Report Display
- **Description:** User views pre-deployment readiness checklist
- **Preconditions:**
  - Run exists; readiness report generated
- **Steps:**
  1. Click "Readiness" tab on run page
  2. Scroll through checklist items
  3. Click on a failed item to see diagnostic
- **Expected Result:**
  - GET `/runs/{run_id}/readiness` called
  - Report displays pass/fail/warning for each check
  - Failed checks include diagnostic details, remediation hints
  - No local computation; all state from backend

---

### 3d. Governance Workflow (Defer to M31)

**Journey:** Request → approval → status tracking → audit trail

#### TC-Governance-001: View Approvals Dashboard
- **Description:** Approver sees pending approvals, filters, and details
- **Preconditions:**
  - Authenticated as `approver@fxlab.local`
  - 2+ pending approvals in system
- **Steps:**
  1. Navigate to `/approvals`
  2. Observe list of pending items
  3. Filter by type: "Promotions" only
  4. Click on one to view detail
- **Expected Result:**
  - GET `/approvals` called (or paginated list endpoint)
  - List shows: type, requester, created_at, status
  - Filter applied server-side: GET `/approvals?type=promotion`
  - Detail page shows full spec and edit decision

#### TC-Governance-002: Rejection Flow
- **Description:** Approver rejects promotion with explanation
- **Preconditions:**
  - Pending promotion exists
- **Steps:**
  1. Open promotion detail
  2. Click "Reject"
  3. Enter rejection reason
  4. Click "Confirm Rejection"
- **Expected Result:**
  - POST `/approvals/{id}/reject` called with reason
  - Status updated to `REJECTED`
  - Requester notified (audit event created)
  - Page shows rejection timestamp and reason

#### TC-Governance-003: Override Request Tracking
- **Description:** User tracks pending and completed overrides
- **Preconditions:**
  - Authenticated with scope `read:overrides`
- **Steps:**
  1. Navigate to `/overrides`
  2. View list of requests (pending + approved)
  3. Filter by status: "Pending"
  4. Click on pending override to view detail
- **Expected Result:**
  - GET `/overrides` returns list with status, created_at, run_id
  - Detail page shows: run, candidate, reason, evidence_link, approval status
  - Pending approvals show "Waiting for approval from..."
  - Approved overrides show approver and timestamp

#### TC-Governance-004: Audit Trail Query
- **Description:** User searches audit trail for governance actions
- **Preconditions:**
  - Authenticated with scope `read:audit`
- **Steps:**
  1. Navigate to `/audit`
  2. Filter by: action_type = "approval", target_type = "promotion"
  3. Select date range (last 7 days)
  4. Click "Search"
  5. Click on an event to view detail
- **Expected Result:**
  - GET `/audit?action_type=approval&target_type=promotion&from=...&to=...` called
  - Results paginated with cursor support
  - Each event shows: actor, action, target, timestamp, metadata
  - Detail view shows all metadata JSON

---

### 3e. Feed Monitoring (Defer to M31)

**Journey:** View feeds → health dashboard → parity events → anomalies

#### TC-Feeds-001: Feed Registry Page
- **Description:** User views list of registered feeds
- **Preconditions:**
  - 3+ feeds exist in system
  - Authenticated with scope `read:feeds`
- **Steps:**
  1. Navigate to `/feeds`
  2. Observe feed list
  3. Click on one feed to view detail
  4. View version history
- **Expected Result:**
  - GET `/feeds` called
  - List shows: name, status, last_sync, provider
  - Detail page shows: config, version history, connectivity test results
  - No local computation of status

#### TC-Feeds-002: Feed Health Dashboard
- **Description:** Operator monitors feed health: anomalies, certification, parity
- **Preconditions:**
  - Feeds exist with health snapshots
- **Steps:**
  1. Navigate to `/feeds`
  2. Click "Health Dashboard"
  3. Observe feed health cards (anomaly flags, certification status)
  4. Click on feed with anomaly
- **Expected Result:**
  - GET `/feed-health` called
  - Dashboard shows per-feed: anomaly_count, certification_status, last_sync
  - Red badge on feeds with anomalies or blocked certification
  - Click-through shows anomaly details and diagnostic steps

#### TC-Feeds-003: Parity Events Dashboard
- **Description:** User views parity discrepancies between official and shadow feeds
- **Preconditions:**
  - Parity events exist in system
- **Steps:**
  1. Navigate to `/parity`
  2. Observe event list (critical, warning, info)
  3. Filter by severity: "CRITICAL"
  4. Click on event to view detail
  5. Click on evidence/chart to view discrepancy
- **Expected Result:**
  - GET `/parity/events` called
  - GET `/parity/summary` called (shows count per severity per instrument)
  - Filter by severity applied server-side
  - Detail shows: official_value, shadow_value, divergence_pct, feeds involved

#### TC-Feeds-004: Anomaly & Certification Viewer
- **Description:** User views blocked feeds and reasons
- **Preconditions:**
  - Feeds exist with blocked certification (anomalies unresolved)
- **Steps:**
  1. Navigate to `/data/certification`
  2. View certification status per feed
  3. Click on BLOCKED feed to see reason
  4. Click "Resolve" to see remediation steps
- **Expected Result:**
  - GET `/data/certification` called
  - Lists: feed_id, status, last_check, anomaly_count
  - Blocked feeds show: anomaly IDs, severity, age
  - Remediation steps provided (e.g., "Re-verify feed connectivity", "Check data schema")

#### TC-Feeds-005: Feed-Blocker for Strategy Promotion
- **Description:** Research launch blocked if promoted strategy uses feeds with unresolved anomalies
- **Preconditions:**
  - Draft strategy uses feeds with blocked certification
  - User attempts to promote
- **Steps:**
  1. Open draft detail
  2. Identify dependent feeds
  3. Click "Promote to Research"
  4. Observe validation
- **Expected Result:**
  - Validation error: "Cannot promote: dependent feeds have unresolved anomalies: Feed X, Feed Y"
  - Remediation hint: "Resolve anomalies or select alternate feeds"
  - Promotion blocked until anomalies cleared or feeds changed

---

### 3f. Admin Panel (Defer to M31)

**Journey:** Manage users, secrets, permissions, system config

#### TC-Admin-001: User Management
- **Description:** Admin views and manages user accounts
- **Preconditions:**
  - Authenticated as `admin@fxlab.local` (scope: `admin:users`)
- **Steps:**
  1. Navigate to `/admin/users`
  2. View user list (paginated)
  3. Click on user to edit
  4. Update scopes: add `approve:strategies`
  5. Click "Save"
- **Expected Result:**
  - GET `/admin/users` called
  - List shows: email, scopes, created_at, last_login
  - Detail view allows scope editing
  - POST `/admin/users/{user_id}/scopes` called with updated scopes
  - Audit event created for scope change

#### TC-Admin-002: Secrets Management
- **Description:** Admin manages API keys for external feeds
- **Preconditions:**
  - Admin user authenticated
- **Steps:**
  1. Navigate to `/admin/secrets`
  2. Click "Add Secret"
  3. Enter: feed_name, api_key (masked)
  4. Click "Save"
  5. Verify secret in list (masked)
- **Expected Result:**
  - Secret never shown in plaintext in response or UI
  - POST `/admin/secrets` called
  - Response includes: id, feed_name, created_at, last_rotated
  - UI shows masked value: "••••••••"
  - Audit log records creation but not the secret value

#### TC-Admin-003: System Health Check
- **Description:** Admin views system dependencies and diagnostics
- **Preconditions:**
  - Admin authenticated
- **Steps:**
  1. Navigate to `/admin/health`
  2. Observe dependency status (database, queue, artifact store)
  3. Observe diagnostics snapshot (queue contention, critical alerts)
- **Expected Result:**
  - GET `/health/dependencies` called
  - Shows: name, status (OK/DEGRADED/DOWN), latency_ms
  - GET `/health/diagnostics` called
  - Shows: queue_contention_count, feed_health_count, parity_critical_count, certification_blocked_count

---

## 4. Infrastructure & Environment

### Docker Compose Test Stack

```yaml
# docker-compose.test.yml
version: '3.9'
services:
  api:
    image: fxlab-api:latest
    ports:
      - "8000:8000"
    environment:
      DATABASE_URL: postgresql://postgres:postgres@postgres:5432/fxlab_test
      REDIS_URL: redis://redis:6379/0
      JWT_SECRET: test_secret_key_do_not_use_in_prod
      LOG_LEVEL: INFO
    depends_on:
      postgres:
        condition: service_healthy
      redis:
        condition: service_healthy

  postgres:
    image: postgres:15-alpine
    environment:
      POSTGRES_DB: fxlab_test
      POSTGRES_PASSWORD: postgres
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U postgres"]
      interval: 5s
      timeout: 5s
      retries: 5

  redis:
    image: redis:7-alpine
    healthcheck:
      test: ["CMD", "redis-cli", "ping"]
      interval: 5s
      timeout: 5s
      retries: 5

  celery:
    image: fxlab-api:latest
    command: celery -A services.api.celery_app worker --loglevel=info
    depends_on:
      - redis

  web:
    image: fxlab-web:latest
    ports:
      - "3000:3000"
    environment:
      REACT_APP_API_BASE_URL: http://localhost:8000
    depends_on:
      - api
```

### Seed Data

Fixtures provide consistent test data:

```python
# tests/e2e/fixtures/seed_data.py

@pytest.fixture
def seed_users(api_client):
    """Create test users with various scopes."""
    return {
        "researcher": create_user(
            email="test_researcher@fxlab.local",
            password="test_password_123",
            scopes=["write:strategies", "read:runs", "request:overrides"]
        ),
        "approver": create_user(
            email="approver@fxlab.local",
            password="test_password_123",
            scopes=["approve:strategies", "approve:overrides"]
        ),
        "viewer": create_user(
            email="viewer@fxlab.local",
            password="test_password_123",
            scopes=["read:runs", "read:feeds"]
        ),
        "admin": create_user(
            email="admin@fxlab.local",
            password="test_password_123",
            scopes=["admin:users", "admin:secrets", "admin:system"]
        ),
    }

@pytest.fixture
def seed_strategies(seed_users, api_client):
    """Create test strategies."""
    researcher_token = authenticate(seed_users["researcher"]["email"], "test_password_123")
    return {
        "draft_a": create_strategy(
            token=researcher_token,
            name="Mean Reversion Strategy",
            type="mean_reversion",
            status="DRAFT"
        ),
        "draft_b": create_strategy(
            token=researcher_token,
            name="Momentum Strategy",
            type="momentum",
            status="DRAFT"
        ),
    }

@pytest.fixture
def seed_runs(seed_strategies, api_client):
    """Create completed runs with results."""
    return {
        "run_001": create_run(
            strategy_id=seed_strategies["draft_a"]["id"],
            status="COMPLETED",
            equity_curve=generate_equity_curve(bars=10000),  # LTTB-eligible
            trades=generate_trades(count=1000)
        ),
        "run_002": create_run(
            strategy_id=seed_strategies["draft_b"]["id"],
            status="COMPLETED",
            equity_curve=generate_equity_curve(bars=500),    # Below LTTB threshold
            trades=generate_trades(count=50)
        ),
    }

@pytest.fixture
def seed_feeds(api_client):
    """Create registered feeds with health snapshots."""
    return {
        "feed_001": create_feed(
            name="Equity Feed A",
            provider="data_vendor_x",
            status="HEALTHY"
        ),
        "feed_002": create_feed(
            name="Equity Feed B",
            provider="data_vendor_y",
            status="ANOMALY_DETECTED",
            anomaly_count=3
        ),
        "feed_003": create_feed(
            name="Forex Feed",
            provider="data_vendor_z",
            status="BLOCKED_CERTIFICATION"
        ),
    }
```

### Database Migrations

- All migrations idempotent and reversible
- Test database seeded from migration baseline
- Cleanup: drop test DB after suite completion (handled by CI fixture)

---

## 5. Test Implementation Guidelines (Deferred to M31)

This section specifies how tests will be implemented; implementation itself is deferred.

### Naming & Organization

Test files follow naming convention: `test_<feature>_<scenario>.py`

```python
# tests/e2e/test_auth_flow.py

import pytest
from playwright.async_api import async_playwright, Page
from src.contracts.auth import LoginRequest, AuthResponse


@pytest.mark.e2e
class TestAuthFlow:
    """End-to-end tests for authentication journeys."""

    @pytest.mark.asyncio
    async def test_login_with_valid_credentials(
        self,
        page: Page,
        seed_users: dict,
        api_base_url: str,
        web_base_url: str,
    ):
        """TC-Auth-001: User logs in with valid credentials."""
        # Setup
        user = seed_users["researcher"]

        # Navigate to login
        await page.goto(f"{web_base_url}/login")

        # Fill form
        await page.fill('input[name="email"]', user["email"])
        await page.fill('input[name="password"]', user["password"])

        # Submit
        await page.click('button[type="submit"]')

        # Assertions
        await page.wait_for_url("**/strategy-studio", timeout=10000)

        # Verify token stored
        token = await page.evaluate('localStorage.getItem("fxlab_auth_token")')
        assert token is not None
        assert "." in token  # JWT format: header.payload.signature
```

### Assertions & Validation

Tests validate:
1. **Navigation:** Expected URL after action
2. **DOM state:** Element presence, visibility, content
3. **API calls:** Endpoint, method, payload, response status
4. **Data flow:** Backend state matches frontend display
5. **Accessibility:** ARIA labels, keyboard navigation, focus management

```python
    @pytest.mark.asyncio
    async def test_login_invalid_credentials(
        self,
        page: Page,
        api_base_url: str,
        web_base_url: str,
    ):
        """TC-Auth-002: Invalid credentials trigger error."""
        await page.goto(f"{web_base_url}/login")

        # Submit invalid credentials
        await page.fill('input[name="email"]', "test_researcher@fxlab.local")
        await page.fill('input[name="password"]', "wrong_password")
        await page.click('button[type="submit"]')

        # Assertions
        error_banner = await page.query_selector('[role="alert"]')
        assert error_banner is not None
        error_text = await error_banner.text_content()
        assert "Invalid email or password" in error_text

        # No token stored
        token = await page.evaluate('localStorage.getItem("fxlab_auth_token")')
        assert token is None
```

### Error & Edge Case Coverage

Every test includes:
- **Happy path:** Primary user journey succeeds
- **Validation errors:** Invalid input caught, message displayed
- **Network errors:** Graceful degradation (retry, offline banner)
- **Permission boundaries:** RBAC enforced at UI and API
- **Concurrency:** Multiple actions in sequence (e.g., autosave + promotion)
- **Accessibility:** Keyboard-only navigation possible

---

## 6. Continuous Integration

### Pre-Merge Gate

```yaml
# .github/workflows/e2e.yml (M31 implementation)

name: E2E Test Suite
on:
  pull_request:
    branches: [main, develop]
  push:
    branches: [main, develop]

jobs:
  e2e:
    runs-on: ubuntu-latest
    timeout-minutes: 15
    steps:
      - uses: actions/checkout@v3
      - uses: actions/setup-python@v4
        with:
          python-version: "3.11"
      - uses: actions/setup-node@v3
        with:
          node-version: "18"

      - name: Install dependencies
        run: |
          pip install -r requirements-dev.txt
          npm install

      - name: Start Docker Compose stack
        run: docker-compose -f docker-compose.test.yml up -d

      - name: Wait for services
        run: |
          npx wait-on http://localhost:8000/health
          npx wait-on http://localhost:3000

      - name: Run E2E tests
        run: python -m pytest tests/e2e -v --tb=short -n 4 --reruns 2

      - name: Upload traces on failure
        if: failure()
        uses: actions/upload-artifact@v3
        with:
          name: playwright-traces
          path: test-results/

      - name: Publish results
        if: always()
        run: |
          python -m pytest tests/e2e --html=report.html --self-contained-html

      - name: Comment PR with results
        if: always()
        uses: actions/github-script@v6
        with:
          script: |
            const fs = require('fs');
            const report = fs.readFileSync('report.html', 'utf8');
            // Parse and comment on PR with summary
```

### Staging Smoke Test

Pre-deploy validation (before production rollout):

```bash
# scripts/smoke-test.sh

#!/bin/bash
set -e

STAGING_API_URL="https://staging-api.fxlab.local"
STAGING_WEB_URL="https://staging.fxlab.local"

export FXLAB_API_BASE_URL="$STAGING_API_URL"
export FXLAB_WEB_BASE_URL="$STAGING_WEB_URL"

# Run critical path tests only (auth, strategy CRUD, export)
python -m pytest tests/e2e/test_auth_flow.py -v --tb=short -m "critical"
python -m pytest tests/e2e/test_strategy_lifecycle.py::TestStrategyLifecycle::test_promote_to_research -v
python -m pytest tests/e2e/test_results_exploration.py::TestResultsExploration::test_export_run_data -v

echo "Smoke test passed. Safe to deploy."
```

---

## 7. Success Metrics & Reporting

### Coverage Requirements

- **Route coverage:** All Phase 3 frontend routes tested (20+ routes)
- **Journey coverage:** All 6 user journeys tested end-to-end
- **Error paths:** Happy path + 2+ error scenarios per feature
- **RBAC coverage:** Each major action tested with missing scope
- **Accessibility:** All primary interactive elements navigable via keyboard

### Pass Criteria

- 100% pass rate (no flaky tests)
- All assertions pass without modification
- No console errors or warnings in browser devtools
- Network traffic matches expected API contract
- Page load times < 3 seconds (excluding external data fetches)

### Reporting

Tests generate:
- **HTML report** with screenshots, execution times, pass/fail summary
- **Junit XML** for CI integration (GitHub Actions, GitLab CI)
- **Trace artifacts** (screenshots, video on failure) uploaded to CI storage
- **Performance report:** Page load times, API latency percentiles

Example summary output:
```
========= E2E Test Results (M31) =========
Platform: ubuntu-latest | Node: 18 | Python: 3.11
Executed:  65 tests in 4m 32s (4 workers, 2 retries)
Passed:    65 (100%)
Failed:    0
Skipped:   0
Flaky:     0

Routes tested:        20/20 (100%)
API endpoints mocked: 23/23 (100%)
RBAC scenarios:       18/18 (100%)
Accessibility:        8/8 pass

Browser coverage:     Chrome, Firefox (WebKit deferred to M31.2)

Next: Deploy to staging and run smoke-test.sh before prod rollout.
========================================
```

---

## 8. Notes for Implementers (M31)

### Known Gaps & Deferrals

1. **WebKit coverage:** Deferred to M31.2 (Friday after M31 completion). Webkit performance in CI requires investigation.
2. **Performance testing:** Load testing (> 100 concurrent users) deferred to Phase 4.
3. **Visual regression:** Screenshot diffing deferred pending design system stabilization (M22 completion).
4. **A/B testing coverage:** Not in scope for M31; feature flag coverage deferred to Phase 4.

### Common Pitfalls to Avoid

- **Flakiness:** Always wait for elements with explicit condition, not arbitrary sleep. Use `page.wait_for_selector()`, `page.wait_for_url()`, `page.wait_for_load_state()`.
- **Token management:** Always mock token refresh; never rely on real backend token TTL timing in tests.
- **Date/time:** Use fixed test dates for reproducibility; never rely on `Date.now()` in tests.
- **Audit trail:** E2E tests create real audit events; include cleanup fixture to prevent audit table bloat.
- **Seed data isolation:** Each test should be independent; use fresh seed data per test (not shared state).

### Resources for Implementers

- **Playwright docs:** https://playwright.dev/python/ (official)
- **pytest-playwright:** https://playwright.dev/python/docs/pytest
- **CLAUDE.md §5 (TDD):** Test first, implementation second; use RED-GREEN-REFACTOR cycle
- **CLAUDE.md §4 (Onion Architecture):** Controllers delegate to services; services call mocks/stubs in E2E
- **CLAUDE.md §7 (Code Commenting):** Every test class/method must have docstring (purpose + preconditions + expected result)

---

## 9. Acceptance Criteria for M31

A feature is **DONE** only when:

- [ ] All test scenarios (TC-Auth-001 through TC-Admin-003) pass
- [ ] 100% pass rate; zero flaky tests (retry policy: 2 in CI only)
- [ ] Coverage >= 80% for new frontend code
- [ ] All routes render without console errors
- [ ] RBAC smoke test: all major actions tested with missing scope
- [ ] Accessibility: keyboard navigation verified for primary surfaces
- [ ] Export testing: zip creation verified (data.csv + metadata.json + README.txt)
- [ ] Performance: page load times < 3 seconds
- [ ] CI pipeline green: E2E suite runs in < 10 minutes (4 workers)
- [ ] Staging smoke test passes before prod deployment
- [ ] HTML report generated and uploaded to CI artifacts
- [ ] All test code documented (docstrings on classes and methods)
- [ ] No `TODO` without ticket ID in test code

---

**End of E2E Test Plan**

Document version: 1.0
Created: 2026-04-03
Classification: Internal — Specification Only (Implementation M31)
