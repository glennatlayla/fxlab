/**
 * Strategy IR import API client (M2.D1).
 *
 * Purpose:
 *   Provide a typed wrapper around the M2.C1 backend endpoint
 *   ``POST /strategies/import-ir`` (multipart/form-data) for the
 *   Strategy Studio "Import from file" tab.
 *
 * Responsibilities:
 *   - Build a ``FormData`` body with the canonical field name ``file``
 *     (matches the FastAPI signature ``file: UploadFile = File(...)``).
 *   - Issue the request through the shared ``apiClient`` so the auth
 *     header, correlation id, and X-Client-Source interceptors fire.
 *   - Surface 400 validation errors (Pydantic error path in ``detail``)
 *     as a typed :class:`ImportIrError` for the UI to render.
 *
 * Does NOT:
 *   - Validate the IR JSON locally — the backend is the schema oracle.
 *   - Read or persist the file beyond the in-flight request.
 *   - Manage React state (the calling component owns that).
 *
 * Dependencies:
 *   - @/api/client (axios instance with auth + correlation injection).
 *
 * Error conditions:
 *   - 400 → :class:`ImportIrError` carrying the backend ``detail``
 *     string (Pydantic error path) so the UI can render it inline.
 *   - 401 → intercepted by apiClient, triggers logout.
 *   - Other failures → AxiosError thrown to the caller.
 *
 * Example:
 *   const result = await importStrategyIr(file);
 *   navigate(`/strategy-studio/${result.strategy.id}`);
 */

import { AxiosError } from "axios";
import { apiClient } from "@/api/client";
import type { StrategyIR } from "@/types/strategy_ir";

// ---------------------------------------------------------------------------
// Types — match the M2.C1 backend response shape
// ---------------------------------------------------------------------------

/**
 * Strategy record returned by ``POST /strategies/import-ir``.
 *
 * Mirrors the persistence columns the backend serialises (see
 * ``services/api/routes/strategies.py::import_strategy_ir``). Only the
 * ``id`` field is load-bearing for M2.D1 (used for navigation), but
 * the full shape is documented here so the import-from-file flow can
 * grow without re-deriving the contract.
 */
export interface ImportedStrategy {
  /** ULID of the persisted strategy. Used for ``/strategy-studio/{id}``. */
  id: string;
  /** Display name from the IR's metadata.strategy_name field. */
  name: string;
  /** Semver-style version string. */
  version: string;
  /** Always ``"ir_upload"`` for this endpoint (vs. ``"draft_form"``). */
  source: string;
  /** ULID of the user who uploaded the IR. */
  created_by: string;
  /** ISO-8601 timestamp of creation. */
  created_at: string;
  /** ISO-8601 timestamp of last update. */
  updated_at: string;
}

/** Envelope returned by ``POST /strategies/import-ir``. */
export interface ImportStrategyIrResponse {
  strategy: ImportedStrategy;
}

/**
 * Typed error for import-IR API failures.
 *
 * Carries the HTTP status and the backend ``detail`` string so the UI
 * can distinguish "your file is malformed" (400) from infrastructure
 * failures (5xx) without parsing free-form messages.
 */
export class ImportIrError extends Error {
  constructor(
    message: string,
    public readonly statusCode?: number,
    public readonly detail?: string,
  ) {
    super(message);
    this.name = "ImportIrError";
  }
}

// ---------------------------------------------------------------------------
// Endpoint client
// ---------------------------------------------------------------------------

/**
 * POST a ``*.strategy_ir.json`` file to ``/strategies/import-ir``.
 *
 * Wraps the upload in a ``FormData`` body using the field name
 * ``file`` (the FastAPI parameter name). Lets axios set the
 * multipart Content-Type + boundary header automatically — manually
 * setting ``multipart/form-data`` strips the boundary and the server
 * returns 422.
 *
 * Args:
 *   file: A browser ``File`` object selected from a drop zone or
 *     ``<input type="file">``. Caller is responsible for filename
 *     extension validation before calling.
 *
 * Returns:
 *   ``{strategy: ImportedStrategy}`` envelope on 201.
 *
 * Raises:
 *   ImportIrError (statusCode=400) when the backend rejects the IR.
 *     The ``detail`` field carries the Pydantic error path string so
 *     the UI can show the offending field to the user.
 *   AxiosError on network failure or non-400 HTTP errors.
 *
 * Example:
 *   try {
 *     const result = await importStrategyIr(file);
 *     navigate(`/strategy-studio/${result.strategy.id}`);
 *   } catch (err) {
 *     if (err instanceof ImportIrError) setError(err.detail ?? err.message);
 *   }
 */
