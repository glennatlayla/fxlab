<!-- WORKPLAN INTEGRITY HEADER (per CLAUDE.md §16)
     Source file:            User Spec/FXLab_Phase_3_workplan_v1_1.md
     Source milestone count: 11
     Source milestone IDs:   M0, M22, M23, M24, M25, M26, M27, M28, M29, M30, M31

     Milestones in this file: M22, M23 (completion only), M24 (completion only),
                               M25, M26, M27, M28, M29, M30, M31
     Milestones DEFERRED:    M0 (bootstrap — DONE, see backend distilled file)
                              M23 backend portions — see FXLab_Phase_3_workplan_v1_1.distilled.md

     Integrity check: 10 milestones referenced + M0 deferred = 11 = source_count ✓

     Purpose: This file is the implementation context source for the Phase 3 frontend track.
     Load this file alongside the backend distilled file for complete Phase 3 context.
     Generated: 2026-03-28T12:00:00Z
-->

# FXLab Phase 3 — Frontend Track Distillation
# Source: FXLab_Phase_3_workplan_v1_1.md  (M22–M31)
# Status: M22–M31 NOT_STARTED (backend M23/M24 PARTIAL — see issues log)

---

## MILESTONE INDEX

```
MILESTONE INDEX
───────────────────────────────────────────────────────────────────
Total source milestones: 11  (M0, M22–M31)
This file covers:        10  (M22–M31 + completion notes for M23/M24)
Deferred to backend distilled file: M0 (DONE)

Frontend track (all NOT_STARTED):
  M22  Frontend Foundation — App Shell, Design System, Auth Integration
  M25  Strategy Studio and Blueprint UX               [blocks: M22]
  M26  Run Monitor and Optimization Progress          [blocks: M25]
  M27  Results Explorer                               [blocks: M26, M24]
  M28  Readiness Report Viewer                        [blocks: M27]
  M29  Governance Workflows Frontend                  [blocks: M22, M23, M28]
  M30  Feed Operations, Parity, Operator Dashboards   [blocks: M22, M24]
  M31  Export UX, Artifact Browser, Acceptance Pack   [blocks: M29, M30]

Backend completion required before frontend:
  M23  Governance Backend APIs     PARTIAL — 4 endpoints missing (see §M23 below)
  M24  Chart/Queue/Feed Health     PARTIAL — see §M24 below
───────────────────────────────────────────────────────────────────
```

---

## DEPENDENCY ORDER

```
M22 (Foundation)
  └── M25 (Strategy Studio)
        └── M26 (Run Monitor)
              └── M27 (Results Explorer) ─────── also needs M24
                    └── M28 (Readiness Viewer)
                          └── M29 (Governance Frontend) ─── also needs M22 + M23
                                └── M31 (Export + Sign-off) ─ also needs M30
M22 + M24
  └── M30 (Feed Ops / Parity / Audit) ───────────── feeds M31

M23 + M24 must be complete before M29 and M30 respectively.
```

---

## BACKEND GAPS BLOCKING FRONTEND (resolve before M23/M24 frontend work)

The following endpoints are defined in the source workplan M23 spec but are not yet
implemented. They must exist before M29 (Governance Frontend) can begin.

| Endpoint | Milestone | Status |
|---|---|---|
| `POST /approvals/{id}/reject` | M23 | MISSING |
| `POST /overrides/request` | M23 | MISSING |
| `GET /overrides/{id}` | M23 | MISSING |
| `POST /strategies/draft/autosave` | M23 | MISSING |
| `GET /strategies/draft/autosave/latest` | M23 | MISSING |
| `DELETE /strategies/draft/autosave/{id}` | M23 | MISSING |
| `evidence_link` URI validation on override requests | M23 | MISSING |

**These must be implemented and tested before M25 (draft autosave) and M29 (approvals UI).**

---

## MILESTONE: M22 — Frontend Foundation

### Objective
Establish the frontend application skeleton, design system, auth flow, and typed API
client layer. Every subsequent frontend milestone builds on this foundation without
modifying it.

