/**
 * Tests for RunTerminalState component.
 *
 * Verifies correct rendering for each terminal status:
 *   - complete → results link
 *   - failed → error + retry button
 *   - cancelled → cancellation reason
 */

import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { RunTerminalState } from "./RunTerminalState";
import type { RunRecord } from "@/types/run";

function makeRun(overrides: Partial<RunRecord> = {}): RunRecord {
  return {
    id: "01HZ0000000000000000000001",
    strategy_build_id: "01HZ0000000000000000000002",
    run_type: "research",
    status: "complete",
    config: {},
    result_uri: null,
    created_by: "user-001",
    created_at: "2026-04-04T10:00:00Z",
    updated_at: "2026-04-04T10:00:00Z",
    started_at: "2026-04-04T10:01:00Z",
    completed_at: "2026-04-04T11:00:00Z",
    ...overrides,
  };
}

describe("RunTerminalState", () => {
  describe("complete", () => {
    it("renders completion message", () => {
      render(<RunTerminalState run={makeRun()} onRetry={vi.fn()} />);
      expect(screen.getByTestId("run-terminal-complete")).toBeInTheDocument();
      expect(screen.getByText("Run Complete")).toBeInTheDocument();
    });

    it("shows results link when result_uri is present", () => {
      render(
        <RunTerminalState
          run={makeRun({ result_uri: "s3://bucket/results.parquet" })}
          onRetry={vi.fn()}
        />,
      );
      const link = screen.getByTestId("results-link");
      expect(link.getAttribute("href")).toBe("s3://bucket/results.parquet");
    });

    it("does not show results link when result_uri is null", () => {
      render(<RunTerminalState run={makeRun({ result_uri: null })} onRetry={vi.fn()} />);
      expect(screen.queryByTestId("results-link")).not.toBeInTheDocument();
    });
  });

  describe("failed", () => {
    it("renders failure message with error", () => {
      render(
        <RunTerminalState
          run={makeRun({ status: "failed", error_message: "Out of memory" })}
          onRetry={vi.fn()}
        />,
      );
      expect(screen.getByTestId("run-terminal-failed")).toBeInTheDocument();
      expect(screen.getByText("Run Failed")).toBeInTheDocument();
      expect(screen.getByText("Out of memory")).toBeInTheDocument();
    });

    it("calls onRetry when retry button is clicked", () => {
      const onRetry = vi.fn();
      render(<RunTerminalState run={makeRun({ status: "failed" })} onRetry={onRetry} />);
      fireEvent.click(screen.getByTestId("retry-button"));
      expect(onRetry).toHaveBeenCalledTimes(1);
    });
  });

  describe("cancelled", () => {
    it("renders cancellation message with reason", () => {
      render(
        <RunTerminalState
          run={makeRun({
            status: "cancelled",
            cancellation_reason: "User requested cancellation",
          })}
          onRetry={vi.fn()}
        />,
      );
      expect(screen.getByTestId("run-terminal-cancelled")).toBeInTheDocument();
      expect(screen.getByText("Run Cancelled")).toBeInTheDocument();
      expect(screen.getByText("User requested cancellation")).toBeInTheDocument();
    });
  });

  it("returns null for non-terminal status", () => {
    const { container } = render(
      <RunTerminalState run={makeRun({ status: "running" })} onRetry={vi.fn()} />,
    );
    expect(container.firstChild).toBeNull();
  });
});
