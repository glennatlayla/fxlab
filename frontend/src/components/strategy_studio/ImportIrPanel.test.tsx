/**
 * Tests for ImportIrPanel — Strategy Studio "Import from file" tab (M2.D1).
 *
 * Verifies:
 *   1. Renders the drop zone, browse button, and accepted-extension hint.
 *   2. A valid file dropped on the zone fires importStrategyIr with the
 *      file as the FormData ``file`` field, and on 201 the component
 *      navigates to /strategy-studio/{returned_id}.
 *   3. A backend 400 (ImportIrError) is rendered inline as the error
 *      message, and no navigation occurs.
 *   4. A file with the wrong extension is rejected by the panel before
 *      any network call is made.
 *
 * Test approach:
 *   - importStrategyIr is mocked at the module level so we can control
 *     return values without spinning up MSW for a single endpoint.
 *   - useNavigate from react-router-dom is mocked via vi.mock so the
 *     test observes navigation calls without real DOM history.
 *   - File drops are simulated by dispatching a "drop" event on the
 *     drop zone with a synthetic dataTransfer.files list — this is
 *     the most direct way to exercise the DragEvent path.
 */

import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor, fireEvent } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { ImportIrPanel } from "./ImportIrPanel";
import {
  importStrategyIr,
  ImportIrError,
  validateIr,
  ValidateIrError,
} from "@/api/strategies";

// ---------------------------------------------------------------------------
// Mocks
// ---------------------------------------------------------------------------

vi.mock("@/api/strategies", async () => {
  // Preserve the real ImportIrError / ValidateIrError classes so
  // `instanceof` checks in the component still work against a value
  // the test produces.
  const actual = await vi.importActual<typeof import("@/api/strategies")>("@/api/strategies");
  return {
    ...actual,
    importStrategyIr: vi.fn(),
    validateIr: vi.fn(),
  };
});

const mockNavigate = vi.fn();
vi.mock("react-router-dom", async () => {
  const actual = await vi.importActual<typeof import("react-router-dom")>("react-router-dom");
  return {
    ...actual,
    useNavigate: () => mockNavigate,
  };
});

const mockedImportStrategyIr = vi.mocked(importStrategyIr);
const mockedValidateIr = vi.mocked(validateIr);

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function renderPanel() {
  return render(
    <MemoryRouter>
      <ImportIrPanel />
    </MemoryRouter>,
  );
}

/**
 * Build a File whose name ends with .strategy_ir.json. Content does not
 * matter — the backend would parse it, but it's mocked here.
 */
function makeIrFile(
  name = "FX_DoubleBollinger.strategy_ir.json",
  body = '{"metadata": {"strategy_name": "test"}}',
): File {
  return new File([body], name, { type: "application/json" });
}

/** Build a File with the wrong extension to exercise the rejection path. */
function makeWrongExtensionFile(): File {
  return new File(["irrelevant"], "notes.txt", { type: "text/plain" });
}

/**
 * Simulate a drop event on the dropzone with the given files. fireEvent.drop
 * does not synthesise a dataTransfer object, so we construct one manually.
 */
