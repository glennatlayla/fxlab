# FXLab Phase 3 — Web UX, Governance, and Results/Export Surfaces
# Implementation Workplan v1.1

## Revision Summary — v1.0 → v1.1

Six structural and compliance gaps identified in review:

1. **M23 was a God Milestone.** Charts, Governance, Queue, and Feed Health backend APIs were
   bundled into one serialization point. Split into M23 (Governance APIs, highest business
   risk first) and M24 (Charts, Queue, Feed Health APIs). M23 and M24 may develop in
   parallel with each other and with M22; this unblocks frontend feature teams earlier.
   Downstream milestones renumbered M25–M31.

2. **SVG performance for high-density datasets.** Recharts is SVG-based. Equity curves for
   high-frequency strategies and trade blotters with 5 000+ rows will cause browser jank.
   Added mandatory LTTB downsampling on the backend (≤ 2 000 points served to the wire),
   Canvas-based rendering requirement when data exceeds a threshold, and a `sampling_applied`
   flag in the chart payload so the UI can warn the user.

3. **Governance rationale was a text box.** A free-text `rationale` field does not satisfy
   SOC 2 Evidence of Review. Made `evidence_link` a required URI field on override requests
   (Jira ticket, Confluence doc, GitHub issue, etc.). Added to DB schema, API contract,
   override request form, and override viewer.

4. **Draft persistence was absent.** Non-technical users filling 20+ parameter fields have
   no recovery path on session timeout or browser crash. Added `POST /strategies/draft/autosave`
   backend endpoint, a `draft_autosaves` table, and localStorage fast-path persistence in
   `StrategyDraftForm` (synced to the backend every 30 s or on field blur).

5. **CSV lineage header breaks Excel.** Prepending a comment block to CSV files causes Excel
   to treat metadata as data rows. Changed exports to a zip bundle: `data.csv` (clean, no
   comments), `metadata.json` (lineage block), `README.txt` (human-readable field guide).
   Updated Section 7.4, export contracts, and M31 acceptance criteria accordingly.

6. **Blocker copy was not actionable for non-technical users.** "This strategy has
   unresolved ambiguity" tells a non-technical operator nothing about what to do next.
   Added a `blocker_owner` field to all blocker payloads (the researcher/engineer who
   created the blocking condition) and a `next_step` field to each blocker code definition.
   `BlockerSummary` component now renders an owner contact card and a recommended next step.

---

## MILESTONE INDEX — READ THIS BEFORE ANYTHING ELSE

```
MILESTONE INDEX
───────────────────────────────────────────────────────────────────
Total milestones: 11
Tracks: Bootstrap, Backend Governance, Backend Charts/Queue/Feed, Frontend

Bootstrap (required before all other tracks):
  M0   Bootstrap — Phase 3 Directory Structure and Frontend Scaffold

Backend Governance track (unblocks M29):
  M23  Governance Backend APIs — Approvals, Overrides, Promotions, Watermarks

Backend Charts/Queue/Feed track (unblocks M27, M30):
  M24  Chart, Queue, and Feed Health Backend APIs — LTTB, Cache, Contention

Frontend track (M22 unblocks all downstream; M25–M31 in dependency order):
  M22  Frontend Foundation — App Shell, Design System, Auth Integration
  M25  Strategy Studio and Blueprint UX               [requires M22]
  M26  Run Monitor and Optimization Progress          [requires M25]
  M27  Results Explorer                               [requires M26, M24]
  M28  Readiness Report Viewer                        [requires M27]
  M29  Governance Workflows Frontend                  [requires M22, M23, M28]
  M30  Feed Operations, Parity, Operator Dashboards   [requires M22, M24]
  M31  Export UX, Artifact Browser, Phase 3 Sign-Off  [requires M29, M30]
───────────────────────────────────────────────────────────────────
INTEGRITY CHECK: Any summary, distillation, or derivative of this file
must reference all 11 milestone IDs above. If any ID is absent from a
derivative, that derivative is incomplete and must not be used as the
sole implementation context.
───────────────────────────────────────────────────────────────────
```

---

## 1. Mission

Implement Phase 3: Web UX, Governance, and Results/Export Surfaces on top of the Phase 1
and Phase 2 operational substrate.

When this phase is complete, a non-technical operator must be able to:

- define a strategy draft and launch research or optimization through the UI without writing code,
  with draft work automatically persisted so session loss does not destroy progress
- monitor optimization progress and inspect intermediate trial results
- read and understand why a candidate is blocked for paper eligibility, and know exactly who
  to contact to unblock it
- review readiness reports and scoring evidence without opening a database
- submit promotion requests and track their governance status through approval
- see override state everywhere a candidate or result appears
- inspect feed health, anomaly events, and parity issues without engineering help
- export trade-level and run-level data in Excel-compatible zip bundles with lineage metadata
- browse and search artifacts, audit history, and queue state from a single authenticated surface

The UI is a client of the platform. It has no authority to compute governance state, derive
readiness grades, or manufacture audit events. Every action the UI initiates must map
one-to-one to an auditable backend mutation or job request.

### Out of scope

- broker order routing
- live or paper execution management
- emergency flatten or position closure actions
- reconciliation against external brokers
- AI or LLM-assisted strategy generation
- automated governance decision-making

Those arrive in Phase 4.

---

## 2. Non-Negotiable Rules

Treat violations as build failures, not warnings.

1. **Phase 1 and Phase 2 contracts are immutable from the UI's perspective.** The frontend
   may not modify Phase 1/2 database tables, queue classes, artifact conventions, or audit
   mechanics. It may only call established API endpoints and consume stable contracts.

2. **No business logic in the frontend.** Readiness grades, governance eligibility, override
   state, RBAC decisions, and blocker reasoning are always server-authoritative. The UI
   reflects what the backend says; it does not compute or infer these values locally.

3. **Every UI mutation maps to an auditable backend action.** If a button press cannot be
   traced to an API call that produces an audit event, the button must not exist.

4. **RBAC is server-enforced; UI hides actions it cannot authorize, never just disables them
   silently.** The frontend checks permission state via API, not via local role inference.
   A 403 from the backend is terminal for that action, not a hint to re-route.

5. **Override state is visible everywhere a candidate, result, or deployment context appears.**
   If an override exists for a strategy build, that watermark must render on every relevant
   surface without requiring the user to navigate away.

6. **Exports are zip bundles. Lineage metadata is never embedded in the data rows.** CSV
   exports use a zip format: `data.csv` (clean, no comment headers), `metadata.json`
   (lineage block), `README.txt` (field guide). This preserves Excel compatibility. Exports
   that strip lineage metadata are non-compliant.

7. **Charts are views over exported data, not a substitute for exportability.** Every chart
   must have a corresponding data export path. A result visible only as a chart and not
   downloadable is a compliance gap.

8. **Blockers are explained in plain language, include an owner, and are actionable.** Every
   blocker rendered by the UI must identify the person or team responsible for creating the
   blocking condition and provide a specific next step. Showing only friendly copy is
   insufficient.

9. **Degraded states are never hidden.** Data quality warnings, holdout contamination markers,
   override badges, quarantined feed indicators, and failed-preflight flags must render
   visibly — not collapsed behind an expand control or softened into neutral colors.

10. **All heavy work is asynchronous.** Form submissions that trigger compile, research run,
    optimization, holdout, or readiness jobs must return a job identity immediately and poll
    for completion. No synchronous spinning.

11. **Draft work is never silently discarded.** The `StrategyDraftForm` must persist work
    locally on every field change and sync to the backend every 30 seconds. A user who loses
    their session must be able to recover their draft on next login.

12. **Separation of duties is architecturally enforced.** The approval surface must not allow
    the submitter of a promotion request to also approve it. This rule is enforced by
    the backend, and the UI must surface it as a clear named state, not a generic error.

13. **Governance evidence links are required URIs, not free text.** Override requests must
    reference an external evidence artifact (Jira ticket, Confluence doc, GitHub issue, etc.)
    by URL. Free-text rationale alone does not satisfy SOC 2 Evidence of Review.

14. **Frontend tests must treat the API as an external boundary.** Unit and component tests
    mock the API client. Integration and E2E tests use the real running backend.