### Key Constraints
- Vite + React 18 + TypeScript 5 with `strict: true`
- Tailwind CSS with project color tokens (no inline styles on reusable components)
- Auth uses Phase 1 OIDC — NOT a stub. `AuthProvider.tsx` must call real token endpoint.
- `useAuth` hook exposes: `user`, `permissions`, `hasScope(scope)`, `logout()`
- `AuthGuard` blocks unauthenticated routes and handles 403 gracefully
- Typed API client generated from OpenAPI spec; extended with Phase 3 endpoints
- TanStack Query with global error handling and retry policy
- Chart engine hook: `useChartEngine(dataLength)` → `"recharts"` if ≤ 500, `"echarts"` if > 500

### Deliverables
- ESLint + Prettier + pre-commit hooks matching backend quality gates
- Shell layout: authenticated sidebar, top bar, breadcrumbs, toast notification system
- Base components: `LoadingState`, `EmptyState`, `ErrorState`, `StatusBadge`,
  `OverrideBanner`, `BlockerSummary` (with owner card + next-step button),
  `DraftRecoveryBanner`
- Vitest + @testing-library/react + MSW configured
- Playwright configured with authenticated test fixture
- CI script: type-check → lint → test → build
- Navigation routes wired with placeholders for all M25–M31 pages

### Acceptance Criteria
- `npm run build` produces type-error-free production bundle
- Auth flow completes end-to-end against running backend in E2E test
- Authenticated routes redirect to login when session absent
- `hasScope` correctly reflects Phase 1/3 RBAC scopes from token claims
- `useChartEngine(400)` returns `"recharts"`; `useChartEngine(600)` returns `"echarts"` in unit test
- `BlockerSummary` renders owner display name and next-step button for known code;
  raw code + fallback for unknown code
- All base components render without errors in Vitest smoke test
- CI gate passes in under 3 minutes on cold run

### Current State (as of 2026-03-28)
- `frontend/` directory exists at project root — ✓
- `frontend/src/App.tsx`, `router.tsx`, `main.tsx` — ✓ (stubs)
- `frontend/src/api/client.ts` — ✓ (axios shell, no typed methods)
- `frontend/src/auth/AuthProvider.tsx` — ⚠ FAKE STUB (login() just calls setIsAuthenticated(true))
- `frontend/src/pages/*.tsx` — ✓ 9 files exist, all `<h1>` placeholders
- `frontend/src/features/` — ✓ directories exist, all EMPTY
- `frontend/src/components/Layout.tsx` — ✓ exists
- ESLint/Prettier/pre-commit — ✗ NOT CONFIGURED
- Tailwind tokens — ✗ NOT CONFIGURED
- `useAuth` hook — ✗ NOT IMPLEMENTED
- `AuthGuard` — ✗ NOT IMPLEMENTED
- `BlockerSummary`, `OverrideBanner`, etc. — ✗ NOT IMPLEMENTED
- Vitest + MSW — ✗ NOT CONFIGURED
- Playwright — ✗ NOT CONFIGURED (playwright.config.ts stub only)

**M22 work required**: replace all stubs with real implementations.

---

## MILESTONE: M23 — Governance Backend APIs (COMPLETION NOTES)

### Status: PARTIAL
The distilled backend track (M0–M12) implemented the governance infrastructure but missed
these M23 deliverables. Complete before M25 and M29.

### Missing Endpoints (implement before M25/M29)
```
POST /approvals/{id}/reject          — approval rejection action
POST /overrides/request              — override request submission
GET  /overrides/{id}                 — override detail retrieval
POST /strategies/draft/autosave      — save draft payload server-side
GET  /strategies/draft/autosave/latest — most recent draft for authenticated user (30-day window)
DELETE /strategies/draft/autosave/{id} — discard a specific autosave
```

### Missing Validation
- `evidence_link` on override requests must be a full absolute HTTP/HTTPS URI with a path
  (not just a root URL). Returns 422 with field-level error if missing or invalid.
- `draft_autosaves` DB table and Alembic migration — not yet created.
- Override watermark creation on override approval — verify this fires.

