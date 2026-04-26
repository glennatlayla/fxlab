/**
 * Application router — defines all frontend routes with RBAC enforcement and code splitting.
 *
 * Architecture:
 *   - All page routes are lazy-loaded for better initial load performance.
 *   - Protected routes enforce RBAC scopes via AuthGuard.
 *   - Lazy components are wrapped in Suspense with PageLoadingFallback spinner.
 *   - Dashboard is accessible to all authenticated users (no scope required).
 *   - All other routes require specific scopes mapped from Permission enum.
 *
 * Route structure:
 *   /login           — public login page
 *   /                — authenticated shell with sidebar
 *     /              — Dashboard (index, no scope required)
 *     /strategy-studio — M25 Strategy Studio (strategies:write scope)
 *     /strategy-studio/:id — M2.D2/D3 Strategy Detail + backtest launcher
 *     /runs          — M26 Run Monitor (runs:write scope)
 *     /runs/:runId/readiness — M28 Readiness Report (runs:write scope)
 *     /feeds         — M30 Feed Operations (feeds:read scope)
 *     /approvals     — M29 Governance Approvals (approvals:write scope)
 *     /overrides     — M29 Governance Overrides (overrides:approve scope)
 *     /audit         — M29 Audit Explorer (audit:read scope)
 *     /queues        — M30 Queue Dashboard (feeds:read scope)
 *     /parity        — M30 Parity Dashboard (feeds:read scope)
 *     /pnl           — M9  P&L Attribution (deployments:read scope)
 *     /artifacts     — M31 Artifact Browser (exports:read scope)
 *     /kill-switch   — M27 Kill Switch (live:trade scope)
 *     /admin         — M2  Admin Panel (admin:manage scope)
 *       /users       — User Management
 *       /secrets     — Secret Rotation
 *
 * Lazy loading:
 *   All page components are wrapped with React.lazy() and split into separate bundles.
 *   Each route's Suspense boundary shows PageLoadingFallback while the bundle loads.
 *   This reduces initial bundle size and improves time-to-interactive (TTI).
 *
 * RBAC enforcement:
 *   AuthGuard checks requiredScope against user's JWT scopes before rendering the page.
 *   If scope is missing, user sees a 403 (Access Denied) view.
 *   Dashboard requires no scope, so all authenticated users can access it.
 *
 *   Scope vocabulary is defined by the backend in services/api/auth.py
 *   (ROLE_SCOPES). Frontend MUST use those literal strings — see
 *   tests/unit/test_frontend_backend_scope_alignment.py which fails
 *   any drift at pytest time. The 2026-04-25 first-clean-install
 *   incident exposed a schism where the frontend used snake_case
 *   verb names (create_strategy, view_runs…) and the backend issued
 *   colon-separated names (strategies:write, runs:write…); admin's
 *   JWT carried the right scopes but every route guard rejected
 *   them. Tranche L standardised on the backend names.
 */

import { lazy, Suspense } from "react";
import { createBrowserRouter, Navigate, Outlet } from "react-router-dom";
import { AppShell } from "./components/layout/AppShell";
import { AuthGuard } from "./components/auth/AuthGuard";
import { FeatureErrorBoundary } from "./components/FeatureErrorBoundary";
import { PageLoadingFallback } from "./components/common/PageLoadingFallback";
import LoginPage from "./components/auth/LoginPage";
import Dashboard from "./pages/Dashboard";

// Lazy-loaded page components — each gets its own code split bundle
const StrategyStudio = lazy(() => import("./pages/StrategyStudio"));
const StrategyDetail = lazy(() => import("./pages/StrategyDetail"));
const Strategies = lazy(() => import("./pages/Strategies"));
const Runs = lazy(() => import("./pages/Runs"));
const RunReadiness = lazy(() => import("./pages/RunReadiness"));
const Feeds = lazy(() => import("./pages/Feeds"));
const FeedDetail = lazy(() => import("./pages/FeedDetail"));
const Approvals = lazy(() => import("./pages/Approvals"));
const Overrides = lazy(() => import("./pages/Overrides"));
const Audit = lazy(() => import("./pages/Audit"));
const Queues = lazy(() => import("./pages/Queues"));
const Parity = lazy(() => import("./pages/Parity"));
const Artifacts = lazy(() => import("./pages/Artifacts"));

// P&L Attribution (M9)
const StrategyPnL = lazy(() => import("./pages/StrategyPnL"));

// Admin panel components (M2)
const AdminLayout = lazy(() => import("./pages/Admin/AdminLayout"));
const UserManagement = lazy(() => import("./pages/Admin/UserManagement"));
const SecretManagement = lazy(() => import("./pages/Admin/SecretManagement"));

// Mobile navigation pages (FE-01, FE-02)
const Emergency = lazy(() => import("./pages/Emergency"));
const Alerts = lazy(() => import("./pages/Alerts"));
const More = lazy(() => import("./pages/More"));

