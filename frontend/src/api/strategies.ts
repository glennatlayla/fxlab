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
