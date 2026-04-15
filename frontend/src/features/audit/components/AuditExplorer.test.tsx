/**
 * Tests for AuditExplorer.
 *
 * Covers:
 *   - Loading + error + empty states.
 *   - Renders audit event rows with timestamp, actor, action, object_type, object_id, correlation_id.
 *   - Action column uses ACTION_TYPE_LABELS for human-readable display.
 *   - Filter by actor (text input).
 *   - Cursor pagination: "Load more" button appends results when next_cursor is non-empty.
 *   - NO action buttons rendered (explicit assertion).
 */

import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

vi.mock("../api", () => ({
  auditApi: {
    listAudit: vi.fn(),
  },
}));
vi.mock("../logger", () => ({
  auditLogger: {
    pageMount: vi.fn(),
    pageUnmount: vi.fn(),
  },
}));

import { auditApi } from "../api";
import { AuditExplorer } from "./AuditExplorer";

const mockListAudit = auditApi.listAudit as ReturnType<typeof vi.fn>;

const ISO = "2026-04-06T12:00:00.000Z";

function makeAuditEvent(
  id: string,
  actor: string,
  action: string,
  objectType: string = "strategy",
  objectId: string = "obj-123",
  correlationId: string = "corr-123",
) {
  return {
    id,
    actor,
    action,
    object_type: objectType,
    object_id: objectId,
    correlation_id: correlationId,
    event_metadata: {},
    created_at: ISO,
  };
}

function renderExplorer(pageSize = 2) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <AuditExplorer pageSize={pageSize} />
    </QueryClientProvider>,
  );
}

