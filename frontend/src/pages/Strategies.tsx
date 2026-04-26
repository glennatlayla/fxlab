/**
 * Strategies — paginated catalogue browse page (M2.D5).
 *
 * Purpose:
 *   Land here from the sidebar "Strategies" link to discover existing
 *   strategies (both IR uploads and draft-form rows). Closes the M2.D
 *   UX gap where Import + Detail + RunBacktest + Results pages exist
 *   but no list view shows what is already in the catalogue.
 *
 * Responsibilities:
 *   - Call ``GET /strategies?page=...&page_size=...&source=...&name_contains=...``
 *     via :func:`listStrategies` whenever the page index, page size,
 *     source filter, or name search changes.
 *   - Render a desktop-friendly table of rows (id, name, source pill,
 *     version, created_at, created_by, "View detail" button).
 *   - Provide a name search box + a source select (all/ir_upload/draft_form).
 *   - Show an empty state with an "Import your first strategy" link
 *     to ``/strategy-studio`` when no strategies match.
 *   - Render a typed error banner from :class:`ListStrategiesError`
 *     (e.g. 422 for an invalid filter value).
 *   - Render Next/Prev pagination controls bounded by ``total_pages``.
 *
 * Does NOT:
 *   - Mutate the catalogue (read-only page; creation lives in Strategy Studio).
 *   - Open the strategy detail inline (clicking a row navigates).
 *   - Manage authentication (the route guard owns ``strategies:write``).
 *
 * Dependencies:
 *   - :func:`listStrategies` from @/api/strategies for the data load.
 *   - :class:`ListStrategiesError` for typed error rendering.
 *   - :func:`useAuth` for session assertion.
 *   - :func:`useNavigate` from react-router-dom for row navigation.
 *
 * Route: ``/strategies`` (protected by ``strategies:write`` scope via
 *   AuthGuard at the router layer — matches the rest of the strategies
 *   surface, since the project does not define a distinct
 *   ``strategies:read`` scope).
 *
 * Example:
 *   <Route path="strategies" element={<Strategies />} />
 */

