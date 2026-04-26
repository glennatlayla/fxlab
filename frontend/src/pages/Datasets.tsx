/**
 * Datasets — admin browse + register page (M4.E3).
 *
 * Purpose:
 *   Provide the ``/admin/datasets`` admin sub-tree page for browsing
 *   the catalog backing :class:`DatasetService` and registering new
 *   entries / toggling certification on existing rows.
 *
 * Responsibilities:
 *   - Fetch one page of catalog rows whenever the page, page_size,
 *     source filter, certification filter, or search query changes.
 *   - Render a paginated table of rows with per-row "Toggle
 *     certification" affordances.
 *   - Open a modal form for registering a new dataset; submit the form
 *     via :func:`registerDataset` and reload the table on success.
 *   - Surface backend errors via a typed banner.
 *
 * Does NOT:
 *   - Manage authentication (the route guard owns ``admin:manage``).
 *   - Validate inputs locally — Pydantic on the backend is the oracle.
 *
 * Route: ``/admin/datasets`` (gated by ``admin:manage`` via AuthGuard).
 */

import { useCallback, useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { useAuth } from "@/auth/useAuth";
import { LoadingState } from "@/components/ui/LoadingState";
import {
  DatasetsApiError,
  listDatasets,
  registerDataset,
  updateDataset,
  type DatasetListItem,
  type PagedDatasets,
} from "@/api/datasets";

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

/** Default page size for the catalog grid. Mirrors the backend default. */
const DEFAULT_PAGE_SIZE = 20;

/** Certification filter literals. */
type CertFilter = "all" | "true" | "false";

/** Timeframe options for the register modal — matches catalog conventions. */
const TIMEFRAME_OPTIONS = ["1m", "5m", "15m", "30m", "1h", "4h", "1d"] as const;

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

/** Render the certification pill for a row. */
function CertPill({ isCertified }: { isCertified: boolean }) {
  const cls = isCertified
    ? "border-emerald-200 bg-emerald-50 text-emerald-800"
    : "border-surface-200 bg-surface-50 text-surface-700";
  const label = isCertified ? "Certified" : "Uncertified";
  return (
    <span
      data-testid={`dataset-cert-${isCertified ? "true" : "false"}`}
      className={
        "inline-flex items-center rounded-full border px-2 py-0.5 text-xs font-medium " + cls
      }
    >
      {label}
    </span>
  );
}

// ---------------------------------------------------------------------------
// Register modal
// ---------------------------------------------------------------------------

interface RegisterModalProps {
  open: boolean;
  onClose: () => void;
  onRegistered: () => void;
}

function RegisterModal({ open, onClose, onRegistered }: RegisterModalProps) {
  const [datasetRef, setDatasetRef] = useState("");
  const [symbolsCsv, setSymbolsCsv] = useState("");
  const [timeframe, setTimeframe] = useState<string>(TIMEFRAME_OPTIONS[2]);
  const [source, setSource] = useState("");
  const [version, setVersion] = useState("");
  const [isCertified, setIsCertified] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const handleSubmit = useCallback(
    async (e: React.FormEvent) => {
      e.preventDefault();
      setError(null);
      const symbols = symbolsCsv
        .split(",")
        .map((s) => s.trim())
        .filter((s) => s.length > 0);
      if (symbols.length === 0) {
        setError("At least one symbol is required.");
        return;
      }
      setSubmitting(true);
      try {
        await registerDataset({
          dataset_ref: datasetRef.trim(),
          symbols,
          timeframe,
          source: source.trim(),
          version: version.trim(),
          is_certified: isCertified,
        });
        // Reset form state then close + notify parent.
        setDatasetRef("");
        setSymbolsCsv("");
        setSource("");
        setVersion("");
        setIsCertified(false);
        onRegistered();
        onClose();
      } catch (err) {
        if (err instanceof DatasetsApiError) {
          setError(err.detail ?? err.message);
        } else if (err instanceof Error) {
          setError(err.message);
        } else {
          setError("Failed to register dataset.");
        }
      } finally {
        setSubmitting(false);
      }
    },
    [datasetRef, symbolsCsv, timeframe, source, version, isCertified, onRegistered, onClose],
  );

  if (!open) return null;

  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-labelledby="datasets-register-modal-title"
      data-testid="datasets-register-modal"
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4"
    >
      <form
        onSubmit={handleSubmit}
        className="w-full max-w-lg space-y-4 rounded-lg bg-white p-6 shadow-xl"
        data-testid="datasets-register-form"
      >
        <div className="flex items-baseline justify-between">
          <h2 id="datasets-register-modal-title" className="text-lg font-semibold text-surface-900">
            Register dataset
          </h2>
          <button
            type="button"
            onClick={onClose}
            data-testid="datasets-register-cancel"
            className="text-sm text-surface-500 hover:text-surface-700"
          >
            Cancel
          </button>
        </div>

        {error && (
          <div
            role="alert"
            data-testid="datasets-register-error"
            className="rounded-md border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700"
          >
            {error}
          </div>
        )}

        <label className="block">
          <span className="text-xs font-medium uppercase tracking-wider text-surface-500">
            Dataset ref
          </span>
          <input
            data-testid="datasets-register-ref"
            type="text"
            value={datasetRef}
            onChange={(e) => setDatasetRef(e.target.value)}
            required
            className="mt-1 w-full rounded-md border border-surface-300 px-3 py-2 text-sm shadow-sm focus:border-brand-500 focus:outline-none focus:ring-1 focus:ring-brand-500"
          />
        </label>

        <label className="block">
          <span className="text-xs font-medium uppercase tracking-wider text-surface-500">
            Symbols (comma-separated)
          </span>
          <input
            data-testid="datasets-register-symbols"
            type="text"
            value={symbolsCsv}
            onChange={(e) => setSymbolsCsv(e.target.value)}
            placeholder="EURUSD, GBPUSD"
            required
            className="mt-1 w-full rounded-md border border-surface-300 px-3 py-2 text-sm shadow-sm focus:border-brand-500 focus:outline-none focus:ring-1 focus:ring-brand-500"
          />
        </label>

        <label className="block">
          <span className="text-xs font-medium uppercase tracking-wider text-surface-500">
            Timeframe
          </span>
          <select
            data-testid="datasets-register-timeframe"
            value={timeframe}
            onChange={(e) => setTimeframe(e.target.value)}
            className="mt-1 w-full rounded-md border border-surface-300 px-3 py-2 text-sm shadow-sm focus:border-brand-500 focus:outline-none focus:ring-1 focus:ring-brand-500"
          >
            {TIMEFRAME_OPTIONS.map((tf) => (
              <option key={tf} value={tf}>
                {tf}
              </option>
            ))}
          </select>
        </label>

        <label className="block">
          <span className="text-xs font-medium uppercase tracking-wider text-surface-500">
            Source
          </span>
          <input
            data-testid="datasets-register-source"
            type="text"
            value={source}
            onChange={(e) => setSource(e.target.value)}
            placeholder="oanda"
            required
            className="mt-1 w-full rounded-md border border-surface-300 px-3 py-2 text-sm shadow-sm focus:border-brand-500 focus:outline-none focus:ring-1 focus:ring-brand-500"
          />
        </label>

        <label className="block">
          <span className="text-xs font-medium uppercase tracking-wider text-surface-500">
            Version
          </span>
          <input
            data-testid="datasets-register-version"
            type="text"
            value={version}
            onChange={(e) => setVersion(e.target.value)}
            placeholder="v1"
            required
            className="mt-1 w-full rounded-md border border-surface-300 px-3 py-2 text-sm shadow-sm focus:border-brand-500 focus:outline-none focus:ring-1 focus:ring-brand-500"
          />
        </label>

        <label className="flex items-center gap-2">
          <input
            data-testid="datasets-register-is-certified"
            type="checkbox"
            checked={isCertified}
            onChange={(e) => setIsCertified(e.target.checked)}
            className="h-4 w-4 rounded border-surface-300 text-brand-600 focus:ring-brand-500"
          />
          <span className="text-sm text-surface-700">Mark as certified on creation</span>
        </label>

        <div className="flex justify-end gap-2 pt-2">
          <button
            type="submit"
            disabled={submitting}
            data-testid="datasets-register-submit"
            className="inline-flex items-center rounded-md bg-brand-600 px-4 py-2 text-sm font-medium text-white shadow-sm hover:bg-brand-700 disabled:cursor-not-allowed disabled:opacity-50"
          >
            {submitting ? "Registering…" : "Register"}
          </button>
        </div>
      </form>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Page component
// ---------------------------------------------------------------------------

export default function Datasets() {
  // Assert a session is present (matches the rest of the admin sub-tree).
  useAuth();

  const [page, setPage] = useState(1);
  const pageSize = DEFAULT_PAGE_SIZE;
  const [sourceFilter, setSourceFilter] = useState("");
  const [certFilter, setCertFilter] = useState<CertFilter>("all");
  const [searchQuery, setSearchQuery] = useState("");

  const [pageData, setPageData] = useState<PagedDatasets | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const [errorStatus, setErrorStatus] = useState<number | null>(null);

  const [registerOpen, setRegisterOpen] = useState(false);
  const [reloadCounter, setReloadCounter] = useState(0);
  const [togglePending, setTogglePending] = useState<string | null>(null);

  const apiOpts = useMemo(
    () => ({
      source: sourceFilter.trim() || undefined,
      is_certified: certFilter === "all" ? undefined : certFilter === "true",
      q: searchQuery.trim() || undefined,
    }),
    [sourceFilter, certFilter, searchQuery],
  );

  useEffect(() => {
    let cancelled = false;
    setIsLoading(true);
    setErrorMessage(null);
    setErrorStatus(null);

    void (async () => {
      try {
        const data = await listDatasets(page, pageSize, apiOpts);
        if (!cancelled) setPageData(data);
      } catch (err) {
        if (cancelled) return;
        if (err instanceof DatasetsApiError) {
          setErrorMessage(err.detail ?? err.message);
          setErrorStatus(err.statusCode ?? null);
        } else {
          setErrorMessage(err instanceof Error ? err.message : "Failed to load datasets.");
        }
        setPageData(null);
      } finally {
        if (!cancelled) setIsLoading(false);
      }
    })();

    return () => {
      cancelled = true;
    };
  }, [page, pageSize, apiOpts, reloadCounter]);

  const handleSourceChange = useCallback((next: string) => {
    setSourceFilter(next);
    setPage(1);
  }, []);
  const handleCertChange = useCallback((next: CertFilter) => {
    setCertFilter(next);
    setPage(1);
  }, []);
  const handleSearchChange = useCallback((next: string) => {
    setSearchQuery(next);
    setPage(1);
  }, []);
  const handlePrev = useCallback(() => {
    setPage((p) => Math.max(1, p - 1));
  }, []);
  const handleNext = useCallback(() => {
    setPage((p) => {
      const totalPages = pageData?.total_pages ?? 1;
      return Math.min(Math.max(totalPages, 1), p + 1);
    });
  }, [pageData?.total_pages]);

  const handleToggleCert = useCallback(async (row: DatasetListItem) => {
    setTogglePending(row.dataset_ref);
    setErrorMessage(null);
    try {
      await updateDataset(row.dataset_ref, { is_certified: !row.is_certified });
      setReloadCounter((c) => c + 1);
    } catch (err) {
      if (err instanceof DatasetsApiError) {
        setErrorMessage(err.detail ?? err.message);
        setErrorStatus(err.statusCode ?? null);
      } else {
        setErrorMessage(err instanceof Error ? err.message : "Failed to toggle certification.");
      }
    } finally {
      setTogglePending(null);
    }
  }, []);

  const totalCount = pageData?.total_count ?? 0;
  const totalPages = pageData?.total_pages ?? 0;
  const hasResults = (pageData?.datasets.length ?? 0) > 0;

  return (
    <div className="space-y-6" data-testid="datasets-page">
      {/* Header */}
      <div className="flex flex-wrap items-baseline justify-between gap-3">
        <div>
          <h1 className="text-2xl font-bold text-surface-900">Datasets</h1>
          <p className="mt-1 text-sm text-surface-500">
            Browse the catalog and register new datasets. Toggle certification per row to gate
            backtests.
          </p>
        </div>
        <button
          type="button"
          data-testid="datasets-register-open"
          onClick={() => setRegisterOpen(true)}
          className="inline-flex items-center rounded-md bg-brand-600 px-3 py-2 text-sm font-medium text-white shadow-sm hover:bg-brand-700"
        >
          Register dataset
        </button>
      </div>

      {/* Filters */}
      <div
        className="grid grid-cols-1 gap-3 rounded-lg border border-surface-200 bg-white p-4 sm:grid-cols-3"
        data-testid="datasets-filters"
      >
        <label className="block">
          <span className="block text-xs font-medium uppercase tracking-wider text-surface-500">
            Search dataset_ref
          </span>
          <input
            data-testid="datasets-search"
            type="search"
            value={searchQuery}
            onChange={(e) => handleSearchChange(e.target.value)}
            placeholder="e.g. eurusd"
            className="mt-1 w-full rounded-md border border-surface-300 px-3 py-2 text-sm shadow-sm focus:border-brand-500 focus:outline-none focus:ring-1 focus:ring-brand-500"
          />
        </label>
        <label className="block">
          <span className="block text-xs font-medium uppercase tracking-wider text-surface-500">
            Source
          </span>
          <input
            data-testid="datasets-source-filter"
            type="text"
            value={sourceFilter}
            onChange={(e) => handleSourceChange(e.target.value)}
            placeholder="e.g. oanda"
            className="mt-1 w-full rounded-md border border-surface-300 px-3 py-2 text-sm shadow-sm focus:border-brand-500 focus:outline-none focus:ring-1 focus:ring-brand-500"
          />
        </label>
        <label className="block">
          <span className="block text-xs font-medium uppercase tracking-wider text-surface-500">
            Certification
          </span>
          <select
            data-testid="datasets-cert-filter"
            value={certFilter}
            onChange={(e) => handleCertChange(e.target.value as CertFilter)}
            className="mt-1 w-full rounded-md border border-surface-300 px-3 py-2 text-sm shadow-sm focus:border-brand-500 focus:outline-none focus:ring-1 focus:ring-brand-500"
          >
            <option value="all">All</option>
            <option value="true">Certified</option>
            <option value="false">Uncertified</option>
          </select>
        </label>
      </div>

      {/* Body — error / loading / empty / table */}
      {errorMessage && (
        <div
          className="rounded-md border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700"
          role="alert"
          data-testid="datasets-error"
        >
          <strong>
            {errorStatus === 422
              ? "Invalid input"
              : errorStatus === 404
                ? "Not found"
                : errorStatus === 403
                  ? "Access denied"
                  : "Datasets error"}
            :
          </strong>{" "}
          {errorMessage}
        </div>
      )}

      {!errorMessage && isLoading && (
        <div data-testid="datasets-loading">
          <LoadingState message="Loading datasets…" />
        </div>
      )}

      {!errorMessage && !isLoading && !hasResults && (
        <div
          className="rounded-lg border border-dashed border-surface-300 bg-white p-10 text-center"
          data-testid="datasets-empty"
        >
          <h2 className="text-lg font-semibold text-surface-800">No datasets registered yet</h2>
          <p className="mt-1 text-sm text-surface-500">
            {searchQuery.trim() || sourceFilter.trim() || certFilter !== "all"
              ? "No datasets match your filters. Clear the filters or try a different search."
              : "Click 'Register dataset' to add the first entry to the catalog."}
          </p>
          <button
            type="button"
            data-testid="datasets-empty-register"
            onClick={() => setRegisterOpen(true)}
            className="mt-4 inline-flex items-center rounded-md bg-brand-600 px-4 py-2 text-sm font-medium text-white shadow-sm hover:bg-brand-700"
          >
            Register your first dataset
          </button>
        </div>
      )}

      {!errorMessage && !isLoading && hasResults && pageData && (
        <div
          className="overflow-hidden rounded-lg border border-surface-200 bg-white"
          data-testid="datasets-table-wrapper"
        >
          <table className="min-w-full divide-y divide-surface-200" data-testid="datasets-table">
            <thead className="bg-surface-50">
              <tr>
                <th className="px-4 py-2 text-left text-xs font-semibold uppercase tracking-wider text-surface-500">
                  Dataset ref
                </th>
                <th className="px-4 py-2 text-left text-xs font-semibold uppercase tracking-wider text-surface-500">
                  Symbols
                </th>
                <th className="px-4 py-2 text-left text-xs font-semibold uppercase tracking-wider text-surface-500">
                  Timeframe
                </th>
                <th className="px-4 py-2 text-left text-xs font-semibold uppercase tracking-wider text-surface-500">
                  Source
                </th>
                <th className="px-4 py-2 text-left text-xs font-semibold uppercase tracking-wider text-surface-500">
                  Version
                </th>
                <th className="px-4 py-2 text-left text-xs font-semibold uppercase tracking-wider text-surface-500">
                  Certification
                </th>
                <th className="px-4 py-2 text-left text-xs font-semibold uppercase tracking-wider text-surface-500">
                  Updated
                </th>
                <th className="px-4 py-2 text-right">
                  <span className="sr-only">Actions</span>
                </th>
              </tr>
            </thead>
            <tbody className="divide-y divide-surface-100">
              {pageData.datasets.map((row) => (
                <tr key={row.id} data-testid={`dataset-row-${row.dataset_ref}`}>
                  <td className="px-4 py-3 align-top">
                    <Link
                      to={`/admin/datasets/${encodeURIComponent(row.dataset_ref)}`}
                      data-testid={`dataset-detail-link-${row.dataset_ref}`}
                      className="font-medium text-brand-700 hover:underline"
                    >
                      {row.dataset_ref}
                    </Link>
                    <div className="mt-0.5 font-mono text-xs text-surface-500">{row.id}</div>
                  </td>
                  <td className="px-4 py-3 align-top text-sm text-surface-700">
                    {row.symbols.join(", ")}
                  </td>
                  <td className="px-4 py-3 align-top text-sm text-surface-700">{row.timeframe}</td>
                  <td className="px-4 py-3 align-top text-sm text-surface-700">{row.source}</td>
                  <td className="px-4 py-3 align-top text-sm text-surface-700">{row.version}</td>
                  <td className="px-4 py-3 align-top">
                    <CertPill isCertified={row.is_certified} />
                  </td>
                  <td className="px-4 py-3 align-top text-xs text-surface-700">
                    {formatIso(row.updated_at)}
                  </td>
                  <td className="px-4 py-3 text-right align-top">
                    <button
                      type="button"
                      data-testid={`dataset-toggle-cert-${row.dataset_ref}`}
                      onClick={() => handleToggleCert(row)}
                      disabled={togglePending === row.dataset_ref}
                      className="inline-flex items-center rounded-md border border-brand-300 bg-white px-3 py-1.5 text-xs font-medium text-brand-700 hover:bg-brand-50 disabled:cursor-not-allowed disabled:opacity-50"
                    >
                      {togglePending === row.dataset_ref
                        ? "Toggling…"
                        : row.is_certified
                          ? "Revoke"
                          : "Certify"}
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {!errorMessage && !isLoading && hasResults && pageData && (
        <div
          className="flex items-center justify-between rounded-lg border border-surface-200 bg-white px-4 py-3 text-sm"
          data-testid="datasets-pagination"
        >
          <div className="text-surface-600">
            Showing {pageData.datasets.length} of {totalCount} — Page{" "}
            <span data-testid="datasets-page-current">{pageData.page}</span> of{" "}
            <span data-testid="datasets-page-total">{Math.max(totalPages, 1)}</span>
          </div>
          <div className="flex gap-2">
            <button
              type="button"
              data-testid="datasets-page-prev"
              onClick={handlePrev}
              disabled={pageData.page <= 1}
              className="rounded-md border border-surface-300 bg-white px-3 py-1.5 text-xs font-medium text-surface-700 hover:bg-surface-50 disabled:cursor-not-allowed disabled:opacity-50"
            >
              Previous
            </button>
            <button
              type="button"
              data-testid="datasets-page-next"
              onClick={handleNext}
              disabled={pageData.page >= totalPages}
              className="rounded-md border border-surface-300 bg-white px-3 py-1.5 text-xs font-medium text-surface-700 hover:bg-surface-50 disabled:cursor-not-allowed disabled:opacity-50"
            >
              Next
            </button>
          </div>
        </div>
      )}

      <RegisterModal
        open={registerOpen}
        onClose={() => setRegisterOpen(false)}
        onRegistered={() => setReloadCounter((c) => c + 1)}
      />
    </div>
  );
}
