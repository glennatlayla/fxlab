/**
 * Tests for PromotionHistory component.
 *
 * Covers:
 *   - Loading state rendering.
 *   - Empty state when no promotions exist.
 *   - Error state with retry.
 *   - Timeline rendering with multiple entries.
 *   - Status badge styling per promotion status.
 *   - Evidence link rendering (clickable, sanitized).
 *   - Override watermark display when present.
 *   - Decision rationale display for decided entries.
 *   - Target environment display (paper/live).
 */

import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { PromotionHistory } from "./PromotionHistory";
import type { PromotionHistoryEntry } from "@/types/governance";

// ---------------------------------------------------------------------------
// Mocks
// ---------------------------------------------------------------------------

vi.mock("../api", () => ({
  governanceApi: {
    listPromotions: vi.fn(),
  },
}));

vi.mock("@/auth/useAuth", () => ({
  useAuth: () => ({
    user: { userId: "01HUSER0000000000000001" },
    hasScope: () => true,
  }),
}));

import { governanceApi } from "../api";

const mockListPromotions = governanceApi.listPromotions as ReturnType<typeof vi.fn>;

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function makePromotion(overrides?: Partial<PromotionHistoryEntry>): PromotionHistoryEntry {
  return {
    id: "01HPROMO00000000000001",
    candidate_id: "01HCANDIDATE0000000001",
    target_environment: "paper",
    submitted_by: "01HUSER0000000000000001",
    status: "pending",
    reviewed_by: null,
    reviewed_at: null,
    decision_rationale: null,
    evidence_link: null,
    created_at: "2026-04-06T12:00:00Z",
    updated_at: "2026-04-06T12:00:00Z",
    override_watermark: null,
    ...overrides,
  };
}

function createQueryClient(): QueryClient {
  return new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
}

