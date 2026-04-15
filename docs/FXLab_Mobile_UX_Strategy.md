# FXLab Mobile Operator Experience — Product & Implementation Package

**Version:** 1.0
**Date:** 2026-04-13
**Author:** Product / UX / Engineering
**Status:** Implementation-Ready Specification

---

## 1. Executive Summary

### Mobile UX Strategy

FXLab's mobile experience is designed as a **purpose-built operator control surface**, not a shrunken desktop. The phone becomes a command console for monitoring, approving, configuring, and emergency-controlling the trading platform when the operator is away from their desk.

The current FXLab frontend is a React 18 / TypeScript / Tailwind CSS application with 18 routes, 175 components, and a fixed 256px sidebar that renders the app unusable on any screen narrower than ~900px. There are zero mobile navigation patterns, no hamburger menu, no bottom nav, no touch-optimised controls. The app is desktop-only in practice.

This document specifies a deliberate mobile operator experience layered onto the existing codebase — not a rewrite, but a targeted set of additions that make the highest-value workflows genuinely functional on a phone.

### Design Philosophy

1. **Operator console, not analyst workbench.** Mobile is for acting and monitoring, not for deep research. Dense strategy editing and multi-chart comparative analysis stay on desktop.
2. **Safety-first interaction design.** Every destructive or high-value action requires explicit confirmation, uses fat-finger-resistant controls, and logs the originating device.
3. **Information density is a feature, not a bug — but only the right information.** Mobile screens surface the most urgent data first with progressive disclosure for detail.
4. **One-handed, thumb-zone-optimised.** Primary actions live in the bottom 40% of the screen. Navigation uses bottom tabs, not a sidebar.
5. **Offline-tolerant, latency-aware.** Optimistic UI where safe; explicit sync indicators where not.

### Top 5 Mobile Operator Use Cases (Priority Order)

1. **Emergency control** — Activate kill switch (global, strategy, or symbol scope), halt a run, freeze a deployment. This is the single most important mobile capability. Every second of delay in an emergency costs money.
2. **Run and deployment monitoring** — See what's running, what's completed, what's failed. Check P&L, positions, and health at a glance.
3. **Approval and governance** — Approve or reject promotion requests, review readiness reports, manage overrides. These are blocking actions that should not wait for desk time.
4. **Risk and configuration adjustment** — Update dollar amounts, risk limits, exposure caps, and alert thresholds from the field.
5. **Alert triage** — See risk alerts, data quality warnings, and audit events. Acknowledge, escalate, or defer.

---

## 2. Mobile User Personas and Usage Modes

### Persona 1: Operator-on-the-Go (Primary)

The platform operator who built and manages the strategies, runs backtests, configures paper/live deployments, and needs to stay in control when away from the desk. This is Glenn. Senior technical user, high context, low patience for unnecessary friction.

**Usage pattern:** Checks phone 5–15 times per day. Each session is 30 seconds to 5 minutes. Wants to see status, act on alerts, approve workflows, and get back to life.

### Persona 2: Approver/Reviewer

A governance role that reviews promotion requests, readiness reports, and override justifications. May or may not be the same person as the operator, but the mobile workflow is distinct: review evidence, approve or reject, move on.

**Usage pattern:** Triggered by notification. Reviews a specific item. Approves or rejects. Session is 1–3 minutes.

### Persona 3: Emergency Responder

Any authorised user who needs to activate emergency controls during a market event, system failure, or runaway strategy. This is the most time-critical persona.

**Usage pattern:** Rare but urgent. Needs to go from lock screen to kill switch activation in under 10 seconds.

### Usage Modes

| Mode | Description | Phone Support | Typical Duration |
|------|-------------|---------------|-----------------|
| **Emergency control** | Kill switch, halt, freeze | First-class, optimised for speed | < 30 seconds |
| **Monitoring** | Run status, P&L, positions, health | First-class, real-time | 30 sec – 2 min |
| **Approval/governance** | Approve, reject, review evidence | First-class, deliberate pace | 1 – 3 min |
| **Lightweight configuration** | Risk limits, dollar amounts, alert thresholds | First-class with confirmation gates | 2 – 5 min |
| **Backtest/optimisation setup** | Configure and launch runs | Supported but simplified | 3 – 8 min |
| **Paper trading setup** | Register deployment, configure equity | Supported but simplified | 2 – 5 min |
| **Deep analysis** | Multi-chart comparison, strategy editing, DSL coding | Discouraged — view-only summaries | N/A |
| **User administration** | Create users, assign roles, rotate secrets | Desktop-preferred, view-only on mobile | N/A |

### Tasks Supported vs. Discouraged on Phone

**Supported (first-class):**
- View dashboard with active runs, positions, P&L, alerts
- Activate/deactivate kill switches at any scope
- Monitor run progress and completion
- Review backtest results (summary metrics, not full equity curves)
- Approve or reject promotion requests
- Review readiness grades and blockers
- Edit risk limits, exposure caps, dollar amounts
- View and triage alerts
- Launch a pre-configured backtest or optimisation (from templates or recent configs)
- Register a paper trading deployment with basic parameters
- View audit trail (recent events, filtered)

**Discouraged (view-only or desktop-redirect):**
- Strategy DSL editing (Monaco editor requires keyboard + screen real estate)
- Parameter grid construction with many dimensions
- Full equity curve analysis with zoom/pan/overlay
- Side-by-side run comparison
- Detailed trade-by-trade inspection
- User creation and role management
- Secret rotation
- Complex override request creation (requires evidence links, long justification)

**Blocked on mobile:**
- Nothing is hard-blocked. Every screen renders. But the UX deliberately steers users toward desktop for tasks that are unsafe or impractical on a small screen. Strategy DSL editing, for example, renders read-only on mobile with a "Continue on Desktop" prompt.

---

## 3. Primary Mobile Workflows

### 3.1 Create and Launch a Backtest

**User goal:** Configure and start a backtest run from the phone.

**Entry point:** Bottom nav → Runs → FAB (+) → "New Backtest"

**Screen flow:**
1. **Run Type Selection** — Card picker: Backtest / Walk-Forward / Monte Carlo / Optimisation
2. **Backtest Setup** — Scrollable form:
   - Strategy picker (searchable dropdown of compiled strategies)
   - Symbol selector (multi-select with search, recently-used pinned at top)
   - Date range (start/end date pickers)
   - Interval selector (segmented control: 1m / 5m / 15m / 1h / 1d)
   - Initial equity (numeric input with currency formatting)
   - Commission per trade (numeric input)
   - Slippage % (numeric input with 0–100 constraint)
   - Advanced section (collapsed by default): lookback buffer days, indicator cache size
3. **Review & Confirm** — Summary card showing all parameters. "Launch Backtest" button with loading state.
4. **Confirmation** — Success toast with link to run monitor. Redirect to active runs list.

**Required inputs:** Strategy ID, at least one symbol, start date, end date. All others have sensible defaults.

**Validation and confirmations:**
- Strategy must be in compiled state (API validates, but UI filters to compiled-only)
- End date must be after start date
- Initial equity must be > 0
- "Launch Backtest" requires a single deliberate tap (no double-tap, but button disables immediately to prevent duplicate submission)

**Failure/edge cases:**
- No compiled strategies → Empty state with "Create strategy on desktop" link
- API validation error → Inline field errors, scroll to first error
- Network failure → Retry button with preserved form state
- Duplicate submission prevention → Mutation key deduplication via React Query

**Visible on mobile:** All setup fields, confirmation summary, submission result.

**Deferred to desktop:** Advanced parameter grid tuning, strategy DSL review before launch.

---

### 3.2 Create and Launch an Optimisation Run

**User goal:** Start an optimisation sweep from the phone.

**Entry point:** Bottom nav → Runs → FAB (+) → "New Optimisation"

**Screen flow:**
1. **Strategy & Symbol Selection** — Same as backtest setup
2. **Optimisation Parameters** — Simplified mobile form:
   - Date range
   - Interval
   - Initial equity
   - Optimisation metric (dropdown: Sharpe / Sortino / Calmar / Profit Factor / Max Drawdown / Total Return)
   - Walk-forward window sizes (in-sample bars, out-of-sample bars, step bars)
   - Parameter grid (simplified: show parameter names from strategy, allow min/max/step for each)
3. **Review & Confirm** — Summary card. "Launch Optimisation" button.
4. **Confirmation** — Success with estimated trial count.

**Required inputs:** Strategy ID, symbol(s), date range, parameter grid (at least one parameter with at least two values), window sizes.

**Validation and confirmations:**
- Parameter grid must produce ≤ 10,000 trials (mobile warning above 1,000; hard block above 10,000 to prevent accidental massive sweeps from phone)
- Walk-forward window sizes: in_sample_bars ≥ 10, out_of_sample_bars ≥ 5, step_bars ≥ 1
- Confirmation screen shows estimated trial count prominently

**Failure/edge cases:**
- Parameter grid too large → Warning modal with trial count, suggest reducing on desktop
- Strategy not compiled → Same as backtest
- Network timeout during submission → Retry with idempotency key

**Visible on mobile:** Core parameters, trial count estimate, submission result.

**Deferred to desktop:** Fine-grained parameter grid construction, multi-dimensional sweep visualisation.

---

### 3.3 Monitor Active Research Runs

**User goal:** See what's running, how far along it is, whether anything has failed.

**Entry point:** Bottom nav → Runs (badge shows active count)

**Screen flow:**
1. **Active Runs List** — Cards showing: run type icon, strategy name, symbol(s), status badge, progress bar (for optimisation), elapsed time, ETA if available. Pull-to-refresh. Filter chips: All / Running / Queued / Failed.
2. **Run Detail** (tap a card) — Full status view:
   - Status with timestamp
   - Configuration summary (collapsed, expandable)
   - Progress bar with trial count (optimisation)
   - Error message if failed
   - "Cancel Run" button (if cancellable)
   - Link to results (if completed)

**Required inputs:** None (read-only monitoring).

**Validation and confirmations:**
- Cancel requires confirmation modal: "Cancel run {id}? This cannot be undone."

**Failure/edge cases:**
- No active runs → Empty state: "No runs in progress"
- Stale data → StaleDataIndicator component (already exists in codebase)
- WebSocket disconnection → Fall back to polling (React Query refetchInterval)

**Visible on mobile:** Status, progress, elapsed time, error summary.

**Deferred to desktop:** Trial-by-trial detail modal, optimisation surface plots.

---

### 3.4 Review Completed Backtest Results

**User goal:** Check how a backtest performed — key metrics, pass/fail assessment.

**Entry point:** Runs list → Completed run card → Results

**Screen flow:**
1. **Results Summary Card** — Key metrics in a 2-column grid:
   - Total return %
   - Annualized return %
   - Max drawdown %
   - Sharpe ratio
   - Win rate
   - Profit factor
   - Total trades
   - Final equity
2. **Equity Curve** (optional) — Simplified single-line chart. Tap to expand to fullscreen landscape mode. No overlays on mobile.
3. **Actions** — "Export Results" button, "View Full Analysis on Desktop" link.

**Required inputs:** None (read-only).

**Visible on mobile:** All summary metrics, simplified equity curve.

**Deferred to desktop:** Drawdown curve overlay, regime bands, trade-by-trade table, indicator attribution, signal summary.

---

### 3.5 Configure a Paper Trading Scenario

**User goal:** Register a deployment for paper trading with initial parameters.

**Entry point:** Bottom nav → Runs → FAB (+) → "Paper Trading"

**Screen flow:**
1. **Deployment Selection** — Pick an existing approved deployment, or create new from a strategy
2. **Paper Trading Setup** — Form:
   - Initial equity (numeric input, currency formatted)
   - Risk limits (max position size, max exposure, max loss per day)
   - Confirm strategy and symbols
3. **Review & Register** — Summary card. "Start Paper Trading" button.
4. **Confirmation** — Success with link to paper trading monitor.

**Required inputs:** Deployment ID (or strategy to create one), initial equity.

**Validation and confirmations:**
- Deployment must be in approved state for paper trading
- Initial equity > 0
- Risk limits must be positive values
- Registration requires explicit confirmation tap

**Failure/edge cases:**
- No approved deployments → "No approved strategies available"
- Registration fails → Error with retry
- Already registered → Show current paper trading status instead

**Visible on mobile:** Setup form, confirmation, registration result.

**Deferred to desktop:** Advanced order routing configuration, fill model selection.

---

### 3.6 Monitor Paper Trading Status

**User goal:** Check positions, P&L, and order status for a paper trading deployment.

**Entry point:** Dashboard → Paper Trading card, or Runs → Paper Trading tab

**Screen flow:**
1. **Paper Trading Overview** — Card per deployment:
   - Strategy name
   - Net P&L (colour-coded green/red)
   - Open positions count
   - Account equity
   - Status badge (active/frozen)
2. **Deployment Detail** (tap) —
   - Account summary (equity, buying power, unrealised P&L)
   - Open positions list (symbol, qty, avg price, current price, P&L)
   - Recent orders (last 10, status badges)
   - "Freeze" / "Unfreeze" toggle
3. **Position Detail** (tap position) — Symbol, quantity, entry price, current price, unrealised P&L, % of portfolio