export async function importStrategyIr(file: File): Promise<ImportStrategyIrResponse> {
  const body = new FormData();
  body.append("file", file);

  try {
    // Pass headers={} (not undefined) so axios skips the default
    // application/json Content-Type and lets the browser pick the
    // multipart boundary itself. The shared interceptor still injects
    // Authorization, X-Correlation-Id, and X-Client-Source.
    const resp = await apiClient.post<ImportStrategyIrResponse>("/strategies/import-ir", body, {
      headers: { "Content-Type": "multipart/form-data" },
    });
    return resp.data;
  } catch (err) {
    if (err instanceof AxiosError && err.response) {
      const status = err.response.status;
      // Backend wraps Pydantic ValidationError messages in detail; fall
      // back to a generic message if the server omitted detail (e.g.
      // a network proxy returned an HTML error page).
      const detail =
        typeof err.response.data?.detail === "string"
          ? err.response.data.detail
          : "Strategy IR import failed";
      throw new ImportIrError(detail, status, detail);
    }
    throw err;
  }
}

// ---------------------------------------------------------------------------
// GET /strategies/{id} — M2.C4 strategy detail (parsed IR + draft view)
// ---------------------------------------------------------------------------

/**
 * Strategy source discriminator returned by ``GET /strategies/{id}``.
 *
 * - ``"ir_upload"``  → ``parsed_ir`` is populated (full StrategyIR).
 * - ``"draft_form"`` → ``draft_fields`` is populated (form payload).
 *
 * The API contract guarantees exactly one of the two is non-null per
 * row; the discriminator tells the UI which view to render.
 */
export type StrategySource = "ir_upload" | "draft_form";

/**
 * Strategy record returned by ``GET /strategies/{id}`` (M2.C4).
 *
 * Mirrors the response body shape from
 * ``services/api/services/strategy_service.py::get_with_parsed_ir``.
 *
 * ``parsed_ir`` is the canonical :class:`StrategyIR` re-validated server-
 * side from the persisted ``code`` column. ``draft_fields`` carries the
 * draft-form payload for non-IR strategies. Exactly one of those is
 * populated; the ``source`` discriminator drives which view renders.
 */
export interface StrategyDetail {
  /** ULID of the persisted strategy. */
  id: string;
  /** Display name (mirrors metadata.strategy_name for IR uploads). */
  name: string;
  /** Raw ``code`` column — stringified IR JSON or DSL payload. */
  code: string;
  /** Semver-style version string. */
  version: string;
  /** ``"ir_upload"`` or ``"draft_form"`` — drives the render branch. */
  source: StrategySource;
  /** ULID of the user who created the strategy. */
  created_by: string;
  /** Whether the strategy is active (soft-delete flag). */
  is_active: boolean;
  /** Optimistic concurrency version (server-managed). */
  row_version: number;
  /** ISO-8601 creation timestamp. */
  created_at: string;
  /** ISO-8601 last-update timestamp. */
  updated_at: string;
  /**
   * ISO-8601 soft-archive timestamp, or null for active rows. Mirror of
   * :class:`libs.contracts.strategy.StrategyListItem.archived_at`.
   */
  archived_at: string | null;
  /** Re-validated StrategyIR for ``source==="ir_upload"``. */
  parsed_ir: StrategyIR | null;
  /** Draft form payload for ``source==="draft_form"``. */
  draft_fields: Record<string, unknown> | null;
}

/** Envelope returned by ``GET /strategies/{id}``. */
export interface GetStrategyResponse {
  strategy: StrategyDetail;
}

/**
 * Typed error for ``GET /strategies/{id}`` failures.
 *
 * Carries the HTTP status and the backend ``detail`` string so the page
 * can distinguish 404 (strategy missing) from 422 (stored IR fails
 * re-validation, schema drift) without parsing free-form messages.
 */
export class GetStrategyError extends Error {
  constructor(
    message: string,
    public readonly statusCode?: number,
    public readonly detail?: string,
  ) {
    super(message);
    this.name = "GetStrategyError";
  }
}

/**
 * GET ``/strategies/{strategyId}`` and unwrap the ``{strategy: ...}``
 * envelope into a typed :class:`StrategyDetail`.
 *
 * Args:
 *   strategyId: ULID of the strategy to load.
 *
 * Returns:
 *   The :class:`StrategyDetail` record (already envelope-unwrapped).
 *
 * Raises:
 *   GetStrategyError (statusCode=404) when the strategy does not exist.
 *   GetStrategyError (statusCode=422) when the persisted IR fails
 *     server-side re-validation (schema drift without backfill).
 *   AxiosError on network failure or other non-2xx HTTP errors.
 *
 * Example:
 *   try {
 *     const strat = await getStrategy("01HZ...");
 *     if (strat.source === "ir_upload" && strat.parsed_ir) {
 *       // render IrDetailView
 *     }
 *   } catch (err) {
 *     if (err instanceof GetStrategyError) setError(err.detail ?? err.message);
 *   }
 */