15. **High-density chart data is downsampled before it reaches the wire.** The backend must
    not serve more than 2 000 equity curve points or 5 000 trade records to a single chart
    request. The frontend must use Canvas-based rendering for datasets above these thresholds.
    Raw, undownsampled data is always available via the export endpoint, never via the chart
    endpoint.

16. **No notebook, CSV attachment, or ad hoc analysis counts as official evidence.** The
    canonical source of truth for readiness, governance, and export data is the backend
    API and artifact store.

---

## 3. Delivery Protocol

Every milestone follows the same execution discipline used in Phases 1 and 2, adapted for
frontend and backend-extension work.

### Per-milestone execution order

```text
1. Read the milestone contract
2. Identify new backend endpoints needed and specify them before UI work begins
3. Define TypeScript type interfaces from the API contracts (code-generate where possible)
4. Write failing tests: component unit tests, API hook tests, and E2E smoke tests
5. Implement minimum code to pass tests
6. Run quality gate: format -> lint -> type-check -> tests with coverage
7. Refactor and re-run quality gate
8. Add Playwright E2E tests for any acceptance-critical user flows
9. Review against milestone acceptance criteria and non-negotiable rules
```

### Onion architecture mapping (Phase 3 additions)

| Layer | FXLab location | Owns |
|---|---|---|
| API extensions | `services/api/routes/` | new governance, chart, contention, feed-health endpoints |
| Governance service | `services/api/` or new service | approval/override state machine, separation-of-duties |
| Frontend application | `frontend/` | SPA shell, routing, auth session |
| Page components | `frontend/src/pages/` | route-level views |
| Feature modules | `frontend/src/features/` | strategy, runs, readiness, feeds, governance, exports, operator |
| Shared UI components | `frontend/src/components/` | design system, charts, data tables, status badges |
| API client | `frontend/src/api/` | generated or hand-authored typed client |
| State / query layer | `frontend/src/hooks/` | TanStack Query hooks wrapping API client |
| Auth module | `frontend/src/auth/` | OIDC session, token refresh, permission helpers |

**Dependency rule:** Page components → Feature modules → Shared components + API hooks → API client.
Feature modules may not import from other feature modules directly.

---

## 4. Default Technical Choices

Inherit all Phase 1 and Phase 2 technical choices for backend extensions. Phase 3 frontend
additions:

| Concern | Choice |
|---|---|
| Frontend framework | React 18 + TypeScript 5 |
| Build tooling | Vite |
| Routing | React Router v6 |
| Server state / caching | TanStack Query v5 |
| Forms | React Hook Form + Zod |
| Styling | Tailwind CSS v3 |
| Headless component primitives | Headless UI or Radix UI |
| Charting (standard density) | Recharts (SVG-based; equity curves ≤ 2 000 points, blotter ≤ 5 000 rows) |
| Charting (high density) | ECharts with Canvas renderer for equity curves > 2 000 points or blotter > 5 000 rows |
| Chart downsampling algorithm | Largest Triangle Three Buckets (LTTB) applied server-side before the chart endpoint responds |
| Data tables | TanStack Table v8 with virtual rows (TanStack Virtual) for tables > 100 rows |
| Auth | OIDC consuming Phase 1 auth service; `@auth0/auth0-react` or equivalent |
| API client | OpenAPI-generated TypeScript client from Phase 1/2 spec; extended manually for Phase 3 additions |
| Frontend testing | Vitest + @testing-library/react + MSW (mock service worker) |
| E2E testing | Playwright |
| Linting | ESLint with TypeScript and React plugins |
| Formatting | Prettier |
| Type checking | tsc strict mode |
| Coverage gate | ≥ 80% component/hook coverage; all acceptance flows E2E-covered |
| Export format | Zip bundle: `data.csv` + `metadata.json` + `README.txt` |

---

## 5. Repository Target Shape (Phase 3 additions)

```text
fxlab/
  frontend/
    index.html
    vite.config.ts
    tsconfig.json
    package.json
    playwright.config.ts
    src/
      main.tsx
      App.tsx
      router.tsx
      auth/
        AuthProvider.tsx
        useAuth.ts
        permissions.ts
      api/
        client.ts
        endpoints/
          strategies.ts
          runs.ts
          readiness.ts
          governance.ts
          feeds.ts
          exports.ts
          artifacts.ts
          audit.ts
          queues.ts
      hooks/
        useStrategy.ts
        useRun.ts
        useReadiness.ts
        useGovernance.ts
        useFeeds.ts
        useExports.ts
        useArtifacts.ts
        useAudit.ts
        useQueues.ts
        useDraftAutosave.ts
      components/
        layout/
          Shell.tsx
          Sidebar.tsx
          TopBar.tsx
        status/
          StatusBadge.tsx
          OverrideBanner.tsx
          BlockerSummary.tsx       ← includes owner card + next-step link
          ContaminationFlag.tsx
          DegradedDataBadge.tsx
          SamplingBanner.tsx       ← rendered when chart data is downsampled
        charts/
          EquityCurve.tsx          ← switches renderer by data density
          DrawdownCurve.tsx
          ParameterHeatmap.tsx
          RegimeOverlay.tsx
          SegmentedPerformanceBar.tsx
        tables/
          TradeBlotter.tsx         ← virtual scroll; Canvas chart path for high density
          TrialSummaryTable.tsx
          CandidateComparisonTable.tsx
          ArtifactTable.tsx
          AuditTable.tsx
        forms/
          StrategyDraftForm.tsx    ← autosave every 30 s + localStorage fast path
          ParameterBoundsForm.tsx
          PromotionRequestForm.tsx
          OverrideRequestForm.tsx  ← evidence_link required URI field
        ui/
          Button.tsx
          Modal.tsx
          Toast.tsx
          Tooltip.tsx
          Pagination.tsx
          EmptyState.tsx
          LoadingState.tsx
          ExportButton.tsx
          DraftRecoveryBanner.tsx  ← shown when a recoverable draft exists on login
      features/
        strategy/
          StrategyStudio.tsx
          BlueprintReview.tsx
          UncertaintyExplainer.tsx
          ParameterTuning.tsx
          CompilationStatus.tsx
          DraftAutosaveManager.ts  ← orchestrates localStorage + backend sync
        runs/
          RunMonitor.tsx
          OptimizationProgress.tsx
          TrialDetail.tsx
        results/
          ResultsExplorer.tsx
          EquityView.tsx
          TradeView.tsx
          SegmentedView.tsx
        readiness/
          ReadinessViewer.tsx
          ScoringBreakdown.tsx
          CandidateComparison.tsx
        governance/
          ApprovalQueue.tsx
          ApprovalDetail.tsx
          OverrideViewer.tsx
          PromotionHistory.tsx
          SeparationGuard.tsx
        feeds/
          FeedRegistry.tsx
          FeedDetail.tsx
          FeedHealthDashboard.tsx
          AnomalyViewer.tsx
          ParityDashboard.tsx
        exports/
          ExportCenter.tsx
          ExportHistory.tsx
          ArtifactBrowser.tsx
        operator/
          QueueHealthDashboard.tsx
          ComputeContention.tsx
          AuditExplorer.tsx
          DiagnosticsShell.tsx
      pages/
        StrategyStudioPage.tsx
        StrategyVersionPage.tsx
        RunPage.tsx
        RunResultsPage.tsx
        RunReadinessPage.tsx
        FeedsPage.tsx
        FeedDetailPage.tsx
        CertificationPage.tsx
        ParityPage.tsx
        ApprovalsPage.tsx
        OverridesPage.tsx
        AuditPage.tsx
        QueuesPage.tsx
        ArtifactsPage.tsx
  services/
    api/
      routes/
        charts.py          ← NEW: downsampled equity/drawdown/segment payloads
        governance.py      ← NEW: approvals, overrides, promotions, watermarks
        queues.py          ← NEW: queue contention and job state
        feed_health.py     ← NEW: feed health summary + anomaly list
```

---

## 6. Phase 3 Domain Model

### New backend entities

- `approval_requests`
- `approval_decisions`
- `override_requests`
- `override_decisions`
- `override_watermarks`
- `promotion_requests`
- `promotion_approvals`
- `chart_cache_entries`
- `draft_autosaves`

### Governance lifecycle definitions

