/**
 * Tests for ArtifactBrowser.
 *
 * Covers:
 *   - Loading + error + empty states.
 *   - Renders artifact table with type badge, subject_id, size, created_at, created_by, download link.
 *   - Artifact type filter (select dropdown) changes query.
 *   - Pagination: Next/Prev buttons.
 *   - Search by subject_id (text input).
 *   - Download button per artifact.
 */

import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

vi.mock("../api", () => ({
  artifactApi: {
    listArtifacts: vi.fn(),
    downloadArtifact: vi.fn(),
  },
}));
vi.mock("../logger", () => ({
  artifactLogger: {
    pageMount: vi.fn(),
    pageUnmount: vi.fn(),
  },
}));

import { artifactApi } from "../api";
import { ArtifactBrowser } from "./ArtifactBrowser";

const mockListArtifacts = artifactApi.listArtifacts as ReturnType<typeof vi.fn>;
const mockDownloadArtifact = artifactApi.downloadArtifact as ReturnType<typeof vi.fn>;

const ISO = "2026-04-06T12:00:00.000Z";

function makeArtifact(id: string, type: string, subjectId: string, sizeBytes: number) {
  return {
    id,
    artifact_type: type,
    subject_id: subjectId,
    storage_path: `/artifacts/${id}`,
    size_bytes: sizeBytes,
    created_at: ISO,
    created_by: "user@example.com",
    metadata: {},
  };
}

function renderBrowser(pageSize = 25) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <ArtifactBrowser pageSize={pageSize} />
    </QueryClientProvider>,
  );
}