export async function getStrategy(strategyId: string): Promise<StrategyDetail> {
  try {
    const resp = await apiClient.get<GetStrategyResponse>(`/strategies/${strategyId}`);
    return resp.data.strategy;
  } catch (err) {
    if (err instanceof AxiosError && err.response) {
      const status = err.response.status;
      const detailRaw = err.response.data?.detail;
      const detail =
        typeof detailRaw === "string"
          ? detailRaw
          : status === 404
            ? `Strategy ${strategyId} not found`
            : `Failed to load strategy (status ${status})`;
      throw new GetStrategyError(
        detail,
        status,
        typeof detailRaw === "string" ? detailRaw : undefined,
      );
    }
    throw err;
  }
}

// ---------------------------------------------------------------------------
// GET /strategies — M2.D5 paginated browse-page endpoint
// ---------------------------------------------------------------------------

/**
 * One row in the M2.D5 strategies browse-page table.
 *
 * Mirrors :class:`libs.contracts.strategy.StrategyListItem`. The frontend
 * uses these to render the catalogue grid; clicking a row navigates to
 * the existing ``/strategy-studio/:id`` detail page.
 */
export interface StrategyListItem {
  /** Strategy ULID. */
  id: string;
  /** Display name (mirrors metadata.strategy_name for IR uploads). */
  name: string;
  /** Provenance flag — drives the source pill in the table. */
  source: StrategySource;
  /** SemVer-style version string. */
  version: string;
  /** ULID of the user who created the strategy. */
  created_by: string;
  /** ISO-8601 timestamp of creation. */
  created_at: string;
  /** Soft-delete flag. ``false`` rows are hidden by default. */
  is_active: boolean;
  /**
   * ISO-8601 timestamp the strategy was soft-archived, or ``null`` for
   * active rows. Drives the "Archived" badge + Restore-vs-Archive
   * action button in the browse page (M5 archive lifecycle).
   */
  archived_at: string | null;
}

/**
 * Response body for ``GET /strategies?page=...`` (M2.D5 envelope).
 *
 * Mirrors :class:`libs.contracts.strategy.StrategyListPage`. The frontend
 * grid renders ``strategies`` and uses ``page`` / ``page_size`` /
 * ``total_count`` / ``total_pages`` to drive Next/Prev affordances and
 * "Page X of Y" copy.
 */
export interface StrategyListPage {
  strategies: StrategyListItem[];
  page: number;
  page_size: number;
  total_count: number;
  total_pages: number;
  /** Convenience field — size of the current page (always strategies.length). */
  count: number;
}

/** Optional filters accepted by :func:`listStrategies`. */
export interface ListStrategiesOptions {
  /** Provenance filter — ``"ir_upload"`` | ``"draft_form"`` | undefined. */
  source?: StrategySource;
  /** Case-insensitive substring filter applied to the strategy name. */
  name_contains?: string;
  /**
   * When true, soft-archived strategies (``archived_at`` non-null) are
   * included in the response. Defaults to false on the server so the
   * Strategies browse page only surfaces archived rows when the
   * "Show archived" toggle is on.
   */
  includeArchived?: boolean;
}

/**
 * Typed error for ``GET /strategies?page=...`` failures.
 *
 * Carries the HTTP status and the backend ``detail`` string so the
 * browse page can render a typed banner without parsing free-form
 * messages.
 */
export class ListStrategiesError extends Error {
  constructor(
    message: string,
    public readonly statusCode?: number,
    public readonly detail?: string,
  ) {
    super(message);
    this.name = "ListStrategiesError";
  }
}

/**
 * Fetch one page of the strategies catalogue.
 *
 * Args:
 *   page: 1-based page index.
 *   page_size: Strategies per page (capped server-side at 200).
 *   opts: Optional ``source`` / ``name_contains`` filters.
 *
 * Returns:
 *   A :class:`StrategyListPage` envelope ready for the browse-page grid.
 *
 * Raises:
 *   ListStrategiesError when the backend returns a non-2xx response.
 *     ``statusCode`` carries the HTTP status (422 for invalid filter
 *     values, 401 for missing auth handled by the global interceptor).
 *   AxiosError on network failure.
 *
 * Example:
 *   const page = await listStrategies(1, 20, { source: "ir_upload" });
 *   for (const row of page.strategies) console.log(row.id, row.name);
 */
export async function listStrategies(
  page: number,
  page_size: number,
  opts?: ListStrategiesOptions,
): Promise<StrategyListPage> {
  const params: Record<string, string> = {
    page: String(page),
    page_size: String(page_size),
  };
  if (opts?.source) params.source = opts.source;
  if (opts?.name_contains && opts.name_contains.trim()) {
    params.name_contains = opts.name_contains.trim();
  }
  if (opts?.includeArchived) {
    // Backend expects the snake_case query param name "include_archived".
    // Only set when truthy — omitting it relies on the FastAPI default
    // of False so the legacy callers' query strings are unchanged.
    params.include_archived = "true";
  }

  try {
    const resp = await apiClient.get<StrategyListPage>("/strategies/", { params });
    return resp.data;
  } catch (err) {
    if (err instanceof AxiosError && err.response) {
      const status = err.response.status;
      const detailRaw = err.response.data?.detail;
      const detail =
        typeof detailRaw === "string" ? detailRaw : `Failed to load strategies (status ${status})`;
      throw new ListStrategiesError(
        detail,
        status,
        typeof detailRaw === "string" ? detailRaw : undefined,
      );
    }
    throw err;
  }
}

