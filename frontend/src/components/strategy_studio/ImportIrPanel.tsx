/**
 * ImportIrPanel — Strategy Studio "Import from file" tab (M2.D1) +
 * inline Validate button (post-M2 Validate-IR feature).
 *
 * Purpose:
 *   Provide an in-page upload surface for ``*.strategy_ir.json`` files,
 *   plus a sibling "Validate" affordance that runs the same backend
 *   pipeline WITHOUT persisting so the operator can iterate on a draft
 *   IR before committing to import. Both flows share the same dropzone
 *   and Browse-button surface; the Validate button operates on whichever
 *   file the operator most recently selected.
 *
 * Responsibilities:
 *   - Render a drop target plus a hidden file input wired to a Browse
 *     button. Drop and Browse both feed the same ``selectFile`` handler.
 *   - Show a "Validate" button next to the dropzone that runs the
 *     selected file's contents through ``validateIr`` and renders a
 *     pass / fail panel inline.
 *   - Reject files whose name does not end with ``.strategy_ir.json``
 *     before any network call (cheap client-side guard — the backend
 *     is still authoritative).
 *   - POST the file via :func:`importStrategyIr` (multipart/form-data,
 *     field name ``file``).
 *   - Navigate to ``/strategy-studio/{id}`` on a 201 import.
 *   - Display backend ``detail`` on a 400 import, distinct from upload-
 *     in-flight and unexpected-failure states.
 *   - Disable the Import button while a Validate request is in flight,
 *     and disable Validate while Import is in flight.
 *
 * Does NOT:
 *   - Validate the IR JSON structure itself client-side (the backend
 *     owns the schema oracle — see services/api/routes/strategies.py).
 *   - Persist the file to disk or local storage.
 *   - Render the resulting strategy detail (M2.D2 owns that view).
 *
 * Dependencies:
 *   - importStrategyIr / ImportIrError / validateIr / ValidateIrError
 *     from @/api/strategies.
 *   - useNavigate from react-router-dom.
 *
 * Error conditions:
 *   - Wrong extension → inline rejection, no upload attempted.
 *   - Backend 400 (Import) → inline error message from ``detail``.
 *   - Backend non-2xx (Validate) → inline error message via
 *     ValidateIrError.
 *   - Network / 5xx → generic "unexpected error" message.
 *
 * Example:
 *   <ImportIrPanel />
 */

import { useCallback, useRef, useState } from "react";
import type { ChangeEvent, DragEvent } from "react";
import { useNavigate } from "react-router-dom";
import {
  ImportIrError,
  importStrategyIr,
  validateIr,
  ValidateIrError,
  type StrategyValidationReport,
} from "@/api/strategies";

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

/** Required filename suffix for IR uploads. */
const IR_FILE_SUFFIX = ".strategy_ir.json";

/** Generic message shown when the backend returns a non-400 failure. */
const GENERIC_FAILURE_MESSAGE = "An unexpected error occurred while importing the strategy IR.";

/** Generic message shown when validateIr fails for non-network reasons. */
const GENERIC_VALIDATE_FAILURE_MESSAGE =
  "An unexpected error occurred while validating the strategy IR.";

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

/**
 * ImportIrPanel React component.
 *
 * Stateless from the caller's perspective — internal state covers
 * the dragover highlight, the in-flight upload / validate flags, the
 * most recent error message, the most recent file the operator
 * selected, and the most recent validation report.
 */