### Acceptance Criteria (from source M23)
- Override request with missing `evidence_link` → 422 with field-level error
- Override request with bare root URL `evidence_link` → 422 (must be full path)
- Submitter cannot approve own request → `SEPARATION_OF_DUTIES` error
- Draft autosave round-trip: POST → GET /latest returns same payload
- All new migrations upgrade and downgrade cleanly
- Service layer coverage ≥ 90%

---

## MILESTONE: M24 — Chart/Queue/Feed Health Backend (COMPLETION NOTES)

### Status: PARTIAL (backend portions substantially done via distilled M7/M8)

### Verify before M27/M30
- LTTB: output ≤ 2 000 points; first/last preserved; `sampling_applied` flag present
- `chart_cache_entries` migration and write-through cache — verify existence
- `chart_endpoint` for > 5 000 trades returns `trades_truncated: true` and `total_trade_count`
- Queue contention endpoint returns correct structure for all Phase 2 queue classes

---

## MILESTONE: M25 — Strategy Studio and Blueprint UX

### Objective
Build the non-technical strategy creation surface with draft persistence, blueprint
review, uncertainty explainer, and parameter bounds form.

### Key Constraints
- `StrategyDraftForm` uses React Hook Form + Zod
- localStorage autosave on every field change (debounced 500 ms)
- Backend sync every 30 s via `DraftAutosaveManager` — calls `POST /strategies/draft/autosave`
- Draft recovery: `GET /strategies/draft/autosave/latest` on page load; show `DraftRecoveryBanner`
  only if a recoverable draft exists — "Restore draft" and "Start fresh" buttons ONLY,
  no implicit auto-restore
- "Start fresh" calls `DELETE /strategies/draft/autosave/{id}` AND clears localStorage
- `BlockerSummary` with owner card and `resolve_uncertainty` next-step when `MATERIAL_AMBIGUITY`

### Deliverables
- `StrategyStudioPage` at `/strategy-studio`
- `StrategyDraftForm` — full field set wired to `POST /strategies/draft`
- `DraftAutosaveManager` — background sync every 30 s
- `DraftRecoveryBanner` — conditional on `GET /strategies/draft/autosave/latest` response
- `BlueprintReview` at `/strategies/{id}/versions/{version}`
- `UncertaintyExplainer` — per-entry severity badge, plain-language description, resolution form
- `ParameterTuning` page — allowed parameterization fields; search space bounds form
- `CompilationStatus` component — stage-by-stage pipeline progress for in-progress compiles

### Acceptance Criteria
- Draft-to-build flow completes end-to-end in E2E test
- Closing browser mid-form and reopening shows `DraftRecoveryBanner` with correct partial data
- "Start fresh" discards draft, calls `DELETE /strategies/draft/autosave/{id}`, clears localStorage
- `MATERIAL_AMBIGUITY` blocker renders owner display name and `resolve_uncertainty` link
- Material ambiguity blocks "compile to paper-eligible" — confirmed by E2E
- `ParameterTuning` form blocks submission when bounds are contradictory

### Depends on
- M22 complete (shell, auth, base components)
- `POST /strategies/draft/autosave`, `GET /strategies/draft/autosave/latest`,
  `DELETE /strategies/draft/autosave/{id}` all implemented and tested (M23 completion)

---

## MILESTONE: M26 — Run Monitor and Optimization Progress

### Objective
Build the run submission surface and live run monitoring views.

### Key Constraints
- Live polling with backoff per Section 8.1: start at 5 s, double on failure, cap at 30 s
- Stale-data indicator appears within 5 s of first poll failure
- Override watermark rendered on run card if strategy build has active override

### Deliverables
- Run submission forms wired to `POST /runs/research` and `POST /runs/optimize`
- `RunPage` at `/runs/{run_id}`: live-polling status, trial progress bar, stale-data indicator
- `OptimizationProgress`: trial count gauge, best-trial-so-far, trials-per-minute
- Terminal state handling: `completed` → results link; `failed` → error + retry; `cancelled` → reason
- Preflight failure display: structured rejection with `BlockerSummary` including owner card
  and next-step link per Section 8.3
- `TrialDetail` modal: full parameters, seed, fold metrics, objective value

