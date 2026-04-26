/**
 * DatasetDetail — admin detail page for a single registered dataset.
 *
 * Purpose:
 *   Render the ``/admin/datasets/:ref`` admin sub-tree page that drills
 *   into one catalog row, showing:
 *     - Header (ref + symbols + certified badge + archived badge).
 *     - Bar inventory (per-symbol row count + min/max bar timestamp).
 *     - Strategies that have referenced this dataset_ref in a research
 *       run (linked to /strategy-studio/:id).
 *     - Most recent runs that referenced this dataset_ref (linked to
 *       /runs/:runId/results).
 *
 * Responsibilities:
 *   - Load the detail envelope via :func:`getDatasetDetail`.
 *   - Render four distinct sections + their empty states.
 *   - Handle 404 ("Dataset not found") and generic error banners.
 *
 * Does NOT:
 *   - Manage authentication (the route guard owns ``admin:manage``).
 *   - Mutate the dataset row (use the parent ``/admin/datasets`` page
 *     for register / certification toggles).
 *
 * Route: ``/admin/datasets/:ref`` (gated by ``admin:manage`` via
 * AuthGuard at the parent ``/admin`` route).
 */

import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { useAuth } from "@/auth/useAuth";
import { LoadingState } from "@/components/ui/LoadingState";
import {
  DatasetsApiError,
  getDatasetDetail,
  type DatasetDetail as DatasetDetailRecord,
} from "@/api/datasets";

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

/** Format an ISO-8601 timestamp as ``YYYY-MM-DD HH:mm UTC`` for table cells. */
function formatIso(iso: string | null): string {
  if (!iso) return "—";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  const pad = (n: number) => String(n).padStart(2, "0");
  return (
    `${d.getUTCFullYear()}-${pad(d.getUTCMonth() + 1)}-${pad(d.getUTCDate())} ` +
    `${pad(d.getUTCHours())}:${pad(d.getUTCMinutes())} UTC`
  );
}

/** Pill rendering the certification status. */
function CertPill({ isCertified }: { isCertified: boolean }) {
  const cls = isCertified
    ? "border-emerald-200 bg-emerald-50 text-emerald-800"
    : "border-surface-200 bg-surface-50 text-surface-700";
  return (
    <span
      data-testid={`dataset-detail-cert-${isCertified ? "true" : "false"}`}
      className={
        "inline-flex items-center rounded-full border px-2 py-0.5 text-xs font-medium " + cls
      }
    >
      {isCertified ? "Certified" : "Uncertified"}
    </span>
  );
}

/** Pill rendering a run lifecycle status with a colour cue. */
function StatusPill({ status }: { status: string }) {
  const palette: Record<string, string> = {
    completed: "border-emerald-200 bg-emerald-50 text-emerald-800",
    running: "border-blue-200 bg-blue-50 text-blue-800",
    queued: "border-blue-200 bg-blue-50 text-blue-800",
    pending: "border-surface-200 bg-surface-50 text-surface-700",
    failed: "border-red-200 bg-red-50 text-red-700",
    cancelled: "border-amber-200 bg-amber-50 text-amber-800",
  };
  const cls = palette[status] ?? "border-surface-200 bg-surface-50 text-surface-700";
  return (
    <span
      data-testid={`run-status-${status}`}
      className={
        "inline-flex items-center rounded-full border px-2 py-0.5 text-xs font-medium " + cls
      }
    >
      {status}
    </span>
  );
}

/** Skeleton row used while the detail payload is loading. */
function SkeletonBlock({ testId, height = "h-20" }: { testId: string; height?: string }) {
  return (
    <div
      data-testid={testId}
      className={"animate-pulse rounded-md border border-surface-200 bg-surface-100 " + height}
    />
  );
}

// ---------------------------------------------------------------------------
// Page component
// ---------------------------------------------------------------------------