- **Approval request:** a formal submission asking an approver to authorize a state transition
  (e.g., promote to holdout, promote to paper-eligible). Created by the requester, never
  auto-approved.
- **Approval decision:** an immutable record of an approver accepting or rejecting an approval
  request. One decision per request. Cannot be modified after creation.
- **Override request:** a formal submission asking for permission to bypass a normal governance
  gate. Requires a structured `evidence_link` URI and a `rationale` text. Requires approver
  action and creates a watermark.
- **Override watermark:** a persistent marker attached to a strategy build or run indicating
  that a governance gate was bypassed under a specific override decision. Visible everywhere
  the build or run appears, including exports.
- **Promotion request:** an audited request to advance a ranked candidate through a lifecycle
  stage. Triggers an approval request by default unless the submitter has direct-promotion
  permission.
- **Draft autosave:** a server-side snapshot of an in-progress `StrategyDraftInput` payload
  associated with a user session. Multiple autosaves per user are possible; the most recent
  is offered for recovery on login.
- **Separation-of-duties constraint:** the approver of a promotion request or override must
  not be the submitter. Enforced by backend; exposed as a named status in the API.

---

## 7. Governance, Approval, and Performance Contracts

### 7.1 Approval state machine

```text
PENDING → APPROVED → (state transition executed)
        → REJECTED → (reason persisted, no transition)
        → EXPIRED  → (TTL elapsed without decision)
        → CANCELLED → (submitter withdrew before decision)
```

Rules:
- Approver must have `approvals:write` permission for the governance scope.
- Submitter and approver may not be the same identity.
- Approval decision is immutable once written.
- Rejected or expired requests may be resubmitted; they create new request records.
- Approved transition must complete within `completion_deadline`; otherwise a
  `promotion_stale` event is logged and the approval lapses.

### 7.2 Override state machine and evidence requirements

```text
OPEN → APPROVED → WATERMARK_ISSUED → ACTIVE
     → REJECTED → (reason persisted)
ACTIVE → REVOKED → (watermark marked revoked, override inactive)
```

Rules:
- Override must reference a specific governance gate by name.
- Override must include:
  - `rationale`: mandatory free-text description of why the gate is being bypassed
  - `evidence_link`: mandatory URI pointing to the external evidence record (Jira ticket URL,
    Confluence document URL, GitHub issue URL, or equivalent). The URI must be parseable and
    must not be a bare domain root. This field satisfies SOC 2 Evidence of Review.
- Active overrides produce a watermark record that attaches to every relevant object.
- Revoking an override marks the watermark `revoked_at` but does not delete evidence.

### 7.3 Chart data contracts

Chart endpoints return structured payloads, not image blobs. The frontend renders from data.

**LTTB downsampling is mandatory** before the endpoint responds:
- `equity_curve`: downsampled to ≤ 2 000 points using the Largest Triangle Three Buckets
  algorithm if the raw series exceeds this threshold.
- `trades`: first 5 000 records by `entry_ts` asc are returned; beyond this the payload
  sets `trades_truncated: true` and the user must use the export endpoint for the full set.
- `segmented_performance`: not downsampled (row count is bounded by fold and regime count).

```python
class EquityCurvePoint(BaseModel):
    ts: datetime
    equity: float
    drawdown: float
    cumulative_return: float
    fold_number: int | None

class TradeRecord(BaseModel):
    trade_id: str
    entry_ts: datetime
    exit_ts: datetime
    symbol: str
    side: Literal["long", "short"]
    quantity: float
    entry_price: float
    exit_price: float
    fill_type: str
    gross_pnl: float
    net_pnl: float
    cost: float
    regime_label: str | None
    fold_number: int | None

class SegmentedPerformanceRow(BaseModel):
    segment_type: Literal["fold", "regime", "calendar"]
    segment_label: str
    sharpe: float
    total_return: float
    max_drawdown: float
    trade_count: int
    win_rate: float

class RunChartsPayload(BaseModel):
    run_id: str
    schema_version: str
    equity_curve: list[EquityCurvePoint]
    sampling_applied: bool           # True when LTTB was applied
    raw_equity_point_count: int      # original count before downsampling
    trades: list[TradeRecord]
    trades_truncated: bool           # True when > 5 000 trades exist
    total_trade_count: int           # true count including truncated records
    segmented_performance: list[SegmentedPerformanceRow]
    regime_labels: dict[str, str] | None
    is_partial: bool
    generated_at: datetime
```

### 7.4 Export bundle format

All exports use a zip bundle format. This preserves Excel compatibility by keeping
the lineage metadata out of the data rows.

Zip bundle structure:

```text
export_{run_id}_{type}_{timestamp}.zip
  data.csv          ← clean CSV, first row is column headers, no comment lines
  metadata.json     ← lineage block (see below)
  README.txt        ← human-readable field descriptions and schema version notes
```

`metadata.json` schema:

```json
{
  "export_schema_version": "3.0",
  "run_id": "...",
  "strategy_build_id": "...",
  "readiness_report_id": "...",
  "exported_by": "...",
  "exported_at": "...",
  "row_count": 0,
  "sort_key": "...",
  "sort_order": "asc | desc",
  "override_watermarks": [],
  "sampling_applied": false,
  "raw_row_count": 0
}
```

If any active override watermarks apply to the run or build at export time, their
`override_watermark_id` values must be included in the `override_watermarks` array.
An export produced under an active override without this field populated is non-compliant.

Parquet exports use file-level metadata (Parquet schema metadata map) for the same lineage
fields. There is no zip bundle for Parquet; the file metadata is the sidecar.

### 7.5 Draft autosave contract

```python
class DraftAutosavePayload(BaseModel):
    user_id: str
    draft_payload: dict          # partial StrategyDraftInput, may be incomplete
    form_step: str               # which step the user was on
    client_ts: datetime          # client-side timestamp
    session_id: str              # browser session identifier

class DraftAutosaveResponse(BaseModel):
    autosave_id: str
    saved_at: datetime
```

Rules:
- `POST /strategies/draft/autosave` accepts a partial payload (Pydantic partial validation,
  not full `StrategyDraftInput` validation).
- The frontend must also persist the same payload to `localStorage` on every field change.
  `localStorage` is the fast recovery path; the backend autosave is the durable recovery path.
- On login, if the server has a recent autosave for the user, `DraftRecoveryBanner`
  renders offering to restore it.
- Autosaves older than 30 days are purged from the server.
- The user may explicitly discard a draft from the recovery banner.

### 7.6 Blocker payload contract

Every blocker code the backend returns must include three fields in its payload:

```python
class BlockerDetail(BaseModel):
    code: str                  # e.g. "MATERIAL_AMBIGUITY"
    message: str               # backend-authoritative message
    blocker_owner_id: str      # user ID of the actor who created the blocking condition
    blocker_owner_display: str # display name for the UI
    next_step: str             # machine-readable action key, e.g. "resolve_uncertainty"
    next_step_url: str | None  # direct link to the relevant UI surface if resolvable in-app
```

The `blocker_owner` is the actor who last modified the object that created the block
(e.g., the researcher who submitted the strategy build, the data engineer who quarantined
the feed). If no owner is determinable, `blocker_owner_display` is `"System"`.

`BlockerSummary` component renders:
- blocker code badge
- plain-language copy from the frontend constants table (Section 8.3)
- owner contact card (display name + link to their profile or email if available)
- "Next step" button or link

### 7.7 Permission model

Phase 3 requires these permission scopes in addition to Phase 1 RBAC:

| Scope | Grants |
|---|---|
| `strategies:write` | create strategy drafts, submit versions for compilation |
| `runs:write` | submit research, optimization, holdout runs |
| `promotions:request` | submit promotion requests |
| `approvals:write` | approve or reject approval requests |
| `overrides:request` | submit override requests |
| `overrides:approve` | approve or reject override requests |
| `exports:read` | download exports and artifacts |
| `feeds:read` | view feed health and parity dashboards |
| `operator:read` | view queue contention and diagnostics |
| `audit:read` | view audit history |

Default roles:

| Role | Scopes |
|---|---|
| `researcher` | `strategies:write`, `runs:write`, `promotions:request`, `exports:read` |
| `approver` | `approvals:write`, `overrides:approve` |
| `operator` | `feeds:read`, `operator:read`, `audit:read`, `exports:read` |
| `admin` | all scopes |

