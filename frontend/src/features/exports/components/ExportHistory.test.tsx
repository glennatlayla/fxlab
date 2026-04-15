/**
 * Tests for ExportHistory.
 *
 * Covers:
 *   - Loading state.
 *   - Renders table of prior exports with schema_version, format, status badge, download link.
 *   - Error state with Retry.
 *   - Empty state.
 *   - Complete export shows download link; pending/processing do not.
 */

import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

vi.mock("../api", () => ({
  exportsApi: {
    listExports: vi.fn(),
  },
}));
vi.mock("../logger", () => ({
  exportsLogger: {
    pageMount: vi.fn(),
    pageUnmount: vi.fn(),
  },
}));

import { exportsApi } from "../api";
import { ExportHistory } from "./ExportHistory";

const mockListExports = exportsApi.listExports as ReturnType<typeof vi.fn>;

const ISO = "2026-04-06T12:00:00.000Z";

function makeExport(id: string, status: string, artifactUri?: string) {
  return {
    id,
    export_type: "trades",
    object_id: "run-123",
    status,
    artifact_uri: artifactUri || null,
    requested_by: "user@example.com",
    created_at: ISO,
    updated_at: ISO,
    override_watermark: null,
  };
}

function renderHistory(objectId = "run-123") {
  // Use retry: false to prevent automatic retries in tests
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false, staleTime: 0 } },
  });
  return render(
    <QueryClientProvider client={client}>
      <ExportHistory objectId={objectId} />
    </QueryClientProvider>,
  );
}

describe("ExportHistory", () => {
  beforeEach(() => {
    vi.resetAllMocks();
  });

  it("renders loading state", () => {
    mockListExports.mockReturnValueOnce(
      new Promise(() => {
        /* pending */
      }),
    );

    renderHistory();

    expect(screen.getByTestId("export-history-loading")).toBeInTheDocument();
  });

  it("renders table of prior exports with columns", async () => {
    mockListExports.mockResolvedValueOnce({
      exports: [
        makeExport("export-001", "complete", "s3://bucket/export1.csv"),
        makeExport("export-002", "pending"),
      ],
      total_count: 2,
    });

    renderHistory();

    await waitFor(() => {
      expect(screen.getByTestId("export-history-table")).toBeInTheDocument();
    });
    expect(screen.getByTestId("export-history-header-type")).toBeInTheDocument();
    expect(screen.getByTestId("export-history-header-status")).toBeInTheDocument();
    expect(screen.getByTestId("export-history-header-requested-by")).toBeInTheDocument();
    expect(screen.getByTestId("export-history-header-created-at")).toBeInTheDocument();
  });

  it("displays exports in table rows", async () => {
    mockListExports.mockResolvedValueOnce({
      exports: [
        makeExport("export-001", "complete", "s3://bucket/export1.csv"),
        makeExport("export-002", "processing"),
      ],
      total_count: 2,
    });

    renderHistory();

    await waitFor(() => {
      expect(screen.getByTestId("export-history-row-export-001")).toBeInTheDocument();
      expect(screen.getByTestId("export-history-row-export-002")).toBeInTheDocument();
    });
  });

  it("shows status badges with correct styling per status", async () => {
    mockListExports.mockResolvedValueOnce({
      exports: [
        makeExport("export-001", "complete", "s3://bucket/export1.csv"),
        makeExport("export-002", "processing"),
        makeExport("export-003", "pending"),
        makeExport("export-004", "failed"),
      ],
      total_count: 4,
    });

    renderHistory();

    await waitFor(() => {
      const completeBadge = screen.getByTestId("export-status-badge-export-001");
      const processingBadge = screen.getByTestId("export-status-badge-export-002");
      const pendingBadge = screen.getByTestId("export-status-badge-export-003");
      const failedBadge = screen.getByTestId("export-status-badge-export-004");

      expect(completeBadge).toHaveClass("bg-emerald-100");
      expect(processingBadge).toHaveClass("bg-amber-100");
      expect(pendingBadge).toHaveClass("bg-blue-100");
      expect(failedBadge).toHaveClass("bg-red-100");
    });
  });

  it("shows download link only for complete exports", async () => {
    mockListExports.mockResolvedValueOnce({
      exports: [
        makeExport("export-001", "complete", "s3://bucket/export1.csv"),
        makeExport("export-002", "processing"),
        makeExport("export-003", "pending"),
      ],
      total_count: 3,
    });

    renderHistory();

    await waitFor(() => {
      expect(screen.getByTestId("export-download-link-export-001")).toBeInTheDocument();
    });
    expect(screen.queryByTestId("export-download-link-export-002")).not.toBeInTheDocument();
    expect(screen.queryByTestId("export-download-link-export-003")).not.toBeInTheDocument();
  });

  it("shows empty state when no exports exist", async () => {
    mockListExports.mockResolvedValueOnce({
      exports: [],
      total_count: 0,
    });

    renderHistory();

    await waitFor(() => {
      expect(screen.getByTestId("export-history-empty")).toBeInTheDocument();
    });
    expect(screen.queryByTestId("export-history-table")).not.toBeInTheDocument();
  });

  it("shows error state with retry button on failure", async () => {
    const error = new Error("Failed to fetch exports");
    mockListExports.mockRejectedValueOnce(error);

    renderHistory();

    await waitFor(() => {
      expect(screen.getByTestId("export-history-error")).toBeInTheDocument();
    });
    expect(screen.getByTestId("export-history-retry-button")).toBeInTheDocument();
  });

  it("refetches exports on retry button click", async () => {
    const error = new Error("Failed to fetch exports");
    mockListExports.mockRejectedValueOnce(error).mockResolvedValueOnce({
      exports: [makeExport("export-001", "complete", "s3://bucket/export1.csv")],
      total_count: 1,
    });

    renderHistory();

    await waitFor(() => {
      expect(screen.getByTestId("export-history-error")).toBeInTheDocument();
    });

    fireEvent.click(screen.getByTestId("export-history-retry-button"));

    await waitFor(() => {
      expect(screen.getByTestId("export-history-table")).toBeInTheDocument();
    });
  });

  it("filters exports by object_id on mount", async () => {
    mockListExports.mockResolvedValueOnce({
      exports: [makeExport("export-001", "complete", "s3://bucket/export1.csv")],
      total_count: 1,
    });

    renderHistory("specific-run-id");

    await waitFor(() => {
      expect(mockListExports).toHaveBeenCalledWith(
        { object_id: "specific-run-id" },
        expect.any(String),
        expect.any(Object),
      );
    });
  });
});