export default function DatasetDetail() {
  // Assert a session is present (matches the rest of the admin sub-tree).
  useAuth();

  const { ref: rawRef } = useParams<{ ref: string }>();
  const ref = rawRef ?? "";

  const [detail, setDetail] = useState<DatasetDetailRecord | null>(null);
  const [isLoading, setIsLoading] = useState<boolean>(true);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const [errorStatus, setErrorStatus] = useState<number | null>(null);

  useEffect(() => {
    if (!ref) {
      setErrorMessage("Missing dataset reference in URL.");
      setErrorStatus(null);
      setIsLoading(false);
      return;
    }

    let cancelled = false;
    setIsLoading(true);
    setErrorMessage(null);
    setErrorStatus(null);

    void (async () => {
      try {
        const data = await getDatasetDetail(ref);
        if (!cancelled) setDetail(data);
      } catch (err) {
        if (cancelled) return;
        if (err instanceof DatasetsApiError) {
          setErrorMessage(err.detail ?? err.message);
          setErrorStatus(err.statusCode ?? null);
        } else {
          setErrorMessage(err instanceof Error ? err.message : "Failed to load dataset detail.");
        }
        setDetail(null);
      } finally {
        if (!cancelled) setIsLoading(false);
      }
    })();

    return () => {
      cancelled = true;
    };
  }, [ref]);

  // --- Loading state: skeletons for header + each section -----------------
  if (isLoading) {
    return (
      <div className="space-y-6" data-testid="dataset-detail-loading">
        <SkeletonBlock testId="dataset-detail-skeleton-header" height="h-16" />
        <SkeletonBlock testId="dataset-detail-skeleton-inventory" />
        <SkeletonBlock testId="dataset-detail-skeleton-strategies" />
        <SkeletonBlock testId="dataset-detail-skeleton-runs" />
        <LoadingState message={`Loading dataset ${ref}…`} />
      </div>
    );
  }

  // --- Error state --------------------------------------------------------
  if (errorMessage) {
    if (errorStatus === 404) {
      return (
        <div
          className="rounded-md border border-amber-200 bg-amber-50 px-4 py-6 text-amber-800"
          role="alert"
          data-testid="dataset-detail-not-found"
        >
          <h2 className="text-lg font-semibold">Dataset not found</h2>
          <p className="mt-1 text-sm">
            No dataset registered for ref <span className="font-mono">{ref}</span>.
          </p>
          <Link
            to="/admin/datasets"
            data-testid="dataset-detail-back-link"
            className="mt-3 inline-flex items-center text-sm font-medium text-brand-700 hover:underline"
          >
            ← Back to datasets list
          </Link>
        </div>
      );
    }
    return (
      <div
        className="rounded-md border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700"
        role="alert"
        data-testid="dataset-detail-error"
      >
        <strong>{errorStatus === 403 ? "Access denied" : "Dataset detail error"}: </strong>
        {errorMessage}
      </div>
    );
  }

  if (!detail) {
    // Defensive: should not happen given the loading + error branches.
    return null;
  }

  const inventoryEmpty = detail.bar_inventory.length === 0;
  const inventoryAllZero =
    detail.bar_inventory.length > 0 && detail.bar_inventory.every((row) => row.row_count === 0);

  return (
    <div className="space-y-6" data-testid="dataset-detail-page">
      {/* Header */}
      <div data-testid="dataset-detail-header" className="space-y-2">
        <Link
          to="/admin/datasets"
          data-testid="dataset-detail-back-link"
          className="text-sm text-brand-700 hover:underline"
        >
          ← Back to datasets list
        </Link>
        <div className="flex flex-wrap items-baseline justify-between gap-3">
          <div>
            <h1
              data-testid="dataset-detail-ref"
              className="break-all text-2xl font-bold text-surface-900"
            >
              {detail.dataset_ref}
            </h1>
            <p className="mt-1 font-mono text-xs text-surface-500">{detail.dataset_id}</p>
          </div>
          <div className="flex items-center gap-2">
            <CertPill isCertified={detail.is_certified} />
          </div>
        </div>
        <div
          className="flex flex-wrap gap-x-6 gap-y-1 text-sm text-surface-700"
          data-testid="dataset-detail-meta"
        >
          <span>
            <span className="font-medium text-surface-900">Symbols:</span>{" "}
            {detail.symbols.join(", ")}
          </span>
          <span>
            <span className="font-medium text-surface-900">Timeframe:</span> {detail.timeframe}
          </span>
          <span>
            <span className="font-medium text-surface-900">Source:</span> {detail.source}
          </span>
          <span>
            <span className="font-medium text-surface-900">Version:</span> {detail.version}
          </span>
          <span>
            <span className="font-medium text-surface-900">Created:</span>{" "}
            {formatIso(detail.created_at)}
          </span>
          <span>
            <span className="font-medium text-surface-900">Updated:</span>{" "}
            {formatIso(detail.updated_at)}
          </span>
        </div>
      </div>

      {/* Bar inventory */}
      <section
        className="space-y-3"
        data-testid="dataset-detail-inventory-section"
        aria-labelledby="dataset-detail-inventory-title"
      >
        <h2 id="dataset-detail-inventory-title" className="text-lg font-semibold text-surface-900">
          Bar inventory
        </h2>
        {inventoryEmpty || inventoryAllZero ? (
          <div
            className="rounded-md border border-dashed border-surface-300 bg-white p-6 text-center text-sm text-surface-600"
            data-testid="dataset-detail-inventory-empty"
          >
            No bars ingested yet for this dataset.
          </div>
        ) : (
          <div
            className="overflow-hidden rounded-lg border border-surface-200 bg-white"
            data-testid="dataset-detail-inventory-table-wrapper"
          >
            <table
              className="min-w-full divide-y divide-surface-200"
              data-testid="dataset-detail-inventory-table"
            >
              <thead className="bg-surface-50">
                <tr>
                  <th className="px-4 py-2 text-left text-xs font-semibold uppercase tracking-wider text-surface-500">
                    Symbol
                  </th>
                  <th className="px-4 py-2 text-left text-xs font-semibold uppercase tracking-wider text-surface-500">
                    Timeframe
                  </th>
                  <th className="px-4 py-2 text-right text-xs font-semibold uppercase tracking-wider text-surface-500">
                    Row count
                  </th>
                  <th className="px-4 py-2 text-left text-xs font-semibold uppercase tracking-wider text-surface-500">
                    Min ts
                  </th>
                  <th className="px-4 py-2 text-left text-xs font-semibold uppercase tracking-wider text-surface-500">
                    Max ts
                  </th>
                </tr>
              </thead>
              <tbody className="divide-y divide-surface-100">
                {detail.bar_inventory.map((row) => (
                  <tr
                    key={`${row.symbol}-${row.timeframe}`}
                    data-testid={`dataset-detail-inventory-row-${row.symbol}`}
                  >
                    <td className="px-4 py-3 text-sm font-medium text-surface-900">{row.symbol}</td>
                    <td className="px-4 py-3 text-sm text-surface-700">{row.timeframe}</td>
                    <td className="px-4 py-3 text-right font-mono text-sm text-surface-700">
                      {row.row_count.toLocaleString()}
                    </td>
                    <td className="px-4 py-3 text-xs text-surface-700">{formatIso(row.min_ts)}</td>
                    <td className="px-4 py-3 text-xs text-surface-700">{formatIso(row.max_ts)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>

      {/* Strategies using this dataset */}
      <section
        className="space-y-3"
        data-testid="dataset-detail-strategies-section"
        aria-labelledby="dataset-detail-strategies-title"
      >
        <h2 id="dataset-detail-strategies-title" className="text-lg font-semibold text-surface-900">
          Strategies using this dataset
        </h2>
        {detail.strategies_using.length === 0 ? (
          <div
            className="rounded-md border border-dashed border-surface-300 bg-white p-6 text-center text-sm text-surface-600"
            data-testid="dataset-detail-strategies-empty"
          >
            No strategies have referenced this dataset yet.
          </div>
        ) : (
          <ul
            className="divide-y divide-surface-100 overflow-hidden rounded-lg border border-surface-200 bg-white"
            data-testid="dataset-detail-strategies-list"
          >
            {detail.strategies_using.map((s) => (
              <li
                key={s.strategy_id}
                className="flex items-center justify-between gap-4 px-4 py-3"
                data-testid={`dataset-detail-strategy-${s.strategy_id}`}
              >
                <div className="min-w-0">
                  <Link
                    to={`/strategy-studio/${encodeURIComponent(s.strategy_id)}`}
                    className="block truncate text-sm font-medium text-brand-700 hover:underline"
                    data-testid={`dataset-detail-strategy-link-${s.strategy_id}`}
                  >
                    {s.name || s.strategy_id}
                  </Link>
                  <p className="font-mono text-xs text-surface-500">{s.strategy_id}</p>
                </div>
                <span className="whitespace-nowrap text-xs text-surface-600">
                  Last used: {formatIso(s.last_used_at)}
                </span>
              </li>
            ))}
          </ul>
        )}
      </section>

      {/* Recent runs */}
      <section
        className="space-y-3"
        data-testid="dataset-detail-runs-section"
        aria-labelledby="dataset-detail-runs-title"
      >
        <h2 id="dataset-detail-runs-title" className="text-lg font-semibold text-surface-900">
          Recent runs
        </h2>
        {detail.recent_runs.length === 0 ? (
          <div
            className="rounded-md border border-dashed border-surface-300 bg-white p-6 text-center text-sm text-surface-600"
            data-testid="dataset-detail-runs-empty"
          >
            No runs have referenced this dataset yet.
          </div>
        ) : (
          <ul
            className="divide-y divide-surface-100 overflow-hidden rounded-lg border border-surface-200 bg-white"
            data-testid="dataset-detail-runs-list"
          >
            {detail.recent_runs.map((r) => (
              <li
                key={r.run_id}
                className="flex items-center justify-between gap-4 px-4 py-3"
                data-testid={`dataset-detail-run-${r.run_id}`}
              >
                <div className="min-w-0">
                  <Link
                    to={`/runs/${encodeURIComponent(r.run_id)}/results`}
                    className="block truncate text-sm font-medium text-brand-700 hover:underline"
                    data-testid={`dataset-detail-run-link-${r.run_id}`}
                  >
                    {r.run_id}
                  </Link>
                  <p className="font-mono text-xs text-surface-500">Strategy: {r.strategy_id}</p>
                </div>
                <div className="flex items-center gap-3">
                  <StatusPill status={r.status} />
                  <span className="whitespace-nowrap text-xs text-surface-600">
                    Completed: {formatIso(r.completed_at)}
                  </span>
                </div>
              </li>
            ))}
          </ul>
        )}
      </section>
    </div>
  );
}