Roles are additive. A user may hold multiple roles. Scope checks are server-side and
must not be replicated as client-side guards only.

---

## 8. Resolved Specification Details (Normative)

### 8.1 Run monitor polling semantics

The run monitor page polls `GET /runs/{run_id}` for job status.

- Initial poll within 2 seconds of page load.
- Exponential backoff: 2 s, 4 s, 8 s, 16 s, cap at 30 s.
- Stop polling on terminal states: `completed`, `failed`, `cancelled`.
- Stale data (poll failure) must render a visible "data stale as of X" indicator.
- Trial count progress is shown as `completed_trials / trial_count`.
- Current trial parameters are shown if available in the run record.

### 8.2 Override watermark rendering rules

A watermark badge must render:

- On every card, row, and heading that displays a strategy build or run subject to an
  active override.
- In the readiness report viewer when the report was generated under an active override.
- In export zip `metadata.json` when the run was executed under an active override.
- The badge must not be smaller than 16px and must use an amber or warning-class color.
- A revoked override watermark must remain visible but rendered in a muted state with
  a "revoked" label.

### 8.3 Blocker code registry (frontend plain-language and action map)

| Code | Plain language copy | Next step key | Next step description |
|---|---|---|---|
| `MATERIAL_AMBIGUITY` | "This strategy has unresolved ambiguity that would materially change results." | `resolve_uncertainty` | "Open the uncertainty ledger and resolve flagged items." |
| `HOLDOUT_CONTAMINATED` | "This strategy's holdout window has already been used and cannot be re-used." | `designate_new_holdout` | "Designate a new holdout window for this strategy build." |
| `DATASET_UNCERTIFIED` | "One or more required datasets are not certified." | `view_certification` | "Open the data certification page for the blocked dataset." |
| `PREFLIGHT_FAILED` | "Pre-run validation did not pass." | `view_preflight` | "Review the preflight report for specific rejection reasons." |
| `PENDING_APPROVAL` | "This action is waiting for approver review." | `view_approval` | "Open the approval request to check its status." |
| `SEPARATION_OF_DUTIES` | "The person who submitted this request cannot also approve it." | `contact_approver` | "A different approver must act on this request." |
| `OVERRIDE_REQUIRED` | "A governance gate blocks this action." | `request_override` | "Submit an override request with evidence link and rationale." |
| `READINESS_GRADE_F` | "This strategy did not meet minimum readiness thresholds." | `view_readiness_breakdown` | "Review the scoring breakdown and address the failing dimensions." |

Unknown codes render the raw code plus: "Contact the platform team for details. Ref: {code}"

### 8.4 Chart data caching policy

- Cache keyed by `(run_id, schema_version)` after first generation.
- Write-once for completed runs. Completed run charts are immutable.
- Partial caches for in-progress runs are marked `is_partial: true`.
- `RunChartsPayload` includes `generated_at` which the UI renders alongside charts.

### 8.5 Chart rendering performance requirements

The frontend must select the rendering engine based on data density at the moment the
`RunChartsPayload` is received:

| Condition | Engine | Component |
|---|---|---|
| `equity_curve.length ≤ 500` | Recharts (SVG) | `EquityCurve.tsx` |
| `equity_curve.length > 500` | ECharts Canvas renderer | `EquityCurve.tsx` |
| `trades.length ≤ 500` | Recharts (SVG) | `TradeBlotter.tsx` chart panel |
| `trades.length > 500` | ECharts Canvas renderer | `TradeBlotter.tsx` chart panel |
| Any chart with `sampling_applied: true` | Either renderer is acceptable | Render `SamplingBanner` |

`SamplingBanner` copy: "Chart shows a representative sample of the data (LTTB algorithm).
Download the full dataset for unsampled values."

The engine-switching logic lives in the chart component, not in the page or feature module.
A `useChartEngine(dataLength)` hook returns `"recharts"` or `"echarts"` and is the
single source of truth for this decision.

### 8.6 Parity and feed health display rules

- A feed with `status = degraded` must render a degraded badge; cannot be suppressed.
- Anomaly events must list `detected_at`, `anomaly_type`, and `resolution_status`.
- Parity mismatches must list `left_source`, `right_source`, `mismatch_count`, `first_seen`,
  and `resolution_status`.
- Unresolved anomalies and parity events block the "launch research" action for any run
  that depends on the affected feed.

### 8.7 Audit explorer display rules

- Audit entries filterable by: actor, action type, target object type, target object ID,
  time range.
- Each entry displays: timestamp, actor, action, target object type and ID, correlation ID,
  evidence references.
- Cursor-based pagination; the UI must not load all records at once.
- Read-only; no mutations originate from the audit explorer.

### 8.8 Draft autosave and recovery rules

- `StrategyDraftForm` writes to `localStorage` on every field change (debounced 500 ms).
- `DraftAutosaveManager` syncs `localStorage` state to `POST /strategies/draft/autosave`
  every 30 seconds and on form blur.
- On login, the frontend calls `GET /strategies/draft/autosave/latest` to check for a
  server-side autosave. If one exists newer than the `localStorage` copy, it wins.
  If `localStorage` is newer, it wins.
- `DraftRecoveryBanner` presents two actions: "Restore draft" and "Start fresh". Both
  must be explicit; there is no implicit auto-restore.
- Server autosaves older than 30 days are excluded from recovery offers.

---

## 9. Concrete Database Schema (Phase 3 additions)

```sql
approval_requests (
  approval_request_id  ULID PK,
  request_type         TEXT NOT NULL,
  target_object_type   TEXT NOT NULL,
  target_object_id     ULID NOT NULL,
  submitter_id         TEXT NOT NULL,
  rationale            TEXT NOT NULL,
  status               TEXT NOT NULL DEFAULT 'pending',
  expires_at           TIMESTAMPTZ,
  correlation_id       TEXT NOT NULL,
  created_at           TIMESTAMPTZ NOT NULL
);

approval_decisions (
  approval_decision_id  ULID PK,
  approval_request_id   ULID NOT NULL REFERENCES approval_requests,
  approver_id           TEXT NOT NULL,
  decision              TEXT NOT NULL,
  rationale             TEXT,
  created_at            TIMESTAMPTZ NOT NULL,
  UNIQUE (approval_request_id)
);

override_requests (
  override_request_id  ULID PK,
  governance_gate      TEXT NOT NULL,
  target_object_type   TEXT NOT NULL,
  target_object_id     ULID NOT NULL,
  submitter_id         TEXT NOT NULL,
  rationale            TEXT NOT NULL,
  evidence_link        TEXT NOT NULL,    -- required URI; SOC 2 Evidence of Review field
  status               TEXT NOT NULL DEFAULT 'open',
  created_at           TIMESTAMPTZ NOT NULL,
  CHECK (evidence_link LIKE 'http%')     -- must be an absolute URL
);

override_decisions (
  override_decision_id   ULID PK,
  override_request_id    ULID NOT NULL REFERENCES override_requests,
  approver_id            TEXT NOT NULL,
  decision               TEXT NOT NULL,
  rationale              TEXT,
  created_at             TIMESTAMPTZ NOT NULL,
  UNIQUE (override_request_id)
);

override_watermarks (
  override_watermark_id  ULID PK,
  override_request_id    ULID NOT NULL REFERENCES override_requests,
  override_decision_id   ULID NOT NULL REFERENCES override_decisions,
  target_object_type     TEXT NOT NULL,
  target_object_id       ULID NOT NULL,
  governance_gate        TEXT NOT NULL,
  issued_at              TIMESTAMPTZ NOT NULL,
  revoked_at             TIMESTAMPTZ,
  revoked_by             TEXT,
  revocation_reason      TEXT
);

promotion_requests (
  promotion_request_id   ULID PK,
  run_id                 ULID NOT NULL REFERENCES runs,
  trial_id               ULID REFERENCES trials,
  promotion_target       TEXT NOT NULL,
  submitter_id           TEXT NOT NULL,
  approval_request_id    ULID REFERENCES approval_requests,
  status                 TEXT NOT NULL DEFAULT 'pending',
  created_at             TIMESTAMPTZ NOT NULL
);

chart_cache_entries (
  chart_cache_id         ULID PK,
  run_id                 ULID NOT NULL,
  schema_version         TEXT NOT NULL,
  payload_json           JSONB NOT NULL,
  is_partial             BOOLEAN NOT NULL DEFAULT false,
  sampling_applied       BOOLEAN NOT NULL DEFAULT false,
  raw_equity_point_count INTEGER,
  generated_at           TIMESTAMPTZ NOT NULL,
  created_at             TIMESTAMPTZ NOT NULL,
  UNIQUE (run_id, schema_version)
);

draft_autosaves (
  autosave_id            ULID PK,
  user_id                TEXT NOT NULL,
  session_id             TEXT NOT NULL,
  draft_payload          JSONB NOT NULL,
  form_step              TEXT NOT NULL,
  client_ts              TIMESTAMPTZ NOT NULL,
  created_at             TIMESTAMPTZ NOT NULL
);

CREATE INDEX ON draft_autosaves (user_id, created_at DESC);
```