describe("ArtifactBrowser", () => {
  beforeEach(() => {
    vi.resetAllMocks();
  });

  it("renders loading state then list of artifacts", async () => {
    mockListArtifacts.mockResolvedValueOnce({
      artifacts: [
        makeArtifact("01HART0000000000000001", "compiled_strategy", "strat-001", 2048000),
        makeArtifact("01HART0000000000000002", "backtest_result", "strat-002", 512000),
      ],
      total_count: 2,
      limit: 25,
      offset: 0,
    });

    renderBrowser(25);

    expect(screen.getByTestId("artifacts-loading")).toBeInTheDocument();
    await waitFor(() => {
      expect(screen.getByTestId("artifacts-row-01HART0000000000000001")).toBeInTheDocument();
    });
    expect(screen.getByText("strat-001")).toBeInTheDocument();
    expect(screen.getByText("strat-002")).toBeInTheDocument();
  });

  it("renders error state with retry on listArtifacts failure", async () => {
    mockListArtifacts.mockRejectedValueOnce(new Error("network down"));
    renderBrowser(25);

    const retry = await screen.findByRole("button", { name: /retry/i });
    expect(screen.getByTestId("artifacts-error")).toHaveTextContent(/network down/i);

    mockListArtifacts.mockResolvedValueOnce({
      artifacts: [makeArtifact("01HART0000000000000099", "readiness_report", "strat-r", 1024000)],
      total_count: 1,
      limit: 25,
      offset: 0,
    });
    fireEvent.click(retry);
    await screen.findByTestId("artifacts-row-01HART0000000000000099");
  });

  it("renders empty state when no artifacts returned", async () => {
    mockListArtifacts.mockResolvedValueOnce({
      artifacts: [],
      total_count: 0,
      limit: 25,
      offset: 0,
    });
    renderBrowser(25);
    expect(await screen.findByTestId("artifacts-empty")).toBeInTheDocument();
  });

  it("filters by artifact type via dropdown", async () => {
    mockListArtifacts
      .mockResolvedValueOnce({
        artifacts: [
          makeArtifact("01HART0000000000000011", "compiled_strategy", "strat-a", 2048000),
          makeArtifact("01HART0000000000000012", "backtest_result", "strat-b", 512000),
        ],
        total_count: 2,
        limit: 25,
        offset: 0,
      })
      .mockResolvedValueOnce({
        artifacts: [
          makeArtifact("01HART0000000000000011", "compiled_strategy", "strat-a", 2048000),
        ],
        total_count: 1,
        limit: 25,
        offset: 0,
      });

    renderBrowser(25);
    await screen.findByTestId("artifacts-row-01HART0000000000000011");

    const typeFilter = screen.getByTestId("artifacts-type-filter") as HTMLSelectElement;
    fireEvent.change(typeFilter, { target: { value: "compiled_strategy" } });

    await waitFor(() => {
      expect(mockListArtifacts).toHaveBeenCalledWith(
        expect.objectContaining({
          artifact_types: ["compiled_strategy"],
        }),
        expect.anything(),
        expect.anything(),
      );
    });
  });

  it("filters by subject_id via text input", async () => {
    mockListArtifacts
      .mockResolvedValueOnce({
        artifacts: [
          makeArtifact("01HART0000000000000021", "compiled_strategy", "strat-search", 2048000),
          makeArtifact("01HART0000000000000022", "backtest_result", "other-id", 512000),
        ],
        total_count: 2,
        limit: 25,
        offset: 0,
      })
      .mockResolvedValueOnce({
        artifacts: [
          makeArtifact("01HART0000000000000021", "compiled_strategy", "strat-search", 2048000),
        ],
        total_count: 1,
        limit: 25,
        offset: 0,
      });

    renderBrowser(25);
    await screen.findByTestId("artifacts-row-01HART0000000000000021");

    const searchInput = screen.getByTestId("artifacts-subject-id-search") as HTMLInputElement;
    fireEvent.change(searchInput, { target: { value: "strat-search" } });

    await waitFor(() => {
      expect(mockListArtifacts).toHaveBeenCalledWith(
        expect.objectContaining({
          subject_id: "strat-search",
        }),
        expect.anything(),
        expect.anything(),
      );
    });
  });

  it("paginates Next/Prev without full reload (re-queries with new offset)", async () => {
    mockListArtifacts
      .mockResolvedValueOnce({
        artifacts: [makeArtifact("01HART00000000000000P1", "compiled_strategy", "s1", 1024000)],
        total_count: 3,
        limit: 1,
        offset: 0,
      })
      .mockResolvedValueOnce({
        artifacts: [makeArtifact("01HART00000000000000P2", "backtest_result", "s2", 2048000)],
        total_count: 3,
        limit: 1,
        offset: 1,
      })
      .mockResolvedValueOnce({
        artifacts: [makeArtifact("01HART00000000000000P1", "compiled_strategy", "s1", 1024000)],
        total_count: 3,
        limit: 1,
        offset: 0,
      });

    renderBrowser(1);
    await screen.findByTestId("artifacts-row-01HART00000000000000P1");

    expect(screen.getByTestId("artifacts-prev-button")).toBeDisabled();
    fireEvent.click(screen.getByTestId("artifacts-next-button"));

    await screen.findByTestId("artifacts-row-01HART00000000000000P2");
    expect(screen.getByTestId("artifacts-prev-button")).not.toBeDisabled();

    fireEvent.click(screen.getByTestId("artifacts-prev-button"));
    await screen.findByTestId("artifacts-row-01HART00000000000000P1");

    expect(mockListArtifacts).toHaveBeenCalledTimes(3);
    const calls = mockListArtifacts.mock.calls.map((c) => c[0]);
    expect(calls).toEqual([
      { artifact_types: [], subject_id: "", limit: 1, offset: 0 },
      { artifact_types: [], subject_id: "", limit: 1, offset: 1 },
      { artifact_types: [], subject_id: "", limit: 1, offset: 0 },
    ]);
  });

  it("renders artifact table with columns: Type (badge), Subject ID, Size, Created At, Created By, Download", async () => {
    mockListArtifacts.mockResolvedValueOnce({
      artifacts: [
        makeArtifact("01HART0000000000000031", "compiled_strategy", "strat-col", 2097152),
      ],
      total_count: 1,
      limit: 25,
      offset: 0,
    });

    renderBrowser(25);
    const row = await screen.findByTestId("artifacts-row-01HART0000000000000031");

    expect(row.textContent).toContain("Compiled Strategy");
    expect(screen.getByText("strat-col")).toBeInTheDocument();
    expect(screen.getByText(/2\.0\s*MB/i)).toBeInTheDocument();
    expect(screen.getByText(/Apr\s+6/i)).toBeInTheDocument();
    expect(screen.getByText("user@example.com")).toBeInTheDocument();
    expect(screen.getByTestId("artifacts-download-01HART0000000000000031")).toBeInTheDocument();
  });

  it("calls downloadArtifact when download button is clicked", async () => {
    mockListArtifacts.mockResolvedValueOnce({
      artifacts: [makeArtifact("01HART0000000000000041", "backtest_result", "strat-dl", 512000)],
      total_count: 1,
      limit: 25,
      offset: 0,
    });

    renderBrowser(25);
    await screen.findByTestId("artifacts-row-01HART0000000000000041");

    const downloadBtn = screen.getByTestId("artifacts-download-01HART0000000000000041");
    fireEvent.click(downloadBtn);

    expect(mockDownloadArtifact).toHaveBeenCalledWith("01HART0000000000000041", expect.any(String));
  });
});
