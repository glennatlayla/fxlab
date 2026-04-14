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
 *     /strategy-studio — M25 Strategy Studio (create_strategy scope)
 *     /runs          — M26 Run Monitor (view_runs scope)
 *     /runs/:runId/readiness — M28 Readiness Report (view_runs scope)
 *     /feeds         — M30 Feed Operations (view_feeds scope)
 *     /approvals     — M29 Governance Approvals (approve_promotion scope)
 *     /overrides     — M29 Governance Overrides (manage_overrides scope)
 *     /audit         — M29 Audit Explorer (view_audit scope)
 *     /queues        — M30 Queue Dashboard (view_feeds scope)
 *     /parity        — M30 Parity Dashboard (view_feeds scope)
 *     /artifacts     — M31 Artifact Browser (export_data scope)
 *     /admin         — M2 Admin Panel (admin:manage scope)
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
 *   Scope names map directly to Permission enum values (e.g., "view_strategies").
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
        // Strategy Studio: requires create_strategy permission
        {
          path: "strategy-studio",
          element: (
            <AuthGuard requiredScope="create_strategy">
              <FeatureErrorBoundary featureName="Strategy Studio">
                <Suspense fallback={<PageLoadingFallback />}>
                  <StrategyStudio />
                </Suspense>
              </FeatureErrorBoundary>
            </AuthGuard>
          ),
        },
        // Run Monitor: requires view_runs permission
        {
          path: "runs",
          element: (
            <AuthGuard requiredScope="view_runs">
              <FeatureErrorBoundary featureName="Run Monitor">
                <Suspense fallback={<PageLoadingFallback />}>
                  <Runs />
                </Suspense>
              </FeatureErrorBoundary>
            </AuthGuard>
          ),
        },
        // Readiness Report: requires view_runs permission (readiness is part of run inspection)
        {
          path: "runs/:runId/readiness",
          element: (
            <AuthGuard requiredScope="view_runs">
              <FeatureErrorBoundary featureName="Readiness Report">
                <Suspense fallback={<PageLoadingFallback />}>
                  <RunReadiness />
                </Suspense>
              </FeatureErrorBoundary>
            </AuthGuard>
          ),
        },
        // Feed Operations: requires view_feeds permission
        {
          path: "feeds",
          element: (
            <AuthGuard requiredScope="view_feeds">
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
            <AuthGuard requiredScope="view_feeds">
              <FeatureErrorBoundary featureName="Feed Detail">
                <Suspense fallback={<PageLoadingFallback />}>
                  <FeedDetail />
                </Suspense>
              </FeatureErrorBoundary>
            </AuthGuard>
          ),
        },
        // Governance Approvals: requires approve_promotion permission
        {
          path: "approvals",
          element: (
            <AuthGuard requiredScope="approve_promotion">
              <FeatureErrorBoundary featureName="Governance Approvals">
                <Suspense fallback={<PageLoadingFallback />}>
                  <Approvals />
                </Suspense>
              </FeatureErrorBoundary>
            </AuthGuard>
          ),
        },
        // Governance Overrides: requires manage_overrides permission
        {
          path: "overrides",
          element: (
            <AuthGuard requiredScope="manage_overrides">
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
            <AuthGuard requiredScope="manage_overrides">
              <FeatureErrorBoundary featureName="Governance Overrides">
                <Suspense fallback={<PageLoadingFallback />}>
                  <Overrides />
                </Suspense>
              </FeatureErrorBoundary>
            </AuthGuard>
          ),
        },
        // Audit Explorer: requires view_audit permission
        {
          path: "audit",
          element: (
            <AuthGuard requiredScope="view_audit">
              <FeatureErrorBoundary featureName="Audit Explorer">
                <Suspense fallback={<PageLoadingFallback />}>
                  <Audit />
                </Suspense>
              </FeatureErrorBoundary>
            </AuthGuard>
          ),
        },
        // Queue Dashboard: requires view_feeds permission (queues are feed-related)
        {
          path: "queues",
          element: (
            <AuthGuard requiredScope="view_feeds">
              <FeatureErrorBoundary featureName="Queue Dashboard">
                <Suspense fallback={<PageLoadingFallback />}>
                  <Queues />
                </Suspense>
              </FeatureErrorBoundary>
            </AuthGuard>
          ),
        },
        // Parity Dashboard: requires view_feeds permission (parity is feed-related)
        {
          path: "parity",
          element: (
            <AuthGuard requiredScope="view_feeds">
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
        // Artifact Browser: requires export_data permission
        {
          path: "artifacts",
          element: (
            <AuthGuard requiredScope="export_data">
              <FeatureErrorBoundary featureName="Artifact Browser">
                <Suspense fallback={<PageLoadingFallback />}>
                  <Artifacts />
                </Suspense>
              </FeatureErrorBoundary>
            </AuthGuard>
          ),
        },
        // Emergency Controls: requires activate_kill_switch permission
        {
          path: "emergency",
          element: (
            <AuthGuard requiredScope="activate_kill_switch">
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
      ],
    },
  ],
  {
    future: {
      v7_relativeSplatPath: true,
    },
  },
);