---

## 10. Canonical API Surfaces (Phase 3 new endpoints)

All mutating endpoints inherit Phase 1 response envelope, `Idempotency-Key` support,
and audit-event emission.

### Governance

```text
POST   /approvals/request
GET    /approvals/{approval_request_id}
GET    /approvals?status=pending&scope=promotions
POST   /approvals/{approval_request_id}/approve
POST   /approvals/{approval_request_id}/reject
POST   /approvals/{approval_request_id}/cancel

POST   /overrides/request              ← body requires evidence_link URI
GET    /overrides/{override_request_id}
POST   /overrides/{override_request_id}/approve
POST   /overrides/{override_request_id}/reject
POST   /overrides/{override_watermark_id}/revoke

POST   /promotions/request
GET    /promotions/{promotion_request_id}
GET    /promotions?run_id={run_id}
```

### Results and charts

```text
GET    /runs/{run_id}/results
GET    /runs/{run_id}/charts           ← returns RunChartsPayload with LTTB-downsampled data
GET    /runs/{run_id}/charts/equity
GET    /runs/{run_id}/charts/drawdown
GET    /runs/{run_id}/charts/segmented
```

### Draft autosave

```text
POST   /strategies/draft/autosave
GET    /strategies/draft/autosave/latest     ← returns most recent autosave for current user
DELETE /strategies/draft/autosave/{id}       ← explicit discard
```

### Feed health

```text
GET    /feeds
GET    /feeds/{feed_id}
GET    /feed-health
GET    /feed-health/{feed_id}
GET    /feed-health/anomalies?feed_id={feed_id}&status=unresolved
GET    /parity/events?status=unresolved
```

### Queues / operator

```text
GET    /queues
GET    /queues/{queue_class}/contention
GET    /queues/jobs?status=running|queued|failed&limit=50
```

### Audit

```text
GET    /audit?actor={}&action_type={}&target_type={}&target_id={}&from={}&to={}&cursor={}
GET    /audit/{audit_event_id}
```

---

## 11. Milestone Dependency Graph

```text
M22  Frontend Foundation — App Shell, Design System, Auth Integration
M23  Governance Backend APIs — Approvals, Overrides, Promotions, Watermarks
M24  Chart, Queue, and Feed Health Backend APIs — LTTB, Cache, Contention, Feed Health
     (M23 and M24 may develop in parallel with each other and with M22;
      they are backend-only milestones with no frontend dependency)

M22 → M25  Strategy Studio and Blueprint UX (needs shell + draft autosave)
M25 → M26  Run Monitor and Optimization Progress
M26 → M27  Results Explorer            (also needs M24 for chart endpoints)
M27 → M28  Readiness Report Viewer
M23 → M29  Governance Workflows Frontend (needs M22 + M23)
M28 → M29
M24 → M30  Feed Operations, Parity, Operator Dashboards (needs M22 + M24)
M29 → M31  Export UX, Artifact Browser, Acceptance Test Pack
M30 → M31
```

No downstream milestone begins until all predecessor acceptance criteria are green.
M23 and M24 are the highest-priority backend milestones and should be started
before or in parallel with M22 to minimize frontend team wait time.

---

## 12. Ordered Milestone Sequence

---

### Milestone 0: Bootstrap — Phase 3 Directory Structure and Frontend Scaffold

**Objective**

Establish the Phase 3 repository skeleton, verify that Phase 1 and Phase 2 API
dependencies are reachable, and create the frontend project directory structure with
the build toolchain installed and passing a cold smoke test. All Phase 3 work begins
here. Nothing in M22–M31 begins until M0 acceptance criteria are green.

**Deliverables**

- `frontend/` directory created at project root
- `frontend/package.json` with declared Phase 3 frontend dependencies
  (React, TypeScript, Vite, TanStack Query, React Router, Tailwind, Vitest, Playwright)
- `frontend/tsconfig.json` with `strict: true`
- `frontend/vite.config.ts`
- `frontend/playwright.config.ts`
- `frontend/src/` with `main.tsx`, `App.tsx`, `router.tsx` stubs
- `frontend/src/api/client.ts` stub (typed API client shell, no implementation yet)
- `frontend/src/auth/` directory with `AuthProvider.tsx`, `useAuth.ts`, `permissions.ts`
  stubs
- `frontend/src/components/`, `frontend/src/features/`, `frontend/src/pages/`,
  `frontend/src/hooks/` directories created with `index.ts` stubs
- `npm install` completes without error
- `npm run build` completes without TypeScript errors on the stub tree
- `npm run test` (Vitest) executes and reports zero tests (no failures)
- Phase 1 health endpoint reachable: `GET /health` returns `{"success": true}` from
  `services/api/main.py`
- Phase 2 API contract check: `services/api/routes/strategies.py` exists and is importable
- `tests/acceptance/test_m0_phase3_bootstrap.py` acceptance test file created and passing
- `tests/unit/test_m0_phase3_structure.py` unit test file created and passing

**Acceptance criteria**

- [ ] `frontend/` directory exists at project root
- [ ] `frontend/package.json` lists all required Phase 3 frontend dependencies
- [ ] `frontend/tsconfig.json` exists with `strict: true` enabled
- [ ] `frontend/src/main.tsx`, `frontend/src/App.tsx`, `frontend/src/router.tsx` exist
- [ ] `frontend/src/api/client.ts` exists
- [ ] `frontend/src/auth/AuthProvider.tsx`, `useAuth.ts`, and `permissions.ts` exist
- [ ] `frontend/src/components/`, `features/`, `pages/`, `hooks/` directories exist
- [ ] `npm run build` exits 0 with zero TypeScript errors on the stub tree
- [ ] Phase 1 `/health` endpoint returns `success: true` (importability check)
- [ ] Phase 2 `services/api/routes/strategies.py` is importable without errors
- [ ] `services/api/routes/charts.py` stub exists (M23/M24 will implement it)
- [ ] `services/api/routes/governance.py` stub exists
- [ ] `services/api/routes/queues.py` stub exists
- [ ] `services/api/routes/feed_health.py` stub exists

---

### Milestone 22: Frontend Foundation — App Shell, Design System, Auth Integration

**Objective**

Establish the frontend application skeleton, design system, auth flow, and the
typed API client layer before any feature work begins. Every subsequent frontend
milestone builds on this foundation without modifying it.

**Deliverables**

- Vite + React 18 + TypeScript 5 project with strict `tsconfig`
- ESLint + Prettier + pre-commit hooks matching backend quality gates
- Tailwind CSS configured with project color tokens, typography, and spacing scale
- Shell layout: authenticated sidebar, top bar, breadcrumbs, toast notification system
- Auth provider using Phase 1 OIDC; session persistence, silent refresh, logout
- `useAuth` hook exposing `user`, `permissions`, `hasScope(scope)`, `logout()`
- `AuthGuard` component blocking unauthenticated routes and gracefully handling 403
- Typed API client generated from Phase 1/2 OpenAPI spec; extended with Phase 3 endpoints
- TanStack Query provider with global error handling and retry policy
- `LoadingState`, `EmptyState`, `ErrorState`, `StatusBadge`, `OverrideBanner`,
  `BlockerSummary` (with owner card and next-step button), `DraftRecoveryBanner` base
  components
- `useChartEngine(dataLength)` hook returning `"recharts"` or `"echarts"` based on threshold
- Vitest + @testing-library/react + MSW configured
- Playwright configured with authenticated test fixture
- CI script: type-check → lint → test → build
- Navigation routes wired with placeholders for all M25–M31 pages