// ---------------------------------------------------------------------------
// POST /strategies/{strategy_id}/clone — duplicate a strategy under a new name
// ---------------------------------------------------------------------------

/**
 * Strategy record returned by ``POST /strategies/{id}/clone``.
 *
 * Mirrors the persistence columns the backend serialises (see
 * ``services/api/routes/strategies.py::clone_strategy_route``). Identical
 * shape to :class:`ImportedStrategy` plus ``row_version`` and
 * ``is_active`` so the caller can pass the body straight into the
 * strategy detail page without an extra GET.
 */
export interface ClonedStrategy {
  /** ULID of the persisted clone (distinct from the source id). */
  id: string;
  /** Display name supplied as ``new_name`` in the request. */
  name: string;
  /** Stored ``code`` body — JSON-encoded IR or DSL payload. */
  code: string;
  /** Inherited from the source row. */
  version: string;
  /** Inherited from the source row (``"ir_upload"`` or ``"draft_form"``). */
  source: StrategySource;
  /** ULID of the operator who clicked Clone. */
  created_by: string;
  /** Soft-delete flag; clones are always active on creation. */
  is_active: boolean;
  /** Always ``1`` for a freshly persisted clone. */
  row_version: number;
  /** ISO-8601 timestamp of clone creation. */
  created_at: string;
  /** ISO-8601 timestamp of clone last update (== created_at on a fresh row). */
  updated_at: string;
}

/** Envelope returned by ``POST /strategies/{id}/clone``. */
export interface CloneStrategyResponse {
  strategy: ClonedStrategy;
}

/**
 * Typed error for ``POST /strategies/{id}/clone`` failures.
 *
 * Carries the HTTP status and the backend ``detail`` string so the UI
 * can branch on 404 (source missing), 409 (name collision), and 422
 * (Pydantic validation) without parsing free-form messages.
 */
export class CloneStrategyError extends Error {
  constructor(
    message: string,
    public readonly statusCode?: number,
    public readonly detail?: string,
  ) {
    super(message);
    this.name = "CloneStrategyError";
  }
}

/**
 * Clone an existing strategy under ``newName``.
 *
 * POSTs to ``/strategies/{sourceId}/clone`` with the body
 * ``{"new_name": newName}``. The backend returns 201 with the cloned
 * Strategy on success, or one of:
 *   - 404 — the source strategy does not exist.
 *   - 409 — a strategy with ``newName`` already exists (case-insensitive).
 *   - 422 — ``new_name`` is empty or longer than 255 characters.
 *
 * The shared ``apiClient`` interceptor injects Authorization and
 * X-Correlation-Id headers, so callers do not need to pass them
 * explicitly.
 *
 * Args:
 *   sourceId: ULID of the strategy to clone.
 *   newName: Display name for the clone. Caller is responsible for
 *     pre-validating non-empty + length; the backend re-validates.
 *
 * Returns:
 *   The :class:`ClonedStrategy` record (already envelope-unwrapped).
 *
 * Raises:
 *   CloneStrategyError — typed wrapper around any non-2xx HTTP
 *     response. ``statusCode`` carries the HTTP status, ``detail``
 *     carries the backend ``detail`` string when present.
 *   AxiosError — on network failure or non-AxiosError errors.
 *
 * Example:
 *   try {
 *     const clone = await cloneStrategy(sourceId, "RSI Reversal (copy)");
 *     navigate(`/strategy-studio/${clone.id}`);
 *   } catch (err) {
 *     if (err instanceof CloneStrategyError && err.statusCode === 409) {
 *       setInlineError("A strategy with that name already exists.");
 *     }
 *   }
 */
export async function cloneStrategy(sourceId: string, newName: string): Promise<ClonedStrategy> {
  try {
    const resp = await apiClient.post<CloneStrategyResponse>(`/strategies/${sourceId}/clone`, {
      new_name: newName,
    });
    return resp.data.strategy;
  } catch (err) {
    if (err instanceof AxiosError && err.response) {
      const status = err.response.status;
      const detailRaw = err.response.data?.detail;
      const detail =
        typeof detailRaw === "string"
          ? detailRaw
          : status === 404
            ? `Strategy ${sourceId} not found`
            : status === 409
              ? `A strategy named "${newName}" already exists`
              : `Failed to clone strategy (status ${status})`;
      throw new CloneStrategyError(
        detail,
        status,
        typeof detailRaw === "string" ? detailRaw : undefined,
      );
    }
    throw err;
  }
}

