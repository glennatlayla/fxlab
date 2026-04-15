/**
 * DeploymentCard component tests — mobile-optimized paper trading card.
 *
 * Test cases:
 *   - test_renders_strategy_name: Card displays the strategy name
 *   - test_renders_status_badge: Status badge is rendered with correct status
 *   - test_renders_pnl_total_green_positive: Total P&L is green when positive
 *   - test_renders_pnl_total_red_negative: Total P&L is red when negative
 *   - test_renders_equity_comparison: Shows equity vs initial equity
 *   - test_renders_position_count: Displays number of open positions
 *   - test_renders_order_count: Displays number of open orders
 *   - test_renders_last_trade_timestamp: Shows last trade time if available
 *   - test_click_calls_onClick_with_deployment_id: Entire card is clickable
 *   - test_frozen_status_shows_frozen_badge: Frozen deployments show frozen indicator
 */

import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, it, expect, vi } from "vitest";
import { DeploymentCard } from "../DeploymentCard";
import type { PaperDeploymentSummary } from "../../types";
import { PAPER_DEPLOYMENT_STATUS } from "../../types";

describe("DeploymentCard", () => {
  const mockDeployment: PaperDeploymentSummary = {
    id: "01ARZ3NDEKTSV4RRFFQ69G5FAV",
    strategy_name: "Momentum Breakout",
    status: PAPER_DEPLOYMENT_STATUS.ACTIVE,
    equity: 12500,
    initial_equity: 10000,
    unrealized_pnl: 1200,
    realized_pnl: 300,
    total_pnl: 1500,
    open_positions: 3,
    open_orders: 2,
    started_at: "2026-04-01T10:00:00Z",
    last_trade_at: "2026-04-13T14:30:00Z",
  };

  it("test_renders_strategy_name", () => {
    render(<DeploymentCard deployment={mockDeployment} onClick={vi.fn()} />);
    expect(screen.getByText("Momentum Breakout")).toBeInTheDocument();
  });

  it("test_renders_status_badge", () => {
    render(<DeploymentCard deployment={mockDeployment} onClick={vi.fn()} />);
    const badge = screen.getByRole("status");
    expect(badge).toBeInTheDocument();
    expect(badge).toHaveTextContent("active");
  });

  it("test_renders_pnl_total_green_positive", () => {
    render(<DeploymentCard deployment={mockDeployment} onClick={vi.fn()} />);
    const pnlElements = screen.getAllByText(/\$1,500/);
    expect(pnlElements.length).toBeGreaterThan(0);
    const container = pnlElements[0].closest("div");
    expect(container).toHaveClass("text-green-400");
  });

  it("test_renders_pnl_total_red_negative", () => {
    const negativeDeploy: PaperDeploymentSummary = {
      ...mockDeployment,
      total_pnl: -500,
      equity: 9500,
    };
    render(
      <DeploymentCard deployment={negativeDeploy} onClick={vi.fn()} />
    );
    const pnlElements = screen.getAllByText(/-\$500/);
    expect(pnlElements.length).toBeGreaterThan(0);
    const container = pnlElements[0].closest("div");
    expect(container).toHaveClass("text-red-400");
  });

  it("test_renders_equity_comparison", () => {
    render(<DeploymentCard deployment={mockDeployment} onClick={vi.fn()} />);
    expect(screen.getByText(/\$12,500/)).toBeInTheDocument();
    expect(screen.getByText(/\$10,000/)).toBeInTheDocument();
  });

  it("test_renders_position_count", () => {
    render(<DeploymentCard deployment={mockDeployment} onClick={vi.fn()} />);
    expect(screen.getByText(/3.*positions/i)).toBeInTheDocument();
  });

  it("test_renders_order_count", () => {
    render(<DeploymentCard deployment={mockDeployment} onClick={vi.fn()} />);
    expect(screen.getByText(/2.*orders/i)).toBeInTheDocument();
  });

  it("test_renders_last_trade_timestamp", () => {
    render(<DeploymentCard deployment={mockDeployment} onClick={vi.fn()} />);
    // The timestamp is rendered as relative time (e.g., "8h ago")
    // Just check that some time text is present
    const container = screen.getByTestId("deployment-card");
    expect(container.textContent).toMatch(/ago|never/i);
  });

  it("test_click_calls_onClick_with_deployment_id", async () => {
    const onClick = vi.fn();
    const { container } = render(
      <DeploymentCard deployment={mockDeployment} onClick={onClick} />
    );
    const card = container.querySelector("[data-testid='deployment-card']");
    expect(card).toBeInTheDocument();

    if (card) {
      await userEvent.click(card);
      expect(onClick).toHaveBeenCalledWith(mockDeployment.id);
    }
  });

  it("test_frozen_status_shows_frozen_badge", () => {
    const frozenDeploy: PaperDeploymentSummary = {
      ...mockDeployment,
      status: PAPER_DEPLOYMENT_STATUS.FROZEN,
    };
    render(
      <DeploymentCard deployment={frozenDeploy} onClick={vi.fn()} />
    );
    const badge = screen.getByRole("status");
    expect(badge).toHaveTextContent("frozen");
  });

  it("test_handles_zero_pnl", () => {
    const zeroPnlDeploy: PaperDeploymentSummary = {
      ...mockDeployment,
      total_pnl: 0,
      unrealized_pnl: 0,
      realized_pnl: 0,
      equity: mockDeployment.initial_equity,
    };
    render(
      <DeploymentCard deployment={zeroPnlDeploy} onClick={vi.fn()} />
    );
    // Check that Total P&L shows $0.00
    const pnlElements = screen.getAllByText(/\$0.00/);
    expect(pnlElements.length).toBeGreaterThan(0);
  });

  it("test_handles_no_last_trade_yet", () => {
    const noTradesDeploy: PaperDeploymentSummary = {
      ...mockDeployment,
      last_trade_at: null,
    };
    render(
      <DeploymentCard deployment={noTradesDeploy} onClick={vi.fn()} />
    );
    expect(screen.queryByText(/never/i)).toBeInTheDocument();
  });

  it("test_handles_different_statuses", () => {
    const statuses = [
      PAPER_DEPLOYMENT_STATUS.ACTIVE,
      PAPER_DEPLOYMENT_STATUS.PAUSED,
      PAPER_DEPLOYMENT_STATUS.FROZEN,
      PAPER_DEPLOYMENT_STATUS.STOPPED,
    ];

    statuses.forEach((status) => {
      const { unmount } = render(
        <DeploymentCard
          deployment={{ ...mockDeployment, status }}
          onClick={vi.fn()}
        />
      );
      const badge = screen.getByRole("status");
      expect(badge).toBeInTheDocument();
      unmount();
    });
  });
});