**Acceptance criteria**

- `npm run build` produces a type-error-free production bundle
- auth flow completes end-to-end against a running backend in E2E test
- authenticated routes redirect to login when session is absent
- `hasScope` correctly reflects Phase 1/3 RBAC scopes from token claims
- `useChartEngine(400)` returns `"recharts"`; `useChartEngine(600)` returns `"echarts"` in
  unit test
- `BlockerSummary` renders owner display name and next-step button for a known code and
  raw code + fallback for an unknown code
- all base components render without errors in Vitest smoke test
- CI gate passes in under 3 minutes on a cold run

---

### Milestone 23: Governance Backend APIs

**Objective**

Implement the governance backend substrate first — this is the highest business risk domain
and unblocks the Governance Workflows Frontend (M29). Chart, queue, and feed health APIs
follow in M24 and may develop in parallel.

**Deliverables**

- `services/api/routes/governance.py`: all approval, override, override-watermark, and
  promotion-request endpoints from Section 10
- Alembic migrations for `approval_requests`, `approval_decisions`, `override_requests`,
  `override_decisions`, `override_watermarks`, `promotion_requests` from Section 9
- `draft_autosaves` table migration and `POST/GET/DELETE /strategies/draft/autosave` endpoints
- Governance service implementing approval and override state machines (Section 7.1–7.2)
- `evidence_link` validation: reject override requests where `evidence_link` is not an
  absolute HTTP/HTTPS URI
- Separation-of-duties enforcement at the service layer
- Repository interfaces and implementations for all governance tables
- Audit event emission on every governance mutation
- Override watermark creation and propagation when override is approved
- `GET /strategies/draft/autosave/latest` returns the most recent autosave for the
  authenticated user within the last 30 days

**Acceptance criteria**

- all governance endpoints respond with correct Phase 1 envelope
- override request with missing or non-URI `evidence_link` returns 422 with field-level error
- override request with a bare domain `evidence_link` (e.g. `"https://jira.example.com"`)
  returns 422 — must be a full path, not a root URL
- submitter cannot approve their own request — `SEPARATION_OF_DUTIES` error returned
- override watermark is created when override is approved
- draft autosave round-trip: POST → GET /latest returns the same payload
- all new migrations upgrade and downgrade cleanly
- service layer coverage ≥ 90%
- OpenAPI docs updated

---

### Milestone 24: Chart, Queue, and Feed Health Backend APIs

**Objective**

Implement the backend data APIs for results visualization, operator queues, and feed
health monitoring. Develops in parallel with M22 and M23. Frontend milestones M27 and
M30 are blocked on this milestone.

**Deliverables**

- `services/api/routes/charts.py`: `GET /runs/{run_id}/charts` and sub-endpoints
  returning `RunChartsPayload`; LTTB downsampling applied server-side for equity curves
  > 2 000 points; `sampling_applied` and `raw_equity_point_count` fields populated
- `chart_cache_entries` migration and write-through caching on first chart request for
  a completed run; partial caches marked `is_partial: true`
- `services/api/routes/queues.py`: queue depth, running, failed, throughput, and
  contention endpoints backed by Celery/Redis inspection APIs
- `services/api/routes/feed_health.py`: feed summary and anomaly list endpoints
- LTTB algorithm implementation in `libs/utils/lttb.py` with unit tests confirming:
  - output ≤ requested point count
  - first and last points always preserved
  - visual accuracy property (peak-to-trough preservation) confirmed against a known series

**Acceptance criteria**

- chart endpoint for a run with > 2 000 equity bars returns ≤ 2 000 points and
  `sampling_applied: true`
- chart endpoint for a run with ≤ 2 000 equity bars returns `sampling_applied: false`
- chart endpoint for a run with > 5 000 trades returns `trades_truncated: true` and
  `total_trade_count` > 5 000
- completed run chart cache is written on first request; second request returns cached entry
  (confirmed by database inspection in integration test)
- LTTB unit tests pass for all three properties above
- queue contention endpoint returns correct structure for all Phase 2 queue classes
- all new migrations upgrade and downgrade cleanly
- service layer coverage ≥ 90%

---

### Milestone 25: Strategy Studio and Blueprint UX

**Objective**

Build the non-technical strategy creation surface with draft persistence, blueprint
review, uncertainty explainer, and parameter bounds form.

**Deliverables**

- `StrategyStudioPage` at `/strategy-studio`
- `StrategyDraftForm`: React Hook Form + Zod; localStorage autosave on every field change
  (debounced 500 ms); backend sync every 30 s via `DraftAutosaveManager`; wired to
  `POST /strategies/draft`
- `DraftRecoveryBanner` shown on page load when `GET /strategies/draft/autosave/latest`
  returns a recoverable draft; "Restore draft" and "Start fresh" buttons only — no
  implicit auto-restore
- `BlueprintReview` at `/strategies/{id}/versions/{version}`: structured IR view in
  non-technical layout
- `UncertaintyExplainer`: per-entry severity badge, plain-language description, resolution
  form; `BlockerSummary` with owner card and `resolve_uncertainty` next-step when
  `MATERIAL_AMBIGUITY` is present
- Blocked-paper badge rendered when any `material` severity entry is unresolved
- `ParameterTuning` page: allowed parameterization fields; search space bounds form
- `CompilationStatus` component: stage-by-stage pipeline progress for in-progress compiles

**Acceptance criteria**

- draft-to-build flow completes end-to-end in E2E test
- closing the browser mid-form and reopening shows `DraftRecoveryBanner` with correct
  partial data (localStorage recovery path tested in Playwright)
- "Start fresh" discards the draft, calls `DELETE /strategies/draft/autosave/{id}`, and
  clears localStorage
- `MATERIAL_AMBIGUITY` blocker renders owner display name and `resolve_uncertainty` link
- material ambiguity entry blocks "compile to paper-eligible" — confirmed by E2E
- `ParameterTuning` form blocks submission when bounds are contradictory

---

### Milestone 26: Run Monitor and Optimization Progress

**Objective**

Build the run submission surface and live run monitoring views.

**Deliverables**

- Run submission forms wired to `POST /runs/research` and `POST /runs/optimize`
- `RunPage` at `/runs/{run_id}`: live-polling status, trial progress bar, stale-data
  indicator on poll failure per Section 8.1 backoff rules
- `OptimizationProgress`: trial count gauge, best-trial-so-far, trials-per-minute
- Terminal state handling: `completed` → results link; `failed` → error + retry;
  `cancelled` → cancellation reason
- Preflight failure display: structured rejection reasons from `run_preflight_results`
  with `BlockerSummary` including blocker owner card and next-step link per Section 8.3
- `TrialDetail` modal: full parameters, seed, fold metrics, objective value
- Override watermark rendered on run card if the strategy build has an active override

**Acceptance criteria**

- run submission E2E passes
- polling backoff respects 30 s cap; stale indicator appears within 5 s of simulated failure
- `PREFLIGHT_FAILED` renders structured rejection reasons with owner card
- trial log renders 100+ rows via virtual scroll without layout breakage
- override watermark renders when strategy build has an active override watermark

---

### Milestone 27: Results Explorer — Equity, Drawdown, Trade Blotter, Trial Tables

**Objective**

Build the quantitative results exploration surface with adaptive chart rendering and
full data export paths.

**Deliverables**

- `RunResultsPage` at `/runs/{run_id}/results`
- `EquityView`: `EquityCurve` component switching between Recharts and ECharts Canvas
  per `useChartEngine(equity_curve.length)`; fold-boundary overlays; `SamplingBanner`
  when `sampling_applied: true`
- `DrawdownCurve` rendered below equity curve; same engine-switching logic
- `SegmentedPerformanceBar`: per-fold and per-regime grouped bar chart
- `RegimeOverlay`: timeline color bands on equity chart per regime label
- `TradeBlotter`: filterable by symbol/side/fold/regime; virtual scroll via TanStack Virtual;
  Canvas chart panel for trade PnL distribution if `trades.length > 500`