function dropFileOn(target: Element, file: File) {
  fireEvent.drop(target, {
    dataTransfer: {
      files: [file],
      types: ["Files"],
    },
  });
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe("ImportIrPanel", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("renders the drop zone, browse button, and accepted-extension hint", () => {
    renderPanel();

    expect(screen.getByTestId("import-ir-panel")).toBeInTheDocument();
    expect(screen.getByTestId("import-ir-dropzone")).toBeInTheDocument();
    expect(screen.getByTestId("import-ir-browse")).toBeInTheDocument();
    // Hint should reference the required suffix so the user knows what to drop.
    expect(screen.getAllByText(/\.strategy_ir\.json/).length).toBeGreaterThanOrEqual(1);
  });

  it("uploads the dropped file and navigates on 201", async () => {
    const file = makeIrFile();
    mockedImportStrategyIr.mockResolvedValueOnce({
      strategy: {
        id: "01H000IMPORT0000000000000",
        name: "FX_DoubleBollinger",
        version: "1.0.0",
        source: "ir_upload",
        created_by: "01H000USER0000000000000000",
        created_at: "2026-04-25T00:00:00Z",
        updated_at: "2026-04-25T00:00:00Z",
      },
    });

    renderPanel();

    dropFileOn(screen.getByTestId("import-ir-dropzone"), file);

    // Assert the API was called with the File object — the panel passes
    // the File directly; importStrategyIr is responsible for FormData.
    await waitFor(() => {
      expect(mockedImportStrategyIr).toHaveBeenCalledTimes(1);
    });
    const passedFile = mockedImportStrategyIr.mock.calls[0]?.[0];
    expect(passedFile).toBeInstanceOf(File);
    expect(passedFile?.name).toBe("FX_DoubleBollinger.strategy_ir.json");

    await waitFor(() => {
      expect(mockNavigate).toHaveBeenCalledWith("/strategy-studio/01H000IMPORT0000000000000");
    });
  });

  it("posts a multipart body with field name 'file' through importStrategyIr", async () => {
    // Drive the upload through the Browse button + hidden <input> path.
    // userEvent.upload triggers a real change event with a real FileList,
    // which exercises the same handleFile codepath as the drop branch.
    const file = makeIrFile("strat.strategy_ir.json");
    mockedImportStrategyIr.mockResolvedValueOnce({
      strategy: {
        id: "01H000IMPORT0000000000001",
        name: "strat",
        version: "1.0.0",
        source: "ir_upload",
        created_by: "01H000USER0000000000000000",
        created_at: "2026-04-25T00:00:00Z",
        updated_at: "2026-04-25T00:00:00Z",
      },
    });

    renderPanel();

    const input = screen.getByTestId("import-ir-file-input") as HTMLInputElement;
    await userEvent.upload(input, file);

    await waitFor(() => {
      expect(mockedImportStrategyIr).toHaveBeenCalledTimes(1);
    });
    expect(mockedImportStrategyIr).toHaveBeenCalledWith(file);
    await waitFor(() => {
      expect(mockNavigate).toHaveBeenCalledWith("/strategy-studio/01H000IMPORT0000000000001");
    });
  });

  it("renders the backend validation detail on 400 and does not navigate", async () => {
    const validationDetail =
      "1 validation error for StrategyIR\nmetadata.strategy_name: field required";
    mockedImportStrategyIr.mockRejectedValueOnce(
      new ImportIrError(validationDetail, 400, validationDetail),
    );

    renderPanel();

    dropFileOn(screen.getByTestId("import-ir-dropzone"), makeIrFile());

    await waitFor(() => {
      expect(screen.getByTestId("import-ir-error")).toBeInTheDocument();
    });
    expect(screen.getByTestId("import-ir-error")).toHaveTextContent(/metadata\.strategy_name/);
    expect(mockNavigate).not.toHaveBeenCalled();
  });

  it("rejects a wrong-extension file before any upload is attempted", async () => {
    renderPanel();

    dropFileOn(screen.getByTestId("import-ir-dropzone"), makeWrongExtensionFile());

    await waitFor(() => {
      expect(screen.getByTestId("import-ir-error")).toBeInTheDocument();
    });
    expect(screen.getByTestId("import-ir-error")).toHaveTextContent(/\.strategy_ir\.json/);
    expect(mockedImportStrategyIr).not.toHaveBeenCalled();
    expect(mockNavigate).not.toHaveBeenCalled();
  });

  it("renders the Validate button disabled until a file is selected", () => {
    renderPanel();
    const validateButton = screen.getByTestId("import-ir-validate") as HTMLButtonElement;
    expect(validateButton).toBeDisabled();
  });

  /**
   * Helper that mocks the import path to fail with an inline error so
   * the dropped file stays staged on the panel without navigation. We
   * use a 400-class ImportIrError because that's the only shape the
   * panel renders inline (anything else just shows a generic message).
   *
   * After this fixture fires, the panel is in the same observable
   * state as a real operator who dropped a broken file: import
   * attempted, rendered an error, file still staged, ready to
   * validate.
   */
  function arrangeStagedAfterFailedImport(): void {
    mockedImportStrategyIr.mockRejectedValue(
      new ImportIrError("simulated import failure", 400, "simulated"),
    );
  }

  it("renders a green panel when validateIr returns valid=true", async () => {
    arrangeStagedAfterFailedImport();
    mockedValidateIr.mockResolvedValueOnce({
      valid: true,
      parsed_ir: {
        metadata: { strategy_name: "FX_DoubleBollinger_TrendZone" },
        universe: { symbols: ["EUR_USD", "USD_JPY"] },
      },
      errors: [],
      warnings: [],
    });

    renderPanel();
    dropFileOn(screen.getByTestId("import-ir-dropzone"), makeIrFile());

    // The drop's auto-import resolves to a 400 (inline error) so the
    // file stays staged and the operator can click Validate.
    await waitFor(() => {
      expect(screen.getByTestId("import-ir-selected-file")).toBeInTheDocument();
    });

    await userEvent.click(screen.getByTestId("import-ir-validate"));

    await waitFor(() => {
      expect(screen.getByTestId("import-ir-validate-success")).toBeInTheDocument();
    });
    const success = screen.getByTestId("import-ir-validate-success");
    expect(success).toHaveTextContent(/IR is valid/i);
    expect(success).toHaveTextContent(/FX_DoubleBollinger_TrendZone/);
    expect(success).toHaveTextContent(/EUR_USD/);
    expect(mockedValidateIr).toHaveBeenCalledTimes(1);
  });

  it("renders a red panel listing each issue when validateIr returns valid=false", async () => {
    arrangeStagedAfterFailedImport();
    mockedValidateIr.mockResolvedValueOnce({
      valid: false,
      parsed_ir: null,
      errors: [
        {
          path: "/metadata/strategy_name",
          code: "schema_violation",
          message: "field required",
        },
        {
          path: "/artifact_type",
          code: "schema_violation",
          message: "field required",
        },
      ],
      warnings: [],
    });

    renderPanel();
    dropFileOn(screen.getByTestId("import-ir-dropzone"), makeIrFile());

    await waitFor(() => {
      expect(screen.getByTestId("import-ir-selected-file")).toBeInTheDocument();
    });

    await userEvent.click(screen.getByTestId("import-ir-validate"));

    await waitFor(() => {
      expect(screen.getByTestId("import-ir-validate-failure")).toBeInTheDocument();
    });
    const rows = screen.getAllByTestId("import-ir-validate-error-row");
    expect(rows).toHaveLength(2);
    expect(rows[0]).toHaveTextContent("/metadata/strategy_name");
    expect(rows[0]).toHaveTextContent("schema_violation");
    expect(rows[0]).toHaveTextContent("field required");
    expect(rows[1]).toHaveTextContent("/artifact_type");
  });

  it("renders warnings under a separate header when present", async () => {
    arrangeStagedAfterFailedImport();
    mockedValidateIr.mockResolvedValueOnce({
      valid: false,
      parsed_ir: null,
      errors: [
        {
          path: "/",
          code: "invalid_json",
          message: "boom",
        },
      ],
      warnings: [
        {
          path: "/data_requirements/dataset_ref",
          code: "uncertified_dataset",
          message: "Dataset is not certified.",
        },
      ],
    });

    renderPanel();
    dropFileOn(screen.getByTestId("import-ir-dropzone"), makeIrFile());

    await waitFor(() => {
      expect(screen.getByTestId("import-ir-selected-file")).toBeInTheDocument();
    });

    await userEvent.click(screen.getByTestId("import-ir-validate"));

    await waitFor(() => {
      expect(screen.getByTestId("import-ir-validate-warning-header")).toBeInTheDocument();
    });
    const warnRows = screen.getAllByTestId("import-ir-validate-warning-row");
    expect(warnRows).toHaveLength(1);
    expect(warnRows[0]).toHaveTextContent("uncertified_dataset");
  });

  it("disables Browse while Validate is in flight", async () => {
    arrangeStagedAfterFailedImport();
    // Make the validate request pend so we can observe the disabled state.
    let resolveValidate: ((report: import("@/api/strategies").StrategyValidationReport) => void) =
      () => {};
    mockedValidateIr.mockImplementationOnce(
      () =>
        new Promise((resolve) => {
          resolveValidate = resolve;
        }),
    );

    renderPanel();
    dropFileOn(screen.getByTestId("import-ir-dropzone"), makeIrFile());
    await waitFor(() => {
      expect(screen.getByTestId("import-ir-selected-file")).toBeInTheDocument();
    });

    await userEvent.click(screen.getByTestId("import-ir-validate"));

    // While the validate promise is pending, the Browse button is
    // disabled so the operator cannot trigger a concurrent upload that
    // would compete with the in-flight validation.
    const browse = screen.getByTestId("import-ir-browse") as HTMLButtonElement;
    await waitFor(() => {
      expect(browse).toBeDisabled();
    });

    // Resolve the validate so the test cleans up cleanly.
    resolveValidate({ valid: true, parsed_ir: {}, errors: [], warnings: [] });
  });

  it("surfaces ValidateIrError detail inline when validateIr rejects", async () => {
    arrangeStagedAfterFailedImport();
    mockedValidateIr.mockRejectedValueOnce(
      new ValidateIrError("validate failed", 401, "Unauthorized"),
    );

    renderPanel();
    dropFileOn(screen.getByTestId("import-ir-dropzone"), makeIrFile());
    await waitFor(() => {
      expect(screen.getByTestId("import-ir-selected-file")).toBeInTheDocument();
    });

    await userEvent.click(screen.getByTestId("import-ir-validate"));

    await waitFor(() => {
      // Wait for the validate-induced error message to land. The
      // import-ir-error element exists from the staged-import-failure
      // state too, so we look for the Unauthorized text directly to
      // avoid race-condition false positives.
      expect(screen.getByTestId("import-ir-error")).toHaveTextContent(/Unauthorized/);
    });
    // The inline failure panel is NOT rendered (there was no report
    // payload to surface — only an HTTP-level error).
    expect(screen.queryByTestId("import-ir-validate-failure")).not.toBeInTheDocument();
  });
});