### Acceptance Criteria
- Run submission E2E passes
- Polling backoff respects 30 s cap; stale indicator appears within 5 s of simulated failure
- `PREFLIGHT_FAILED` renders structured rejection reasons with owner card
- Trial log renders 100+ rows via virtual scroll without layout breakage
- Override watermark renders when strategy build has active override watermark

### Depends on: M25

---

## MILESTONE: M27 — Results Explorer

### Objective
Build the quantitative results exploration surface with adaptive chart rendering and
full data export paths.

### Key Constraints
- `useChartEngine(n)`: Recharts for ≤ 500 points, ECharts Canvas for > 500 points
- LTTB `sampling_applied` flag drives `SamplingBanner` — must not be suppressible
- `trades_truncated` banner shows "Showing first 5 000 of {total_trade_count} trades"
- TanStack Virtual for all tables with > 100 rows (no layout breakage at 1 000 rows)
- "Download data" → zip bundle from backend export endpoint

### Deliverables
- `RunResultsPage` at `/runs/{run_id}/results`
- `EquityView`: engine-switching + fold-boundary overlays + `SamplingBanner`
- `DrawdownCurve` with same engine-switching logic
- `SegmentedPerformanceBar`: per-fold and per-regime grouped bar chart
- `RegimeOverlay`: timeline color bands on equity chart
- `TradeBlotter`: filterable, virtual-scroll, Canvas PnL distribution for > 500 trades
- `TrialSummaryTable`: virtual scroll, highlight top-N, link to `TrialDetail`
- `CandidateComparisonTable`: side-by-side metric comparison
- `SamplingBanner` copy per Section 8.5

### Acceptance Criteria
- Equity curve renders Recharts for 400-point series; ECharts for 1 500-point — confirmed by DOM renderer attribute
- `SamplingBanner` renders when `sampling_applied: true`
- `trades_truncated` banner renders when `trades_truncated: true`
- "Download data" triggers zip bundle download; extracted `metadata.json` contains `run_id`
  and correct `export_schema_version`
- Fold-boundary overlays render on equity chart for walk-forward run
- `TradeBlotter` with 1 000 rows renders via virtual scroll without horizontal overflow

### Depends on: M26, M24 (chart endpoints)

---

## MILESTONE: M28 — Readiness Report Viewer and Candidate Comparison

### Objective
Build the readiness evaluation surface and candidate scoring breakdown feeding the
governance promotion workflow.

### Key Constraints
- Grade A–F color-coded per Phase 2 §8.4 (fetch colors from spec — do not guess)
- "Submit for promotion" button ABSENT (not disabled) when grade is F
- "Submit for promotion" disabled (not absent) when pending approval already exists
- Override watermark displayed in amber when active override applies

### Deliverables
- `RunReadinessPage` at `/runs/{run_id}/readiness`
- `ReadinessViewer`: grade badge, overall score, policy version prominently shown
- `ScoringBreakdown`: per-dimension sub-score cards with threshold + pass/fail
- Holdout evaluation status card, regime consistency table
- `READINESS_GRADE_F` renders `BlockerSummary` per failing dimension with owner card
  and `view_readiness_breakdown` next-step
- "Generate readiness report" wired to `POST /runs/{run_id}/readiness`; gated on `runs:write`
- Report history list in reverse chronological order
- "Submit for promotion" button with presence/disabled logic per constraints above

### Acceptance Criteria
- Readiness report loads and grade renders for completed run in E2E test
- A–F grade badges use correct color mapping
- "Submit for promotion" is ABSENT (not merely disabled) when grade is F — confirmed by DOM inspection
- Override watermark renders in amber when active override applies
- `BlockerSummary` includes owner display name and next-step button

### Depends on: M27

---

## MILESTONE: M29 — Governance Workflows Frontend

### Objective
Build the full approval and override management surfaces with separation-of-duties
enforcement and evidence-link requirement.

### Key Constraints
- `evidence_link` is required and must be a valid URL — Zod `.url()` validation
- `SeparationGuard` prevents submitters from approving/rejecting own requests — must block buttons
  in DOM, not just show a warning
