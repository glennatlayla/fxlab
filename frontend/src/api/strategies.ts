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