- `TrialSummaryTable`: full trial grid; virtual scroll; highlight top-N; link to `TrialDetail`
- `CandidateComparisonTable`: side-by-side metric comparison
- "Download data" on every chart and table wired to zip bundle export endpoint
- `SamplingBanner` copy per Section 8.5
- `trades_truncated` banner: "Showing first 5 000 of {total_trade_count} trades.
  Download the full dataset for all records."

**Acceptance criteria**

- equity curve renders with Recharts for a 400-point series; with ECharts for a 1 500-point
  series — confirmed by inspecting DOM renderer attribute in unit tests
- `SamplingBanner` renders when `sampling_applied: true`
- `trades_truncated` banner renders when `trades_truncated: true`
- "Download data" triggers zip bundle download; extracted `metadata.json` contains `run_id`
  and correct `export_schema_version`
- fold-boundary overlays render on equity chart for a walk-forward run
- `TradeBlotter` with 1 000 rows renders via virtual scroll without horizontal overflow

---

### Milestone 28: Readiness Report Viewer and Candidate Comparison

**Objective**

Build the readiness evaluation surface and the candidate scoring breakdown that feeds
the governance promotion workflow.

**Deliverables**

- `RunReadinessPage` at `/runs/{run_id}/readiness`
- `ReadinessViewer`: overall grade badge (A–F, color-coded per Phase 2 §8.4); overall score;
  policy version displayed prominently
- `ScoringBreakdown`: per-dimension sub-score cards with threshold and pass/fail
- Holdout evaluation status card: pass/fail, dates, contamination flag
- Regime consistency table: per-regime Sharpe with pass/fail
- `READINESS_GRADE_F` renders `BlockerSummary` for each failing dimension including
  owner card and `view_readiness_breakdown` next-step
- "Generate readiness report" wired to `POST /runs/{run_id}/readiness`; disabled without
  `runs:write` scope
- Report history list: prior reports in reverse chronological order
- Override watermark on report if active override applies to the strategy build
- "Submit for promotion" wired to M29 governance flow; absent when grade is F;
  disabled when pending approval already exists for this run

**Acceptance criteria**

- readiness report loads and grade renders for a completed run in E2E test
- A–F grade badges use correct color mapping
- "Submit for promotion" is absent (not merely disabled) when grade is F — confirmed
  by unit test inspecting rendered DOM
- override watermark renders in amber when active override applies
- `BlockerSummary` for a failing dimension includes owner display name and next-step button

---

### Milestone 29: Governance Workflows Frontend — Approvals, Promotions, Override Visibility

**Objective**

Build the full approval and override management surfaces, enforcing separation-of-duties
in the UI and requiring evidence links for override requests.

**Deliverables**

- `ApprovalsPage` at `/approvals`: list filterable by status and request type
- `ApprovalDetail`: rationale, target object link, submitter, timestamps;
  approve/reject with confirmation modal
- `SeparationGuard` component: renders a named status block preventing submitters from
  interacting with approve/reject controls on their own requests
- `PromotionRequestForm` modal: rationale field; target stage; wired to
  `POST /promotions/request`
- `PromotionHistory` panel on `StrategyVersionPage`: timeline of all promotion requests
- `OverridesPage` at `/overrides`: active and historical overrides filterable by status
  and governance gate
- `OverrideRequestForm` modal: governance gate selector, target object, rationale text
  (non-empty), `evidence_link` field (required URI; Zod `.url()` validation with inline
  help copy: "Paste a link to your Jira ticket, Confluence doc, or GitHub issue")
- `OverrideViewer`: watermark detail, evidence link as a clickable external link,
  decision rationale, revocation history
- Override watermarks propagated to all required surfaces (Section 8.2)

**Acceptance criteria**

- complete approval flow in E2E test
- submitter cannot approve their own request: `SeparationGuard` renders and blocks buttons
- override request form rejects submission when `evidence_link` is empty — Zod validation
- override request form rejects submission when `evidence_link` is not a valid URL — Zod
- evidence link in `OverrideViewer` renders as a clickable `<a target="_blank">` link
- override watermark renders on all five required surfaces — confirmed by unit tests per surface
- approved override shows `ACTIVE` status; revoked override shows muted "revoked" label
- `ApprovalsPage` filters by status without full page reload

---

### Milestone 30: Feed Operations, Parity, Operator Dashboards, and Audit Explorer

**Objective**

Build the operational surfaces for data, infrastructure, and governance audit visibility.

**Deliverables**

- `FeedsPage` at `/feeds`: paginated feed list with health status badge; search by
  name/symbol/source
- `FeedDetailPage` at `/feeds/{feed_id}`: metadata, health timeline, anomaly list
- `FeedHealthDashboard`: summary cards for active/degraded/failed feeds
- `AnomalyViewer`: filterable anomaly event table across all feeds
- `ParityPage` at `/parity`: parity event list filterable by status
- Research launch blocker: if a required feed has unresolved anomalies or parity events,
  the "launch research" button is disabled with `DegradedDataBadge` and a tooltip that
  includes the blocker owner (the data engineer responsible for the feed)
- `QueuesPage` at `/queues`: per-queue-class card with depth, running, failed, throughput
- `ComputeContention`: per-queue-class contention chart over a selectable time range
- `AuditExplorer` at `/audit`: filterable paginated event table per Section 8.7;
  cursor pagination; no mutations
- `DiagnosticsShell`: read-only service health, version info, non-secret configuration

**Acceptance criteria**

- degraded feed renders non-neutral badge that cannot be suppressed — confirmed in unit test
- "launch research" is disabled with `DegradedDataBadge` and shows feed owner in tooltip
  when required feed has an unresolved anomaly — confirmed via MSW mock
- `AuditExplorer` cursor pagination loads next page without full reload
- `AuditExplorer` renders no action buttons
- `ComputeContention` time-range selector loads correct data window without re-rendering
  unrelated page sections

---

### Milestone 31: Export UX, Artifact Browser, Acceptance Test Pack, and Phase 3 Sign-Off

**Objective**

Complete export and artifact surfaces, execute the full Phase 3 acceptance test pack,
harden permissions, and confirm the phase is ready for sign-off.

**Deliverables**

- `ExportCenter` on `RunResultsPage`: download buttons for all Phase 2 export types;
  format selector (CSV zip, JSON, Parquet); in-progress state; `metadata.json` preview
  before download confirming run_id, export_schema_version, and override watermarks
- Lineage metadata check: extracted `metadata.json` from downloaded zip must contain all
  required fields — confirmed in Playwright download test
- `ExportHistory`: prior exports with schema_version, format, row_count, download link
- `ArtifactsPage` at `/artifacts`: searchable, filterable artifact browser; pagination
- `ArtifactBrowser` embedded on `RunPage` and `StrategyVersionPage`
- Phase 3 acceptance test pack: full Playwright suite for all Phase 3 Definition of Done items
- Permissions hardening: smoke test every protected route and action with a no-scope user;
  confirm 403 handling is graceful
- Accessibility sweep: keyboard navigation, ARIA labels, color contrast on all primary surfaces
- `npm run build` produces clean bundle with zero TypeScript errors, zero ESLint errors,
  coverage ≥ 80%

**Acceptance criteria**

- all Phase 3 Definition of Done criteria satisfied (Section 16)
- downloaded zip for a CSV export contains: `data.csv` (no comment rows), `metadata.json`
  (all required fields), `README.txt` — confirmed by Playwright download + unzip test
- zip exported under an active override includes the watermark ID in `metadata.json`
  `override_watermarks` array
- `ArtifactsPage` artifact-type filter returns correct results in E2E
- permissions smoke test: no-scope user sees only login; `researcher` role sees only
  researcher surfaces; action buttons outside scope are absent from DOM
- keyboard navigation reaches all primary interactive elements without mouse

---

## 13. Frontend Route Architecture