function renderWithProviders(candidateId: string) {
  const queryClient = createQueryClient();
  return render(
    <QueryClientProvider client={queryClient}>
      <PromotionHistory candidateId={candidateId} />
    </QueryClientProvider>,
  );
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe("PromotionHistory", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("renders loading state while fetching", () => {
    mockListPromotions.mockReturnValue(new Promise(() => {})); // never resolves
    renderWithProviders("01HCANDIDATE0000000001");
    expect(screen.getByRole("status")).toBeInTheDocument();
    expect(screen.getByText(/loading/i)).toBeInTheDocument();
  });

  it("renders empty state when no promotions exist", async () => {
    mockListPromotions.mockResolvedValue([]);
    renderWithProviders("01HCANDIDATE0000000001");
    expect(await screen.findByText(/no promotion/i)).toBeInTheDocument();
  });

  it("renders error state with retry button on failure", async () => {
    mockListPromotions.mockRejectedValue(new Error("network fail"));
    renderWithProviders("01HCANDIDATE0000000001");
    expect(await screen.findByRole("alert")).toBeInTheDocument();
    expect(screen.getByText(/retry/i)).toBeInTheDocument();
  });

  it("retries when retry button is clicked", async () => {
    mockListPromotions.mockRejectedValueOnce(new Error("fail"));
    mockListPromotions.mockResolvedValueOnce([makePromotion()]);
    renderWithProviders("01HCANDIDATE0000000001");

    const retryButton = await screen.findByText(/retry/i);
    fireEvent.click(retryButton);

    expect(await screen.findByText("paper")).toBeInTheDocument();
    expect(mockListPromotions).toHaveBeenCalledTimes(2);
  });

  it("renders timeline entries for multiple promotions", async () => {
    mockListPromotions.mockResolvedValue([
      makePromotion({ id: "promo-1", status: "completed" }),
      makePromotion({ id: "promo-2", status: "pending" }),
    ]);
    renderWithProviders("01HCANDIDATE0000000001");

    const entries = await screen.findAllByTestId(/^promotion-entry-/);
    expect(entries).toHaveLength(2);
  });

  it("displays target environment for each entry", async () => {
    mockListPromotions.mockResolvedValue([
      makePromotion({ target_environment: "paper" }),
      makePromotion({ id: "promo-2", target_environment: "live" }),
    ]);
    renderWithProviders("01HCANDIDATE0000000001");

    expect(await screen.findByText("paper")).toBeInTheDocument();
    expect(screen.getByText("live")).toBeInTheDocument();
  });

  it("renders status badge for each promotion status", async () => {
    const statuses = [
      "pending",
      "validating",
      "approved",
      "rejected",
      "deploying",
      "completed",
      "failed",
    ] as const;
    mockListPromotions.mockResolvedValue(
      statuses.map((status, idx) => makePromotion({ id: `promo-${idx}`, status })),
    );
    renderWithProviders("01HCANDIDATE0000000001");

    const entries = await screen.findAllByTestId(/^promotion-entry-/);
    expect(entries).toHaveLength(statuses.length);
  });

  it("displays decision rationale when present", async () => {
    mockListPromotions.mockResolvedValue([
      makePromotion({
        status: "approved",
        decision_rationale: "Backtest results meet threshold.",
      }),
    ]);
    renderWithProviders("01HCANDIDATE0000000001");

    expect(await screen.findByText("Backtest results meet threshold.")).toBeInTheDocument();
  });

  it("does not render rationale section when null", async () => {
    mockListPromotions.mockResolvedValue([
      makePromotion({ status: "pending", decision_rationale: null }),
    ]);
    renderWithProviders("01HCANDIDATE0000000001");

    await screen.findByTestId("promotion-entry-01HPROMO00000000000001");
    expect(screen.queryByTestId("promotion-rationale")).not.toBeInTheDocument();
  });

  it("renders evidence link as clickable anchor", async () => {
    mockListPromotions.mockResolvedValue([
      makePromotion({
        evidence_link: "https://jira.example.com/FX-789",
      }),
    ]);
    renderWithProviders("01HCANDIDATE0000000001");

    const link = await screen.findByRole("link", { name: /evidence/i });
    expect(link).toHaveAttribute("href", "https://jira.example.com/FX-789");
    expect(link).toHaveAttribute("target", "_blank");
    expect(link).toHaveAttribute("rel", "noopener noreferrer");
  });

  it("blocks javascript: protocol in evidence link", async () => {
    mockListPromotions.mockResolvedValue([
      makePromotion({
        evidence_link: "javascript:alert(1)",
      }),
    ]);
    renderWithProviders("01HCANDIDATE0000000001");

    await screen.findByTestId("promotion-entry-01HPROMO00000000000001");
    expect(screen.queryByRole("link", { name: /evidence/i })).not.toBeInTheDocument();
  });

  it("renders reviewer info when reviewed", async () => {
    mockListPromotions.mockResolvedValue([
      makePromotion({
        status: "approved",
        reviewed_by: "01HREVIEWER000000000001",
        reviewed_at: "2026-04-06T14:00:00Z",
      }),
    ]);
    renderWithProviders("01HCANDIDATE0000000001");

    expect(await screen.findByText(/01HREVIEWER000000000001/)).toBeInTheDocument();
  });

  it("renders override watermark when present", async () => {
    mockListPromotions.mockResolvedValue([
      makePromotion({
        override_watermark: { override_id: "01HOVERRIDE000000000001" },
      }),
    ]);
    renderWithProviders("01HCANDIDATE0000000001");

    expect(await screen.findByTestId("promotion-watermark")).toBeInTheDocument();
  });

  it("does not render watermark section when null", async () => {
    mockListPromotions.mockResolvedValue([makePromotion({ override_watermark: null })]);
    renderWithProviders("01HCANDIDATE0000000001");

    await screen.findByTestId("promotion-entry-01HPROMO00000000000001");
    expect(screen.queryByTestId("promotion-watermark")).not.toBeInTheDocument();
  });

  it("displays submitter ID", async () => {
    mockListPromotions.mockResolvedValue([
      makePromotion({ submitted_by: "01HSUBMITTER000000001" }),
    ]);
    renderWithProviders("01HCANDIDATE0000000001");

    expect(await screen.findByText(/01HSUBMITTER000000001/)).toBeInTheDocument();
  });

  it("displays created_at timestamp", async () => {
    mockListPromotions.mockResolvedValue([makePromotion({ created_at: "2026-04-06T12:00:00Z" })]);
    renderWithProviders("01HCANDIDATE0000000001");

    expect(await screen.findByText(/2026-04-06/)).toBeInTheDocument();
  });

  it("passes candidateId to listPromotions API call", async () => {
    mockListPromotions.mockResolvedValue([]);
    renderWithProviders("01HCANDIDATE_SPECIFIC");

    await screen.findByText(/no promotion/i);
    expect(mockListPromotions).toHaveBeenCalledWith(
      "01HCANDIDATE_SPECIFIC",
      expect.any(String),
      expect.anything(),
    );
  });
});