// ---------------------------------------------------------------------------
// GET /strategies/{strategy_id}/runs — recent runs section on StrategyDetail
// ---------------------------------------------------------------------------

/** Default page size for the recent-runs section on the StrategyDetail page. */
export const DEFAULT_STRATEGY_RUNS_PAGE_SIZE = 20;

/** Lifecycle status values surfaced on the recent-runs row. */
export type RunStatus = "pending" | "queued" | "running" | "completed" | "failed" | "cancelled";

/**
 * Compact summary metrics surfaced inline on a recent-runs row.
 *
 * Mirrors :class:`libs.contracts.run_results.RunSummaryMetrics`. Decimal
 * fields arrive over the wire as strings (Pydantic default Decimal
 * encoding) so the frontend table can render them via standard
 * string-to-number coercion when needed; ``null`` means "engine did not
 * report this metric" and is rendered as an em-dash.
 */
export interface RunSummaryMetrics {
  /** Total return percentage. ``null`` when the run produced no result. */
  total_return_pct: string | null;
  /** Annualised Sharpe ratio. ``null`` when not available. */
  sharpe_ratio: string | null;
  /** Fraction of winning trades, 0.0-1.0. ``null`` when not available. */
  win_rate: string | null;
  /** Total trade count; ``0`` when the run produced no result body. */
  trade_count: number;
}

/**
 * One row in the recent-runs section on the StrategyDetail page.
 *
 * Mirrors :class:`libs.contracts.run_results.RunSummaryItem`. Clicking the
 * row's "View results" button navigates to ``/runs/{id}/results``.
 */
export interface RunSummaryItem {
  /** ULID of the run; navigation target for ``/runs/{id}/results``. */
  id: string;
  /** Lifecycle status. Drives the status pill variant. */
  status: RunStatus;
  /** ISO-8601 timestamp when execution began. ``null`` for QUEUED runs. */
  started_at: string | null;
  /** ISO-8601 timestamp when execution finished. ``null`` for non-terminal. */
  completed_at: string | null;
  /** Headline metrics surfaced on the row. */
  summary_metrics: RunSummaryMetrics;
}

/**
 * Response body for ``GET /strategies/{strategy_id}/runs``.
 *
 * Mirrors :class:`libs.contracts.run_results.StrategyRunsPage`. The frontend
 * grid renders ``runs`` and uses ``page`` / ``page_size`` / ``total_count``
 * / ``total_pages`` to drive Next/Prev affordances and "Page X of Y" copy.
 */
export interface StrategyRunsPage {
  runs: RunSummaryItem[];
  page: number;
  page_size: number;
  total_count: number;
  total_pages: number;
}

/**
 * Typed error for ``GET /strategies/{strategy_id}/runs`` failures.
 *
 * Carries the HTTP status and the backend ``detail`` string so the
 * recent-runs section can render a typed banner without parsing
 * free-form messages.
 */
export class GetStrategyRunsError extends Error {
  constructor(
    message: string,
    public readonly statusCode?: number,
    public readonly detail?: string,
  ) {
    super(message);
    this.name = "GetStrategyRunsError";
  }
}

/**
 * Fetch one page of recent runs for a given strategy.
 *
 * Args:
 *   strategyId: ULID of the strategy whose run history to fetch.
 *   page: 1-based page index (default 1).
 *   page_size: Runs per page (server-capped at 200; default 20).
 *
 * Returns:
 *   A :class:`StrategyRunsPage` envelope ready for the recent-runs table.
 *
 * Raises:
 *   GetStrategyRunsError when the backend returns a non-2xx response.
 *     ``statusCode`` carries the HTTP status (422 for invalid pagination,
 *     503 when the research-run service is not configured, 401 for
 *     missing auth handled by the global interceptor).
 *   AxiosError on network failure.
 *
 * Example:
 *   const page = await getStrategyRuns("01HZ...", 1, 20);
 *   for (const row of page.runs) console.log(row.id, row.status);
 */
export async function getStrategyRuns(
  strategyId: string,
  page: number = 1,
  page_size: number = DEFAULT_STRATEGY_RUNS_PAGE_SIZE,
): Promise<StrategyRunsPage> {
  try {
    const resp = await apiClient.get<StrategyRunsPage>(`/strategies/${strategyId}/runs`, {
      params: {
        page: String(page),
        page_size: String(page_size),
      },
    });
    return resp.data;
  } catch (err) {
    if (err instanceof AxiosError && err.response) {
      const status = err.response.status;
      const detailRaw = err.response.data?.detail;
      const detail =
        typeof detailRaw === "string"
          ? detailRaw
          : `Failed to load runs for strategy ${strategyId} (status ${status})`;
      throw new GetStrategyRunsError(
        detail,
        status,
        typeof detailRaw === "string" ? detailRaw : undefined,
      );
    }
    throw err;
  }
}