// Run Results viewer (M2.D4) — completed-run results page powered by the
// M2.C3 sub-resource endpoints (metrics, equity-curve, blotter). Auth
// scope matches those endpoints (exports:read).
const RunResults = lazy(() => import("./pages/RunResults"));

export const router = createBrowserRouter(
  [
    {
      path: "/login",
      element: <LoginPage />,
    },
    {
      path: "/",
      element: (
        <AuthGuard>
          <AppShell />
        </AuthGuard>
      ),
      children: [
        // Dashboard: no scope required, accessible to all authenticated users
        { index: true, element: <Dashboard /> },
        // Strategy Studio: requires strategies:write scope
        {
          path: "strategy-studio",
          element: (
            <AuthGuard requiredScope="strategies:write">
              <FeatureErrorBoundary featureName="Strategy Studio">
                <Suspense fallback={<PageLoadingFallback />}>
                  <StrategyStudio />
                </Suspense>
              </FeatureErrorBoundary>
            </AuthGuard>
          ),
        },
        // Strategies catalogue / browse page (M2.D5): paginated list of all
        // imported + draft strategies. Same scope as the rest of the
        // strategies surface — the project does not define a separate
        // strategies:read scope.
        {
          path: "strategies",
          element: (
            <AuthGuard requiredScope="strategies:write">
              <FeatureErrorBoundary featureName="Strategies">
                <Suspense fallback={<PageLoadingFallback />}>
                  <Strategies />
                </Suspense>
              </FeatureErrorBoundary>
            </AuthGuard>
          ),
        },
        // Strategy Detail (M2.D2 + M2.D3 wiring): renders the parsed IR
        // and the "Execute backtest" affordance for an IR-imported
        // strategy. ImportIrPanel navigates here on a 201 from
        // POST /strategies/import-ir. Same scope as the studio root.
        {
          path: "strategy-studio/:id",
          element: (
            <AuthGuard requiredScope="strategies:write">
              <FeatureErrorBoundary featureName="Strategy Detail">
                <Suspense fallback={<PageLoadingFallback />}>
                  <StrategyDetail />
                </Suspense>
              </FeatureErrorBoundary>
            </AuthGuard>
          ),
        },
        // Run Monitor: requires runs:write scope
        {
          path: "runs",
          element: (
            <AuthGuard requiredScope="runs:write">
              <FeatureErrorBoundary featureName="Run Monitor">
                <Suspense fallback={<PageLoadingFallback />}>
                  <Runs />
                </Suspense>
              </FeatureErrorBoundary>
            </AuthGuard>
          ),
        },
        // Readiness Report: requires runs:write scope (readiness is part of run inspection)
        {
          path: "runs/:runId/readiness",
          element: (
            <AuthGuard requiredScope="runs:write">
              <FeatureErrorBoundary featureName="Readiness Report">
                <Suspense fallback={<PageLoadingFallback />}>
                  <RunReadiness />
                </Suspense>
              </FeatureErrorBoundary>
            </AuthGuard>
          ),
        },
        // Feed Operations: requires feeds:read scope
        {
          path: "feeds",
          element: (
            <AuthGuard requiredScope="feeds:read">
              <FeatureErrorBoundary featureName="Feed Operations">
                <Suspense fallback={<PageLoadingFallback />}>
                  <Feeds />
                </Suspense>
              </FeatureErrorBoundary>
            </AuthGuard>
          ),
        },
        {
          path: "feeds/:feedId",
          element: (
            <AuthGuard requiredScope="feeds:read">
              <FeatureErrorBoundary featureName="Feed Detail">
                <Suspense fallback={<PageLoadingFallback />}>
                  <FeedDetail />
                </Suspense>
              </FeatureErrorBoundary>
            </AuthGuard>
          ),
        },
        // Governance Approvals: requires approvals:write scope
        {
          path: "approvals",
          element: (
            <AuthGuard requiredScope="approvals:write">
              <FeatureErrorBoundary featureName="Governance Approvals">
                <Suspense fallback={<PageLoadingFallback />}>
                  <Approvals />
                </Suspense>
              </FeatureErrorBoundary>
            </AuthGuard>
          ),
        },
        // Governance Overrides: requires overrides:approve scope
        {
          path: "overrides",
          element: (
            <AuthGuard requiredScope="overrides:approve">
              <FeatureErrorBoundary featureName="Governance Overrides">
                <Suspense fallback={<PageLoadingFallback />}>
                  <Overrides />
                </Suspense>
              </FeatureErrorBoundary>
            </AuthGuard>
          ),
        },
        {
          path: "overrides/:id",
          element: (
            <AuthGuard requiredScope="overrides:approve">
              <FeatureErrorBoundary featureName="Governance Overrides">
                <Suspense fallback={<PageLoadingFallback />}>
                  <Overrides />
                </Suspense>
              </FeatureErrorBoundary>
            </AuthGuard>
          ),
        },
        // Audit Explorer: requires audit:read scope
        {
          path: "audit",
          element: (
            <AuthGuard requiredScope="audit:read">
              <FeatureErrorBoundary featureName="Audit Explorer">
                <Suspense fallback={<PageLoadingFallback />}>
                  <Audit />
                </Suspense>
              </FeatureErrorBoundary>
            </AuthGuard>
          ),
        },
        // Queue Dashboard: requires feeds:read scope (queues are feed-related)
        {
          path: "queues",
          element: (
            <AuthGuard requiredScope="feeds:read">
              <FeatureErrorBoundary featureName="Queue Dashboard">
                <Suspense fallback={<PageLoadingFallback />}>
                  <Queues />
                </Suspense>
              </FeatureErrorBoundary>
            </AuthGuard>
          ),
        },
        // Parity Dashboard: requires feeds:read scope (parity is feed-related)
        {
          path: "parity",
          element: (
            <AuthGuard requiredScope="feeds:read">
              <FeatureErrorBoundary featureName="Parity Dashboard">
                <Suspense fallback={<PageLoadingFallback />}>
                  <Parity />
                </Suspense>
              </FeatureErrorBoundary>
            </AuthGuard>
          ),
        },
        // P&L Attribution: requires deployments:read permission (M9)
        {
          path: "pnl/:deploymentId",
          element: (
            <AuthGuard requiredScope="deployments:read">
              <FeatureErrorBoundary featureName="P&L Attribution">
                <Suspense fallback={<PageLoadingFallback />}>
                  <StrategyPnL />
                </Suspense>
              </FeatureErrorBoundary>
            </AuthGuard>
          ),
        },
        // Artifact Browser: requires exports:read scope
        {
          path: "artifacts",
          element: (
            <AuthGuard requiredScope="exports:read">
              <FeatureErrorBoundary featureName="Artifact Browser">
                <Suspense fallback={<PageLoadingFallback />}>
                  <Artifacts />
                </Suspense>
              </FeatureErrorBoundary>
            </AuthGuard>
          ),
        },
        // Emergency Controls: requires live:trade scope
        {
          path: "emergency",
          element: (
            <AuthGuard requiredScope="live:trade">
              <FeatureErrorBoundary featureName="Emergency Controls">
                <Suspense fallback={<PageLoadingFallback />}>
                  <Emergency />
                </Suspense>
              </FeatureErrorBoundary>
            </AuthGuard>
          ),
        },
        // Alerts: accessible to all authenticated users (no scope required)
        {
          path: "alerts",
          element: (
            <FeatureErrorBoundary featureName="Alerts">
              <Suspense fallback={<PageLoadingFallback />}>
                <Alerts />
              </Suspense>
            </FeatureErrorBoundary>
          ),
        },
        // More: accessible to all authenticated users (shows scoped items)
        {
          path: "more",
          element: (
            <FeatureErrorBoundary featureName="More Options">
              <Suspense fallback={<PageLoadingFallback />}>
                <More />
              </Suspense>
            </FeatureErrorBoundary>
          ),
        },
        // Admin Panel: M2 User Management and Secret Rotation (requires admin:manage)
        {
          path: "admin",
          element: (
            <AuthGuard requiredScope="admin:manage">
              <FeatureErrorBoundary featureName="Admin Panel">
                <Suspense fallback={<PageLoadingFallback />}>
                  <AdminLayout>
                    <Suspense fallback={<PageLoadingFallback />}>
                      <Outlet />
                    </Suspense>
                  </AdminLayout>
                </Suspense>
              </FeatureErrorBoundary>
            </AuthGuard>
          ),
          children: [
            {
              index: true,
              element: <Navigate to="users" replace />,
            },
            {
              path: "users",
              element: (
                <Suspense fallback={<PageLoadingFallback />}>
                  <UserManagement />
                </Suspense>
              ),
            },
            {
              path: "secrets",
              element: (
                <Suspense fallback={<PageLoadingFallback />}>
                  <SecretManagement />
                </Suspense>
              ),
            },
          ],
        },
        // Run Results viewer (M2.D4): completed-run results page consuming
        // the M2.C3 sub-resource endpoints. Scope matches those endpoints
        // (exports:read).
        {
          path: "runs/:runId/results",
          element: (
            <AuthGuard requiredScope="exports:read">
              <FeatureErrorBoundary featureName="Run Results">
                <Suspense fallback={<PageLoadingFallback />}>
                  <RunResults />
                </Suspense>
              </FeatureErrorBoundary>
            </AuthGuard>
          ),
        },
      ],
    },
  ],
  {
    future: {
      v7_relativeSplatPath: true,
    },
  },
);