- Override watermarks must propagate to all five required surfaces (see Section 8.2)
- Inline help copy for `evidence_link`: "Paste a link to your Jira ticket, Confluence doc,
  or GitHub issue"

### Deliverables
- `ApprovalsPage` at `/approvals`: list filterable by status and request type
- `ApprovalDetail`: rationale, target object link, submitter, timestamps; approve/reject modal
- `SeparationGuard` component
- `PromotionRequestForm` modal: rationale, target stage; wired to `POST /promotions/request`
- `PromotionHistory` panel on `StrategyVersionPage`
- `OverridesPage` at `/overrides`: active and historical overrides filterable by status and gate
- `OverrideRequestForm` modal: gate selector, target, rationale, `evidence_link` (required URI)
- `OverrideViewer`: watermark detail, evidence link as clickable external link, decision rationale,
  revocation history

### Acceptance Criteria
- Complete approval flow in E2E test
- Submitter cannot approve own request: `SeparationGuard` renders and blocks buttons
- Override request form rejects when `evidence_link` is empty — Zod validation
- Override request form rejects when `evidence_link` is not a valid URL — Zod
- Evidence link in `OverrideViewer` renders as `<a target="_blank">` clickable link
- Override watermark renders on all five required surfaces — unit tests per surface
- Approved override shows `ACTIVE`; revoked shows muted "revoked"
- `ApprovalsPage` filters by status without full page reload

### Depends on: M22, M23 (all governance endpoints), M28

---

## MILESTONE: M30 — Feed Operations, Parity, Operator Dashboards, and Audit Explorer

### Objective
Build operational surfaces for data health, infrastructure, and governance audit visibility.

### Key Constraints
- Degraded feed badge cannot be suppressed — it is not an opt-in warning
- "Launch research" button disabled with `DegradedDataBadge` + tooltip showing feed owner
  when required feed has unresolved anomaly
- `AuditExplorer` is READ-ONLY — no action buttons of any kind
- Cursor pagination on `AuditExplorer` — no full page reload on next page

### Deliverables
- `FeedsPage` at `/feeds`: paginated list with health badge; search by name/symbol/source
- `FeedDetailPage` at `/feeds/{feed_id}`: metadata, health timeline, anomaly list
- `FeedHealthDashboard`: summary cards for active/degraded/failed feeds
- `AnomalyViewer`: filterable anomaly event table across all feeds
- `ParityPage` at `/parity`: parity event list filterable by status
- Research launch blocker with `DegradedDataBadge` and owner tooltip
- `QueuesPage` at `/queues`: per-queue-class card with depth, running, failed, throughput
- `ComputeContention`: per-queue-class contention chart over selectable time range
- `AuditExplorer` at `/audit`: filterable, paginated, cursor-based, no mutations
- `DiagnosticsShell`: read-only service health, version info, non-secret configuration

### Acceptance Criteria
- Degraded feed renders non-neutral badge that cannot be suppressed — confirmed in unit test
- "Launch research" disabled with `DegradedDataBadge` showing feed owner in tooltip when
  required feed has unresolved anomaly — confirmed via MSW mock
- `AuditExplorer` cursor pagination loads next page without full reload
- `AuditExplorer` renders no action buttons
- `ComputeContention` time-range selector loads correct data window without re-rendering
  unrelated page sections

### Depends on: M22, M24 (feed health, queue, parity endpoints)

---

## MILESTONE: M31 — Export UX, Artifact Browser, Acceptance Test Pack, Phase 3 Sign-Off

### Objective
Complete export and artifact surfaces, execute the full Phase 3 acceptance test pack,
harden permissions, and confirm phase is ready for sign-off.

### Key Constraints
- CSV zip bundle format: `data.csv` (no comment rows), `metadata.json`, `README.txt`
- `metadata.json` must contain: `run_id`, `export_schema_version`, `override_watermarks`
- `ExportCenter` shows in-progress state; `metadata.json` preview before download
- All protected routes and actions smoke-tested with a no-scope user
- Accessibility sweep: keyboard navigation, ARIA labels, color contrast — all primary surfaces
- `npm run build` must exit 0 with zero TypeScript errors, zero ESLint errors, coverage ≥ 80%