**Required inputs:** None (monitoring is read-only; freeze/unfreeze is the only action).

**Visible on mobile:** P&L, positions, account equity, freeze control.

**Deferred to desktop:** Full order history, reconciliation view, execution timeline replay.

---

### 3.7 Adjust Admin Settings

**User goal:** View and modify platform configuration settings.

**Entry point:** Bottom nav → More → Admin (if authorised)

**Screen flow:**
1. **Admin Hub** — Section cards:
   - User Management (view-only on mobile, "Manage on Desktop" for mutations)
   - Secret Management (view status, rotation dates — no rotation from mobile)
   - Platform Settings (if applicable)
2. **User List** (view-only) — Searchable list of users with role badges
3. **Secret Status** — List of secrets with expiration status, last rotated date. Expiring secrets highlighted.

**Required inputs:** None on mobile (view-only admin).

**Validation and confirmations:** N/A — mutations disabled on mobile.

**Failure/edge cases:**
- User without admin:manage scope → 403 screen, "Contact administrator"

**Visible on mobile:** User list, role assignments, secret expiration status.

**Deferred to desktop:** User creation, role changes, secret rotation, password resets. These are high-risk operations that benefit from full keyboard and deliberate desktop workflow.

---

### 3.8 Update Dollar Amounts, Risk Limits, or Exposure Caps

**User goal:** Adjust financial parameters for a deployment — position limits, loss thresholds, exposure caps.

**Entry point:** Dashboard → Deployment card → "Risk Settings", or More → Risk Settings

**Screen flow:**
1. **Deployment Picker** — If multiple active deployments, select one
2. **Risk Settings Editor** — Sectioned form:
   - **Position Limits:** Max position size ($), max position count
   - **Exposure Caps:** Max gross exposure ($), max net exposure ($), max single-name exposure (%)
   - **Loss Limits:** Max daily loss ($), max drawdown (%), circuit breaker threshold ($)
   - **Alert Thresholds:** VaR limit, concentration limit, correlation threshold
   - Each field shows current value, with edit icon to modify
3. **Change Review** — Diff view: "Current → New" for each changed field. All unchanged fields collapsed.
4. **Confirm Changes** — Re-authentication required (MFA or PIN). "Apply Changes" button.
5. **Confirmation** — Success with audit trail entry ID.

**Required inputs:** At least one changed value. All values must be positive (where applicable).

**Validation and confirmations:**
- All dollar amounts validated as positive decimals
- Percentage values validated 0–100
- Changes > 50% from current value trigger a warning: "This is a large change. Confirm?"
- MFA re-authentication required before applying any risk limit change
- Changes are logged with device identifier in audit trail

**Failure/edge cases:**
- Stale data (someone else changed limits) → Conflict error, force refresh
- MFA failure → Block change, suggest retry
- Network failure during save → Explicit error, no partial apply (server-side transaction)

**Visible on mobile:** Current values, edit form, diff review, confirmation.

**Deferred to desktop:** Historical limit change timeline, limit simulation/scenario analysis.

---

### 3.9 Review Alerts, Logs, Audit Trail, and Overrides

**User goal:** Triage recent alerts, review audit events, check override status.

**Entry point:** Dashboard → Alert badge, or Bottom nav → More → Alerts/Audit

**Screen flow:**
1. **Alert Centre** — Chronological feed of alerts:
   - Risk alerts (VaR breach, concentration, correlation)
   - Data quality alerts
   - System health alerts
   - Each card: severity icon, title, deployment, timestamp, "View" action
   - Filter chips: All / Critical / Warning / Info
   - Pull-to-refresh
2. **Alert Detail** (tap) — Full alert context, related deployment, affected positions, recommended action
3. **Audit Trail** — Searchable event log:
   - Filter by: event type, user, date range
   - Each entry: timestamp, user, action, resource, result
   - Infinite scroll pagination
4. **Active Overrides** — List of current overrides with type, scope, expiry, evidence link

**Required inputs:** None (read-only).

**Visible on mobile:** Alert feed, audit log with filters, override status.

**Deferred to desktop:** Audit export (CSV/JSON), complex multi-filter queries, override creation.

---

### 3.10 Approve, Block, or Promote Workflows

**User goal:** Act on a pending governance item — approve a promotion, reject with rationale, review readiness.

**Entry point:** Dashboard → "Pending Approvals" badge, or Bottom nav → More → Approvals

**Screen flow:**
1. **Approval Queue** — List of pending items:
   - Strategy name, requested by, requested at, readiness grade
   - Badge: awaiting your review
2. **Approval Detail** (tap) —
   - Strategy summary (name, version, symbols, run type)
   - Readiness grade (A/B/C/D) with blocker summary
   - Key metrics (Sharpe, drawdown, win rate)
   - Holdout test results (if available)
   - Requester identity
   - SoD check: "You cannot approve your own submission" (if applicable)
3. **Action Sheet** —
   - "Approve" — Single tap + confirmation modal
   - "Reject" — Opens text input for rationale (minimum 10 characters, enforced)
   - "Defer" — Dismiss without action, remains in queue

**Required inputs:** Rationale for rejection (min 10 chars). Approval requires no additional input.

**Validation and confirmations:**
- Separation of duties enforced: cannot approve own promotion
- Approval requires confirmation modal: "Approve promotion of {strategy} to {target}?"
- Rejection requires rationale (validated client-side and server-side)
- Both actions log device identifier in audit trail

**Failure/edge cases:**
- SoD violation → UI disables approve/reject, shows "Submitted by you — another approver required"
- Already acted on (race condition) → 409 Conflict, refresh queue
- Network failure → Retry with preserved rationale text

**Visible on mobile:** Approval queue, readiness summary, key metrics, action buttons.

**Deferred to desktop:** Full readiness report with regime consistency table, detailed blocker breakdown, historical promotion audit.

---

### 3.11 Access Emergency Controls (Kill Switch, Run Halt)

**User goal:** Stop something immediately. Kill a strategy, halt all execution, freeze a deployment.

**Entry point:** Three access paths (redundancy is intentional for emergencies):
1. Dashboard → persistent "Emergency" FAB (red, always visible)
2. Bottom nav → More → Emergency Controls
3. Notification tap → Direct to kill switch (if alert-triggered)

**Screen flow:**
1. **Emergency Controls Hub** — Three large tap targets:
   - **Global Kill** — Stop ALL deployments immediately (red, full-width)
   - **Strategy Kill** — Stop a specific strategy (orange)
   - **Symbol Kill** — Halt all activity on a symbol (orange)
   - Below: list of currently active kills with deactivation option
2. **Kill Switch Activation** (tap) —
   - Scope confirmation: "This will halt {scope description}"
   - Reason input (optional but recommended, free text)
   - **Slide-to-confirm** gesture (not a tap — prevents accidental activation)
   - For Global Kill: additional "Type KILL to confirm" text input
3. **Activation Result** — Confirmation with:
   - Halt event ID
   - Mean time to halt (mtth_ms)
   - Affected deployments count
   - Timestamp
4. **Active Kill Status** — Shows all active kills with:
   - Scope, activated by, activated at
   - "Deactivate" button (same slide-to-confirm pattern)

**Required inputs:** Kill scope. Reason is optional. Global kill requires text confirmation.

**Validation and confirmations:**
- Global kill: slide-to-confirm + type "KILL" — two independent confirmation gates
- Strategy/symbol kill: slide-to-confirm only
- Deactivation: slide-to-confirm
- All actions require valid authentication (token not expired)
- MFA re-authentication if last auth was > 5 minutes ago

**Failure/edge cases:**
- Network failure during kill activation → Immediate retry with exponential backoff (up to 3 retries). If all fail, show: "Kill switch activation may have failed. Contact operations immediately. Call: {ops phone number}"
- Already killed (idempotent) → Show success, note "already active"
- Token expired during emergency → Quick re-auth flow (PIN only, not full OIDC)

**Visible on mobile:** All emergency controls. Nothing deferred. Speed is paramount.

**Deferred to desktop:** Emergency posture configuration (flatten_all, cancel_open, hold, custom). Posture definition is complex and should be pre-configured on desktop, then simply executed on mobile.

---

## 4. Mobile Information Architecture

### Bottom Navigation Model (5 tabs)

The fixed sidebar is replaced on mobile with a bottom tab bar. Five tabs based on frequency and criticality:

| Tab | Icon | Label | Content |
|-----|------|-------|---------|
| 1 | `LayoutDashboard` | **Home** | Dashboard with status cards, alerts, quick actions |
| 2 | `Play` | **Runs** | Active runs, completed runs, new run creation |
| 3 | `ShieldAlert` | **Emergency** | Kill switches and emergency controls (red accent) |
| 4 | `Bell` | **Alerts** | Alert feed, audit log, notifications |
| 5 | `MoreHorizontal` | **More** | Approvals, Risk Settings, Feeds, Queues, Overrides, Audit, Admin, Artifacts |

The Emergency tab is always visible and uses a distinct red accent colour to ensure it is never missed. It is positioned in the centre of the tab bar (thumb-zone optimal for right-handed and left-handed users).

### Primary Sections (within "More" overflow)

The "More" tab contains a clean list of secondary sections:

- Approvals (with pending count badge)
- Risk Settings
- Overrides
- Audit Trail
- Feeds & Queues
- Parity
- Artifacts / Exports
- Admin (if authorised)
- Settings (session, notifications, display preferences)

### Mobile Home/Dashboard Screen

The dashboard is the first screen after login. It surfaces the most urgent information in priority order:

1. **Alert Banner** (if any critical alerts) — Red banner at top: "2 Critical Alerts" — tap to view
2. **Emergency Status** — If any kill switches are active, show prominently: "Global Kill Active since 14:23 UTC"
3. **Active Runs Card** — Count of running/queued runs, with status breakdown. Tap → Runs tab.
4. **P&L Summary Card** — Aggregate P&L across active deployments. Green/red colouring.
5. **Pending Approvals Card** — Count of items awaiting action. Tap → Approvals.
6. **Recent Completions** — Last 3 completed runs with status and key metric.
7. **Quick Actions** — Row of shortcut buttons: "New Backtest", "Risk Settings", "Kill Switch"

### Notification / Alert Centre Behaviour

- Push notifications for: critical risk alerts, kill switch activations/deactivations, run completions, run failures, approval requests, deployment state changes
- Notification tap deep-links to the relevant detail screen
- In-app badge counts on: Alerts tab (unread count), Approvals in More (pending count), Runs tab (active count)
- Alert centre supports pull-to-refresh and infinite scroll
- Critical alerts persist until acknowledged; info alerts auto-dismiss after 24 hours

### Quick Actions / Shortcuts

Persistent quick-action row on Dashboard (horizontally scrollable):

- **New Backtest** → Backtest setup
- **Risk Settings** → Deployment picker → Risk editor
- **Kill Switch** → Emergency controls
- **Approvals** → Approval queue
- **Export** → Recent exports

### Urgency-First Information Surfacing

The mobile UI follows a strict urgency hierarchy:

1. **Active kill switches** — Always visible (banner) when active
2. **Critical alerts** — Banner + badge, one tap to view
3. **Failed runs** — Prominent in run list, sorted to top
4. **Pending approvals** — Badge on More tab + dashboard card
5. **Running processes** — Dashboard summary card
6. **Completed results** — Available but not pushed to foreground
7. **Configuration/admin** — Buried in More tab, intentionally low-urgency

---

## 5. Screen-by-Screen Wireframe Descriptions

### 5.1 Mobile Home / Dashboard

```
┌─────────────────────────────┐
│ [FXLab]         [user] [⚙] │  ← Compact top bar: logo, avatar, settings
├─────────────────────────────┤
│ ⚠ 2 Critical Alerts    [→] │  ← Alert banner (red, if alerts exist)
├─────────────────────────────┤
│ ┌───────────┐ ┌───────────┐ │
│ │ Active    │ │ P&L       │ │  ← 2-column summary cards
│ │ Runs: 3   │ │ +$4,230   │ │
│ │ 2▶ 1⏳    │ │ ▲ 1.2%    │ │
│ └───────────┘ └───────────┘ │
│ ┌───────────┐ ┌───────────┐ │
│ │ Approvals │ │ Alerts    │ │
│ │ 2 pending │ │ 5 new     │ │
│ │   ◉       │ │ 2 crit    │ │
│ └───────────┘ └───────────┘ │
├─────────────────────────────┤
│ Quick Actions               │
│ [+ Backtest] [Risk] [Kill]  │  ← Horizontally scrollable pill buttons
├─────────────────────────────┤
│ Recent Completions          │
│ ┌─────────────────────────┐ │
│ │ Backtest · AAPL,MSFT    │ │
│ │ Sharpe: 1.45  ✅ Done   │ │
│ └─────────────────────────┘ │
│ ┌─────────────────────────┐ │
│ │ WalkFwd · SPY           │ │
│ │ Stability: 0.87  ✅     │ │
│ └─────────────────────────┘ │
├─────────────────────────────┤
│ [🏠] [▶Runs] [🛑Emrg] [🔔] [⋯]│  ← Bottom tab bar
└─────────────────────────────┘
```

**Major components:** Alert banner, 4 summary cards (2×2 grid), quick action row, recent completions list, bottom tab bar.

