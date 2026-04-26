/**
 * Dataset catalog API client (M4.E3 admin browse + register page).
 *
 * Purpose:
 *   Typed wrapper around the M4.E3 admin endpoints under
 *   ``/datasets/`` for the ``/admin/datasets`` page:
 *     - ``GET /datasets/`` — paginated list with optional filters.
 *     - ``POST /datasets/`` — register a new dataset.
 *     - ``PATCH /datasets/{ref}`` — toggle certification or version.
 *
 * Responsibilities:
 *   - Build typed parameter / body objects for each endpoint.
 *   - Surface server-side errors as a typed :class:`DatasetsApiError`
 *     so the UI can render the backend ``detail`` string without
 *     parsing AxiosError generics.
 *
 * Does NOT:
 *   - Validate inputs locally — Pydantic on the backend is the oracle.
 *   - Hold React state.
 *
 * Dependencies:
 *   - @/api/client (the shared axios instance with auth injection).
 */

import { AxiosError } from "axios";
import { apiClient } from "@/api/client";

// ---------------------------------------------------------------------------
// Types — mirror the backend Pydantic shapes
// ---------------------------------------------------------------------------

/**
 * One row in the paginated catalog list.
 *
 * Mirrors ``libs.contracts.dataset.DatasetListItem``.
 */
export interface DatasetListItem {
  /** ULID primary key. */
  id: string;
  /** Catalog reference key (UNIQUE). */
  dataset_ref: string;
  /** Symbols covered by the dataset. */
  symbols: string[];
  /** Bar resolution (e.g. ``"15m"``, ``"1h"``). */
  timeframe: string;
  /** Provenance tag (e.g. ``"oanda"``, ``"alpaca"``). */
  source: string;
  /** Catalog version string. */
  version: string;
  /** Whether the dataset has cleared the certification gate. */
  is_certified: boolean;
  /** ULID of the registering user, or null for bootstrap seeds. */
  created_by: string | null;
  /** ISO-8601 insert timestamp (or null). */
  created_at: string | null;
  /** ISO-8601 last-update timestamp (or null). */
  updated_at: string | null;
}

/** Paginated envelope returned by ``GET /datasets/``. */
export interface PagedDatasets {
  datasets: DatasetListItem[];
  page: number;
  page_size: number;
  total_count: number;
  total_pages: number;
}

/** Optional filters accepted by :func:`listDatasets`. */
export interface ListDatasetsOptions {
  /** Filter by exact provenance tag. */
  source?: string;
  /** Filter by certification flag. */
  is_certified?: boolean;
  /** Case-insensitive substring search on ``dataset_ref``. */
  q?: string;
}

/** Request body for ``POST /datasets/``. */
export interface RegisterDatasetRequest {
  dataset_ref: string;
  symbols: string[];
  timeframe: string;
  source: string;
  version: string;
  is_certified?: boolean;
}

/** Request body for ``PATCH /datasets/{ref}``. */
export interface UpdateDatasetRequest {
  is_certified?: boolean;
  version?: string;
}

// ---------------------------------------------------------------------------
// Detail-page types — mirror libs.contracts.dataset.DatasetDetail
// ---------------------------------------------------------------------------

/**
 * One row in the dataset Detail page's bar-inventory section.
 *
 * Mirrors :class:`libs.contracts.dataset.BarInventoryRow`.
 */
export interface BarInventoryRow {
  /** Symbol the row applies to. */
  symbol: string;
  /** Bar resolution string. */
  timeframe: string;
  /** Number of candle bars stored for this pair. */
  row_count: number;
  /** ISO-8601 timestamp of oldest bar, or null when row_count == 0. */
  min_ts: string | null;
  /** ISO-8601 timestamp of newest bar, or null when row_count == 0. */
  max_ts: string | null;
}

/**
 * One entry in the dataset Detail page's Strategies-using section.
 *
 * Mirrors :class:`libs.contracts.dataset.StrategyRef`.
 */
export interface StrategyRef {
  /** ULID of the strategy. */
  strategy_id: string;
  /** Display name (may be empty if the strategy row has been deleted). */
  name: string;
  /** ISO-8601 timestamp of the most recent completed run, or null. */
  last_used_at: string | null;
}

/**
 * One entry in the dataset Detail page's Recent-runs section.
 *
 * Mirrors :class:`libs.contracts.dataset.RecentRunRef`.
 */
export interface RecentRunRef {
  /** ULID of the research run. */
  run_id: string;
  /** ULID of the strategy the run targets. */
  strategy_id: string;
  /** Lifecycle status string. */
  status: string;
  /** ISO-8601 timestamp of completion, or null when still in flight. */
  completed_at: string | null;
}

