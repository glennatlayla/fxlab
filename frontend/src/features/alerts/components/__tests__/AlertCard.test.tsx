/**
 * AlertCard component tests.
 *
 * Tests verify:
 * - Rendering of alert title, message, source, and timestamp.
 * - Severity-based styling (color borders, icons).
 * - Acknowledged state appearance (dimmed, check badge).
 * - Click handler triggering detail view.
 * - Message truncation to 2 lines.
 */

import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { AlertCard } from "../AlertCard";
import type { Alert } from "../../types";

describe("AlertCard", () => {
  const mockAlert: Alert = {
    id: "alert-001",
    severity: "critical",
    title: "VaR Breach",
    message: "Portfolio VaR (6.2%) exceeds threshold (5.0%)",
    source: "risk-gate",
    created_at: "2026-04-13T12:00:00Z",
    acknowledged: false,
  };

  describe("rendering", () => {
    // The "renders formatted timestamp" test below depends on the relative-time
    // formatter producing an "ago" / "just now" string. Without a fixed clock,
    // mockAlert.created_at drifts past the formatter's 7-day window as system
    // time advances and falls back to "Apr 13", failing the assertion. Pin the
    // clock to a deterministic instant 6 hours after the alert's created_at so
    // the formatter consistently emits "6 hours ago".
    beforeEach(() => {
      vi.useFakeTimers();
      vi.setSystemTime(new Date("2026-04-13T18:00:00Z"));
    });

    afterEach(() => {
      vi.useRealTimers();
    });

    it("renders alert title", () => {
      render(<AlertCard alert={mockAlert} onClick={vi.fn()} />);
      expect(screen.getByText("VaR Breach")).toBeInTheDocument();
    });

    it("renders alert message", () => {
      render(<AlertCard alert={mockAlert} onClick={vi.fn()} />);
      expect(screen.getByText(/Portfolio VaR/)).toBeInTheDocument();
    });

    it("renders source badge", () => {
      render(<AlertCard alert={mockAlert} onClick={vi.fn()} />);
      expect(screen.getByText("risk-gate")).toBeInTheDocument();
    });

    it("renders formatted timestamp", () => {
      render(<AlertCard alert={mockAlert} onClick={vi.fn()} />);
      // With the clock pinned in beforeEach, mockAlert.created_at is exactly
      // 6 hours in the past, so the formatter returns "6 hours ago".
      const timeText = screen.getByText(/ago|just now/i);
      expect(timeText).toBeInTheDocument();
    });
  });

  describe("severity styling", () => {
    it("critical severity has red left border", () => {
      const { container } = render(<AlertCard alert={mockAlert} onClick={vi.fn()} />);
      const card = container.querySelector("[data-testid=alert-card]");
      expect(card).toHaveClass("border-l-red-600");
    });

    it("warning severity has amber left border", () => {
      const warningAlert: Alert = {
        ...mockAlert,
        severity: "warning",
      };
      const { container } = render(<AlertCard alert={warningAlert} onClick={vi.fn()} />);
      const card = container.querySelector("[data-testid=alert-card]");
      expect(card).toHaveClass("border-l-amber-600");
    });

    it("info severity has blue left border", () => {
      const infoAlert: Alert = {
        ...mockAlert,
        severity: "info",
      };
      const { container } = render(<AlertCard alert={infoAlert} onClick={vi.fn()} />);
      const card = container.querySelector("[data-testid=alert-card]");
      expect(card).toHaveClass("border-l-blue-600");
    });

    it("critical severity has AlertTriangle icon", () => {
      const { container } = render(<AlertCard alert={mockAlert} onClick={vi.fn()} />);
      const icon = container.querySelector("[data-testid=alert-icon]");
      expect(icon).toBeInTheDocument();
      expect(icon?.querySelector("svg")).toBeInTheDocument();
    });
  });

  describe("acknowledged state", () => {
    it("unacknowledged alert is fully visible", () => {
      const { container } = render(<AlertCard alert={mockAlert} onClick={vi.fn()} />);
      const card = container.querySelector("[data-testid=alert-card]");
      expect(card).not.toHaveClass("opacity-60");
    });

    it("acknowledged alert is dimmed", () => {
      const acknowledgedAlert: Alert = {
        ...mockAlert,
        acknowledged: true,
      };
      const { container } = render(<AlertCard alert={acknowledgedAlert} onClick={vi.fn()} />);
      const card = container.querySelector("[data-testid=alert-card]");
      expect(card).toHaveClass("opacity-60");
    });

    it("shows check badge for acknowledged alert", () => {
      const acknowledgedAlert: Alert = {
        ...mockAlert,
        acknowledged: true,
      };
      const { container } = render(<AlertCard alert={acknowledgedAlert} onClick={vi.fn()} />);
      const badge = container.querySelector("[data-testid=acknowledged-badge]");
      expect(badge).toBeInTheDocument();
    });
  });

  describe("interaction", () => {
    it("calls onClick when card is clicked", async () => {
      const onClickMock = vi.fn();
      render(<AlertCard alert={mockAlert} onClick={onClickMock} />);

      const card = screen.getByRole("button", { hidden: true });
      await userEvent.click(card);

      expect(onClickMock).toHaveBeenCalledOnce();
      expect(onClickMock).toHaveBeenCalledWith(mockAlert);
    });

    it("truncates long message to 2 lines", () => {
      const longAlert: Alert = {
        ...mockAlert,
        message:
          "This is a very long message that should be truncated to two lines. " +
          "It continues on and on to demonstrate the text truncation behavior.",
      };
      const { container } = render(<AlertCard alert={longAlert} onClick={vi.fn()} />);
      const message = container.querySelector("[data-testid=alert-message]");
      expect(message).toHaveClass("line-clamp-2");
    });
  });
});