**Layout hierarchy:** Alert banner → summary cards → quick actions → recent activity → tab bar.

**Actions:** Tap any card → navigate to detail section. Tap quick action → shortcut to workflow.

**Mobile interaction:** Pull-to-refresh updates all cards. Cards are touch targets (min 48px height). Summary values use large typography for at-a-glance reading.

**Dense data handling:** Dashboard shows counts and single headline metrics only. No tables, no charts. Tap through for detail.

---

### 5.2 Backtest Setup Screen

```
┌─────────────────────────────┐
│ [←]  New Backtest           │
├─────────────────────────────┤
│                             │
│ Strategy                    │
│ ┌─────────────────────[▼]─┐ │
│ │ Select strategy...       │ │  ← Searchable bottom sheet picker
│ └─────────────────────────┘ │
│                             │
│ Symbols                     │
│ ┌─────────────────────────┐ │
│ │ [AAPL ×] [MSFT ×] [+]  │ │  ← Chip input with search
│ └─────────────────────────┘ │
│                             │
│ Date Range                  │
│ ┌───────────┐ ┌───────────┐ │
│ │ 2024-01-01│ │ 2024-06-30│ │  ← Native date pickers
│ │ Start     │ │ End       │ │
│ └───────────┘ └───────────┘ │
│                             │
│ Interval                    │
│ [1m][5m][15m][ 1h ][ 1d ]  │  ← Segmented control
│                             │
│ Initial Equity              │
│ ┌─────────────────────────┐ │
│ │ $  100,000.00           │ │  ← Numeric keypad, currency format
│ └─────────────────────────┘ │
│                             │
│ ▼ Advanced Options          │  ← Collapsed by default
│                             │
│ ┌─────────────────────────┐ │
│ │    Launch Backtest       │ │  ← Primary action, bottom-anchored
│ └─────────────────────────┘ │
├─────────────────────────────┤
│ [🏠] [▶Runs] [🛑Emrg] [🔔] [⋯]│
└─────────────────────────────┘
```

**Major components:** Back button, form fields (strategy picker, symbol chips, date pickers, segmented control, numeric input), collapsible advanced section, sticky submit button.

**Layout hierarchy:** Linear scrollable form. Submit button anchored to bottom above tab bar.

**Actions:** Fill form → Launch. Each field validates on blur.

**Mobile interaction:** Strategy picker opens as bottom sheet with search. Symbol input opens bottom sheet with search and recent symbols. Date pickers use native OS date picker. Numeric fields open numeric keypad. Segmented control uses horizontal scroll if needed.

**Dense data handling:** Advanced options collapsed. Only essential fields visible by default.

---

### 5.3 Optimisation Setup Screen

Same structure as Backtest Setup, with additional fields:

- Optimisation metric (dropdown / bottom sheet)
- Window sizes (in-sample bars, out-of-sample bars, step bars) — three numeric inputs in a row
- Parameter grid section — for each strategy parameter, show name with min/max/step inputs

Adds a **trial count estimator** that updates live as the user adjusts the parameter grid: "~360 trials estimated" with colour coding (green < 500, yellow 500–2000, red > 2000).

---

### 5.4 Active Run Monitor

```
┌─────────────────────────────┐
│ [←]  Runs                   │
│ [All] [Running] [Queued] [Failed] │  ← Filter chips, horizontally scrollable
├─────────────────────────────┤
│ ┌─────────────────────────┐ │
│ │ 🔬 Backtest             │ │
│ │ MA Crossover · AAPL     │ │
│ │ ▓▓▓▓▓▓▓░░░ 72%         │ │  ← Progress bar
│ │ Running · 3m 22s        │ │
│ └─────────────────────────┘ │
│ ┌─────────────────────────┐ │
│ │ 🔄 Walk-Forward         │ │
│ │ RSI MeanRev · SPY       │ │
│ │ ▓▓▓▓░░░░░░ 40%         │ │
│ │ Running · 12m 05s       │ │
│ └─────────────────────────┘ │
│ ┌─────────────────────────┐ │
│ │ ⏳ Monte Carlo           │ │
│ │ Stochastic · AAPL       │ │
│ │ Queued · waiting...     │ │
│ └─────────────────────────┘ │
│                             │
│ Completed (3)          [▼]  │  ← Collapsible section
│ ┌─────────────────────────┐ │
│ │ ✅ Backtest · MSFT      │ │
│ │ Sharpe 1.45 · 42 trades │ │
│ │ Completed 5m ago        │ │
│ └─────────────────────────┘ │
│                             │
│       [+ New Run]           │  ← FAB positioned above tab bar
├─────────────────────────────┤
│ [🏠] [▶Runs] [🛑Emrg] [🔔] [⋯]│
└─────────────────────────────┘
```

**Major components:** Filter chips, run cards with progress bars, collapsible completed section, FAB for new run.

**Actions:** Tap card → run detail. Tap FAB → run type selector. Pull-to-refresh.

**Mobile interaction:** Run cards auto-update via polling (5s interval for running, 30s for queued). Progress bar animates smoothly. Status badges use colour coding (blue=running, yellow=queued, red=failed, green=completed).

**Dense data handling:** Shows only essential info per card. Full config visible on detail screen.

---

### 5.5 Results Summary Screen

```
┌─────────────────────────────┐
│ [←]  Backtest Results       │
│ MA Crossover · AAPL, MSFT   │
├─────────────────────────────┤
│ ┌───────────┐ ┌───────────┐ │
│ │ Return    │ │ Sharpe    │ │
│ │ +12.5%    │ │ 1.45      │ │  ← 2-column metric grid
│ └───────────┘ └───────────┘ │
│ ┌───────────┐ ┌───────────┐ │
│ │ Max DD    │ │ Win Rate  │ │
│ │ -8.3%     │ │ 58%       │ │
│ └───────────┘ └───────────┘ │
│ ┌───────────┐ ┌───────────┐ │
│ │ Trades    │ │ P. Factor │ │
│ │ 42        │ │ 1.72      │ │
│ └───────────┘ └───────────┘ │
│ ┌───────────┐ ┌───────────┐ │
│ │ Equity    │ │ Annual.   │ │
│ │ $112,500  │ │ +25.0%    │ │
│ └───────────┘ └───────────┘ │
├─────────────────────────────┤
│ Equity Curve                │
│ ┌─────────────────────────┐ │
│ │    📈 (simplified)      │ │  ← Tap to fullscreen landscape
│ │   ╱╲  ╱╲╱╲   ╱         │ │
│ │  ╱  ╲╱     ╲╱          │ │
│ └─────────────────────────┘ │
│        [Tap to expand]      │
├─────────────────────────────┤
│ [Export] [Full Analysis →]  │
├─────────────────────────────┤
│ [🏠] [▶Runs] [🛑Emrg] [🔔] [⋯]│
└─────────────────────────────┘
```

**Major components:** Metric grid (4 rows × 2 columns), simplified equity curve, action buttons.

**Actions:** Export results (triggers export job), "Full Analysis" links to desktop-optimised view.

**Charts on mobile:** Simplified line chart (no overlays, no regime bands). Single tap → fullscreen landscape mode with pinch-to-zoom. Axis labels auto-abbreviated.

---

### 5.6 Paper Trading Setup Screen

Same structure as Backtest Setup, but:
- Deployment picker instead of strategy picker (shows approved deployments)
- Initial equity input
- Risk limit fields (max position size, max exposure, max daily loss)
- "Start Paper Trading" button

No date range (paper trading is open-ended). No interval (uses live/delayed data).

---

### 5.7 Paper Trading Monitor

```
┌─────────────────────────────┐
│ [←]  Paper Trading          │
│ MA Crossover · Active       │
├─────────────────────────────┤
│ ┌─────────────────────────┐ │
│ │ P&L Today    Equity     │ │
│ │ +$430        $100,430   │ │  ← Live-updating via WebSocket
│ │ ▲ 0.43%                 │ │
│ └─────────────────────────┘ │
├─────────────────────────────┤
│ Open Positions (2)          │
│ ┌─────────────────────────┐ │
│ │ AAPL  100 sh  +$280     │ │
│ │ avg $172.30  now $175.10│ │
│ └─────────────────────────┘ │
│ ┌─────────────────────────┐ │
│ │ MSFT  50 sh   +$150     │ │
│ │ avg $410.00  now $413.00│ │
│ └─────────────────────────┘ │
├─────────────────────────────┤
│ Recent Orders (3)           │
│ BUY  AAPL 100 @ $172.30 ✅ │
│ BUY  MSFT  50 @ $410.00 ✅ │
│ SELL GOOG  25 @ $142.00 ✅ │
├─────────────────────────────┤
│ [Freeze Deployment]         │  ← Orange button, confirmation required
├─────────────────────────────┤
│ [🏠] [▶Runs] [🛑Emrg] [🔔] [⋯]│
└─────────────────────────────┘
```

**Major components:** P&L header (live), positions list, recent orders, freeze button.

**Real-time updates:** WebSocket connection for position and P&L updates. Connection status indicator in top bar.

---

### 5.8 Admin Settings Hub

```
┌─────────────────────────────┐
│ [←]  Admin                  │
├─────────────────────────────┤
│ ┌─────────────────────────┐ │
│ │ 👥 Users           [→]  │ │
│ │ 12 users · 3 roles      │ │
│ │ View only on mobile      │ │
│ └─────────────────────────┘ │
│ ┌─────────────────────────┐ │
│ │ 🔑 Secrets          [→] │ │
│ │ 8 secrets · 1 expiring  │ │
│ │ View only on mobile      │ │
│ └─────────────────────────┘ │
│                             │
│ ℹ User management and       │
│ secret rotation require     │
│ desktop access.             │
├─────────────────────────────┤
│ [🏠] [▶Runs] [🛑Emrg] [🔔] [⋯]│
└─────────────────────────────┘
```

**Major components:** Section cards with summary counts, informational notice about desktop-only mutations.

---

### 5.9 Risk Settings Editor

```
┌─────────────────────────────┐
│ [←]  Risk Settings          │
│ MA Crossover Deployment     │
├─────────────────────────────┤
│ Position Limits             │
│ ┌─────────────────────────┐ │
│ │ Max Position Size       │ │
│ │ $ 25,000.00        [✏] │ │
│ └─────────────────────────┘ │
│ ┌─────────────────────────┐ │
│ │ Max Position Count      │ │
│ │ 10                 [✏] │ │
│ └─────────────────────────┘ │
│                             │
│ Exposure Caps               │
│ ┌─────────────────────────┐ │
│ │ Max Gross Exposure      │ │
│ │ $ 200,000.00       [✏] │ │
│ └─────────────────────────┘ │
│ ┌─────────────────────────┐ │
│ │ Max Single-Name %       │ │
│ │ 15.0%              [✏] │ │
│ └─────────────────────────┘ │
│                             │
│ Loss Limits                 │
│ ┌─────────────────────────┐ │
│ │ Max Daily Loss          │ │
│ │ $ 5,000.00         [✏] │ │
│ └─────────────────────────┘ │
│ ┌─────────────────────────┐ │
│ │ Circuit Breaker         │ │
│ │ $ 10,000.00        [✏] │ │
│ └─────────────────────────┘ │
│                             │
│ ┌─────────────────────────┐ │
│ │   Review Changes (2)    │ │  ← Appears when changes exist
│ └─────────────────────────┘ │
├─────────────────────────────┤
│ [🏠] [▶Runs] [🛑Emrg] [🔔] [⋯]│
└─────────────────────────────┘
```

**Mobile interaction:** Tap edit icon → field becomes editable with numeric keypad. Changed fields show yellow highlight. "Review Changes" button appears when any field is modified. Tapping it shows the diff screen with MFA re-auth before applying.

---

### 5.10 Alerts / Logs Screen

```
┌─────────────────────────────┐
│ [←]  Alerts                 │
│ [All][Critical][Warning][Info]│
├─────────────────────────────┤
│ ┌─────────────────────────┐ │
│ │ 🔴 VaR Breach           │ │
│ │ Deployment: MA Cross    │ │
│ │ VaR 99%: -$12,400       │ │
│ │ 2 minutes ago           │ │
│ └─────────────────────────┘ │
│ ┌─────────────────────────┐ │
│ │ 🟡 Concentration Alert  │ │
│ │ Deployment: RSI MeanRev │ │
│ │ AAPL: 42% of portfolio  │ │
│ │ 15 minutes ago          │ │
│ └─────────────────────────┘ │
│ ┌─────────────────────────┐ │
│ │ 🔵 Run Completed        │ │
│ │ Backtest: Stochastic    │ │
│ │ Sharpe: 0.82            │ │
│ │ 1 hour ago              │ │
│ └─────────────────────────┘ │
│                             │
│ ── Audit Trail ──           │
│ 14:23 admin activated       │
│       global kill switch    │
│ 14:20 system risk alert     │
│       VaR breach detected   │
│ 14:15 glenn approved        │
│       MA Cross promotion    │
│           [Load more...]    │
├─────────────────────────────┤
│ [🏠] [▶Runs] [🛑Emrg] [🔔] [⋯]│
└─────────────────────────────┘
```

