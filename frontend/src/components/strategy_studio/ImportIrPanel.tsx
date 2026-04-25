/**
 * ImportIrPanel — Strategy Studio "Import from file" tab (M2.D1).
 *
 * Purpose:
 *   Provide an in-page upload surface for ``*.strategy_ir.json`` files.
 *   Users either drag-and-drop a file onto the zone or click the
 *   "Browse" button to pick one. On success the panel navigates to
 *   ``/strategy-studio/{strategy_id}``; on a 400 from the backend it
 *   surfaces the Pydantic error path inline.
 *
 * Responsibilities:
 *   - Render a drop target plus a hidden file input wired to a Browse
 *     button. Both flows feed the same ``handleFile`` handler.
 *   - Reject files whose name does not end with ``.strategy_ir.json``
 *     before any network call (cheap client-side guard — the backend
 *     is still authoritative).
 *   - POST the file via :func:`importStrategyIr` (multipart/form-data,
 *     field name ``file``).
 *   - Navigate to ``/strategy-studio/{id}`` on 201.
 *   - Display backend ``detail`` on 400, distinct from upload-in-flight
 *     and unexpected-failure states.
 *
 * Does NOT:
 *   - Validate the IR JSON structure itself (the backend owns the
 *     schema oracle — see services/api/routes/strategies.py).
 *   - Persist the file to disk or local storage.
 *   - Render the resulting strategy detail (M2.D2 owns that view).
 *
 * Dependencies:
 *   - importStrategyIr / ImportIrError from @/api/strategies.
 *   - useNavigate from react-router-dom.
 *
 * Error conditions:
 *   - Wrong extension → inline rejection, no upload attempted.
 *   - Backend 400 → inline error message from ``detail``.
 *   - Network / 5xx → generic "unexpected error" message.
 *
 * Example:
 *   <ImportIrPanel />
 */

import { useCallback, useRef, useState } from "react";
import type { ChangeEvent, DragEvent } from "react";
import { useNavigate } from "react-router-dom";
import { ImportIrError, importStrategyIr } from "@/api/strategies";

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

/** Required filename suffix for IR uploads. */
const IR_FILE_SUFFIX = ".strategy_ir.json";

/** Generic message shown when the backend returns a non-400 failure. */
const GENERIC_FAILURE_MESSAGE = "An unexpected error occurred while importing the strategy IR.";

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

/**
 * ImportIrPanel React component.
 *
 * Stateless from the caller's perspective — internal state covers
 * the dragover highlight, the in-flight upload flag, and the most
 * recent error message.
 */
export function ImportIrPanel(): React.ReactElement {
  const navigate = useNavigate();
  const fileInputRef = useRef<HTMLInputElement>(null);

  const [isDragOver, setIsDragOver] = useState(false);
  const [isUploading, setIsUploading] = useState(false);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);

  // ---- Centralised handler for both drop and Browse paths ----
  const handleFile = useCallback(
    async (file: File) => {
      // Reset any prior error so the user sees the new attempt's outcome.
      setErrorMessage(null);

      // Cheap client-side extension guard. The backend still validates
      // content, but rejecting obviously-wrong files here saves a round
      // trip and gives immediate feedback in the dragover position.
      if (!file.name.endsWith(IR_FILE_SUFFIX)) {
        setErrorMessage(`File must end with "${IR_FILE_SUFFIX}". Got: ${file.name}`);
        return;
      }

      setIsUploading(true);
      try {
        const result = await importStrategyIr(file);
        navigate(`/strategy-studio/${result.strategy.id}`);
      } catch (err) {
        if (err instanceof ImportIrError) {
          // 400 from the backend → show the Pydantic error path the user
          // needs to fix. Falls back to message if detail is somehow blank.
          setErrorMessage(err.detail ?? err.message);
        } else {
          setErrorMessage(GENERIC_FAILURE_MESSAGE);
        }
      } finally {
        setIsUploading(false);
      }
    },
    [navigate],
  );

  // ---- Drop-zone event handlers ----
  const handleDragOver = useCallback((event: DragEvent<HTMLDivElement>) => {
    // preventDefault is required to enable the drop event below.
    event.preventDefault();
    setIsDragOver(true);
  }, []);

  const handleDragLeave = useCallback(() => {
    setIsDragOver(false);
  }, []);

  const handleDrop = useCallback(
    (event: DragEvent<HTMLDivElement>) => {
      event.preventDefault();
      setIsDragOver(false);
      const file = event.dataTransfer.files?.[0];
      if (file) {
        void handleFile(file);
      }
    },
    [handleFile],
  );

  // ---- Browse-button + file input ----
  const handleBrowseClick = useCallback(() => {
    fileInputRef.current?.click();
  }, []);

  const handleFileInputChange = useCallback(
    (event: ChangeEvent<HTMLInputElement>) => {
      const file = event.target.files?.[0];
      if (file) {
        void handleFile(file);
      }
      // Reset the input so re-selecting the same filename re-triggers
      // onChange (browsers suppress duplicate selections otherwise).
      event.target.value = "";
    },
    [handleFile],
  );

  return (
    <div className="space-y-4" data-testid="import-ir-panel">
      <div
        role="button"
        tabIndex={0}
        aria-label="Drop a strategy_ir.json file here, or click Browse to select one"
        onDragOver={handleDragOver}
        onDragLeave={handleDragLeave}
        onDrop={handleDrop}
        data-testid="import-ir-dropzone"
        className={[
          "rounded-lg border-2 border-dashed px-6 py-10 text-center transition-colors",
          isDragOver
            ? "border-brand-500 bg-brand-50"
            : "border-surface-300 bg-surface-50 hover:border-surface-400",
        ].join(" ")}
      >
        <p className="text-sm font-medium text-surface-700">
          Drop a <code className="kbd">{IR_FILE_SUFFIX}</code> file here
        </p>
        <p className="mt-1 text-xs text-surface-500">
          Accepted file extension: <code className="kbd">{IR_FILE_SUFFIX}</code>
        </p>

        <div className="mt-4">
          <button
            type="button"
            onClick={handleBrowseClick}
            disabled={isUploading}
            className="inline-flex items-center rounded-md bg-brand-600 px-4 py-2 text-sm font-medium text-white shadow-sm hover:bg-brand-700 disabled:cursor-not-allowed disabled:bg-surface-300"
            data-testid="import-ir-browse"
          >
            {isUploading ? "Uploading…" : "Browse"}
          </button>
          <input
            ref={fileInputRef}
            type="file"
            accept=".json,application/json"
            onChange={handleFileInputChange}
            className="hidden"
            data-testid="import-ir-file-input"
          />
        </div>
      </div>

      {errorMessage && (
        <div
          role="alert"
          data-testid="import-ir-error"
          className="rounded-md border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700"
        >
          <strong>Import failed:</strong> {errorMessage}
        </div>
      )}
    </div>
  );
}