```text
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

All routes except `/403` and `/404` require an authenticated session. Routes requiring
a scope that the current user lacks render `ForbiddenPage`; they do not redirect to login.

---

## 14. Queue Classes (Phase 3 additions)

No new queue classes required. Phase 3 consumes Phase 2 queues as read-only telemetry.
The `queues.py` backend extension in M24 exposes Phase 2 queue metrics as read-only API
responses. No queue configuration changes are needed.

---

## 15. Observability

### Backend (Phase 3 additions)

Every new route emits Phase 1 structured log fields plus:

| Field | When present |
|---|---|
| `approval_request_id` | governance mutation contexts |
| `override_request_id` | override mutation contexts |
| `override_watermark_id` | watermark creation and revocation |
| `promotion_request_id` | promotion submission and decision |
| `chart_cache_hit` | chart endpoint — true if served from cache |
| `sampling_applied` | chart endpoint — true if LTTB was applied |
| `export_schema_version` | export endpoint responses |
| `ui_actor` | governance endpoints: actor identity from auth token |

Recommended backend metrics:

- `approval_requests_total{request_type,status}`
- `override_requests_total{governance_gate,status}`
- `chart_cache_hits_total`
- `chart_cache_misses_total`
- `lttb_applied_total`
- `export_requests_total{format,export_type}`
- `draft_autosaves_total`

### Frontend

The frontend must not log sensitive data (PII, tokens, strategy parameters) to the
browser console at any severity in production builds.

Frontend error events must be sent to the Phase 1 telemetry service on:
- unhandled Promise rejection
- React error boundary catch
- 4xx/5xx API responses not handled at the feature level

Each event must include: page route, component name, error code, correlation ID if
available from the API response.

---

## 16. Acceptance Test Pack

Minimum Playwright E2E acceptance tests:

1. unauthenticated user redirected to login from any protected route
2. no-scope user cannot access any feature page; sees empty navigator
3. researcher creates strategy draft, saves mid-form, closes browser, recovers draft via
   `DraftRecoveryBanner` on next login
4. "Start fresh" discards draft, clears localStorage, calls DELETE autosave endpoint
5. material ambiguity blocks "compile to paper-eligible"; blocker renders owner display name
6. researcher submits optimization run, monitors progress, views trial log updating live
7. completed run displays equity curve with correct engine (Recharts for short series,
   ECharts Canvas for long series — asserted via DOM)
8. `SamplingBanner` renders when equity curve `sampling_applied: true`
9. `trades_truncated` banner renders when `trades_truncated: true`
10. walk-forward equity curve renders fold-boundary overlays
11. regime overlay renders colored bands on equity chart
12. readiness report displays grade, policy version, per-dimension scores
13. grade F renders `BlockerSummary` with owner card and `view_readiness_breakdown` next-step
14. "Submit for promotion" absent when grade is F
15. promotion request submitted → pending approval state renders on run page
16. approver approves promotion — `SeparationGuard` absent for the approver
17. submitter cannot approve own request — `SeparationGuard` renders, blocks buttons
18. override request form rejects non-URL `evidence_link`
19. override request approved → watermark renders on run card, readiness page, and trade blotter
20. revoked watermark renders muted "revoked" label on all five required surfaces
21. degraded feed blocks "launch research" with `DegradedDataBadge` and feed owner in tooltip
22. CSV zip export contains `data.csv` (no comment rows), `metadata.json` with all fields,
    `README.txt`
23. zip export under active override includes watermark ID in `metadata.json`
24. artifact browser type filter returns correct results
25. audit explorer pagination loads next page; no action buttons present in DOM
26. queue health renders depth and contention per Phase 2 queue class
27. keyboard navigation reaches all primary interactive elements on strategy studio page
28. permissions smoke test: each role sees exactly the surfaces authorized by its scopes

---

## 17. Test Fixtures to Seed

- completed optimization run with walk-forward folds and regime baseline; equity curve
  with > 2 000 points (to exercise LTTB path) and with ≤ 2 000 points (SVG path)
- completed run with > 5 000 trades (to exercise `trades_truncated` path)
- completed run with grade-A readiness report
- completed run with grade-F readiness report (two failing dimensions with known owner IDs)
- run with an active override watermark (evidence_link pointing to a mock Jira URL)
- run whose required feed has an unresolved anomaly with an assigned data engineer owner
- pending approval request submitted by User A (for separation-of-duties test)
- approved override with active watermark and revoked override with muted watermark
- in-progress draft autosave for a test user (for recovery banner test)
- CSV and Parquet exports with canonical lineage zip bundle structure

---

## 18. Coding Standards (Phase 3 frontend additions)

- no `any` types without suppression comment and ticket reference
- no local state for server data — all server data through TanStack Query
- no `useEffect` for data fetching — use TanStack Query hooks only
- no inline styles — Tailwind utilities only; no `style={{}}` outside animation
- no hardcoded color values — only design system tokens
- no feature-level code in `pages/` — pages are composition only
- all permissions checks via `hasScope()` — no hardcoded role strings in component logic
- all user-visible strings via constant map — no hardcoded copy in JSX (prep for i18n)
- all chart engine selection via `useChartEngine(n)` — no inline threshold comparisons
  in component render functions
- `evidence_link` field validated with Zod `.url()` on the frontend and `CHECK` constraint
  at the database layer — never trust one side alone
- component test files co-located with component (`Component.test.tsx`)
- E2E tests in `frontend/e2e/` only; no Playwright code in `src/`

---

## 19. What Not To Do

- do not compute readiness, governance state, or override eligibility in the frontend
- do not implement role-based route guards as the sole access control
- do not render a blocker message without an owner and next step
- do not accept a free-text-only rationale for override requests — `evidence_link` is required
- do not allow the audit explorer to be used for mutations of any kind
- do not cache sensitive data (tokens, permission claims) in `localStorage`
- do not render charts without a corresponding zip bundle export path
- do not serve more than 2 000 equity curve points or 5 000 trade rows from the chart endpoint
- do not prepend metadata comments to CSV files — use the zip bundle format
- do not suppress degraded feed indicators, override watermarks, or contamination flags
- do not allow the separation-of-duties check to be bypassed client-side
- do not make synchronous blocking requests in UI event handlers
- do not build features that depend on backend endpoints not yet implemented and green

---

## 20. Phase 3 Definition of Done

Phase 3 is done only when all of the following are true:

1. a non-technical user can create a strategy draft, recover it after a session loss,
   and launch research/optimization through the UI in an E2E test without backend errors
2. every blocker rendered in the UI includes an owner and an actionable next step
3. a user can understand why a candidate is blocked for paper eligibility and know
   exactly who to contact to resolve it
4. approvers can see evidence, readiness score breakdown, audit history, and override
   state in one place; the evidence_link in any override is a clickable external URL
5. feed health, anomalies, and parity issues are visible with non-suppressible
   degraded-state indicators that include the responsible data engineer's identity
6. authorized users can download zip bundles containing clean CSVs and sidecar
   `metadata.json`; every export contains override watermark IDs where applicable
7. queue contention and job state are visible to operators
8. every UI mutation is backed by a stable backend API endpoint that emits an audit event
9. the separation-of-duties constraint is enforced in the UI and confirmed by E2E test
10. override watermarks are visible on all five required surfaces and cannot be hidden
11. chart rendering adapts to data density: SVG for small series, Canvas for large series
12. LTTB downsampling is applied server-side; raw data is available only via export
13. keyboard navigation reaches all primary interactive elements
14. frontend CI gate passes: zero TypeScript errors, zero ESLint errors, coverage ≥ 80%,
    all Playwright tests green
15. backend API extensions from M23 and M24 are fully documented in OpenAPI with
    correct error codes, envelope shapes, `evidence_link` validation notes, and
    idempotency behavior
16. a new developer can navigate the full strategy-to-promotion workflow from a fixture
    state, download a lineage-tagged export, and verify the watermark chain without reading
    code or querying the database directly

---

## 21. Final Guidance for Claude

If there is tension between "show the user more information" and "preserve governance
integrity by sourcing state from the backend only," always choose governance integrity.

If there is tension between "more interactive chart features" and "every chart data point
is exportable and the export is Excel-compatible," choose exportability and compatibility.

If there is tension between "a free-text rationale box is sufficient" and "evidence links
must be external, auditable, and machine-readable," choose the external evidence link.
Text boxes cannot be audited across systems. URLs can.

If there is tension between "simpler permission logic" and "separation of duties is
architecturally enforced," choose separation of duties.

If there is tension between "ship the frontend now and wire the API later," remember Rule 12:
specify and implement the endpoint first.

If there is tension between "draft loss is unlikely" and "non-technical users lose work,"
remember that lost work destroys adoption faster than any bug. Autosave is not a nice-to-have.

That is the governing spirit of this workplan.
