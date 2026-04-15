/**
 * DiagnosticsShell — read-only service health, dependency status, and platform metrics.
 *
 * Purpose:
 *   Render the operator diagnostics overview panel. Surfaces service health
 *   (GET /health), dependency reachability (GET /health/dependencies), and
 *   platform-wide operational counts (GET /health/diagnostics) in a single view.
 *
 * Responsibilities:
 *   - Fetch three health/diagnostic endpoints concurrently.
 *   - Render service status badge, dependency list with colour-coded badges,
 *     and operational counts.
 *   - Loading, error states.
 *
 * Does NOT:
 *   - Mutate any configuration — read-only surface.
 *   - Compute health state locally — consumes backend responses verbatim.
 *   - Render action buttons — per M30 spec this is informational only.
 *
 * Dependencies:
 *   - apiClient from @/api/client.
 *   - Zod schemas from @/types/diagnostics.
 *   - feedsLogger from ../logger (reuses feeds logger for page lifecycle).
 */

import { memo, useEffect, useId } from "react";
import { useQuery } from "@tanstack/react-query";
import { apiClient } from "@/api/client";
import {
  ServiceHealthSchema,
  DependencyHealthResponseSchema,
  DiagnosticsSnapshotSchema,
} from "@/types/diagnostics";
import type { DependencyStatus } from "@/types/diagnostics";
import { feedsLogger } from "../logger";

// ---------------------------------------------------------------------------
// Dependency status badge styling
// ---------------------------------------------------------------------------