/**
 * Top-level envelope for the dataset Detail page.
 *
 * Mirrors :class:`libs.contracts.dataset.DatasetDetail`.
 */
export interface DatasetDetail {
  dataset_ref: string;
  dataset_id: string;
  symbols: string[];
  timeframe: string;
  source: string;
  version: string;
  is_certified: boolean;
  created_at: string | null;
  updated_at: string | null;
  bar_inventory: BarInventoryRow[];
  strategies_using: StrategyRef[];
  recent_runs: RecentRunRef[];
}

/**
 * Typed error for /datasets/ endpoint failures.
 *
 * Carries the HTTP status and the backend ``detail`` string so the UI
 * can distinguish 404 / 422 / 401 without parsing free-form messages.
 */
export class DatasetsApiError extends Error {
  constructor(
    message: string,
    public readonly statusCode?: number,
    public readonly detail?: string,
  ) {
    super(message);
    this.name = "DatasetsApiError";
  }
}

function wrapAxiosError(err: unknown, fallback: string): never {
  if (err instanceof AxiosError && err.response) {
    const detailRaw = err.response.data?.detail;
    const detail = typeof detailRaw === "string" ? detailRaw : fallback;
    throw new DatasetsApiError(detail, err.response.status, detail);
  }
  throw err;
}

// ---------------------------------------------------------------------------
// Endpoint clients
// ---------------------------------------------------------------------------

/**
 * Fetch one page of the datasets catalog.
 *
 * Args:
 *   page: 1-based page index.
 *   page_size: Datasets per page (capped at 200 server-side).
 *   opts: Optional filters.
 *
 * Returns:
 *   :class:`PagedDatasets` envelope ready for the catalog grid.
 *
 * Raises:
 *   :class:`DatasetsApiError` on non-2xx responses.
 */
export async function listDatasets(
  page: number,
  page_size: number,
  opts?: ListDatasetsOptions,
): Promise<PagedDatasets> {
  const params: Record<string, string | boolean> = {
    page: String(page),
    page_size: String(page_size),
  };
  if (opts?.source) params.source = opts.source;
  if (opts?.is_certified !== undefined) params.is_certified = opts.is_certified;
  if (opts?.q && opts.q.trim()) params.q = opts.q.trim();

  try {
    const resp = await apiClient.get<PagedDatasets>("/datasets/", { params });
    return resp.data;
  } catch (err) {
    wrapAxiosError(err, "Failed to load datasets");
  }
}

/**
 * Register (or upsert) a dataset entry.
 *
 * Returns:
 *   The persisted :class:`DatasetListItem` (with timestamps populated
 *   on a fresh insert).
 *
 * Raises:
 *   :class:`DatasetsApiError` on non-2xx responses.
 */
export async function registerDataset(body: RegisterDatasetRequest): Promise<DatasetListItem> {
  try {
    const resp = await apiClient.post<DatasetListItem>("/datasets/", body);
    return resp.data;
  } catch (err) {
    wrapAxiosError(err, "Failed to register dataset");
  }
}

/**
 * Update is_certified and/or version on an existing dataset row.
 *
 * Returns:
 *   The updated :class:`DatasetListItem`.
 *
 * Raises:
 *   :class:`DatasetsApiError` on non-2xx responses (404 if the ref is
 *   not registered, 422 if both fields are omitted).
 */
export async function updateDataset(
  dataset_ref: string,
  body: UpdateDatasetRequest,
): Promise<DatasetListItem> {
  try {
    const resp = await apiClient.patch<DatasetListItem>(
      `/datasets/${encodeURIComponent(dataset_ref)}`,
      body,
    );
    return resp.data;
  } catch (err) {
    wrapAxiosError(err, "Failed to update dataset");
  }
}

/**
 * Fetch the rich :class:`DatasetDetail` envelope for a single
 * registered dataset. Powers the ``/admin/datasets/:ref`` page.
 *
 * Args:
 *   ref: Catalog reference key (will be percent-encoded for the URL).
 *
 * Returns:
 *   :class:`DatasetDetail` populated with header metadata, bar
 *   inventory, strategies-using, and recent runs.
 *
 * Raises:
 *   :class:`DatasetsApiError` on non-2xx responses (404 if the ref is
 *   not registered, 401/403 on auth failure).
 */
export async function getDatasetDetail(ref: string): Promise<DatasetDetail> {
  try {
    const resp = await apiClient.get<DatasetDetail>(`/datasets/${encodeURIComponent(ref)}/detail`);
    return resp.data;
  } catch (err) {
    wrapAxiosError(err, "Failed to load dataset detail");
  }
}