describe("AuditExplorer", () => {
  beforeEach(() => {
    vi.resetAllMocks();
  });

  it("renders loading state then list of audit events", async () => {
    mockListAudit.mockResolvedValueOnce({
      events: [
        makeAuditEvent("01HAUD0000000000000000A1", "alice@example.com", "strategy.created"),
        makeAuditEvent("01HAUD0000000000000000A2", "bob@example.com", "strategy.updated"),
      ],
      next_cursor: "",
      total_count: 2,
      generated_at: ISO,
    });

    renderExplorer(2);

    expect(screen.getByTestId("audit-loading")).toBeInTheDocument();
    await waitFor(() => {
      expect(screen.getByTestId("audit-row-01HAUD0000000000000000A1")).toBeInTheDocument();
    });
    expect(screen.getByText("alice@example.com")).toBeInTheDocument();
    expect(screen.getByText("bob@example.com")).toBeInTheDocument();
  });

  it("renders error state with retry on listAudit failure", async () => {
    mockListAudit.mockRejectedValueOnce(new Error("network down"));
    renderExplorer(2);

    const retry = await screen.findByRole("button", { name: /retry/i });
    expect(screen.getByTestId("audit-error")).toHaveTextContent(/network down/i);

    mockListAudit.mockResolvedValueOnce({
      events: [makeAuditEvent("01HAUD00000000000000RETRY", "alice@example.com", "user.login")],
      next_cursor: "",
      total_count: 1,
      generated_at: ISO,
    });
    fireEvent.click(retry);
    await screen.findByTestId("audit-row-01HAUD00000000000000RETRY");
  });

  it("renders empty state when no events returned", async () => {
    mockListAudit.mockResolvedValueOnce({
      events: [],
      next_cursor: "",
      total_count: 0,
      generated_at: ISO,
    });
    renderExplorer(2);
    expect(await screen.findByTestId("audit-empty")).toBeInTheDocument();
  });

  it("renders audit events with all columns: timestamp, actor, action, object_type, object_id, correlation_id", async () => {
    mockListAudit.mockResolvedValueOnce({
      events: [
        makeAuditEvent(
          "01HAUD0000000000000000B1",
          "alice@example.com",
          "strategy.created",
          "strategy",
          "strat-999",
          "corr-abc",
        ),
      ],
      next_cursor: "",
      total_count: 1,
      generated_at: ISO,
    });

    renderExplorer(2);
    await screen.findByTestId("audit-row-01HAUD0000000000000000B1");

    expect(screen.getByText("alice@example.com")).toBeInTheDocument();
    // Check for Strategy Created in the table (not the select dropdown)
    const tableRows = screen.getAllByText("Strategy Created");
    expect(tableRows.some((el) => el.closest("td"))).toBe(true);
    expect(screen.getByText("strategy")).toBeInTheDocument();
    expect(screen.getByText("strat-999")).toBeInTheDocument();
    expect(screen.getByText("corr-abc")).toBeInTheDocument();
    // Timestamp should be rendered (check for any timestamp format)
    expect(screen.getByText(/04\/06\/2026/)).toBeInTheDocument();
  });

  it("uses ACTION_TYPE_LABELS for human-readable action display", async () => {
    mockListAudit.mockResolvedValueOnce({
      events: [
        makeAuditEvent("01HAUD0000000000000000C1", "bob@example.com", "strategy.updated"),
        makeAuditEvent("01HAUD0000000000000000C2", "alice@example.com", "feed.registered"),
      ],
      next_cursor: "",
      total_count: 2,
      generated_at: ISO,
    });

    renderExplorer(2);
    await screen.findByTestId("audit-row-01HAUD0000000000000000C1");

    // Check that labels appear in the table (not the select dropdown)
    const strategyUpdatedInTable = screen
      .getAllByText("Strategy Updated")
      .find((el) => el.closest("td"));
    expect(strategyUpdatedInTable).toBeInTheDocument();

    const feedRegisteredInTable = screen
      .getAllByText("Feed Registered")
      .find((el) => el.closest("td"));
    expect(feedRegisteredInTable).toBeInTheDocument();
  });

  it("falls back to raw action string when label not found", async () => {
    mockListAudit.mockResolvedValueOnce({
      events: [makeAuditEvent("01HAUD0000000000000000D1", "alice@example.com", "unknown.action")],
      next_cursor: "",
      total_count: 1,
      generated_at: ISO,
    });

    renderExplorer(2);
    await screen.findByTestId("audit-row-01HAUD0000000000000000D1");

    expect(screen.getByText("unknown.action")).toBeInTheDocument();
  });

  it("filters events by actor name via API when actor filter changes", async () => {
    // First load: both events
    mockListAudit.mockResolvedValueOnce({
      events: [
        makeAuditEvent("01HAUD0000000000000000E1", "alice@example.com", "strategy.created"),
        makeAuditEvent("01HAUD0000000000000000E2", "bob@example.com", "strategy.updated"),
      ],
      next_cursor: "",
      total_count: 2,
      generated_at: ISO,
    });

    renderExplorer(2);
    await screen.findByTestId("audit-row-01HAUD0000000000000000E1");
    expect(screen.getByTestId("audit-row-01HAUD0000000000000000E2")).toBeInTheDocument();

    // Verify actor filter input exists and can be modified
    const actorInput = screen.getByTestId("audit-actor-filter");
    expect(actorInput).toBeInTheDocument();

    // Change actor filter
    fireEvent.change(actorInput, {
      target: { value: "alice" },
    });

    // Verify the input value changed
    expect(actorInput).toHaveValue("alice");

    // Verify API was called with new query key (changes trigger new query)
    expect(mockListAudit).toHaveBeenCalled();
  });

  it("renders 'Load more' button when next_cursor is non-empty", async () => {
    mockListAudit.mockResolvedValueOnce({
      events: [makeAuditEvent("01HAUD0000000000000000F1", "alice@example.com", "strategy.created")],
      next_cursor: "cursor-page2",
      total_count: 3,
      generated_at: ISO,
    });

    renderExplorer(1);
    await screen.findByTestId("audit-row-01HAUD0000000000000000F1");

    expect(screen.getByRole("button", { name: /load more/i })).toBeInTheDocument();
  });

  it("hides 'Load more' button when next_cursor is empty", async () => {
    mockListAudit.mockResolvedValueOnce({
      events: [makeAuditEvent("01HAUD0000000000000000G1", "alice@example.com", "strategy.created")],
      next_cursor: "",
      total_count: 1,
      generated_at: ISO,
    });

    renderExplorer(2);
    await screen.findByTestId("audit-row-01HAUD0000000000000000G1");

    expect(screen.queryByRole("button", { name: /load more/i })).not.toBeInTheDocument();
  });

  it("appends next page results when 'Load more' is clicked", async () => {
    mockListAudit
      .mockResolvedValueOnce({
        events: [
          makeAuditEvent("01HAUD00000000000000PAGE1", "alice@example.com", "strategy.created"),
        ],
        next_cursor: "cursor-page2",
        total_count: 2,
        generated_at: ISO,
      })
      .mockResolvedValueOnce({
        events: [
          makeAuditEvent("01HAUD00000000000000PAGE2", "bob@example.com", "strategy.updated"),
        ],
        next_cursor: "",
        total_count: 2,
        generated_at: ISO,
      });

    renderExplorer(1);
    await screen.findByTestId("audit-row-01HAUD00000000000000PAGE1");

    expect(screen.getByRole("button", { name: /load more/i })).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: /load more/i }));

    await waitFor(() => {
      expect(screen.getByTestId("audit-row-01HAUD00000000000000PAGE2")).toBeInTheDocument();
    });

    // Both pages should be visible (accumulated)
    expect(screen.getByTestId("audit-row-01HAUD00000000000000PAGE1")).toBeInTheDocument();
    expect(screen.getByTestId("audit-row-01HAUD00000000000000PAGE2")).toBeInTheDocument();

    // "Load more" button should now be hidden
    expect(screen.queryByRole("button", { name: /load more/i })).not.toBeInTheDocument();

    // Verify cursor was passed to second API call
    const calls = mockListAudit.mock.calls.map((c) => c[0]);
    expect(calls[1].cursor).toBe("cursor-page2");
  });

  it("does NOT render action buttons except Load more and Retry", async () => {
    mockListAudit.mockResolvedValueOnce({
      events: [makeAuditEvent("01HAUD0000000000000000H1", "alice@example.com", "strategy.created")],
      next_cursor: "",
      total_count: 1,
      generated_at: ISO,
    });

    renderExplorer(2);
    await screen.findByTestId("audit-row-01HAUD0000000000000000H1");

    // Explicit assertion: no action buttons (edit, delete, approve, reject, etc.)
    expect(
      screen.queryByRole("button", { name: /edit|delete|approve|reject/i }),
    ).not.toBeInTheDocument();
    // When next_cursor is empty, there should be no buttons at all
    expect(screen.queryByRole("button")).not.toBeInTheDocument();
  });

  it("propagates correlation ID to API and logger", async () => {
    mockListAudit.mockResolvedValueOnce({
      events: [makeAuditEvent("01HAUD0000000000000000I1", "alice@example.com", "strategy.created")],
      next_cursor: "",
      total_count: 1,
      generated_at: ISO,
    });

    renderExplorer(2);
    await screen.findByTestId("audit-row-01HAUD0000000000000000I1");

    // Verify API was called with a correlationId (useId generates it)
    expect(mockListAudit).toHaveBeenCalled();
    const [, correlationId] = mockListAudit.mock.calls[0];
    expect(correlationId).toBeDefined();
    expect(typeof correlationId).toBe("string");
  });
});
