/**
 * Tests for RunReadinessPage container component.
 *
 * AC-1: Readiness report loads and grade renders for a completed run.
 * AC-3: "Submit for promotion" is absent when grade is F.
 * AC-4: Override watermark renders in amber when active override applies.
 * AC-5: BlockerSummary for a failing dimension includes owner and next-step.
 */

import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor, fireEvent } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { RunReadinessPage } from "./RunReadinessPage";
import { readinessApi } from "../api";
import { ReadinessNotFoundError, ReadinessAuthError, ReadinessNetworkError } from "../errors";
import type { ReadinessReportPayload } from "@/types/readiness";

// ---------------------------------------------------------------------------
// Mocks
// ---------------------------------------------------------------------------

vi.mock("../api", () => ({
  readinessApi: {
    getReadinessReport: vi.fn(),
    generateReadinessReport: vi.fn(),
    submitForPromotion: vi.fn(),
  },
}));

vi.mock("../logger", () => ({
  readinessLogger: {
    pageMount: vi.fn(),
    pageUnmount: vi.fn(),
    fetchStart: vi.fn(),
    fetchSuccess: vi.fn(),
    fetchFailure: vi.fn(),
    generateStart: vi.fn(),
    generateSuccess: vi.fn(),
    generateFailure: vi.fn(),
    promotionStart: vi.fn(),
    promotionSuccess: vi.fn(),
    promotionFailure: vi.fn(),
  },
}));

vi.mock("@/auth/useAuth", () => ({
  useAuth: () => ({
    user: {
      userId: "user-1",
      email: "test@test.com",
      role: "developer",
      scopes: ["runs:write", "request_promotion"],
    },
    hasScope: (scope: string) => ["runs:write", "request_promotion"].includes(scope),
    isLoading: false,
  }),
}));

const mockGetReadinessReport = vi.mocked(readinessApi.getReadinessReport);

// ---------------------------------------------------------------------------
// Fixtures
// ---------------------------------------------------------------------------

function makePayload(overrides?: Partial<ReadinessReportPayload>): ReadinessReportPayload {
  return {
    run_id: "01HRUN0000000000000000001",
    grade: "B",
    score: 72,
    policy_version: "1",
    dimensions: [
      {
        dimension: "oos_stability",
        label: "OOS Stability",
        score: 85,
        weight: 0.2,
        threshold: 35,
        passed: true,
        details: null,
      },
      {
        dimension: "drawdown",
        label: "Max Drawdown",
        score: 65,
        weight: 0.2,
        threshold: 35,
        passed: true,
        details: null,
      },
      {
        dimension: "trade_count",
        label: "Trade Count",
        score: 90,
        weight: 0.15,
        threshold: 35,
        passed: true,
        details: null,
      },
      {
        dimension: "holdout_pass",
        label: "Holdout Evaluation",
        score: 72,
        weight: 0.2,
        threshold: 35,
        passed: true,
        details: null,
      },
      {
        dimension: "regime_consistency",
        label: "Regime Consistency",
        score: 68,
        weight: 0.15,
        threshold: 35,
        passed: true,
        details: null,
      },
      {
        dimension: "parameter_stability",
        label: "Parameter Stability",
        score: 75,
        weight: 0.1,
        threshold: 35,
        passed: true,
        details: null,
      },
    ],
    blockers: [],
    holdout: {
      evaluated: true,
      passed: true,
      start_date: "2025-06-01T00:00:00Z",
      end_date: "2025-12-31T00:00:00Z",
      contamination_detected: false,
      sharpe_ratio: 1.25,
    },
    regime_consistency: [
      { regime: "bull", sharpe_ratio: 1.85, passed: true, trade_count: 45 },
      { regime: "bear", sharpe_ratio: 0.42, passed: true, trade_count: 32 },
    ],
    override_watermark: null,
    assessed_at: "2026-04-06T12:00:00Z",
    assessor: "readiness-engine",
    has_pending_promotion: false,
    report_history: [],
    ...overrides,
  };
}

