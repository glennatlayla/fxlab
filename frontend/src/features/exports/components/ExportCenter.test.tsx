/**
 * Tests for ExportCenter.
 *
 * Covers:
 *   - Renders format selector (CSV, JSON, Parquet).
 *   - Metadata preview shows run_id, export_schema_version, override watermarks.
 *   - Clicking export triggers createExport API call.
 *   - Shows in-progress/pending state while export is processing.
 *   - Shows download link when export is complete.
 *   - Override watermark IDs visible when present.
 */

import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

vi.mock("../api", () => ({
  exportsApi: {
    createExport: vi.fn(),
    getExport: vi.fn(),
  },
}));
vi.mock("../logger", () => ({
  exportsLogger: {
    pageMount: vi.fn(),
    pageUnmount: vi.fn(),
  },
}));

import { exportsApi } from "../api";
import { ExportCenter } from "./ExportCenter";

const mockCreateExport = exportsApi.createExport as ReturnType<typeof vi.fn>;
const mockGetExport = exportsApi.getExport as ReturnType<typeof vi.fn>;

const ISO = "2026-04-06T12:00:00.000Z";

function makeExportJob(id: string, status: string, artifactUri?: string) {
  return {
    id,
    export_type: "runs",
    object_id: "run-123",
    status,
    artifact_uri: artifactUri || null,
    requested_by: "user@example.com",
    created_at: ISO,
    updated_at: ISO,
    override_watermark: null,
  };
}

function renderCenter(runId = "run-123", overrideWatermarks?: string[]) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <ExportCenter runId={runId} overrideWatermarks={overrideWatermarks} />
    </QueryClientProvider>,
  );
}

describe("ExportCenter", () => {
  beforeEach(() => {
    vi.resetAllMocks();
  });

  it("renders format selector with CSV, JSON, Parquet options", () => {
    renderCenter();

    expect(screen.getByTestId("export-format-selector")).toBeInTheDocument();
    expect(screen.getByLabelText(/csv/i)).toBeInTheDocument();
    expect(screen.getByLabelText(/json/i)).toBeInTheDocument();
    expect(screen.getByLabelText(/parquet/i)).toBeInTheDocument();
  });

  it("displays metadata preview with run_id and schema version", () => {
    renderCenter("run-456");

    expect(screen.getByTestId("export-metadata-preview")).toBeInTheDocument();
    expect(screen.getByText(/run-456/)).toBeInTheDocument();
    expect(screen.getByTestId("export-schema-version")).toBeInTheDocument();
  });

  it("shows override watermark IDs when present", () => {
    const watermarks = ["wm-001", "wm-002"];
    renderCenter("run-123", watermarks);

    const watermarkSection = screen.getByTestId("export-override-watermarks");
    expect(watermarkSection).toBeInTheDocument();
    expect(watermarkSection).toHaveTextContent("wm-001");
    expect(watermarkSection).toHaveTextContent("wm-002");
  });

  it("triggers createExport API call on export button click", async () => {
    mockCreateExport.mockResolvedValueOnce(makeExportJob("export-001", "processing"));
    mockGetExport.mockResolvedValueOnce(
      makeExportJob("export-001", "complete", "s3://bucket/export.zip"),
    );

    renderCenter("run-123");

    expect(screen.getByTestId("export-button")).toBeEnabled();
    fireEvent.click(screen.getByTestId("export-button"));

    await waitFor(() => {
      expect(mockCreateExport).toHaveBeenCalledWith(
        "runs",
        "run-123",
        expect.any(String),
        expect.any(Object),
      );
    });
  });

  it("shows in-progress spinner while export is processing", async () => {
    mockCreateExport.mockResolvedValueOnce(makeExportJob("export-001", "processing"));

    renderCenter("run-123");
    fireEvent.click(screen.getByTestId("export-button"));

    await waitFor(() => {
      expect(screen.getByTestId("export-progress-spinner")).toBeInTheDocument();
    });
  });

  it("shows download link when export is complete", async () => {
    mockCreateExport.mockResolvedValueOnce(makeExportJob("export-001", "processing"));
    mockGetExport.mockResolvedValueOnce(
      makeExportJob("export-001", "complete", "s3://bucket/export.zip"),
    );

    renderCenter("run-123");
    fireEvent.click(screen.getByTestId("export-button"));

    await waitFor(() => {
      expect(screen.getByTestId("export-download-button")).toBeInTheDocument();
    });
    expect(screen.getByTestId("export-download-button")).not.toBeDisabled();
  });

  it("disables export button while export is in progress", async () => {
    mockCreateExport.mockResolvedValueOnce(makeExportJob("export-001", "processing"));

    renderCenter("run-123");
    fireEvent.click(screen.getByTestId("export-button"));

    await waitFor(() => {
      expect(screen.getByTestId("export-button")).toBeDisabled();
    });
  });

  it("shows error message on export failure", async () => {
    const error = new Error("Network error");
    mockCreateExport.mockRejectedValueOnce(error);

    renderCenter("run-123");
    fireEvent.click(screen.getByTestId("export-button"));

    await waitFor(() => {
      expect(screen.getByTestId("export-error-message")).toBeInTheDocument();
    });
    expect(screen.getByTestId("export-error-message")).toHaveTextContent(/network error/i);
  });
});