**Dense data handling:** Alerts as cards with progressive disclosure (tap for detail). Audit trail as compact timeline. Infinite scroll with cursor-based pagination.

---

### 5.11 Approval / Review Screen

```
┌─────────────────────────────┐
│ [←]  Approval               │
│ Promote MA Crossover        │
├─────────────────────────────┤
│ Requested by: john.doe      │
│ Requested: Apr 13, 14:00    │
│                             │
│ ┌─────────────────────────┐ │
│ │ Readiness Grade         │ │
│ │        [ A ]            │ │  ← Large grade badge
│ │ 12/12 checks passed     │ │
│ └─────────────────────────┘ │
│                             │
│ Key Metrics                 │
│ Sharpe: 1.45  |  DD: -8.3% │
│ Trades: 42    |  WR: 58%   │
│                             │
│ Holdout Test: ✅ Passed     │
│ Sharpe: 1.32 (in-sample)   │
│ Sharpe: 1.18 (holdout)     │
│                             │
│ ▼ Blocker Details (0)       │  ← Expandable, empty if grade A
│ ▼ Full Readiness Report     │  ← Expandable
│                             │
│ ┌───────────┐ ┌───────────┐ │
│ │  Approve  │ │  Reject   │ │  ← Side-by-side action buttons
│ │    ✅     │ │    ❌     │ │
│ └───────────┘ └───────────┘ │
├─────────────────────────────┤
│ [🏠] [▶Runs] [🛑Emrg] [🔔] [⋯]│
└─────────────────────────────┘
```

---

### 5.12 Emergency Controls Screen

```
┌─────────────────────────────┐
│ [←]  Emergency Controls     │
├─────────────────────────────┤
│                             │
│ ┌─────────────────────────┐ │
│ │                         │ │
│ │   🛑 GLOBAL KILL        │ │  ← Full-width red button, 80px tall
│ │   Stop ALL deployments  │ │
│ │                         │ │
│ └─────────────────────────┘ │
│                             │
│ ┌─────────────────────────┐ │
│ │ ⚠ Strategy Kill    [→]  │ │  ← Orange, opens strategy picker
│ └─────────────────────────┘ │
│ ┌─────────────────────────┐ │
│ │ ⚠ Symbol Kill      [→]  │ │  ← Orange, opens symbol picker
│ └─────────────────────────┘ │
│                             │
│ Active Kills (1)            │
│ ┌─────────────────────────┐ │
│ │ 🔴 Symbol: AAPL         │ │
│ │ By: glenn · 14:23 UTC   │ │
│ │ [Deactivate]            │ │
│ └─────────────────────────┘ │
│                             │
│ ℹ Global kill requires      │
│ slide-to-confirm + type     │
│ "KILL" to activate.         │
├─────────────────────────────┤
│ [🏠] [▶Runs] [🛑Emrg] [🔔] [⋯]│
└─────────────────────────────┘
```

**Mobile interaction:** Global Kill button is intentionally oversized (80px height) for emergency speed. Tap → slide-to-confirm overlay → type "KILL" → activation. Strategy/Symbol kills open a picker first, then slide-to-confirm. All actions have haptic feedback on activation.

---

## 6. Mobile UI / Component Standards

### Forms

- Single-column layout, full-width fields
- Field labels above inputs (not inline placeholders that disappear)
- Inline validation on blur, error messages below field in red
- Sticky submit button anchored to bottom of viewport (above tab bar)
- Form state preserved during navigation away and back (React Query mutation cache or local state)

### Numeric Entry

- Trigger numeric keypad via `inputMode="decimal"` (not `type="number"` which has inconsistent behaviour)
- Currency fields: prefix with "$", auto-format with commas on blur (e.g., "100,000.00")
- Percentage fields: suffix with "%", constrain 0–100
- Stepper buttons (+ / −) flanking the input for fine adjustments
- Large input font (18px minimum) for readability

### Date/Time Selection

- Native OS date picker via `<input type="date">` — consistent, accessible, no library bloat
- Date range: two separate pickers (start, end) side by side
- Default values: last 6 months for backtests, today for monitoring views
- ISO 8601 display for timestamps in logs/audit (with relative time: "5m ago")

### Charts

- Use Recharts (not ECharts) on mobile — lighter weight, native React
- Simplified rendering: single line, no overlays, no regime bands
- ResponsiveContainer wrapping at 100% width, fixed 200px height in card view
- Tap to expand to fullscreen landscape mode with pinch-to-zoom
- Axis labels: abbreviated (e.g., "$100K" not "$100,000", "Jan" not "January")
- Maximum 500 data points on mobile (downsample server-side if needed)

### Logs

- Compact timeline format: timestamp + user + action on two lines
- Infinite scroll with cursor-based pagination (load 20 at a time)
- No horizontal scrolling — wrap long text
- Filter chips at top (horizontally scrollable)
- Tap entry to expand detail in a bottom sheet

### Tables

- Tables are forbidden on mobile for data wider than 3 columns. Use card lists instead.
- Position tables → position cards (symbol, qty, P&L per card)
- Audit tables → timeline entries
- Trade tables → trade cards
- If a table is absolutely necessary (e.g., correlation matrix), render as horizontally scrollable with frozen first column and sticky header

### Filters

- Horizontally scrollable chip row at top of list screens
- Active filters highlighted with filled background
- "Clear all" chip at the end
- Complex multi-field filters open in a bottom sheet (not inline expansion)

### Confirmations

- Standard actions: bottom sheet with action description + "Confirm" / "Cancel" buttons
- Destructive actions: modal overlay with red-accented "Confirm" button + action description
- Kill switch (global): slide-to-confirm + text input ("Type KILL to confirm")
- Risk limit changes: MFA re-authentication before final confirmation

### Alerts

- Critical: red banner at top of screen, persistent until dismissed
- Warning: yellow card in alert feed
- Info: blue card in alert feed, auto-dismisses after 24h
- Push notifications for critical and warning severity
- Haptic feedback on critical alert arrival

### Destructive Actions

- Never a single tap. Always requires either:
  - Confirmation modal (cancel run, reject approval)
  - Slide-to-confirm (kill switch activation/deactivation)
  - MFA + confirmation (risk limit changes, deployment freeze)
- Red colour accent on destructive buttons
- Action description in confirmation includes the specific scope: "Cancel backtest run {id}?" not just "Are you sure?"

### Loading / Progress States

- Skeleton screens for initial page loads (not spinners)
- Pull-to-refresh on all list screens
- Progress bars for running processes (animated, with percentage)
- Optimistic updates where safe (e.g., marking an alert as read)
- Explicit "Retrying..." state for failed network requests

### Authentication / Session

- JWT stored in memory only (no localStorage on mobile — matches current desktop pattern)
- Session timeout: 30 minutes of inactivity (configurable)
- Background refresh: silent token refresh before expiry
- Emergency override: if token expires during kill switch activation, allow PIN-only re-auth
- Biometric unlock option (FaceID/TouchID) for return-to-app within 5 minutes

### Touch Target Sizing

- Minimum touch target: 48×48px (Google Material Design guideline)
- Recommended for primary actions: 56×56px
- Kill switch button: 80px height minimum
- Spacing between adjacent touch targets: minimum 8px gap

### Typography Priorities

- Dashboard headline metrics: 28–32px bold
- Card titles: 16px semibold
- Card body text: 14px regular
- Timestamps and metadata: 12px regular, muted colour
- Form labels: 14px medium
- Form inputs: 16px regular (prevents iOS zoom on focus)
- Minimum body text: 14px (never smaller on mobile)

### One-Handed Usability

- Bottom tab bar for primary navigation (thumb zone)
- Primary action buttons anchored to bottom of screen
- Pull-to-refresh (top of screen) is the only common top-zone gesture
- Destructive actions require deliberate gesture (slide, not tap), reducing accidental activation
- Bottom sheets for pickers and confirmations (thumb-reachable dismiss)

### Thumb-Zone Placement

```
┌─────────────────────────┐
│                         │  ← Hard to reach (back button, settings)
│    READ-ONLY CONTENT    │
│                         │  ← Natural viewing zone (cards, metrics)
│                         │
│    SECONDARY ACTIONS    │  ← Easy reach (filter chips, card taps)
│                         │
│    PRIMARY ACTIONS      │  ← Thumb zone (submit, confirm, navigate)
│  ───────────────────── │
│  [Tab] [Tab] [Tab] [Tab]│  ← Bottom tab bar (optimal thumb reach)
└─────────────────────────┘
```

### Prevention of Accidental Taps

- Kill switch: slide-to-confirm gesture (not tap)
- Adjacent destructive/constructive buttons: minimum 16px gap + different colours
- Confirmation modals dim background and require deliberate tap on modal (tapping background cancels)
- Double-submission prevention: all mutation buttons disable immediately on tap
- Debounce all tap handlers (300ms)

### Dark Mode and Contrast