export function ImportIrPanel(): React.ReactElement {
  const navigate = useNavigate();
  const fileInputRef = useRef<HTMLInputElement>(null);

  const [isDragOver, setIsDragOver] = useState(false);
  const [isUploading, setIsUploading] = useState(false);
  const [isValidating, setIsValidating] = useState(false);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  /**
   * The most recently selected file. Both Validate and the auto-import
   * path consume it. Persisted at the panel level so the operator can
   * click Validate after dropping, then click Import (or vice versa)
   * without re-selecting.
   */
  const [selectedFile, setSelectedFile] = useState<File | null>(null);
  /**
   * Most recent validation result. ``null`` when no validation has
   * been attempted yet on the current file. The shape is the backend
   * report verbatim so the renderer can surface every issue field.
   */
  const [validationReport, setValidationReport] = useState<StrategyValidationReport | null>(
    null,
  );

  // ---- Centralised import handler. Persists via importStrategyIr. ----
  const importFile = useCallback(
    async (file: File) => {
      setErrorMessage(null);
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

  // ---- File-acceptance handler. Validates the extension + stages the
  //      file, then auto-imports. The auto-import-on-drop UX has shipped
  //      since M2.D1; the explicit Import button below covers the
  //      "validated, edited, ready to import" loop where the operator
  //      no longer wants to re-drop the file.
  const handleFile = useCallback(
    (file: File) => {
      // Reset any prior error / report so the user sees the new attempt's outcome.
      setErrorMessage(null);
      setValidationReport(null);

      // Cheap client-side extension guard. The backend still validates
      // content, but rejecting obviously-wrong files here saves a round
      // trip and gives immediate feedback in the dragover position.
      if (!file.name.endsWith(IR_FILE_SUFFIX)) {
        setErrorMessage(`File must end with "${IR_FILE_SUFFIX}". Got: ${file.name}`);
        return;
      }

      setSelectedFile(file);
      void importFile(file);
    },
    [importFile],
  );


  // ---- Validate-only path. Reads the selected file and runs validateIr. ----
  const handleValidate = useCallback(async () => {
    if (!selectedFile) {
      setErrorMessage(`No file selected. Drop a ${IR_FILE_SUFFIX} file or click Browse first.`);
      return;
    }
    setErrorMessage(null);
    setValidationReport(null);
    setIsValidating(true);
    try {
      const text = await selectedFile.text();
      const report = await validateIr(text);
      setValidationReport(report);
    } catch (err) {
      if (err instanceof ValidateIrError) {
        setErrorMessage(err.detail ?? err.message);
      } else {
        setErrorMessage(GENERIC_VALIDATE_FAILURE_MESSAGE);
      }
    } finally {
      setIsValidating(false);
    }
  }, [selectedFile]);

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

        <div className="mt-4 flex flex-wrap items-center justify-center gap-2">
          <button
            type="button"
            onClick={handleBrowseClick}
            disabled={isUploading || isValidating}
            className="inline-flex items-center rounded-md bg-brand-600 px-4 py-2 text-sm font-medium text-white shadow-sm hover:bg-brand-700 disabled:cursor-not-allowed disabled:bg-surface-300"
            data-testid="import-ir-browse"
          >
            {isUploading ? "Uploading…" : "Browse"}
          </button>
          {/*
           * Validate button — runs the no-save validation pipeline
           * against the most recently selected file. Disabled while
           * either flow is in flight or no file has been selected yet
           * so the operator never triggers a validate against stale
           * input.
           */}
          <button
            type="button"
            onClick={() => void handleValidate()}
            disabled={isValidating || isUploading || !selectedFile}
            className="inline-flex items-center rounded-md border border-surface-300 bg-white px-4 py-2 text-sm font-medium text-surface-700 shadow-sm hover:bg-surface-50 disabled:cursor-not-allowed disabled:bg-surface-100 disabled:text-surface-400"
            data-testid="import-ir-validate"
          >
            {isValidating ? "Validating…" : "Validate"}
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
        {selectedFile && (
          <p className="mt-3 text-xs text-surface-500" data-testid="import-ir-selected-file">
            Selected: <span className="font-mono">{selectedFile.name}</span>
          </p>
        )}
      </div>

      {errorMessage && (
        <div
          role="alert"
          data-testid="import-ir-error"
          className="rounded-md border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700"
        >
          <strong>Failed:</strong> {errorMessage}
        </div>
      )}

      {validationReport && validationReport.valid && (
        <div
          role="status"
          data-testid="import-ir-validate-success"
          className="rounded-md border border-green-200 bg-green-50 px-4 py-3 text-sm text-green-800"
        >
          <strong>IR is valid.</strong>
          {(() => {
            // Surface the parsed strategy name + symbols inline so the
            // operator can confirm the file resolved to the strategy
            // they expected. Defensive optional chaining: parsed_ir is
            // typed Record<string, unknown> so we narrow each lookup.
            const ir = validationReport.parsed_ir;
            if (!ir) return null;
            const metadata = ir.metadata as { strategy_name?: unknown } | undefined;
            const name = typeof metadata?.strategy_name === "string" ? metadata.strategy_name : null;
            const universe = ir.universe as { symbols?: unknown } | undefined;
            const symbols = Array.isArray(universe?.symbols)
              ? (universe!.symbols as unknown[]).filter((s): s is string => typeof s === "string")
              : [];
            return (
              <dl className="mt-2 grid grid-cols-1 gap-1 text-xs sm:grid-cols-2">
                {name && (
                  <div>
                    <dt className="font-medium uppercase tracking-wider text-green-700">
                      Strategy
                    </dt>
                    <dd className="mt-0.5 font-mono">{name}</dd>
                  </div>
                )}
                {symbols.length > 0 && (
                  <div>
                    <dt className="font-medium uppercase tracking-wider text-green-700">
                      Symbols
                    </dt>
                    <dd className="mt-0.5 font-mono">{symbols.join(", ")}</dd>
                  </div>
                )}
              </dl>
            );
          })()}
        </div>
      )}

      {validationReport && !validationReport.valid && (
        <div
          role="alert"
          data-testid="import-ir-validate-failure"
          className="rounded-md border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700"
        >
          <strong>IR is not valid.</strong>
          <p className="mt-1 text-xs text-red-600">
            {validationReport.errors.length} error
            {validationReport.errors.length === 1 ? "" : "s"} detected.
          </p>
          <ul
            className="mt-2 space-y-1 text-xs"
            data-testid="import-ir-validate-error-list"
          >
            {validationReport.errors.map((issue, idx) => (
              <li
                key={`${issue.path}-${idx}`}
                data-testid="import-ir-validate-error-row"
                className="rounded border border-red-100 bg-white px-2 py-1 text-red-700"
              >
                <span className="font-mono">{issue.path}</span>{" "}
                <span className="rounded bg-red-100 px-1 text-[10px] font-medium uppercase text-red-800">
                  {issue.code}
                </span>{" "}
                <span>{issue.message}</span>
              </li>
            ))}
          </ul>
          {validationReport.warnings.length > 0 && (
            <>
              <p
                className="mt-3 text-xs font-medium text-amber-700"
                data-testid="import-ir-validate-warning-header"
              >
                {validationReport.warnings.length} warning
                {validationReport.warnings.length === 1 ? "" : "s"}:
              </p>
              <ul className="mt-1 space-y-1 text-xs">
                {validationReport.warnings.map((issue, idx) => (
                  <li
                    key={`warn-${issue.path}-${idx}`}
                    data-testid="import-ir-validate-warning-row"
                    className="rounded border border-amber-100 bg-amber-50 px-2 py-1 text-amber-800"
                  >
                    <span className="font-mono">{issue.path}</span>{" "}
                    <span className="rounded bg-amber-100 px-1 text-[10px] font-medium uppercase">
                      {issue.code}
                    </span>{" "}
                    <span>{issue.message}</span>
                  </li>
                ))}
              </ul>
            </>
          )}
        </div>
      )}
    </div>
  );
}