// ---------------------------------------------------------------------------
// POST /strategies/{strategy_id}/archive | /restore — soft-archive lifecycle
// ---------------------------------------------------------------------------

/**
 * Strategy record returned by ``POST /strategies/{id}/archive`` and
 * ``POST /strategies/{id}/restore``.
 *
 * Mirrors the backend response shape from
 * ``services/api/routes/strategies.py::archive_strategy_route`` /
 * ``restore_strategy_route``: the persistence dict the service hands
 * back, including the post-write ``archived_at`` (ISO-8601 string for
 * archive, ``null`` after restore) and the bumped ``row_version``.
 *
 * Identical shape to :class:`ClonedStrategy` plus ``archived_at`` so
 * the page can display it in the same row without a follow-up GET.
 */
export interface ArchivedStrategy {
  /** ULID of the affected strategy (unchanged across the lifecycle write). */
  id: string;
  /** Display name (unchanged). */
  name: string;
  /** Stored ``code`` body. */
  code: string;
  /** Inherited from the existing row. */
  version: string;
  /** Inherited from the existing row. */
  source: StrategySource;
  /** ULID of the original creator (unchanged). */
  created_by: string;
  /** Soft-delete flag (unchanged by archive/restore — orthogonal to is_active). */
  is_active: boolean;
  /** Bumped on every archive/restore write. */
  row_version: number;
  /**
   * ISO-8601 archive timestamp after a successful archive call, or
   * ``null`` after restore. Drives the UI's archive badge + Restore vs.
   * Archive button selection.
   */
  archived_at: string | null;
  /** ISO-8601 creation timestamp (unchanged). */
  created_at: string;
  /** ISO-8601 last-update timestamp (== now after the write). */
  updated_at: string;
}

/** Envelope returned by ``POST /strategies/{id}/archive`` and ``/restore``. */
export interface ArchiveStrategyResponse {
  strategy: ArchivedStrategy;
}

/**
 * Typed error for archive/restore endpoint failures.
 *
 * Carries the HTTP status and the backend ``detail`` string so the
 * Strategies browse page can branch on 404 (gone), 409 (already in
 * the requested state, or row_version conflict) without parsing
 * free-form messages.
 */
export class ArchiveStrategyError extends Error {
  constructor(
    message: string,
    public readonly statusCode?: number,
    public readonly detail?: string,
  ) {
    super(message);
    this.name = "ArchiveStrategyError";
  }
}

/**
 * Build a typed :class:`ArchiveStrategyError` from a caught axios error.
 *
 * Centralised so archiveStrategy and restoreStrategy share one error-
 * shape contract.
 */
function makeArchiveError(
  err: unknown,
  fallbackPrefix: string,
  strategyId: string,
): ArchiveStrategyError | unknown {
  if (err instanceof AxiosError && err.response) {
    const status = err.response.status;
    const detailRaw = err.response.data?.detail;
    const detail =
      typeof detailRaw === "string"
        ? detailRaw
        : status === 404
          ? `Strategy ${strategyId} not found`
          : status === 409
            ? `${fallbackPrefix} ${strategyId}: conflict`
            : `${fallbackPrefix} ${strategyId} (status ${status})`;
    return new ArchiveStrategyError(
      detail,
      status,
      typeof detailRaw === "string" ? detailRaw : undefined,
    );
  }
  return err;
}

/**
 * Soft-archive a strategy via ``POST /strategies/{id}/archive``.
 *
 * The backend sets ``archived_at = now`` and bumps ``row_version``.
 * The strategy disappears from the default catalogue browse view but
 * its history (runs, audit trail, deployments) is retained.
 *
 * Args:
 *   strategyId: ULID of the strategy to archive.
 *
 * Returns:
 *   The updated :class:`ArchivedStrategy` record (already envelope-
 *   unwrapped) carrying the new ``archived_at`` ISO-8601 timestamp
 *   and the bumped ``row_version``.
 *
 * Raises:
 *   ArchiveStrategyError (statusCode=404) — strategy does not exist.
 *   ArchiveStrategyError (statusCode=409) — strategy is already
 *     archived, or a concurrent writer mutated the row.
 *   AxiosError on network failure or other non-2xx HTTP errors.
 *
 * Example:
 *   try {
 *     const archived = await archiveStrategy(row.id);
 *     toast.success(`Archived "${archived.name}".`);
 *   } catch (err) {
 *     if (err instanceof ArchiveStrategyError) toast.error(err.detail ?? err.message);
 *   }
 */
export async function archiveStrategy(strategyId: string): Promise<ArchivedStrategy> {
  try {
    const resp = await apiClient.post<ArchiveStrategyResponse>(`/strategies/${strategyId}/archive`);
    return resp.data.strategy;
  } catch (err) {
    throw makeArchiveError(err, "Failed to archive strategy", strategyId);
  }
}