- Dark mode as default for trading apps (reduces eye strain, standard in fintech)
- Use existing FXLab brand palette — surface-950 (#020617) as dark background
- WCAG AA contrast minimum (4.5:1) for all text
- Colour-coded values: green for positive P&L/returns, red for negative — verified against both light and dark backgrounds
- Status colours (success/warning/danger) tested for colour-blind accessibility (deuteranopia, protanopia)
- Chart lines: use both colour and pattern/thickness to differentiate series

---

## 7. Security and Governance Requirements for Mobile

### Session Management

- **Session timeout:** 30 minutes of inactivity (same as desktop)
- **Active session indicator:** Green dot in top bar when connected; yellow when reconnecting; red when disconnected
- **Background handling:** When app backgrounds, WebSocket connections are paused. On foreground, stale data is refreshed before displaying. No actions are possible while in background.
- **Multi-device sessions:** Server tracks active sessions. If risk limit change is made from mobile while desktop is active, desktop session receives a push update.

### MFA / Re-Authentication for High-Risk Actions

The following actions require step-up authentication on mobile, regardless of how recently the user authenticated:

| Action | Re-Auth Method | Rationale |
|--------|---------------|-----------|
| Kill switch activation (any scope) | Biometric or PIN | Speed-critical, must not add friction beyond minimum |
| Kill switch deactivation | Biometric or PIN + slide-to-confirm | Deactivation is equally dangerous |
| Risk limit change | Full MFA (biometric + PIN or TOTP) | Financial impact, irreversible market exposure |
| Deployment state change (freeze, activate) | Biometric or PIN | Operational impact |
| Approval or rejection | Biometric or PIN | Governance integrity |
| Override creation | Full MFA | SOC 2 evidence chain |

For emergency actions (kill switch), if biometric fails, fall back to PIN immediately — never block emergency action behind a broken biometric sensor.

### Device Trust

- **No device registration requirement** (would add friction to emergency scenarios)
- **Device fingerprint logged** in audit trail (user agent, screen dimensions, platform)
- **Jailbreak/root detection:** Not enforced (web app, not native), but logged if detectable via browser APIs
- **TLS only:** All API communication over HTTPS. Certificate pinning if native app wrapping is added later.

### Safe Handling of Kill Switches and Admin Actions

- Kill switch activation is idempotent — multiple activations do not cause errors
- Kill switch deactivation requires the same auth level as activation
- Admin mutations (user management, secret rotation) are disabled on mobile entirely — these require desktop
- All mobile-originated actions carry a `source: "mobile"` field in the audit event
- Emergency posture (flatten_all, cancel_open) can be executed from mobile but cannot be configured from mobile (configuration requires desktop)

### Audit Logging for Mobile-Originated Actions

Every mutation from mobile writes an audit event with:

```json
{
  "event_type": "kill_switch_activated",
  "user_id": "01H...",
  "timestamp": "2026-04-13T14:23:00Z",
  "source": "mobile",
  "device_info": {
    "user_agent": "...",
    "platform": "iOS",
    "screen_width": 390,
    "screen_height": 844
  },
  "ip_address": "...",
  "auth_method": "biometric",
  "correlation_id": "01H..."
}
```

### Fat-Finger Protections

- Kill switch: slide-to-confirm + text confirmation (global)
- Risk limits: MFA + diff review before applying
- Approvals: confirmation modal with scope description
- Cancel run: confirmation modal with run ID
- All numeric inputs: show current value alongside new value during edit
- Large changes (>50% delta): explicit warning modal
- Undo capability for non-destructive actions (within 10-second window where possible)

### Approval Integrity and Non-Repudiation

- Approval/rejection actions are cryptographically tied to the user's JWT (sub claim)
- Separation of duties enforced server-side — cannot approve own submission regardless of client
- Rejection rationale is required (min 10 chars) and stored immutably in audit trail
- Timestamp of approval action comes from server, not client (prevents clock manipulation)
- Device fingerprint attached to approval audit event for forensic trail

---

## 8. API / Backend Requirements

### Mobile-Specific Summary Endpoints

The current API is designed for desktop consumption with full-detail responses. Mobile needs lighter payloads.

| New Endpoint | Purpose | Payload |
|-------------|---------|---------|
| `GET /mobile/dashboard` | Single call for all dashboard cards | `{active_runs: {count, breakdown}, pnl: {total, pct}, pending_approvals: count, critical_alerts: count, active_kills: [...], recent_completions: [{id, type, strategy, status, key_metric}]}` |
| `GET /mobile/runs/summary` | Compact run list for cards | `{runs: [{id, type, strategy_name, symbols, status, progress_pct, elapsed_ms}], total}` |
| `GET /mobile/pnl/overview` | Aggregate P&L across deployments | `{total_pnl, total_pnl_pct, by_deployment: [{id, name, pnl, pnl_pct}]}` |

**Rationale:** The dashboard screen currently requires 4+ API calls (runs list, P&L, approvals, alerts). A single `/mobile/dashboard` endpoint reduces round-trips from 4+ to 1, which matters on cellular networks with high latency.

### Simplified Payloads for Existing Endpoints

Several existing endpoints return more data than mobile needs. Add a `?view=compact` query parameter:

- `GET /research/runs?view=compact` — Omit config details, return only: id, type, strategy_id, status, progress, created_at, completed_at, key_metric
- `GET /pnl/{id}/summary?view=compact` — Omit timeseries, return only headline numbers
- `GET /risk/analytics/summary/{id}?view=compact` — Omit matrices, return only VaR, concentration_hhi, top_exposures (top 3)

### Pagination and Streaming for Logs

- **Audit endpoint:** Already supports cursor-based pagination — good as-is
- **Alert endpoint:** Add cursor-based pagination if not present: `GET /risk/alerts?cursor=&limit=20`
- **Reduce default page size** for mobile: `limit=20` (desktop uses 50-100)

### Optimised Run-Status Polling or Push Updates

**Current state:** Frontend uses React Query polling with staleTime of 5 minutes — too slow for run monitoring.

**Required changes:**

1. **Server-Sent Events (SSE) endpoint:** `GET /runs/events?run_ids=X,Y,Z` — stream status updates for specified runs. SSE is simpler than WebSocket for one-way server→client updates and works reliably on mobile browsers.

2. **Fallback polling:** If SSE connection drops, fall back to `GET /mobile/runs/summary` at 5-second intervals for active runs, 30-second for queued.

3. **Push notifications:** For critical events (run failed, kill switch activated, approval requested), send push notification via web push API or FCM if native app wrapper exists.

### Reduced Payload Views

Add `fields` parameter to key endpoints to request only needed fields:

```
GET /research/runs/{id}?fields=id,status,config.run_type,config.strategy_id,config.symbols,created_at,completed_at
```

This avoids transferring large result objects when only status is needed.

### Server-Side Validation Requirements

All validation currently happens server-side (good). Additional mobile-specific validation:

- **Rate limiting on mutations:** Mobile users should not be able to submit more than 5 runs per minute (prevents accidental rapid-fire submissions from a laggy connection)
- **Idempotency keys:** All mutation endpoints should accept an `Idempotency-Key` header to prevent duplicate submissions from network retries
- **Source tracking:** Accept `X-Client-Source: mobile` header, logged in audit trail

### Permission Scoping for Mobile

No changes to the permission model are needed — the existing scope-based system works correctly. However:

- **Admin mutations** should be blocked at the API level when `X-Client-Source: mobile` header is present (for user creation, secret rotation). This is a defense-in-depth measure — the UI also disables these, but the API should enforce it.
- This is an **optional** hardening measure. If it creates maintenance burden, rely on UI-level controls alone.

### Equity Curve Downsampling

Add server-side downsampling for equity curve data:

```
GET /research/runs/{id}/result?max_points=500
```

Returns at most 500 data points using LTTB (Largest Triangle Three Bucket) downsampling. Mobile charts cannot render thousands of points performantly.

---

## 9. Implementation Plan

### Phase 1: Core Mobile Shell + Emergency + Monitoring (Weeks 1–5)

**Goal:** Make the app usable on a phone for the three highest-value workflows: emergency control, run monitoring, and approvals. Also: eliminate three known blockers (dashboard data, WebSocket mobile lifecycle, MFA fallback) so that Phase 2 ships without surprises.

**Features:**
1. Mobile layout shell (bottom tab bar, hide sidebar on small screens, responsive top bar)
2. `/mobile/dashboard` backend summary endpoint (single call returns all dashboard card data)
3. Mobile dashboard (summary cards, alert banner, quick actions) wired to the summary endpoint
4. Emergency controls screen (kill switch activation/deactivation with slide-to-confirm)
5. Run monitor (active run cards with status and progress)
6. Results summary (metric grid for completed runs)
7. MFA re-authentication component with PIN/TOTP fallback (built now, used in Phase 2 risk editor)
8. WebSocket mobile lifecycle hardening (background/foreground reconnection, stale data detection)
9. Audit source tracking (backend: `source: "mobile"` in all mobile-originated audit events)

**Dependencies:**
- Backend: `/mobile/dashboard` endpoint (BE-01, built in parallel with frontend dashboard)
- Backend: audit source tracking (BE-07, must ship with first mobile release)
- Tailwind breakpoint additions to existing layout components

**Technical risks:**
- Kill switch slide-to-confirm requires a new interaction component not in the current codebase.
- WebAuthn (biometric) availability varies by mobile browser. Mitigation: the MFA component is built with PIN/TOTP as the primary path, biometric as progressive enhancement — not the other way around. This means risk limit editing will work on every mobile browser from day one, even if biometric is unavailable.

**UX risks:**
- Bottom tab bar may conflict with browser chrome on iOS Safari (safe area insets needed).
- Emergency controls must be tested on actual devices — simulator is insufficient for gesture verification.

**Sequence:**
1. Mobile layout shell + bottom nav (foundation for everything else)
2. `/mobile/dashboard` endpoint (backend, parallel with step 1)
3. Dashboard screen wired to summary endpoint (validates the shell + backend integration)
4. Emergency controls (highest-value single screen)
5. Run monitor (second-highest-value)
6. Results summary (completes the monitoring loop)
7. MFA re-auth component with PIN/TOTP fallback (built now, tested standalone)
8. WebSocket mobile lifecycle hardening + real-device testing
9. Audit source tracking (backend)

---

### Phase 2: Configuration + Run Setup + Paper Trading (Weeks 6–9)

**Goal:** Enable risk configuration, run creation, paper trading, and alert triage from mobile.

**Features:**
1. Risk settings editor with MFA re-auth (uses MFA component built in Phase 1)
2. Alert/audit screen
3. Backtest setup form
4. Optimisation setup form
5. Paper trading setup and monitor

**Dependencies:**
- Phase 1 complete (layout shell, dashboard, MFA component, WebSocket hardening)
- Risk limits PUT endpoint validation for large-change warnings

**Technical risks:**
- Form state preservation across navigation requires careful React Query / state management.

**UX risks:**
- Backtest setup form may feel too long on phone. Mitigation: sensible defaults, collapsed advanced section.
- Optimisation parameter grid is inherently desktop-oriented. Mobile version must be simplified (min/max/step per param, not full grid builder).

**Sequence:**
1. Risk settings editor (high-value configuration, MFA component ready from Phase 1)
2. Alert/audit screen (operational awareness)
3. Backtest setup (most common run type)
4. Optimisation setup (builds on backtest form)
5. Paper trading setup and monitor (extends run monitoring)

---

### Phase 3: Polish, Push Notifications, and Performance (Weeks 10–12)

**Goal:** Production-grade mobile experience with push notifications, real-time streaming, and performance optimisation.

**Features:**
1. Push notifications (critical alerts, run completion, approval requests)
2. SSE endpoint for real-time run status
3. Compact view parameters for existing endpoints
4. Equity curve downsampling endpoint
5. Biometric session resume as progressive enhancement (FaceID/TouchID within 5-minute window — layered on top of the PIN/TOTP foundation built in Phase 1)
6. Dark mode optimisation and accessibility audit
7. Performance tuning (bundle size, lazy loading, skeleton screens)

**Dependencies:**
- Web Push API registration (service worker)
- SSE infrastructure (or fallback to polling)
- Server-side downsampling library (LTTB)

**Technical risks:**
- Web Push requires service worker registration, which adds complexity to the Vite build pipeline
- SSE connections on mobile may be killed by OS battery optimisation. Polling fallback is mandatory.

**UX risks:**
- Push notification permission fatigue — only request on first critical alert, not on app open
- Dark mode colour contrast must be re-verified for all component states

**Sequence:**
1. SSE for run status + polling fallback
2. Push notifications
3. Compact views + downsampling
4. Biometric session resume (progressive enhancement)
5. Dark mode + accessibility audit
6. Performance tuning + final QA

---

## 10. User Stories and Acceptance Criteria

### US-1: Mobile Dashboard

**As** an operator, **I want** to see a dashboard on my phone showing active runs, P&L, pending approvals, and critical alerts, **so that** I can assess platform health in under 10 seconds.

**Acceptance criteria:**
- [ ] Dashboard loads within 3 seconds on 4G connection (simulated with Chrome DevTools network throttling)
- [ ] Dashboard displays without horizontal scrolling on any screen width ≥ 320px
- [ ] Active run count, P&L summary, pending approval count, and critical alert count are visible without scrolling
- [ ] Tapping any summary card navigates to the corresponding detail section
- [ ] Pull-to-refresh updates all dashboard data
- [ ] If kill switches are active, an alert banner is visible at the top of the screen

### US-2: Kill Switch Activation

**As** an operator in an emergency, **I want** to activate the kill switch from my phone, **so that** I can halt trading immediately regardless of my location.

**Acceptance criteria:**
- [ ] Kill switch is reachable in ≤ 2 taps from any screen (Emergency tab is always in bottom nav)
- [ ] Global kill requires slide-to-confirm gesture + typing "KILL"
- [ ] Strategy/symbol kill requires slide-to-confirm gesture only
- [ ] Kill activation completes within 5 seconds of final confirmation (network time)
- [ ] Activation result shows halt event ID, affected deployment count, and mean time to halt
- [ ] Active kills are listed with scope, activator, and timestamp
- [ ] Deactivation requires the same slide-to-confirm gesture
- [ ] If network fails during activation, UI shows retry with exponential backoff (3 attempts)
- [ ] All kill switch actions are logged with `source: "mobile"` in audit trail

### US-3: Run Monitoring

**As** an operator, **I want** to monitor active research runs on my phone, **so that** I can check progress and catch failures without being at my desk.

**Acceptance criteria:**
- [ ] Active runs list renders without horizontal scrolling
- [ ] Each run card shows: type, strategy name, symbol(s), status, progress bar, elapsed time
- [ ] Run cards update at least every 10 seconds for running runs
- [ ] Failed runs sort to the top of the list
- [ ] Tapping a run card shows full detail including error message (if failed)
- [ ] Cancel run action requires confirmation modal
- [ ] Filter chips (All / Running / Queued / Failed) work correctly

### US-4: Backtest Creation

**As** an operator, **I want** to create and launch a backtest from my phone, **so that** I can start research runs while away from my desk.

**Acceptance criteria:**
- [ ] Backtest can be configured and launched in ≤ 8 taps (strategy selection, symbol selection, date range, launch)
- [ ] Strategy picker shows only compiled strategies, with search
- [ ] Symbol picker supports search and shows recently-used symbols
- [ ] Date pickers use native OS date selection
- [ ] Initial equity input opens numeric keypad with currency formatting
- [ ] Form validates on field blur with inline error messages
- [ ] Duplicate submission is prevented (button disables on tap)
- [ ] Success redirects to run monitor with the new run visible

### US-5: Results Review

**As** an operator, **I want** to review backtest results on my phone, **so that** I can make decisions about strategy performance remotely.

**Acceptance criteria:**
- [ ] Results screen shows 8 key metrics (return, annualised return, max DD, Sharpe, win rate, profit factor, trades, final equity) in a 2-column grid
- [ ] All metrics render without horizontal scrolling on 320px width
- [ ] Simplified equity curve renders in a 200px-height card
- [ ] Tapping equity curve opens fullscreen landscape view
- [ ] "Export Results" button triggers export job creation

### US-6: Risk Limit Editing

**As** an operator, **I want** to edit risk limits from my phone, **so that** I can adjust position sizes and exposure caps in response to market conditions.

**Acceptance criteria:**
- [ ] Risk settings show current values for all limit fields
- [ ] Tapping edit icon on a field opens inline editing with numeric keypad
- [ ] Changed fields are visually highlighted (yellow background)
- [ ] "Review Changes" shows diff (current → new) for all modified fields
- [ ] Changes > 50% from current value trigger a warning dialog
- [ ] MFA re-authentication is required before applying changes
- [ ] Successful save shows audit trail entry ID
- [ ] Concurrent modification (stale data) shows conflict error with refresh option

### US-7: Approval Workflow

**As** an approver, **I want** to approve or reject promotion requests from my phone, **so that** governance actions are not delayed by my physical location.

**Acceptance criteria:**
- [ ] Pending approvals count is visible on dashboard
- [ ] Approval detail shows: requester, readiness grade, key metrics, holdout results
- [ ] Approve action requires confirmation modal
- [ ] Reject action requires rationale input (minimum 10 characters, enforced)
- [ ] SoD violation disables approve/reject buttons with explanation text
- [ ] Approval/rejection logged with `source: "mobile"` in audit trail

### US-8: Alert Triage

**As** an operator, **I want** to view and triage alerts on my phone, **so that** I can respond to risk events and system issues promptly.

**Acceptance criteria:**
- [ ] Critical alerts are visible within 1 tap from dashboard (alert banner → alert detail)
- [ ] Alert feed loads with newest-first ordering
- [ ] Filter chips (All / Critical / Warning / Info) filter the alert feed
- [ ] Each alert card shows: severity icon, title, deployment, timestamp
- [ ] Tapping an alert shows full context in a bottom sheet or detail view
- [ ] Pull-to-refresh loads new alerts

### US-9: Paper Trading Monitor

**As** an operator, **I want** to monitor paper trading positions and P&L on my phone, **so that** I can track strategy performance in real-time.

**Acceptance criteria:**
- [ ] Paper trading overview shows: net P&L, equity, position count per deployment
- [ ] Position list shows: symbol, quantity, average price, current price, P&L
- [ ] P&L values update in real-time via WebSocket (when connected) or polling (fallback)
- [ ] Freeze/unfreeze deployment action requires confirmation
- [ ] Connection status indicator shows WebSocket state

### US-10: Mobile Navigation

**As** a mobile user, **I want** to navigate the app using a bottom tab bar, **so that** all primary sections are reachable with my thumb.

**Acceptance criteria:**
- [ ] Bottom tab bar renders on screens < 1024px width
- [ ] Sidebar is hidden on screens < 1024px width
- [ ] All 5 tab icons have labels and meet 48×48px minimum touch target
- [ ] Active tab is visually distinct (filled icon + accent colour)
- [ ] Badge counts update on Runs and Alerts tabs
- [ ] Tab bar respects iOS safe area insets (no overlap with home indicator)

---

## 11. Engineering Ticket Breakdown

### Frontend Tickets

**FE-01: Mobile Layout Shell**
- **Description:** Replace fixed sidebar layout with responsive layout: sidebar on desktop (≥1024px), bottom tab bar on mobile (<1024px). Update AppShell, Sidebar, TopBar to use responsive visibility. Add BottomTabBar component.
- **Dependencies:** None (foundation ticket)
- **Priority:** P0 — foundation for all other mobile work. The sidebar responsive fix itself is a one-line change; the real work is the bottom tab bar and responsive top bar.
- **Acceptance criteria:** App renders with bottom tabs on mobile, sidebar on desktop. No horizontal scrolling on 320px screen. Safe area insets handled on iOS.

**FE-02: BottomTabBar Component**
- **Description:** Create BottomTabBar with 5 tabs (Home, Runs, Emergency, Alerts, More). Centre Emergency tab with red accent. Badge support on Runs and Alerts tabs. Tab routing integration with react-router-dom.
- **Dependencies:** FE-01
- **Priority:** P0
- **Acceptance criteria:** 5 tabs render, navigation works, badges update, touch targets ≥ 48px, Emergency tab visually distinct.

**FE-03: Mobile Dashboard Screen**
- **Description:** Build mobile-optimised dashboard with: alert banner, 2×2 summary card grid (active runs, P&L, approvals, alerts), quick action row, recent completions list. Pull-to-refresh. Responsive — renders as current placeholder on desktop.
- **Dependencies:** FE-01, FE-02
- **Priority:** P0
- **Acceptance criteria:** Per US-1 acceptance criteria.

**FE-04: Emergency Controls Screen**
- **Description:** Build Emergency Controls page with: Global Kill button (80px, red), Strategy Kill picker (uses BottomSheet from FE-22), Symbol Kill picker, active kills list with deactivation. Slide-to-confirm gesture (from FE-22). Text confirmation for global kill. Reuses existing ConfirmationModal for deactivation confirmations.
- **Dependencies:** FE-01, FE-02, FE-22
- **Priority:** P0
- **Acceptance criteria:** Per US-2 acceptance criteria.

**FE-00: Responsive Quick Fixes**
- **Description:** Apply targeted Tailwind responsive fixes to existing components that are currently broken on 430px viewports due to hardcoded grid column counts. Specifically: `ApprovalDetail.tsx` grid-cols-2 → grid-cols-1 sm:grid-cols-2, `RunDetailView.tsx` grid-cols-2 → grid-cols-1 sm:grid-cols-2, `OptimizationProgress.tsx` grid-cols-3 → grid-cols-1 sm:grid-cols-3. This makes these screens mobile-functional without building new mobile-specific pages, reducing the scope of FE-06 and FE-10.
- **Dependencies:** None
- **Priority:** P0 — 1–2 hours of work, high leverage. Ship in week 1 alongside FE-01.
- **Acceptance criteria:** ApprovalDetail, RunDetailView, and OptimizationProgress render without horizontal scrolling on 430px viewport. No desktop regressions (verify sm: breakpoint renders same as current grid-cols-2/3 on desktop).

**FE-05: SlideToConfirm Component**
- **Description:** MERGED INTO FE-22 (Mobile Interaction Primitives). See FE-22.
- **Status:** Superseded by FE-22.

**FE-22: Mobile Interaction Primitives Kit**
- **Description:** Unified mobile interaction layer containing three components and one hook, built as a coordinated kit with shared touch handling, backdrop management, focus trapping, and safe area calculations. Includes: (1) `SlideToConfirm` — gesture component for destructive/emergency actions, minimum 200px slide distance, haptic feedback, customisable label and colour theme. (2) `BottomSheet` — overlay that renders at 50% viewport height, stretches to 90% on search focus, swipe-down to dismiss, backdrop tap to cancel. Supports search, single/multi-select, recently-used items. (3) `useMediaQuery` hook — the codebase currently has zero JavaScript-level viewport detection; all responsive behaviour is CSS-only. This hook enables conditional component tree rendering (sidebar vs. bottom tabs, table vs. card list). Consolidates FE-05 and FE-09.
- **Dependencies:** None (reusable primitives)
- **Priority:** P0 — Phase 1, week 2. Consumed by FE-04 (SlideToConfirm), FE-08 (BottomSheet), FE-10 (BottomSheet), FE-01 (useMediaQuery for sidebar toggle).
- **Acceptance criteria:** SlideToConfirm works on iOS Safari and Android Chrome with haptic feedback. BottomSheet renders, scrolls, and dismisses correctly on 430px viewport. useMediaQuery correctly detects viewport transitions across Tailwind breakpoints. All three share a common backdrop/focus-trap primitive.

**FE-06: Run Monitor Mobile Cards**
- **Description:** Create mobile-optimised run card component showing: type icon, strategy name, symbols, status badge, progress bar, elapsed time. Filter chips row. FAB for new run. Run detail links to existing RunDetailView (made mobile-ready by FE-00). Responsive run list page.
- **Dependencies:** FE-01, FE-00
- **Priority:** P0
- **Acceptance criteria:** Per US-3 acceptance criteria.

**FE-07: Results Summary Mobile**
- **Description:** Build mobile results screen with 2-column metric grid (8 metrics), simplified equity curve (200px height), fullscreen landscape chart viewer, export button.
- **Dependencies:** FE-06
- **Priority:** P1
- **Acceptance criteria:** Per US-5 acceptance criteria.

**FE-08: Backtest Setup Form (Mobile)**
- **Description:** Mobile-optimised backtest creation form: strategy picker (uses BottomSheet from FE-22), symbol chips (uses BottomSheet from FE-22), native date pickers, segmented interval selector, numeric equity input, collapsible advanced section, sticky submit button.
- **Dependencies:** FE-01, FE-22
- **Priority:** P1
- **Acceptance criteria:** Per US-4 acceptance criteria.

**FE-09: BottomSheetPicker Component**
- **Description:** MERGED INTO FE-22 (Mobile Interaction Primitives). See FE-22.
- **Status:** Superseded by FE-22.

**FE-10: Approval Queue and Detail**
- **Description:** Build mobile approval queue (card list with pending items). The approval detail screen is now mostly handled by FE-00 (responsive fixes to ApprovalDetail.tsx), so this ticket focuses on: queue list with pending count badge, action buttons (approve/reject) using existing ConfirmationModal, rejection rationale input with 10-char minimum, SoD enforcement display.
- **Dependencies:** FE-01, FE-00
- **Priority:** P0 (MVP — approval workflow is in the MVP scope)
- **Acceptance criteria:** Per US-7 acceptance criteria.

**FE-11: Risk Settings Editor Mobile**
- **Description:** Build risk settings editor with: deployment picker, sectioned limit display (current values), inline edit mode, change diff review, MFA re-auth integration, large-change warning. Numeric inputs with currency/percentage formatting.
- **Dependencies:** FE-01, FE-12
- **Priority:** P1
- **Acceptance criteria:** Per US-6 acceptance criteria.

**FE-12: MFA Re-Authentication Component**
- **Description:** Modal component for step-up authentication. PIN/TOTP is the primary path (works everywhere). WebAuthn (biometric) is progressive enhancement layered on top. Returns auth confirmation to parent on success. Timeout after 60 seconds. Built in Phase 1 so it is tested and ready before Phase 2 risk editor needs it.
- **Dependencies:** None (auth component)
- **Priority:** P0 — Phase 1. Building this early eliminates the risk of discovering browser-specific MFA failures when the risk editor ships in Phase 2. PIN/TOTP as the primary path guarantees every mobile browser works from day one; biometric is added as a convenience in Phase 3.
- **Acceptance criteria:** PIN and TOTP auth methods work on iOS Safari and Android Chrome. Biometric (WebAuthn) works where supported, fails gracefully to PIN/TOTP where not. 60-second timeout with retry.

**FE-13: Alert Feed Screen**
- **Description:** Build alert/notification screen with: severity-coded cards, filter chips, infinite scroll with cursor pagination, bottom sheet detail view. Pull-to-refresh. Audit trail section with compact timeline.
- **Dependencies:** FE-01
- **Priority:** P1
- **Acceptance criteria:** Per US-8 acceptance criteria.

**FE-14: Paper Trading Monitor Mobile**
- **Description:** Build paper trading overview (deployment cards with P&L) and detail screen (account summary, positions list, recent orders, freeze/unfreeze toggle). WebSocket integration for live updates. Connection status indicator.
- **Dependencies:** FE-01, FE-06
- **Priority:** P2
- **Acceptance criteria:** Per US-9 acceptance criteria.

**FE-15: Optimisation Setup Form (Mobile)**
- **Description:** Extend backtest form with: optimisation metric picker, window size inputs, simplified parameter grid (min/max/step per parameter), trial count estimator with colour coding. Validation for max trial count.
- **Dependencies:** FE-08
- **Priority:** P2
- **Acceptance criteria:** Parameter grid produces correct trial count. Warning at > 1000 trials. Block at > 10,000 trials.

**FE-16: Paper Trading Setup Form**
- **Description:** Build paper trading registration form: deployment picker, initial equity input, risk limit fields, review card, submit. Validates deployment is in approved state.
- **Dependencies:** FE-08, FE-11
- **Priority:** P2
- **Acceptance criteria:** Registration succeeds, redirects to paper trading monitor.

**FE-17: Admin Hub (View-Only Mobile)**
- **Description:** Build admin section for mobile showing: user list (read-only), secret expiration status (read-only). Desktop-redirect messaging for mutations.
- **Dependencies:** FE-01
- **Priority:** P3
- **Acceptance criteria:** Users and secrets display correctly. No mutation controls on mobile. "Manage on Desktop" link renders.

**FE-18: Dark Mode and Accessibility Audit**
- **Description:** Verify all mobile components meet WCAG AA contrast ratios in dark mode. Test colour-blind accessibility for status colours. Add aria-labels to all interactive elements. Test with VoiceOver (iOS) and TalkBack (Android).
- **Dependencies:** All FE tickets
- **Priority:** P2
- **Acceptance criteria:** All text meets 4.5:1 contrast ratio. All interactive elements have accessible labels. Status colours distinguishable for deuteranopia and protanopia.

**FE-19: Fullscreen Landscape Chart Viewer**
- **Description:** Modal chart viewer that forces landscape orientation, renders equity curve with pinch-to-zoom and pan. LTTB-downsampled data. Abbreviated axis labels. Close button in safe zone.
- **Dependencies:** FE-07
- **Priority:** P2
- **Acceptance criteria:** Chart renders in landscape. Pinch-to-zoom works on iOS and Android. Close button ≥ 48px touch target.

**FE-20: Push Notification Registration**
- **Description:** Service worker registration for Web Push API. Permission request UX (request on first critical alert, not on app launch). Handle notification tap → deep link to relevant screen.
- **Dependencies:** BE-03
- **Priority:** P3
- **Acceptance criteria:** Push notifications received on iOS Safari 16.4+ and Android Chrome. Deep link navigates to correct screen. Permission request not shown until first relevant event.

---

### Backend Tickets

**BE-01: Mobile Dashboard Endpoint**
- **Description:** Create `GET /mobile/dashboard` endpoint returning aggregated data: active run count/breakdown, total P&L, pending approval count, critical alert count, active kills, recent completions (last 5). Single query per data source, assembled in service layer.
- **Dependencies:** None (uses existing services)
- **Priority:** P0 — Phase 1. The mobile dashboard is the landing screen; making 4+ serial API calls on cellular latency makes it feel broken. This single endpoint eliminates that problem.
- **Acceptance criteria:** Returns all dashboard fields in < 200ms. Response payload < 5KB. Auth required. Scoped to user's visible deployments.

**BE-02: Compact View Parameter**
- **Description:** Add `?view=compact` query parameter to: `/research/runs`, `/research/runs/{id}`, `/pnl/{id}/summary`, `/risk/analytics/summary/{id}`. Compact views omit large nested objects (full results, timeseries, matrices) and return only headline fields.
- **Dependencies:** None
- **Priority:** P2
- **Acceptance criteria:** Compact response payload is < 20% of full response. No breaking changes to default (non-compact) responses.

**BE-03: Push Notification Infrastructure**
- **Description:** Add Web Push subscription management: `POST /push/subscribe` (register endpoint + keys), `DELETE /push/subscribe` (unsubscribe). Send push notifications for: critical risk alerts, kill switch events, run failures, approval requests.
- **Dependencies:** None
- **Priority:** P3
- **Acceptance criteria:** Push subscriptions persist in database. Notifications delivered within 30 seconds of triggering event. Unsubscribe removes subscription.

**BE-04: Server-Sent Events for Run Status**
- **Description:** Create `GET /runs/events?run_ids=X,Y,Z` SSE endpoint. Stream status updates (status change, progress update) for specified runs. Auto-close connection when all runs reach terminal state. JWT auth required.
- **Dependencies:** None
- **Priority:** P3
- **Acceptance criteria:** SSE connection established with valid JWT. Status updates delivered within 2 seconds of state change. Connection auto-closes on terminal state. Reconnection supported (Last-Event-ID header).

**BE-05: Equity Curve Downsampling**
- **Description:** Add `?max_points=N` parameter to `GET /research/runs/{id}/result`. Apply LTTB downsampling to equity curve data when data points exceed max_points. Default max_points=5000 (desktop), recommended 500 for mobile.
- **Dependencies:** LTTB algorithm implementation (pure Python, no external dependency needed)
- **Priority:** P3
- **Acceptance criteria:** Downsampled curve preserves visual shape. Performance: downsample 10,000 points to 500 in < 50ms. Original data unchanged when max_points >= actual points.

**BE-06: Idempotency Key Support**
- **Description:** Add `Idempotency-Key` header support to all mutation endpoints. Store key → response mapping in Redis with 24-hour TTL. Return cached response for duplicate keys.
- **Dependencies:** Redis availability
- **Priority:** P2
- **Acceptance criteria:** Duplicate request with same idempotency key returns original response without side effects. Different key creates new resource. Expired key (>24h) allows new creation.

**BE-07: Audit Source Tracking**
- **Description:** Add `source` field to all audit events. Accept `X-Client-Source` header from clients. Default to "desktop" if header absent. Validate against whitelist: "desktop", "mobile", "api", "system".
- **Dependencies:** None
- **Priority:** P0 — Phase 1. Must ship with the first mobile release for governance traceability.
- **Acceptance criteria:** All audit events include source field. Mobile-originated actions logged with source="mobile". Existing audit queries can filter by source.

---

### API Tickets

**API-01: Rate Limiting for Mobile Mutations**
- **Description:** Add rate limiting to mutation endpoints when `X-Client-Source: mobile`. Max 5 run submissions per minute, 10 risk limit changes per hour. Return 429 with Retry-After header.
- **Dependencies:** BE-07
- **Priority:** P2
- **Acceptance criteria:** Rate limits enforced per user. 429 response includes Retry-After. Non-mobile clients unaffected.

---

### Design / UX Tickets

**UX-01: Mobile Component Design System**
- **Description:** Extract and codify the design system from the components built in week 1–2 (FE-01, FE-02, FE-22, FE-00). Document the actual touch target sizes, spacing grid, typography scale, colour usage, and gesture physics as implemented, not as speculated. Produce a Figma (or equivalent) component library that matches the working code. This approach eliminates the spec-build-reconcile loop that occurs when design specs and implementation run in parallel.
- **Dependencies:** FE-01, FE-02, FE-22 (extract from working components, not prescribe to them)
- **Priority:** P0 — scheduled for week 2–3, after the first components are built.
- **Acceptance criteria:** Specs cover all components listed in Section 6. Touch target sizes, contrast ratios, and safe area handling documented. Every spec entry has a corresponding working component as evidence.

**UX-02: Interaction Pattern Specification**
- **Description:** Define gesture specifications: slide-to-confirm dimensions and physics, bottom sheet behaviour (snap points, drag dismiss), pull-to-refresh indicator, filter chip interaction. Produce annotated interaction diagrams.
- **Dependencies:** UX-01
- **Priority:** P0
- **Acceptance criteria:** Each interaction pattern has: trigger, animation, success/cancel states, accessibility fallback.

**UX-03: Device Testing Matrix**
- **Description:** Define minimum supported devices and browsers for mobile. Recommended: iPhone 12+ (iOS 15+), Samsung Galaxy S21+ (Android 12+), Chrome 100+, Safari 15.4+. Establish testing protocol for each device.
- **Dependencies:** None
- **Priority:** P1
- **Acceptance criteria:** Matrix covers ≥ 90% of target user devices. Testing protocol documented with screenshots/recordings.

---

### QA Tickets

**QA-01: Mobile Layout Regression Tests**
- **Description:** Playwright tests for mobile viewport (375×812, 390×844, 360×780). Verify: bottom tab bar renders, sidebar hidden, no horizontal scrolling, safe area handled. Run on Chrome and Safari (via WebKit).
- **Dependencies:** FE-01, FE-02
- **Priority:** P0
- **Acceptance criteria:** Tests pass on all 3 viewports in Chrome and WebKit. Zero horizontal overflow. Tab bar visible and interactive.

**QA-02: Kill Switch Mobile E2E Tests**
- **Description:** End-to-end tests for kill switch workflow on mobile viewport: navigate to Emergency, activate global kill (slide + type), verify confirmation, deactivate. Test network failure handling. Test concurrent kill activation.
- **Dependencies:** FE-04
- **Priority:** P0
- **Acceptance criteria:** Full kill switch lifecycle passes. Network failure shows retry UI. Activation completes within 5 seconds.

**QA-03: Form Input Mobile Tests**
- **Description:** Test all mobile form inputs: numeric keypad triggers, currency formatting, date picker native integration, symbol search, strategy picker. Test validation error display and inline feedback.
- **Dependencies:** FE-08, FE-11
- **Priority:** P1
- **Acceptance criteria:** All inputs trigger correct keyboard type. Validation errors display inline. Form state preserved on navigation away/back.

**QA-04: Accessibility Audit**
- **Description:** Full mobile accessibility audit: VoiceOver (iOS), TalkBack (Android), keyboard navigation, contrast ratio verification, screen reader announcement verification for dynamic content (alerts, status updates).
- **Dependencies:** All FE tickets
- **Priority:** P2
- **Acceptance criteria:** All interactive elements navigable via screen reader. Dynamic content announced. Contrast ratios meet WCAG AA.

**QA-05: WebSocket Mobile Lifecycle Testing**
- **Description:** Real-device testing of WebSocket behaviour across mobile browser lifecycle events: app backgrounding (30s, 1m, 5m), foregrounding, network switch (WiFi → cellular), airplane mode toggle, screen lock/unlock. Verify the existing `useWebSocket` hook reconnects correctly in all cases. Test on iOS Safari (which kills WebSocket after ~30s background) and Android Chrome. Document any cases where reconnection fails or stale data is displayed.
- **Dependencies:** FE-14 or any screen that uses WebSocket (paper trading monitor). Can also be tested against existing `LiveDashboard` component.
- **Priority:** P0 — Phase 1. iOS Safari's aggressive WebSocket killing is a known platform behaviour that will silently break paper trading monitoring if not addressed before users rely on it.
- **Acceptance criteria:** WebSocket reconnects within 5 seconds of app foregrounding after background periods of 30s, 1m, and 5m. Stale data indicator appears immediately when connection is lost. No stale position/P&L data displayed without a visible staleness warning. Reconnection works after network switch. All tests documented with real-device screenshots/recordings.

**FE-21: WebSocket Mobile Lifecycle Hardening**
- **Description:** Harden the existing `useWebSocket` hook for mobile browser lifecycle: add `visibilitychange` event listener to detect background/foreground transitions, force reconnect on foreground, add explicit stale-data timestamp comparison (reject updates older than last known state), add connection status indicator component (green/yellow/red dot). If QA-05 reveals iOS Safari-specific issues, implement polling fallback that activates automatically when WebSocket reconnection fails 3 times consecutively.
- **Dependencies:** QA-05 findings
- **Priority:** P0 — Phase 1.
- **Acceptance criteria:** `visibilitychange` listener triggers reconnect on foreground. Stale data never displayed silently. Connection indicator visible on all screens that use live data. Polling fallback activates after 3 consecutive reconnection failures.

**QA-06: Performance Benchmarking**
- **Description:** Measure and baseline: dashboard load time (target < 3s on 4G), time to interactive, bundle size impact of mobile components, WebSocket reconnection time after backgrounding. Use Lighthouse CI for automated scoring.
- **Dependencies:** All Phase 1 FE tickets
- **Priority:** P2
- **Acceptance criteria:** Dashboard loads < 3s on simulated 4G. Lighthouse mobile score ≥ 80. No layout shift > 0.1 CLS. WebSocket reconnection after foreground < 5s.

---

## 12. Desktop-vs-Mobile Boundary

### First-Class on Mobile

These workflows are designed to be equally functional on mobile and desktop:

- Dashboard / platform health overview
- Kill switch activation and deactivation (all scopes)
- Run monitoring (active, queued, failed, completed)
- Results summary viewing (key metrics)
- Approval and rejection of governance items
- Risk limit viewing and editing
- Alert viewing and triage
- Paper trading P&L and position monitoring
- Export job creation
- Notification receipt and deep-linking

### View-Only on Mobile

These workflows render on mobile but with mutations disabled:

- **User management** — View user list and roles; create/edit/disable requires desktop
- **Secret management** — View expiration status; rotation requires desktop
- **Override creation** — View existing overrides; creating new overrides requires desktop (evidence link entry + long justification is impractical on phone)
- **Strategy DSL** — View strategy code read-only; editing requires desktop (Monaco editor)

### Desktop-Preferred (Functional on Mobile but Intentionally Simplified)

These workflows work on mobile but are deliberately reduced:

- **Backtest/optimisation setup** — Functional but uses simplified forms. Advanced parameter grids and multi-dimensional sweeps should be configured on desktop.
- **Equity curve analysis** — Mobile shows simplified single-line chart. Desktop shows overlays, regime bands, trade markers, drawdown.
- **Audit trail deep queries** — Mobile supports basic filtering. Complex multi-field queries and CSV export are desktop-preferred.
- **Feed diagnostics** — Mobile shows health summary. Detailed diagnostic panels and anomaly analysis are desktop-preferred.
- **Parity dashboard** — Mobile shows summary status. Detailed cross-system comparison is desktop-preferred.

### Blocked on Mobile

**Nothing is hard-blocked.** Every route renders. The philosophy is that a degraded mobile experience is better than no mobile experience in an emergency. However, the following are actively discouraged with UI messaging:

- **Strategy DSL editing** — "Continue editing on desktop" prompt. Read-only code view on mobile.
- **Secret rotation** — "Rotate secrets on desktop" prompt. Viewing expiration status is allowed.
- **User creation and role changes** — "Manage users on desktop" prompt.

### Architectural Issues That Fight Good Mobile UX

All issues below have planned mitigations in the implementation plan. Items marked ✅ are addressed in Phase 1.

1. ✅ **Fixed sidebar layout (AppShell.tsx):** The `ml-sidebar` CSS class is hardcoded on the `<main>` element. Fix: change to `ml-0 lg:ml-sidebar` and hide the sidebar below `lg`. One-line change, first commit of FE-01.

2. ✅ **No mobile navigation component exists.** The sidebar is the only navigation. A BottomTabBar component must be created from scratch. This is the real structural work in Phase 1 (FE-02) — estimated 2–3 days including routing integration, badge support, and safe area handling.

3. ✅ **Dashboard is a placeholder.** The current Dashboard page shows empty cards. The `/mobile/dashboard` summary endpoint (BE-01) is built in Phase 1 and the mobile dashboard (FE-03) is wired to it — eliminating both the data gap and the multi-call latency problem on cellular.

4. **Chart rendering assumes desktop width.** ResponsiveContainer handles width, but height is often hardcoded. Charts need explicit mobile height constraints and a fullscreen landscape viewer. Addressed in Phase 1 (FE-07) and Phase 2 (FE-19).

5. **Table-heavy layouts.** Several screens (audit, feeds, queues) use table layouts that break on narrow screens. These need card-based alternatives for mobile. Addressed incrementally across Phase 2 screens.

6. **No push notification infrastructure.** The app has no service worker, no push subscription management, no server-side push delivery. Phase 3 (BE-03, FE-20).

7. ✅ **WebSocket reconnection on mobile.** iOS Safari kills WebSocket connections after ~30s in background. Phase 1 includes explicit hardening (FE-21): `visibilitychange`-driven reconnect, stale data indicator, and polling fallback. Verified via real-device testing (QA-05).

8. ✅ **MFA browser compatibility.** WebAuthn (biometric) support varies across mobile browsers. Phase 1 builds the MFA component (FE-12) with PIN/TOTP as the primary path — guaranteed to work on every browser. Biometric is added as progressive enhancement in Phase 3.

---

## A. Recommended MVP Mobile Scope

The MVP should make the app genuinely usable on a phone for the three highest-value scenarios, and eliminate all known blockers so that Phase 2 ships clean. Target: **5 weeks of development.**

**MVP includes:**

1. **Mobile layout shell** — Bottom tab bar (5 tabs), sidebar hidden on mobile, responsive top bar
2. **`/mobile/dashboard` backend endpoint** — Single API call returning all dashboard card data (eliminates 4+ serial calls on cellular)
3. **Mobile dashboard** — Summary cards (active runs, P&L, approvals, alerts), alert banner, quick actions, wired to the summary endpoint
4. **Emergency controls** — Full kill switch workflow (global/strategy/symbol) with slide-to-confirm
5. **Run monitor** — Active run cards, filter chips, run detail, cancel action
6. **Results summary** — Metric grid, simplified equity curve
7. **Approval workflow** — Queue list, detail view, approve/reject actions with SoD enforcement
8. **MFA re-auth component** — PIN/TOTP as primary path, biometric as progressive enhancement. Built and tested in Phase 1 so Phase 2 risk editor has no auth surprises.
9. **WebSocket mobile lifecycle hardening** — `visibilitychange`-driven reconnection, stale data indicator, polling fallback after 3 consecutive reconnection failures. Verified on real iOS Safari and Android Chrome devices.
10. **Audit source tracking** (backend) — `source: "mobile"` in all audit events from mobile

**MVP excludes (Phase 2+):**

- Backtest/optimisation setup forms
- Risk settings editor (Phase 2 — but the MFA component it depends on ships in Phase 1)
- Paper trading setup and monitor
- Alert feed and audit trail screen
- Push notifications
- SSE / real-time run updates
- Compact API views
- Biometric as the primary auth method (Phase 3 progressive enhancement)

**Rationale:** The MVP covers emergency response (kill switch), operational awareness (monitoring), and governance (approvals) — the three scenarios where mobile access has the highest business value and where delay is most costly. It also eliminates the three blockers that would otherwise create production surprises in Phase 2: the slow multi-call dashboard, untested WebSocket behaviour on mobile browsers, and browser-dependent MFA failures.

---

## B. "Do Not Skip" Safety Checklist

Before any mobile release, verify every item:

- [ ] **Kill switch works end-to-end on iOS Safari and Android Chrome.** Test on real devices, not simulators.
- [ ] **Slide-to-confirm cannot be accidentally triggered.** Test with fast scrolling, incidental touch, and pocket-touch scenarios.
- [ ] **Global kill text confirmation ("KILL") is enforced client-side AND server-side.** Mobile should not be able to bypass the text gate.
- [ ] **MFA re-auth is required for risk limit changes.** Test that bypassing the frontend auth component does not bypass server-side verification.
- [ ] **SoD is enforced server-side for approvals.** Test that a user cannot approve their own promotion via mobile API calls (not just UI).
- [ ] **Audit trail includes device source for all mobile mutations.** Spot-check: activate kill switch from mobile, verify audit event has `source: "mobile"`.
- [ ] **No horizontal scrolling on 320px viewport.** Test every mobile screen at minimum width.
- [ ] **All touch targets ≥ 48px.** Measure with browser DevTools on every interactive element.
- [ ] **Token refresh works during extended mobile sessions.** Leave the app open for 30+ minutes, verify no forced logout during active use.
- [ ] **WebSocket reconnects after backgrounding.** Background the app for 5 minutes, foreground, verify live data resumes.
- [ ] **Network failure during kill switch shows retry, not silent failure.** Simulate offline during kill activation.
- [ ] **Form state is not lost on accidental navigation.** Start filling a backtest form, switch tabs, come back — form state preserved.
- [ ] **Dark mode contrast meets WCAG AA.** Test every status colour against dark background.
- [ ] **Numeric inputs open numeric keypad, not text keyboard.** Test on iOS and Android.
- [ ] **Kill switch is reachable in ≤ 2 taps from any screen.** Time it. Document the path.

---

## C. Top 10 Implementation Tickets (Do First)

| Priority | Ticket | Type | Rationale |
|----------|--------|------|-----------|
| 1 | **FE-01: Mobile Layout Shell** | Frontend | Foundation — sidebar responsive fix + responsive top bar |
| 2 | **FE-02: BottomTabBar Component** | Frontend | Navigation — the real structural work in Phase 1 |
| 3 | **BE-01: Mobile Dashboard Endpoint** | Backend | Parallel with FE-01/02. Eliminates slow multi-call dashboard on cellular. |
| 4 | **FE-22: Mobile Interaction Primitives** | Frontend | Unified kit: SlideToConfirm + BottomSheet + useMediaQuery. All three Phase 2 forms depend on BottomSheet; Emergency depends on SlideToConfirm; conditional rendering depends on useMediaQuery. Build once, use everywhere. |
| 5 | **FE-04: Emergency Controls Screen** | Frontend | Highest-value single screen (consumes SlideToConfirm from FE-22) |
| 6 | **FE-00: Responsive Quick Fixes** | Frontend | 5 one-line Tailwind fixes to existing components (ApprovalDetail, RunDetailView, OptimizationProgress, etc.) that make them mobile-ready without new screens. 1–2 hours total, eliminates the need for custom mobile rewrites of these pages. |
| 7 | **FE-03: Mobile Dashboard Screen** | Frontend | Landing screen, wired to BE-01 summary endpoint |
| 8 | **FE-06: Run Monitor Mobile Cards** | Frontend | Second-highest-value workflow |
| 9 | **FE-12: MFA Re-Auth Component** | Frontend | PIN/TOTP primary path. Built now so Phase 2 risk editor has no auth surprises. |
| 10 | **BE-07: Audit Source Tracking + X-Client-Source** | Backend + Frontend | One-line Axios interceptor addition + backend source field. Must ship with first mobile release. |

**Week-by-week delivery:**
- Week 1: FE-01 + FE-02 + BE-01 + FE-00 (shell, nav, dashboard endpoint, quick responsive fixes — all in parallel)
- Week 2: FE-22 + FE-04 + FE-03 (interaction primitives + emergency controls + dashboard wired to backend)
- Week 3: FE-06 + FE-12 + BE-07 (run monitor + MFA component + audit tracking)
- Week 4: FE-10 + FE-21 + QA-01 + QA-05 (approvals + WebSocket hardening + regression tests + real-device testing)
- Week 5: QA-02 (kill switch E2E) + integration testing + release candidate

---

## D. Plan Optimizations Applied (Revision 2)

This section documents six structural optimizations applied to the plan after auditing the existing codebase for mobile readiness. These are not cosmetic changes — each one either eliminates tickets, collapses serial work into parallel, or prevents rework.

### Optimization 1: Responsive Quick-Fix Pass (new ticket FE-00)

**What changed:** Added a 1–2 hour ticket that applies targeted Tailwind fixes to existing components before any new mobile screens are built.

**Why it matters:** The codebase audit revealed that ~60–70% of dashboard-style pages already render acceptably on a 430px viewport thanks to existing `grid-cols-1 sm:grid-cols-2 lg:grid-cols-4` patterns. The pages that break do so because of a handful of hardcoded `grid-cols-2` and `grid-cols-3` layouts in metadata displays. Five one-line changes fix them:

| Component | Current | Fix |
|-----------|---------|-----|
| `ApprovalDetail.tsx` (line ~105) | `grid grid-cols-2 gap-x-4` | `grid grid-cols-1 sm:grid-cols-2 gap-x-4` |
| `RunDetailView.tsx` (line ~164) | `grid grid-cols-2` | `grid grid-cols-1 sm:grid-cols-2` |
| `OptimizationProgress.tsx` (line ~46) | `grid grid-cols-3 gap-4` | `grid grid-cols-1 sm:grid-cols-3 gap-4` |
| `ArtifactBrowser.tsx` filters | Already responsive | No change needed |
| `ScoringBreakdown.tsx` | Already `grid-cols-1 sm:grid-cols-2 lg:grid-cols-3` | No change needed |

**Impact:** The Approval Detail screen, Run Detail view, and Optimization Progress view become mobile-functional without building new mobile-specific screens. This reduces the scope of FE-10 (Approval Queue) — it only needs the queue list and action buttons, not a full detail redesign. Similarly, FE-06 (Run Monitor) can link to the existing RunDetailView rather than building a separate mobile detail screen.

### Optimization 2: Consolidate Interaction Primitives (FE-05 + FE-09 merged into FE-22)

**What changed:** Merged SlideToConfirm (FE-05), BottomSheetPicker (FE-09), and a new `useMediaQuery` hook into a single "Mobile Interaction Primitives" ticket (FE-22).

**Why it matters:** All three are overlay/gesture patterns that share foundational concerns: touch event handling, backdrop management, focus trapping, safe area insets, and the `useMediaQuery` hook (which the codebase currently lacks entirely). Building them as three separate tickets means three separate implementations of backdrop click handling, three separate focus traps, three separate safe area calculations. Building them as a coordinated kit means one shared primitive layer with three consumers.

The `useMediaQuery` hook is the silent dependency that the plan was missing. The layout shell (FE-01) needs it to conditionally render sidebar vs. bottom tabs. The BottomSheet needs it to decide snap-point heights. Every screen that wants to show/hide content by viewport needs it. Without it, the plan defaults to CSS-only responsive hiding, which can't handle cases like "render a completely different component tree on mobile" (e.g., card list vs. table).

**Impact:** Eliminates FE-05 and FE-09 as separate tickets. Reduces total frontend tickets by 1 (net) while adding capability. Shared primitives mean consistent gesture behaviour across all mobile screens.

### Optimization 3: Reuse Existing ConfirmationModal

**What changed:** The plan originally assumed all mobile confirmations would need new components. The codebase audit found that `ConfirmationModal` (in `features/governance/components/`) already works on mobile — it uses `max-w-lg mx-4` which renders correctly on 430px screens, and has focus trapping, Escape-to-close, and backdrop click-to-close built in.

**Impact:** Every ticket that specifies "confirmation modal" (FE-04 kill switch, FE-10 approvals, FE-06 run cancel, FE-11 risk editor, FE-14 paper trading freeze) can import the existing component directly. No new confirmation modal needs to be built. The only new interaction pattern is SlideToConfirm (for kill switch gestures), which is in the FE-22 primitives kit.

### Optimization 4: X-Client-Source as a One-Line Axios Change

**What changed:** The plan had BE-07 (audit source tracking) as a backend ticket with an implicit frontend dependency ("the frontend needs to send X-Client-Source"). The codebase audit found that the Axios client (`api/client.ts`) already has a request interceptor that injects `Authorization` and `X-Correlation-Id` headers on every request. Adding `X-Client-Source` is a single line in that interceptor.

**Impact:** BE-07 becomes a self-contained backend+frontend ticket: one line in the Axios interceptor (detect viewport width, set `"mobile"` or `"desktop"`), plus the backend source field. No separate frontend ticket needed. Ships in week 3 with zero additional coordination.

### Optimization 5: Extract Design System From Built Components (UX-01 rephased)

**What changed:** The original plan had UX-01 (Mobile Component Design System) running in parallel with FE-01/02 in week 1. This creates a coordination problem: designers produce specs while engineers build components, and the specs inevitably diverge from what gets built because the engineers discover constraints (safe area behaviour, touch event quirks, Tailwind utility limitations) that the spec didn't anticipate.

**New approach:** UX-01 moves to week 2, after the layout shell and interaction primitives are built. The design system is extracted from the working components rather than prescribed to them. The primitives kit (FE-22) establishes the actual touch target sizes, spacing grid, typography scale, and gesture physics through implementation. UX-01 then codifies those decisions into a reference document and Figma library.

**Impact:** Eliminates the spec-build-reconcile loop. Engineers make informed decisions during FE-01/02/22 (they already have Tailwind's design system as a framework). The design system ticket becomes documentation of working patterns rather than speculative prescription.

### Optimization 6: Defer Results Table Redesign (explicit scope cut)

**What changed:** The codebase audit revealed that results tables (`TradeBlotter`, `CandidateComparisonTable`, `TrialSummaryTable`) use hardcoded pixel-width grid columns (e.g., `grid-cols-[80px_60px_60px_80px_80px_80px_80px]`). These force ~560px minimum width and will always cause horizontal scrolling on a 430px screen. Making these tables mobile-friendly requires a virtual scrolling + responsive column hiding redesign — significant work for a feature the plan already classified as "desktop-preferred."

**Decision:** Explicitly exclude results table mobile redesign from all three phases. These tables render with `overflow-x-auto` (horizontal scroll), which is acceptable for a "desktop-preferred" feature. The Results Summary screen (FE-07) provides the mobile-friendly view of results (metric grid + simplified chart). Users who need trade-by-trade detail use desktop.

**Impact:** Removes a hidden scope trap. Without this explicit decision, someone would eventually file a bug about horizontal scrolling in the trade blotter on mobile, and the team would spend a week redesigning virtual tables for a feature that was never intended to be mobile-first.