function renderPage(runId = "01HRUN0000000000000000001") {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter initialEntries={[`/runs/${runId}/readiness`]}>
        <Routes>
          <Route path="/runs/:runId/readiness" element={<RunReadinessPage runId={runId} />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe("RunReadinessPage", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  // -------------------------------------------------------------------------
  // Loading & success
  // -------------------------------------------------------------------------

  it("shows loading state while report is being fetched", () => {
    mockGetReadinessReport.mockReturnValue(new Promise(() => {}));
    renderPage();
    expect(screen.getByTestId("readiness-loading")).toBeInTheDocument();
  });

  it("renders readiness page after successful fetch (AC-1)", async () => {
    mockGetReadinessReport.mockResolvedValue(makePayload());
    renderPage();
    await waitFor(() => {
      expect(screen.getByTestId("run-readiness-page")).toBeInTheDocument();
    });
  });

  it("renders grade badge (AC-1)", async () => {
    mockGetReadinessReport.mockResolvedValue(makePayload());
    renderPage();
    await waitFor(() => {
      expect(screen.getByTestId("grade-badge")).toBeInTheDocument();
      expect(screen.getByText("B")).toBeInTheDocument();
    });
  });

  it("renders scoring breakdown section", async () => {
    mockGetReadinessReport.mockResolvedValue(makePayload());
    renderPage();
    await waitFor(() => {
      expect(screen.getByText("OOS Stability")).toBeInTheDocument();
    });
  });

  it("renders holdout status card", async () => {
    mockGetReadinessReport.mockResolvedValue(makePayload());
    renderPage();
    await waitFor(() => {
      expect(screen.getByTestId("holdout-status-card")).toBeInTheDocument();
    });
  });

  it("renders regime consistency table", async () => {
    mockGetReadinessReport.mockResolvedValue(makePayload());
    renderPage();
    await waitFor(() => {
      expect(screen.getByText("bull")).toBeInTheDocument();
    });
  });

  // -------------------------------------------------------------------------
  // Error states
  // -------------------------------------------------------------------------

  it("shows error state when fetch fails", async () => {
    mockGetReadinessReport.mockRejectedValue(new Error("Network failure"));
    renderPage();
    await waitFor(() => {
      expect(screen.getByTestId("readiness-error")).toBeInTheDocument();
    });
  });

  it("shows not-found message for ReadinessNotFoundError", async () => {
    mockGetReadinessReport.mockRejectedValue(new ReadinessNotFoundError("run-gone"));
    renderPage();
    await waitFor(() => {
      expect(screen.getByText(/no readiness report/i)).toBeInTheDocument();
    });
  });

  it("shows auth error message for 401", async () => {
    mockGetReadinessReport.mockRejectedValue(new ReadinessAuthError("run-1", 401));
    renderPage();
    await waitFor(() => {
      expect(screen.getByText(/session.*expired/i)).toBeInTheDocument();
    });
  });

  it("shows auth error message for 403", async () => {
    mockGetReadinessReport.mockRejectedValue(new ReadinessAuthError("run-1", 403));
    renderPage();
    await waitFor(() => {
      expect(screen.getByText(/permission/i)).toBeInTheDocument();
    });
  });

  // -------------------------------------------------------------------------
  // Grade F renders BlockerSummary (AC-3, AC-5)
  // -------------------------------------------------------------------------

  it("renders BlockerSummary when grade is F (AC-5)", async () => {
    mockGetReadinessReport.mockResolvedValue(
      makePayload({
        grade: "F",
        score: 22,
        blockers: [
          {
            code: "HOLDOUT_FAIL",
            message: "Holdout Sharpe is negative",
            blocker_owner: "Quantitative Research",
            next_step: "Re-evaluate holdout period",
            severity: "critical",
          },
        ],
      }),
    );
    renderPage();
    await waitFor(() => {
      expect(screen.getByText("Quantitative Research")).toBeInTheDocument();
      expect(screen.getByText("Re-evaluate holdout period")).toBeInTheDocument();
    });
  });

  it("does not render promotion button when grade is F (AC-3)", async () => {
    mockGetReadinessReport.mockResolvedValue(makePayload({ grade: "F", score: 22 }));
    renderPage();
    await waitFor(() => {
      expect(screen.getByTestId("run-readiness-page")).toBeInTheDocument();
    });
    expect(screen.queryByRole("button", { name: /submit for promotion/i })).not.toBeInTheDocument();
  });

  // -------------------------------------------------------------------------
  // Override watermark (AC-4)
  // -------------------------------------------------------------------------

  it("renders override watermark in amber when active override applies (AC-4)", async () => {
    mockGetReadinessReport.mockResolvedValue(
      makePayload({
        override_watermark: {
          override_id: "01HOVERRIDE00000000000001",
          is_active: true,
          override_type: "grade_override",
          rationale: "CRO approval",
          evidence_link: "https://jira.example.com/RISK-1",
          created_at: "2026-04-01T00:00:00Z",
        },
      }),
    );
    renderPage();
    await waitFor(() => {
      const banner = screen.getByTestId("override-watermark-banner");
      expect(banner).toBeInTheDocument();
      expect(banner.className).toContain("amber");
    });
  });

  it("does not render override watermark when null", async () => {
    mockGetReadinessReport.mockResolvedValue(makePayload({ override_watermark: null }));
    renderPage();
    await waitFor(() => {
      expect(screen.getByTestId("run-readiness-page")).toBeInTheDocument();
    });
    expect(screen.queryByTestId("override-watermark-banner")).not.toBeInTheDocument();
  });

  // -------------------------------------------------------------------------
  // Promotion button
  // -------------------------------------------------------------------------

  it("renders promotion button for non-F grades", async () => {
    mockGetReadinessReport.mockResolvedValue(makePayload({ grade: "B" }));
    renderPage();
    await waitFor(() => {
      expect(screen.getByRole("button", { name: /submit for promotion/i })).toBeInTheDocument();
    });
  });

  it("disables promotion button when pending promotion exists", async () => {
    mockGetReadinessReport.mockResolvedValue(makePayload({ has_pending_promotion: true }));
    renderPage();
    await waitFor(() => {
      const btn = screen.getByRole("button", { name: /submit for promotion/i });
      expect(btn).toBeDisabled();
    });
  });

  // -------------------------------------------------------------------------
  // Generate readiness report button
  // -------------------------------------------------------------------------

  it("renders generate report button", async () => {
    mockGetReadinessReport.mockResolvedValue(makePayload());
    renderPage();
    await waitFor(() => {
      expect(screen.getByRole("button", { name: /generate.*report/i })).toBeInTheDocument();
    });
  });

  // -------------------------------------------------------------------------
  // Report history
  // -------------------------------------------------------------------------

  // -------------------------------------------------------------------------
  // Promotion error display
  // -------------------------------------------------------------------------

  it("shows promotion error banner when submitForPromotion fails", async () => {
    mockGetReadinessReport.mockResolvedValue(makePayload());
    const mockSubmit = vi.mocked(readinessApi.submitForPromotion);
    mockSubmit.mockRejectedValue(new ReadinessNetworkError("run-1", 500));

    renderPage();
    await waitFor(() => {
      expect(screen.getByTestId("run-readiness-page")).toBeInTheDocument();
    });

    // Open the promotion form.
    fireEvent.click(screen.getByRole("button", { name: /submit for promotion/i }));

    // Fill rationale (minimum 10 chars) and confirm.
    fireEvent.change(screen.getByTestId("promotion-rationale-input"), {
      target: { value: "Strong OOS performance" },
    });
    fireEvent.click(screen.getByTestId("promotion-confirm-button"));

    await waitFor(() => {
      expect(screen.getByTestId("promotion-error-banner")).toBeInTheDocument();
    });
  });

  // -------------------------------------------------------------------------
  // Report history
  // -------------------------------------------------------------------------

  it("renders report history when entries exist", async () => {
    mockGetReadinessReport.mockResolvedValue(
      makePayload({
        report_history: [
          {
            report_id: "rpt-1",
            grade: "D",
            score: 38,
            assessed_at: "2026-04-03T10:00:00Z",
            policy_version: "1",
            assessor: "manual",
          },
        ],
      }),
    );
    renderPage();
    await waitFor(() => {
      expect(screen.getByTestId("report-history-entry-rpt-1")).toBeInTheDocument();
    });
  });
});