const DEP_STATUS_CLASSES: Record<DependencyStatus, string> = {
  OK: "bg-emerald-100 text-emerald-800 ring-emerald-600/20",
  DEGRADED: "bg-amber-100 text-amber-900 ring-amber-600/30",
  DOWN: "bg-red-100 text-red-800 ring-red-600/20",
};

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export const DiagnosticsShell = memo(function DiagnosticsShell() {
  const correlationId = useId();

  useEffect(() => {
    feedsLogger.pageMount("DiagnosticsShell", correlationId);
    return () => feedsLogger.pageUnmount("DiagnosticsShell", correlationId);
  }, [correlationId]);

  const healthQuery = useQuery({
    queryKey: ["diagnostics", "service-health"],
    queryFn: async ({ signal }) => {
      const response = await apiClient.get("/health", { signal });
      const parsed = ServiceHealthSchema.safeParse(response.data);
      if (!parsed.success) throw new Error("Invalid service health response");
      return parsed.data;
    },
  });

  const depsQuery = useQuery({
    queryKey: ["diagnostics", "dependencies"],
    queryFn: async ({ signal }) => {
      const response = await apiClient.get("/health/dependencies", { signal });
      const parsed = DependencyHealthResponseSchema.safeParse(response.data);
      if (!parsed.success) throw new Error("Invalid dependency health response");
      return parsed.data;
    },
  });

  const snapQuery = useQuery({
    queryKey: ["diagnostics", "snapshot"],
    queryFn: async ({ signal }) => {
      const response = await apiClient.get("/health/diagnostics", { signal });
      const parsed = DiagnosticsSnapshotSchema.safeParse(response.data);
      if (!parsed.success) throw new Error("Invalid diagnostics snapshot");
      return parsed.data;
    },
  });

  const isLoading = healthQuery.isLoading || depsQuery.isLoading || snapQuery.isLoading;
  const error = healthQuery.error ?? depsQuery.error ?? snapQuery.error;
  const refetchAll = () => {
    healthQuery.refetch();
    depsQuery.refetch();
    snapQuery.refetch();
  };

  if (isLoading) {
    return (
      <div
        data-testid="diagnostics-loading"
        role="status"
        className="flex items-center justify-center py-12"
      >
        <p className="text-sm text-slate-500">Loading diagnostics…</p>
      </div>
    );
  }

  if (error) {
    return (
      <div
        data-testid="diagnostics-error"
        role="alert"
        className="rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700"
      >
        <p className="font-medium">Failed to load diagnostics</p>
        <p className="mt-1">{error instanceof Error ? error.message : "Unknown error."}</p>
        <button
          type="button"
          onClick={refetchAll}
          className="mt-2 rounded-md bg-red-600 px-3 py-1.5 text-sm text-white hover:bg-red-700"
        >
          Retry
        </button>
      </div>
    );
  }

  const health = healthQuery.data;
  const deps = depsQuery.data;
  const snap = snapQuery.data;

  return (
    <article data-testid="diagnostics-shell" className="mx-auto max-w-4xl space-y-6">
      {/* Service health */}
      <section aria-label="Service health" className="space-y-2">
        <h2 className="text-sm font-semibold text-slate-700">Service Health</h2>
        {health && (
          <div className="rounded-lg border border-slate-200 bg-white px-4 py-3 text-sm">
            <div className="flex items-center justify-between">
              <span className="font-medium text-slate-900">{health.service}</span>
              <span data-testid="diagnostics-service-status" className="text-sm text-slate-600">
                {health.status}
              </span>
            </div>
            {health.version && (
              <p className="mt-1 text-xs text-slate-500">Version: {health.version}</p>
            )}
          </div>
        )}
      </section>

      {/* Dependency health */}
      <section aria-label="Dependencies" className="space-y-2">
        <h2 className="text-sm font-semibold text-slate-700">Dependencies</h2>
        {deps && deps.dependencies.length === 0 ? (
          <p data-testid="diagnostics-deps-empty" className="text-xs text-slate-500">
            No dependencies configured.
          </p>
        ) : (
          <ul className="divide-y divide-slate-100 rounded-lg border border-slate-200 bg-white">
            {deps?.dependencies.map((dep) => (
              <li
                key={dep.name}
                data-testid={`diagnostics-dep-${dep.name}`}
                className="flex items-center justify-between px-4 py-2 text-sm"
              >
                <div className="flex items-center gap-3">
                  <span
                    data-testid={`dep-status-badge-${dep.name}`}
                    className={`inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium ring-1 ring-inset ${DEP_STATUS_CLASSES[dep.status]}`}
                  >
                    {dep.status}
                  </span>
                  <span className="font-medium text-slate-900">{dep.name}</span>
                </div>
                <div className="flex items-center gap-3 text-xs text-slate-500">
                  {dep.latency_ms > 0 && <span>{dep.latency_ms.toFixed(1)} ms</span>}
                  {dep.detail && <span className="text-red-600">{dep.detail}</span>}
                </div>
              </li>
            ))}
          </ul>
        )}
      </section>

      {/* Operational counts */}
      {snap && (
        <section aria-label="Operational counts" className="space-y-2">
          <h2 className="text-sm font-semibold text-slate-700">Operational Counts</h2>
          <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
            <div className="rounded-lg border border-slate-200 bg-white px-4 py-3 text-center">
              <p
                data-testid="diagnostics-queue-contention"
                className="text-2xl font-semibold text-slate-900"
              >
                {snap.queue_contention_count}
              </p>
              <p className="mt-1 text-xs text-slate-500">Queue Contention</p>
            </div>
            <div className="rounded-lg border border-slate-200 bg-white px-4 py-3 text-center">
              <p
                data-testid="diagnostics-feed-health"
                className="text-2xl font-semibold text-slate-900"
              >
                {snap.feed_health_count}
              </p>
              <p className="mt-1 text-xs text-slate-500">Feed Health</p>
            </div>
            <div className="rounded-lg border border-slate-200 bg-white px-4 py-3 text-center">
              <p
                data-testid="diagnostics-parity-critical"
                className="text-2xl font-semibold text-slate-900"
              >
                {snap.parity_critical_count}
              </p>
              <p className="mt-1 text-xs text-slate-500">Parity Critical</p>
            </div>
            <div className="rounded-lg border border-slate-200 bg-white px-4 py-3 text-center">
              <p
                data-testid="diagnostics-cert-blocked"
                className="text-2xl font-semibold text-slate-900"
              >
                {snap.certification_blocked_count}
              </p>
              <p className="mt-1 text-xs text-slate-500">Cert Blocked</p>
            </div>
          </div>
          <p className="text-xs text-slate-400">Generated at {snap.generated_at}</p>
        </section>
      )}
    </article>
  );
});
