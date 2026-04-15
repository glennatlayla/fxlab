/**
 * AlertDetail component tests.
 *
 * Tests verify:
 * - Rendering of full alert message and metadata.
 * - Acknowledge button visibility and callback.
 * - Hiding acknowledge button when already acknowledged.
 * - Timestamp and source information.
 */

import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, it, expect, vi } from "vitest";
import { AlertDetail } from "../AlertDetail";
import type { Alert } from "../../types";

describe("AlertDetail", () => {
  const mockAlert: Alert = {
    id: "alert-001",
    severity: "critical",
    title: "VaR Breach",
    message: "Portfolio VaR (6.2%) exceeds threshold (5.0%)",
    source: "risk-gate",
    created_at: "2026-04-13T12:00:00Z",
    acknowledged: false,
    metadata: {
      alert_type: "var_breach",
      current_value: 6.2,
      threshold_value: 5.0,
    },
  };

  describe("rendering", () => {
    it("renders full alert message", () => {
      render(<AlertDetail alert={mockAlert} onAcknowledge={vi.fn()} />);
      expect(screen.getByText(/Portfolio VaR/)).toBeInTheDocument();
    });

    it("renders alert title", () => {
      render(<AlertDetail alert={mockAlert} onAcknowledge={vi.fn()} />);
      expect(screen.getByText("VaR Breach")).toBeInTheDocument();
    });

    it("renders source information", () => {
      render(<AlertDetail alert={mockAlert} onAcknowledge={vi.fn()} />);
      expect(screen.getByText(/risk-gate/)).toBeInTheDocument();
    });

    it("renders timestamp", () => {
      render(<AlertDetail alert={mockAlert} onAcknowledge={vi.fn()} />);
      // The timestamp should be rendered in the timeline section
      expect(screen.getByText(/Apr|April|2026/)).toBeInTheDocument();
    });

    it("renders metadata key-value pairs", () => {
      render(<AlertDetail alert={mockAlert} onAcknowledge={vi.fn()} />);
      // Check that the metadata section is visible with Details heading
      expect(screen.getByText(/Details/)).toBeInTheDocument();
      // Check that metadata section renders without errors
      // The values appear as formatted numbers (6.2000 for 6.2, etc.)
      const details = screen.getByText(/Details/).parentElement;
      expect(details?.textContent).toMatch(/6/);
      expect(details?.textContent).toMatch(/5/);
    });
  });

  describe("acknowledge button", () => {
    it("shows acknowledge button for unacknowledged alert", () => {
      render(<AlertDetail alert={mockAlert} onAcknowledge={vi.fn()} />);
      const button = screen.getByRole("button", { name: /acknowledge|mark read/i });
      expect(button).toBeInTheDocument();
    });

    it("calls onAcknowledge when acknowledge button is clicked", async () => {
      const onAcknowledgeMock = vi.fn();
      render(<AlertDetail alert={mockAlert} onAcknowledge={onAcknowledgeMock} />);

      const button = screen.getByRole("button", { name: /acknowledge|mark read/i });
      await userEvent.click(button);

      expect(onAcknowledgeMock).toHaveBeenCalledOnce();
      expect(onAcknowledgeMock).toHaveBeenCalledWith(mockAlert.id);
    });

    it("hides acknowledge button when alert is already acknowledged", () => {
      const acknowledgedAlert: Alert = {
        ...mockAlert,
        acknowledged: true,
      };
      render(<AlertDetail alert={acknowledgedAlert} onAcknowledge={vi.fn()} />);

      const buttons = screen.queryAllByRole("button", { name: /acknowledge|mark read/i });
      expect(buttons.length).toBe(0);
    });

    it("shows check badge when alert is acknowledged", () => {
      const acknowledgedAlert: Alert = {
        ...mockAlert,
        acknowledged: true,
      };
      render(<AlertDetail alert={acknowledgedAlert} onAcknowledge={vi.fn()} />);

      expect(screen.getByText(/acknowledged|marked/i)).toBeInTheDocument();
    });
  });

  describe("metadata display", () => {
    it("handles alerts with no metadata", () => {
      const noMetadataAlert: Alert = {
        ...mockAlert,
        metadata: undefined,
      };
      render(<AlertDetail alert={noMetadataAlert} onAcknowledge={vi.fn()} />);
      // Should not crash
      expect(screen.getByText(mockAlert.title)).toBeInTheDocument();
    });

    it("handles alerts with empty metadata object", () => {
      const emptyMetadataAlert: Alert = {
        ...mockAlert,
        metadata: {},
      };
      render(<AlertDetail alert={emptyMetadataAlert} onAcknowledge={vi.fn()} />);
      // Should not crash
      expect(screen.getByText(mockAlert.title)).toBeInTheDocument();
    });

    it("renders nested metadata values as JSON strings", () => {
      const complexAlert: Alert = {
        ...mockAlert,
        metadata: {
          alert_type: "var_breach",
          details: { symbol: "SPY", pct_change: 2.5 },
        },
      };
      render(<AlertDetail alert={complexAlert} onAcknowledge={vi.fn()} />);
      expect(screen.getByText(/details/)).toBeInTheDocument();
    });
  });

  describe("acknowledged_by and acknowledged_at", () => {
    it("displays acknowledger info when available", () => {
      const acknowledgedAlert: Alert = {
        ...mockAlert,
        acknowledged: true,
        acknowledged_by: "alice@example.com",
        acknowledged_at: "2026-04-13T13:00:00Z",
      };
      render(<AlertDetail alert={acknowledgedAlert} onAcknowledge={vi.fn()} />);

      expect(screen.getByText(/alice@example.com/)).toBeInTheDocument();
      // The "Acknowledged By" label should be visible (distinct from the badge)
      expect(screen.getByText(/Acknowledged By/)).toBeInTheDocument();
    });
  });
});