import { useCallback, useEffect, useMemo, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import toast from "react-hot-toast";
import { useAuth } from "@/auth/useAuth";
import { LoadingState } from "@/components/ui/LoadingState";
import {
  cloneStrategy,
  CloneStrategyError,
  listStrategies,
  ListStrategiesError,
  type StrategyListItem,
  type StrategyListPage,
} from "@/api/strategies";

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

/** Default page size for the catalogue grid. Mirrors the backend default. */
const DEFAULT_PAGE_SIZE = 20;

/**
 * Hard cap on the clone modal's ``new_name`` field. Mirrors the
 * backend ``Strategy.name`` SQL column limit (255) and the Pydantic
 * ``CloneStrategyRequest`` ``max_length=255`` so the client-side
 * validator returns the same verdict the server would.
 */
const CLONE_NAME_MAX_LEN = 255;

/** Source filter literals — keep in sync with the backend regex. */
type SourceFilter = "all" | "ir_upload" | "draft_form";

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

/**
 * Format an ISO-8601 timestamp as ``YYYY-MM-DD HH:mm UTC`` for table cells.
 *
 * Args:
 *   iso: ISO-8601 timestamp from the backend.
 *
 * Returns:
 *   Short human-readable form, or the raw string when parsing fails.
 */
function formatIso(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  const pad = (n: number) => String(n).padStart(2, "0");
  return (
    `${d.getUTCFullYear()}-${pad(d.getUTCMonth() + 1)}-${pad(d.getUTCDate())} ` +
    `${pad(d.getUTCHours())}:${pad(d.getUTCMinutes())} UTC`
  );
}

/**
 * Render the source pill for a row.
 *
 * Mirrors the styling used on :file:`StrategyDetail.tsx` so the source
 * affordance reads identically across the Import → List → Detail flow.
 */
function SourcePill({ source }: { source: StrategyListItem["source"] }) {
  const label = source === "ir_upload" ? "Imported IR" : "Draft form";
  const cls =
    source === "ir_upload"
      ? "border-brand-200 bg-brand-50 text-brand-800"
      : "border-surface-200 bg-surface-50 text-surface-700";
  return (
    <span
      data-testid={`strategy-row-source-${source}`}
      className={
        "inline-flex items-center rounded-full border px-2 py-0.5 text-xs font-medium " + cls
      }
    >
      {label}
    </span>
  );
}

// ---------------------------------------------------------------------------
// Clone modal
// ---------------------------------------------------------------------------

/** Props for :func:`CloneStrategyModal`. */
interface CloneStrategyModalProps {
  /** Source strategy this modal will clone. ``null`` means "modal hidden". */
  source: StrategyListItem | null;
  /** Called when the user clicks Cancel, presses Escape, or clones successfully. */
  onClose: () => void;
  /**
   * Called after a successful POST /strategies/{id}/clone. Receives the
   * new clone id so the page can refresh the list and (today) navigate
   * to the clone's detail view via the parent's navigate hook.
   */
  onCloned: (newId: string) => void;
}

/**
 * Small modal asking the operator for the clone's ``new_name``.
 *
 * Behaviour:
 * - Pre-fills the input with ``"{source.name} (copy)"``.
 * - Client-side validates: non-empty after trim, at most
 *   :data:`CLONE_NAME_MAX_LEN` characters. Inline error renders below
 *   the input. Submit is blocked while a request is in flight.
 * - On success: calls ``onCloned(clone.id)`` and ``onClose()``.
 * - On 409: shows "A strategy with that name already exists." inline
 *   and keeps the modal open so the operator can retry without
 *   re-clicking Clone.
 * - On any other error: fires ``toast.error`` with the backend
 *   message (or a generic fallback) and keeps the modal open.
 *
 * Uses ``role="dialog"`` + ``aria-modal`` for accessibility. Escape
 * dismisses unless a request is in flight (prevents accidental
 * cancellation of an in-progress write).
 */
function CloneStrategyModal({
  source,
  onClose,
  onCloned,
}: CloneStrategyModalProps): React.ReactElement | null {
  // Controlled name state. Re-seeds when the source changes so
  // re-opening the modal for a different row resets the input.
  const [name, setName] = useState<string>("");
  const [submitting, setSubmitting] = useState<boolean>(false);
  const [inlineError, setInlineError] = useState<string | null>(null);

  useEffect(() => {
    if (source) {
      setName(`${source.name} (copy)`);
      setInlineError(null);
      setSubmitting(false);
    }
  }, [source]);

  // Escape-to-close, but never while a request is in flight (the
  // server might still create the clone — leaving the modal open lets
  // the operator see the result).
  useEffect(() => {
    if (!source) return undefined;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape" && !submitting) {
        onClose();
      }
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [source, submitting, onClose]);

  const handleSubmit = useCallback(
    async (e?: React.FormEvent) => {
      e?.preventDefault();
      if (!source || submitting) return;

      const trimmed = name.trim();
      if (!trimmed) {
        setInlineError("Name is required.");
        return;
      }
      if (trimmed.length > CLONE_NAME_MAX_LEN) {
        setInlineError(`Name must be ${CLONE_NAME_MAX_LEN} characters or fewer.`);
        return;
      }

      setSubmitting(true);
      setInlineError(null);
      try {
        const clone = await cloneStrategy(source.id, trimmed);
        toast.success(`Cloned as "${clone.name}".`);
        onCloned(clone.id);
        onClose();
      } catch (err) {
        if (err instanceof CloneStrategyError && err.statusCode === 409) {
          // Inline 409 — the operator can edit the name and retry.
          setInlineError("A strategy with that name already exists.");
        } else if (err instanceof CloneStrategyError) {
          // 404 / 422 / 5xx — show the backend detail in a toast and
          // leave the modal open so the operator can decide what to do.
          toast.error(err.detail ?? err.message);
        } else if (err instanceof Error) {
          toast.error(err.message);
        } else {
          toast.error("Failed to clone strategy.");
        }
      } finally {
        setSubmitting(false);
      }
    },
    [name, source, submitting, onCloned, onClose],
  );

  if (!source) return null;

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 px-4"
      role="dialog"
      aria-modal="true"
      aria-labelledby="strategies-clone-modal-title"
      data-testid="strategies-clone-modal"
    >
      <form
        onSubmit={handleSubmit}
        className="w-full max-w-md rounded-lg bg-white p-6 shadow-xl"
        data-testid="strategies-clone-form"
      >
        <h2
          id="strategies-clone-modal-title"
          className="text-lg font-semibold text-surface-900"
        >
          Clone {source.name}
        </h2>
        <p className="mt-1 text-sm text-surface-500">
          A copy of this strategy's source code will be saved under a new name.
          Run history, deployments, and approvals are not copied.
        </p>

        <div className="mt-4">
          <label
            htmlFor="strategies-clone-name-input"
            className="block text-xs font-medium uppercase tracking-wider text-surface-500"
          >
            New name
          </label>
          <input
            id="strategies-clone-name-input"
            data-testid="strategies-clone-name-input"
            type="text"
            value={name}
            onChange={(e) => {
              setName(e.target.value);
              if (inlineError) setInlineError(null);
            }}
            maxLength={CLONE_NAME_MAX_LEN}
            disabled={submitting}
            autoFocus
            className="mt-1 w-full rounded-md border border-surface-300 bg-white px-3 py-2 text-sm shadow-sm focus:border-brand-500 focus:outline-none focus:ring-1 focus:ring-brand-500 disabled:bg-surface-50 disabled:text-surface-500"
          />
          {inlineError && (
            <p
              className="mt-1 text-xs text-red-700"
              role="alert"
              data-testid="strategies-clone-name-error"
            >
              {inlineError}
            </p>
          )}
        </div>

        <div className="mt-6 flex justify-end gap-2">
          <button
            type="button"
            data-testid="strategies-clone-cancel"
            onClick={onClose}
            disabled={submitting}
            className="rounded-md border border-surface-300 bg-white px-4 py-2 text-sm font-medium text-surface-700 hover:bg-surface-50 disabled:cursor-not-allowed disabled:opacity-50"
          >
            Cancel
          </button>
          <button
            type="submit"
            data-testid="strategies-clone-submit"
            disabled={submitting}
            className="rounded-md bg-brand-600 px-4 py-2 text-sm font-medium text-white shadow-sm hover:bg-brand-700 disabled:cursor-not-allowed disabled:opacity-50"
          >
            {submitting ? "Cloning…" : "Clone"}
          </button>
        </div>
      </form>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Page component
// ---------------------------------------------------------------------------

/**
 * Top-level component for the ``/strategies`` route.
 *
 * Holds local UI state for filters + pagination, debounces the name
 * search by collapsing rapid keystrokes onto a single ``effect`` cycle
 * (React batches setState calls inside the same event), and renders
 * one of: loading, error banner, empty state, or the populated table.
 */
export default function Strategies() {
  // useAuth is invoked so the page asserts a valid session is present
  // (matches StrategyStudio / StrategyDetail / RunResults). The route
  // AuthGuard owns scope enforcement.
  useAuth();
  const navigate = useNavigate();

  // Filter + pagination state.
  const [page, setPage] = useState(1);
  const pageSize = DEFAULT_PAGE_SIZE;
  const [sourceFilter, setSourceFilter] = useState<SourceFilter>("all");
  const [nameQuery, setNameQuery] = useState("");

  // Loaded data + status.
  const [pageData, setPageData] = useState<StrategyListPage | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const [errorStatus, setErrorStatus] = useState<number | null>(null);

  // Clone modal state. ``cloneSource`` carries the row the operator
  // clicked Clone on; ``null`` means the modal is closed. We store the
  // full :class:`StrategyListItem` (rather than just the id) so the
  // modal can render the source name in its title without a separate
  // lookup against ``pageData``.
  const [cloneSource, setCloneSource] = useState<StrategyListItem | null>(null);

  // Reload counter — bumped after a successful clone so the list
  // refreshes and the new row becomes visible without a manual refresh.
  const [refreshTick, setRefreshTick] = useState(0);

  // Memoised api opts so the effect dependency is referentially stable.
  const apiOpts = useMemo(
    () => ({
      source: sourceFilter === "all" ? undefined : sourceFilter,
      name_contains: nameQuery.trim() || undefined,
    }),
    [sourceFilter, nameQuery],
  );

  useEffect(() => {
    let cancelled = false;
    setIsLoading(true);
    setErrorMessage(null);
    setErrorStatus(null);

    void (async () => {
      try {
        const data = await listStrategies(page, pageSize, apiOpts);
        if (!cancelled) setPageData(data);
      } catch (err) {
        if (cancelled) return;
        if (err instanceof ListStrategiesError) {
          setErrorMessage(err.message);
          setErrorStatus(err.statusCode ?? null);
        } else {
          setErrorMessage(err instanceof Error ? err.message : "Failed to load strategies.");
        }
        setPageData(null);
      } finally {
        if (!cancelled) setIsLoading(false);
      }
    })();

    return () => {
      cancelled = true;
    };
  }, [page, pageSize, apiOpts, refreshTick]);

  // Reset to page 1 when the filters change so the user does not land
  // on an out-of-range page (e.g. switching from "all" to a 1-row source
  // while sitting on page 3).
  const handleSourceChange = useCallback((next: SourceFilter) => {
    setSourceFilter(next);
    setPage(1);
  }, []);

  const handleNameChange = useCallback((next: string) => {
    setNameQuery(next);
    setPage(1);
  }, []);

  const handleViewDetail = useCallback(
    (id: string) => {
      navigate(`/strategy-studio/${id}`);
    },
    [navigate],
  );

  const handlePrev = useCallback(() => {
    setPage((p) => Math.max(1, p - 1));
  }, []);

  const handleNext = useCallback(() => {
    setPage((p) => {
      const totalPages = pageData?.total_pages ?? 1;
      return Math.min(Math.max(totalPages, 1), p + 1);
    });
  }, [pageData?.total_pages]);

  // ---------------------------------------------------------------------
  // Rendering
  // ---------------------------------------------------------------------

  const totalCount = pageData?.total_count ?? 0;
  const totalPages = pageData?.total_pages ?? 0;
  const hasResults = (pageData?.strategies.length ?? 0) > 0;

  return (
    <div className="space-y-6" data-testid="strategies-page">
      {/* Header */}
      <div className="flex flex-wrap items-baseline justify-between gap-3">
        <div>
          <h1 className="text-2xl font-bold text-surface-900">Strategies</h1>
          <p className="mt-1 text-sm text-surface-500">
            Browse the strategy catalogue. Click a row to open its detail page or run a backtest.
          </p>
        </div>
        <Link
          to="/strategy-studio"
          data-testid="strategies-import-link-header"
          className="inline-flex items-center rounded-md bg-brand-600 px-3 py-2 text-sm font-medium text-white shadow-sm hover:bg-brand-700"
        >
          Import strategy
        </Link>
      </div>

      {/* Filters */}
      <div
        className="flex flex-wrap items-end gap-3 rounded-lg border border-surface-200 bg-white p-4"
        data-testid="strategies-filters"
      >
        <div className="min-w-[14rem] flex-1">
          <label
            htmlFor="strategies-name-search"
            className="block text-xs font-medium uppercase tracking-wider text-surface-500"
          >
            Search by name
          </label>
          <input
            id="strategies-name-search"
            data-testid="strategies-name-search"
            type="search"
            value={nameQuery}
            onChange={(e) => handleNameChange(e.target.value)}
            placeholder="e.g. Bollinger"
            className="mt-1 w-full rounded-md border border-surface-300 bg-white px-3 py-2 text-sm shadow-sm focus:border-brand-500 focus:outline-none focus:ring-1 focus:ring-brand-500"
          />
        </div>
        <div>
          <label
            htmlFor="strategies-source-filter"
            className="block text-xs font-medium uppercase tracking-wider text-surface-500"
          >
            Source
          </label>
          <select
            id="strategies-source-filter"
            data-testid="strategies-source-filter"
            value={sourceFilter}
            onChange={(e) => handleSourceChange(e.target.value as SourceFilter)}
            className="mt-1 rounded-md border border-surface-300 bg-white px-3 py-2 text-sm shadow-sm focus:border-brand-500 focus:outline-none focus:ring-1 focus:ring-brand-500"
          >
            <option value="all">All</option>
            <option value="ir_upload">Imported IR</option>
            <option value="draft_form">Draft form</option>
          </select>
        </div>
      </div>

      {/* Body — error / loading / empty / table */}
      {errorMessage && (
        <div
          className="rounded-md border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700"
          role="alert"
          data-testid="strategies-error"
        >
          <strong>
            {errorStatus === 422
              ? "Invalid filter"
              : errorStatus === 403
                ? "Access denied"
                : "Failed to load strategies"}
            :
          </strong>{" "}
          {errorMessage}
        </div>
      )}

      {!errorMessage && isLoading && (
        <div data-testid="strategies-loading">
          <LoadingState message="Loading strategies…" />
        </div>
      )}

      {!errorMessage && !isLoading && !hasResults && (
        <div
          className="rounded-lg border border-dashed border-surface-300 bg-white p-10 text-center"
          data-testid="strategies-empty"
        >
          <h2 className="text-lg font-semibold text-surface-800">No strategies yet</h2>
          <p className="mt-1 text-sm text-surface-500">
            {nameQuery.trim() || sourceFilter !== "all"
              ? "No strategies match your filters. Clear the filters or try a different search."
              : "Your catalogue is empty. Import a strategy from a strategy_ir.json file or build one in Strategy Studio."}
          </p>
          <Link
            to="/strategy-studio"
            data-testid="strategies-empty-import-link"
            className="mt-4 inline-flex items-center rounded-md bg-brand-600 px-4 py-2 text-sm font-medium text-white shadow-sm hover:bg-brand-700"
          >
            Import your first strategy
          </Link>
        </div>
      )}

      {!errorMessage && !isLoading && hasResults && pageData && (
        <div
          className="overflow-hidden rounded-lg border border-surface-200 bg-white"
          data-testid="strategies-table-wrapper"
        >
          <table className="min-w-full divide-y divide-surface-200" data-testid="strategies-table">
            <thead className="bg-surface-50">
              <tr>
                <th
                  scope="col"
                  className="px-4 py-2 text-left text-xs font-semibold uppercase tracking-wider text-surface-500"
                >
                  Name
                </th>
                <th
                  scope="col"
                  className="px-4 py-2 text-left text-xs font-semibold uppercase tracking-wider text-surface-500"
                >
                  Source
                </th>
                <th
                  scope="col"
                  className="px-4 py-2 text-left text-xs font-semibold uppercase tracking-wider text-surface-500"
                >
                  Version
                </th>
                <th
                  scope="col"
                  className="px-4 py-2 text-left text-xs font-semibold uppercase tracking-wider text-surface-500"
                >
                  Created
                </th>
                <th
                  scope="col"
                  className="px-4 py-2 text-left text-xs font-semibold uppercase tracking-wider text-surface-500"
                >
                  Created by
                </th>
                <th scope="col" className="px-4 py-2 text-right">
                  <span className="sr-only">Actions</span>
                </th>
              </tr>
            </thead>
            <tbody className="divide-y divide-surface-100">
              {pageData.strategies.map((row) => (
                <tr key={row.id} data-testid={`strategy-row-${row.id}`}>
                  <td className="px-4 py-3 align-top">
                    <div className="font-medium text-surface-900">{row.name}</div>
                    <div className="mt-0.5 font-mono text-xs text-surface-500">{row.id}</div>
                  </td>
                  <td className="px-4 py-3 align-top">
                    <SourcePill source={row.source} />
                  </td>
                  <td className="px-4 py-3 align-top text-sm text-surface-700">v{row.version}</td>
                  <td className="px-4 py-3 align-top text-sm text-surface-700">
                    {formatIso(row.created_at)}
                  </td>
                  <td className="px-4 py-3 align-top font-mono text-xs text-surface-700">
                    {row.created_by}
                  </td>
                  <td className="px-4 py-3 text-right align-top">
                    <div className="flex justify-end gap-2">
                      <button
                        type="button"
                        data-testid={`strategy-row-clone-${row.id}`}
                        onClick={() => setCloneSource(row)}
                        className="inline-flex items-center rounded-md border border-surface-300 bg-white px-3 py-1.5 text-xs font-medium text-surface-700 hover:bg-surface-50"
                        aria-label={`Clone ${row.name}`}
                      >
                        {/* Inline SVG copy icon — keeps the page free of
                            new icon-library imports for a single button. */}
                        <svg
                          xmlns="http://www.w3.org/2000/svg"
                          viewBox="0 0 20 20"
                          fill="currentColor"
                          aria-hidden="true"
                          className="mr-1 h-3.5 w-3.5"
                        >
                          <path d="M6 3a2 2 0 00-2 2v9a2 2 0 002 2h6a2 2 0 002-2V5a2 2 0 00-2-2H6z" />
                          <path d="M14 5h-1a2 2 0 012 2v8a2 2 0 01-2 2H8a2 2 0 002 2h4a2 2 0 002-2V7a2 2 0 00-2-2z" />
                        </svg>
                        Clone
                      </button>
                      <button
                        type="button"
                        data-testid={`strategy-row-detail-${row.id}`}
                        onClick={() => handleViewDetail(row.id)}
                        className="inline-flex items-center rounded-md border border-brand-300 bg-white px-3 py-1.5 text-xs font-medium text-brand-700 hover:bg-brand-50"
                      >
                        View detail
                      </button>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {/* Pagination */}
      {!errorMessage && !isLoading && hasResults && pageData && (
        <div
          className="flex items-center justify-between rounded-lg border border-surface-200 bg-white px-4 py-3 text-sm"
          data-testid="strategies-pagination"
        >
          <div className="text-surface-600">
            Showing {pageData.strategies.length} of {totalCount} — Page{" "}
            <span data-testid="strategies-page-current">{pageData.page}</span> of{" "}
            <span data-testid="strategies-page-total">{Math.max(totalPages, 1)}</span>
          </div>
          <div className="flex gap-2">
            <button
              type="button"
              data-testid="strategies-page-prev"
              onClick={handlePrev}
              disabled={pageData.page <= 1}
              className="rounded-md border border-surface-300 bg-white px-3 py-1.5 text-xs font-medium text-surface-700 hover:bg-surface-50 disabled:cursor-not-allowed disabled:opacity-50"
            >
              Previous
            </button>
            <button
              type="button"
              data-testid="strategies-page-next"
              onClick={handleNext}
              disabled={pageData.page >= totalPages}
              className="rounded-md border border-surface-300 bg-white px-3 py-1.5 text-xs font-medium text-surface-700 hover:bg-surface-50 disabled:cursor-not-allowed disabled:opacity-50"
            >
              Next
            </button>
          </div>
        </div>
      )}

      {/* Clone modal — mounted only while a source row is selected. */}
      <CloneStrategyModal
        source={cloneSource}
        onClose={() => setCloneSource(null)}
        onCloned={(newId) => {
          // Bump the refresh tick so the list re-fetches and the new
          // row appears, then navigate the operator to the clone's
          // detail page (matches the import-IR success flow).
          setRefreshTick((n) => n + 1);
          navigate(`/strategy-studio/${newId}`);
        }}
      />
    </div>
  );
}