/**
 * One issue surfaced by ``POST /strategies/validate-ir``.
 *
 * Mirrors :class:`libs.contracts.strategy.ValidationIssue`. The path is
 * a JSON pointer (``"/metadata/strategy_name"``) — leading slash + slash
 * separated segments — or ``"/"`` for root issues like malformed JSON.
 */
export interface StrategyValidationIssue {
  /** JSON pointer (RFC 6901) into the IR document, or ``"/"`` for root. */
  path: string;
  /**
   * Stable, machine-readable error code so the UI can branch on the
   * failure kind without parsing free-form text.
   * Known values: ``"invalid_json"``, ``"schema_violation"``,
   * ``"undefined_reference"``, ``"dataset_not_found"``, ``"truncated"``,
   * ``"unexpected_error"``.
   */
  code: string;
  /** Human-readable explanation suitable for inline display. */
  message: string;
}

/**
 * Response body for ``POST /strategies/validate-ir``.
 *
 * Mirrors :class:`libs.contracts.strategy.StrategyValidationReport`.
 *
 * - ``valid===true`` → ``parsed_ir`` carries the canonical parsed IR
 *   dict (deep-equals the input on success). ``errors`` is empty.
 * - ``valid===false`` → ``errors`` lists every detected issue. Capped
 *   server-side at 100 rows; truncation is surfaced as a trailing
 *   ``code==="truncated"`` issue so the operator knows more errors
 *   exist beyond what was rendered.
 */
export interface StrategyValidationReport {
  /** True when every pipeline stage passed. */
  valid: boolean;
  /** Canonical parsed IR on success, ``null`` on failure. */
  parsed_ir: Record<string, unknown> | null;
  /** Fatal issues; empty when ``valid`` is true. */
  errors: StrategyValidationIssue[];
  /** Non-fatal issues (e.g. uncertified dataset references). */
  warnings: StrategyValidationIssue[];
}

/**
 * Typed error for ``POST /strategies/validate-ir`` failures.
 *
 * The endpoint returns 200 for both pass and fail; this error class
 * covers the auth (401/403) and malformed-body (422) branches plus
 * any network-level failures. A successful 200 response (regardless of
 * the report's ``valid`` flag) is NOT an error.
 */
export class ValidateIrError extends Error {
  constructor(
    message: string,
    public readonly statusCode?: number,
    public readonly detail?: string,
  ) {
    super(message);
    this.name = "ValidateIrError";
  }
}

/**
 * POST raw IR JSON text to ``/strategies/validate-ir`` and return the report.
 *
 * The endpoint always returns 200 on a well-formed request — both
 * "this IR is valid" and "this IR is broken in N ways" share the same
 * HTTP status. The verdict lives on the response body's ``valid`` flag.
 *
 * Args:
 *   irText: Raw IR JSON text from the operator's textarea. Must be
 *     non-empty (server enforces ``min_length=1`` and a 1 MiB cap).
 *
 * Returns:
 *   A :class:`StrategyValidationReport` describing the verdict.
 *
 * Raises:
 *   ValidateIrError on non-2xx responses (401, 403, 422 for empty
 *     text, etc.). The caller should render the report inline on a
 *     200 response without treating it as an error.
 *   AxiosError on network failure.
 *
 * Example:
 *   try {
 *     const report = await validateIr(text);
 *     if (report.valid) toast.success("IR is valid.");
 *     else setErrors(report.errors);
 *   } catch (err) {
 *     if (err instanceof ValidateIrError) setError(err.detail ?? err.message);
 *   }
 */
export async function validateIr(irText: string): Promise<StrategyValidationReport> {
  try {
    const resp = await apiClient.post<StrategyValidationReport>("/strategies/validate-ir", {
      ir_text: irText,
    });
    return resp.data;
  } catch (err) {
    if (err instanceof AxiosError && err.response) {
      const status = err.response.status;
      const detailRaw = err.response.data?.detail;
      const detail =
        typeof detailRaw === "string"
          ? detailRaw
          : status === 422
            ? "IR text is required (request body validation failed)"
            : `Failed to validate IR (status ${status})`;
      throw new ValidateIrError(
        detail,
        status,
        typeof detailRaw === "string" ? detailRaw : undefined,
      );
    }
    throw err;
  }
}

/**
 * Typed error for ``GET /strategies/{id}/ir.json`` download failures.
 *
 * Carries the HTTP status and the backend ``detail`` string so the page
 * can branch on 404 (gone), 401/403 (auth), or 5xx (infrastructure)
 * without parsing free-form messages.
 */
export class DownloadIrError extends Error {
  constructor(
    message: string,
    public readonly statusCode?: number,
    public readonly detail?: string,
  ) {
    super(message);
    this.name = "DownloadIrError";
  }
}

