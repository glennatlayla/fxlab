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
import { describe, it, expect, vi } from "vitest";
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
      // Timestamp should be displayed in relative or formatted form
      // It will show "just now", "minutes ago", "hours ago", etc. depending on current time
      const timeText = screen.getByText(/ago|just now/i);
      expect(timeText).toBeInTheDocument();
    });
  });

  describe("severity styling", () => {
    it("critical severity has red left border", () => {
      const { container } = render(
        <AlertCard alert={mockAlert} onClick={vi.fn()} />,
      );
      const card = container.querySelector("[data-testid=alert-card]");
      expect(card).toHaveClass("border-l-red-600");
    });

    it("warning severity has amber left border", () => {
      const warningAlert: Alert = {
        ...mockAlert,
        severity: "warning",
      };
      const { container } = render(
        <AlertCard alert={warningAlert} onClick={vi.fn()} />,
      );
      const card = container.querySelector("[data-testid=alert-card]");
      expect(card).toHaveClass("border-l-amber-600");
    });

    it("info severity has blue left border", () => {
      const infoAlert: Alert = {
        ...mockAlert,
        severity: "info",
      };
      const { container } = render(
        <AlertCard alert={infoAlert} onClick={vi.fn()} />,
      );
      const card = container.querySelector("[data-testid=alert-card]");
      expect(card).toHaveClass("border-l-blue-600");
    });

    it("critical severity has AlertTriangle icon", () => {
      const { container } = render(
        <AlertCard alert={mockAlert} onClick={vi.fn()} />,
      );
      const icon = container.querySelector("[data-testid=alert-icon]");
      expect(icon).toBeInTheDocument();
      expect(icon?.querySelector("svg")).toBeInTheDocument();
    });
  });

  describe("acknowledged state", () => {
    it("unacknowledged alert is fully visible", () => {
      const { container } = render(
        <AlertCard alert={mockAlert} onClick={vi.fn()} />,
      );
      const card = container.querySelector("[data-testid=alert-card]");
      expect(card).not.toHaveClass("opacity-60");
    });

    it("acknowledged alert is dimmed", () => {
      const acknowledgedAlert: Alert = {
        ...mockAlert,
        acknowledged: true,
      };
      const { container } = render(
        <AlertCard alert={acknowledgedAlert} onClick={vi.fn()} />,
      );
      const card = container.querySelector("[data-testid=alert-card]");
      expect(card).toHaveClass("opacity-60");
    });

    it("shows check badge for acknowledged alert", () => {
      const acknowledgedAlert: Alert = {
        ...mockAlert,
        acknowledged: true,
      };
      const { container } = render(
        <AlertCard alert={acknowledgedAlert} onClick={vi.fn()} />,
      );
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
      const { container } = render(
        <AlertCard alert={longAlert} onClick={vi.fn()} />,
      );
      const message = container.querySelector("[data-testid=alert-message]");
      expect(message).toHaveClass("line-clamp-2");
    });
  });
});