### Deliverables
- `ExportCenter` on `RunResultsPage`: download buttons for all Phase 2 export types;
  format selector; in-progress state; `metadata.json` preview before download
- `ExportHistory`: prior exports with schema_version, format, row_count, download link
- `ArtifactsPage` at `/artifacts`: searchable, filterable, paginated artifact browser
- `ArtifactBrowser` embedded on `RunPage` and `StrategyVersionPage`
- Phase 3 Playwright acceptance suite for all Definition of Done items
- Permissions hardening: smoke test every protected route/action with no-scope user
- Accessibility sweep for all primary surfaces

### Acceptance Criteria
- All Phase 3 Definition of Done criteria satisfied
- Downloaded zip: `data.csv` (no comment rows) + `metadata.json` (all required fields) + `README.txt`
  — confirmed by Playwright download + unzip test
- Zip exported under active override includes watermark ID in `metadata.json` `override_watermarks`
- `ArtifactsPage` artifact-type filter returns correct results in E2E
- Permissions smoke test: no-scope user sees only login; `researcher` role sees only researcher surfaces;
  out-of-scope action buttons absent from DOM
- Keyboard navigation reaches all primary interactive elements without mouse

### Depends on: M29, M30

---

## FRONTEND ROUTE ARCHITECTURE (Source §13)

```
/                           → redirect to /strategy-studio
/strategy-studio            → StrategyStudioPage
/strategies/:id/versions/:v → StrategyVersionPage
/runs/new/research          → RunNewPage (research form)
/runs/new/optimize          → RunNewPage (optimize form)
/runs/:run_id               → RunPage
/runs/:run_id/results       → RunResultsPage
/runs/:run_id/readiness     → RunReadinessPage
/feeds                      → FeedsPage
/feeds/:feed_id             → FeedDetailPage
/data/certification         → CertificationPage
/parity                     → ParityPage
/approvals                  → ApprovalsPage
/approvals/:id              → ApprovalDetailPage
/overrides                  → OverridesPage
/overrides/:id              → OverrideDetailPage
/queues                     → QueuesPage
/artifacts                  → ArtifactsPage
/audit                      → AuditPage
/403                        → ForbiddenPage
/404                        → NotFoundPage
```

All routes except `/403` and `/404` require an authenticated session.
Routes requiring a scope the user lacks render `ForbiddenPage` — do NOT redirect to login.

---

## OBSERVABILITY — FRONTEND (Source §15)

### Frontend error telemetry
- Unhandled query errors logged to structured error sink with `correlation_id` from response header
- Auth failures (401, 403) increment `auth_failure_total{reason}` metric
- Poll backoff events logged with `poll_attempt`, `backoff_ms`, `endpoint`

### Recommended frontend metrics
- `page_load_total{page}` — histogram of time-to-interactive per page
- `chart_engine_used_total{engine}` — recharts vs echarts selection frequency
- `draft_recovery_offered_total` — how often recovery banner is shown
- `draft_recovery_accepted_total` — how often users restore vs discard

---

## QUALITY GATES (frontend-specific, in addition to CLAUDE.md §6)

| Gate | Threshold |
|---|---|
| TypeScript strict errors | 0 |
| ESLint errors | 0 |
| Vitest line coverage | ≥ 80% |
| Playwright E2E pass rate | 100% |
| Bundle size (gzipped) | < 500 KB initial chunk |
| Lighthouse accessibility score | ≥ 90 |
| Cold CI run time | < 3 minutes |

---

## SESSION ORIENTATION CHECKLIST (read before starting any M22–M31 session)

Per CLAUDE.md §16 Rule 5, before writing any code:

1. Confirm progress file shows M22–M31 status correctly
2. Confirm source workplan milestone count = 11; progress file references 11 milestones
3. For M25 or M29: confirm M23 missing endpoints are implemented and tested
4. For M27 or M30: confirm M24 LTTB, cache, and contention endpoints are verified
5. Do not begin M25 until M22 acceptance criteria are ALL green (not just scaffold)
6. Do not declare any frontend milestone DONE without running the full E2E suite