/**
 * Sanitise a string for use as a download filename.
 *
 * Mirrors the backend's ``_sanitise_filename_token`` so the suggested
 * filename in the browser's Save dialog matches the backend's
 * Content-Disposition header even on platforms where the browser
 * picks its own filename rather than honouring the server hint.
 *
 * Keeps alphanumerics, dots, hyphens, underscores, and spaces; replaces
 * everything else with an underscore. Falls back to ``"strategy"`` when
 * the resulting string is empty.
 */
function sanitiseFilenameToken(value: string): string {
  // eslint-disable-next-line no-control-regex
  const cleaned = value.replace(/[^a-zA-Z0-9._\- ]/g, "_").trim();
  return cleaned || "strategy";
}

/**
 * Fetch the canonical IR JSON for a strategy and trigger a browser download.
 *
 * Pulls the JSON via ``GET /strategies/{strategyId}/ir.json`` (with the
 * shared apiClient interceptors injecting the auth header) and wraps
 * the response body in a ``Blob`` + temporary anchor + click + revoke
 * sequence so the browser's Save dialog opens. Mirrors the
 * ``exportBlotterCsv`` pattern in @/api/run_results so both download
 * surfaces behave identically.
 *
 * Args:
 *   strategyId: ULID of the strategy whose IR to download.
 *   strategyName: Display name; embedded in the suggested filename
 *     (sanitised to remove path separators / quoting characters).
 *
 * Returns:
 *   ``Promise<void>`` — resolves once the browser has been handed the
 *   Blob and the temporary URL has been revoked.
 *
 * Raises:
 *   DownloadIrError on non-2xx responses (404 if the strategy does
 *     not exist; 401/403 on auth failure).
 *   AxiosError on network failure.
 *
 * Example:
 *   try {
 *     await downloadStrategyIr(strategy.id, strategy.name);
 *     setStatus({ kind: "success", message: "IR downloaded." });
 *   } catch (err) {
 *     if (err instanceof DownloadIrError) setStatus({ kind: "error", message: err.message });
 *   }
 */
export async function downloadStrategyIr(
  strategyId: string,
  strategyName: string,
): Promise<void> {
  let response;
  try {
    response = await apiClient.get<Blob>(`/strategies/${strategyId}/ir.json`, {
      responseType: "blob",
    });
  } catch (err) {
    if (err instanceof AxiosError && err.response) {
      const status = err.response.status;
      // axios returns a Blob even on error responses when responseType
      // is "blob"; pull the detail by reading the blob if possible,
      // otherwise fall back to a status-derived message.
      let detail: string | undefined;
      const data = err.response.data as unknown;
      if (data && typeof (data as Blob).text === "function") {
        try {
          const text = await (data as Blob).text();
          const parsed = JSON.parse(text) as { detail?: unknown };
          if (typeof parsed.detail === "string") detail = parsed.detail;
        } catch {
          // Body wasn't a JSON envelope — fall through to status message.
        }
      }
      const message =
        detail ??
        (status === 404
          ? `Strategy ${strategyId} not found`
          : `Failed to download IR (status ${status})`);
      throw new DownloadIrError(message, status, detail);
    }
    throw err;
  }

  const blob = response.data;
  const url = URL.createObjectURL(blob);
  try {
    const anchor = document.createElement("a");
    anchor.href = url;
    anchor.download = `${sanitiseFilenameToken(strategyName)}.strategy_ir.json`;
    anchor.style.display = "none";
    document.body.appendChild(anchor);
    try {
      anchor.click();
    } finally {
      document.body.removeChild(anchor);
    }
  } finally {
    URL.revokeObjectURL(url);
  }
}

/**
 * Restore a soft-archived strategy via ``POST /strategies/{id}/restore``.
 *
 * Inverse of :func:`archiveStrategy`. The backend clears ``archived_at``
 * and bumps ``row_version``; the strategy reappears in the default
 * catalogue immediately.
 *
 * Args:
 *   strategyId: ULID of the strategy to restore.
 *
 * Returns:
 *   The updated :class:`ArchivedStrategy` record carrying
 *   ``archived_at: null`` and a bumped ``row_version``.
 *
 * Raises:
 *   ArchiveStrategyError (statusCode=404) — strategy does not exist.
 *   ArchiveStrategyError (statusCode=409) — strategy is not currently
 *     archived, or a concurrent writer mutated the row.
 *   AxiosError on network failure or other non-2xx HTTP errors.
 */
export async function restoreStrategy(strategyId: string): Promise<ArchivedStrategy> {
  try {
    const resp = await apiClient.post<ArchiveStrategyResponse>(`/strategies/${strategyId}/restore`);
    return resp.data.strategy;
  } catch (err) {
    throw makeArchiveError(err, "Failed to restore strategy", strategyId);
  }
}
