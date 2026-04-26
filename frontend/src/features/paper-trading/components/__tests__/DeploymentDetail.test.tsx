/**
 * DeploymentDetail component tests — full paper trading deployment details.
 *
 * Test cases:
 *   - test_renders_account_summary: Shows equity, P&L, and margin summary
 *   - test_renders_positions_list: Displays all open positions with entry/current prices
 *   - test_renders_orders_list: Displays pending and filled orders with status
 *   - test_renders_freeze_button_for_active: Freeze button visible for active deployment
 *   - test_renders_unfreeze_button_for_frozen: Unfreeze button visible for frozen deployment
 *   - test_freeze_button_disabled_while_loading: Button disabled during freeze operation
 *   - test_unfreeze_button_disabled_while_loading: Button disabled during unfreeze operation
 *   - test_click_freeze_calls_onFreeze: Freeze button triggers callback
 *   - test_click_unfreeze_calls_onUnfreeze: Unfreeze button triggers callback
 *   - test_renders_empty_positions_state: Shows message when no positions
 *   - test_renders_empty_orders_state: Shows message when no orders
 */

import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, it, expect, vi } from "vitest";
import { DeploymentDetail } from "../DeploymentDetail";
import type { PaperDeploymentSummary, PaperPosition, PaperOrder } from "../../types";
import { PAPER_DEPLOYMENT_STATUS, ORDER_STATUS } from "../../types";

describe("DeploymentDetail", () => {
  const mockDeployment: PaperDeploymentSummary = {
    id: "01ARZ3NDEKTSV4RRFFQ69G5FAV",
    strategy_name: "Momentum Breakout",
    status: PAPER_DEPLOYMENT_STATUS.ACTIVE,
    equity: 12500,
    initial_equity: 10000,
    unrealized_pnl: 1200,
    realized_pnl: 300,
    total_pnl: 1500,
    open_positions: 2,
    open_orders: 1,
    started_at: "2026-04-01T10:00:00Z",
    last_trade_at: "2026-04-13T14:30:00Z",
  };

  const mockPositions: PaperPosition[] = [
    {
      symbol: "AAPL",
      side: "long",
      quantity: 10,
      entry_price: 150.0,
      current_price: 160.0,
      unrealized_pnl: 100.0,
      pnl_pct: 6.67,
    },
    {
      symbol: "MSFT",
      side: "short",
      quantity: 5,
      entry_price: 300.0,
      current_price: 290.0,
      unrealized_pnl: 50.0,
      pnl_pct: 3.33,
    },
  ];

  const mockOrders: PaperOrder[] = [
    {
      id: "order-001",
      symbol: "TSLA",
      side: "long",
      type: "limit",
      quantity: 5,
      price: 250.0,
      status: ORDER_STATUS.PENDING,
      created_at: "2026-04-13T14:00:00Z",
    },
  ];

  it("test_renders_account_summary", () => {
    render(
      <DeploymentDetail
        deployment={mockDeployment}
        positions={mockPositions}
        orders={mockOrders}
        isLoading={false}
        onFreeze={vi.fn()}
        onUnfreeze={vi.fn()}
      />,
    );

    expect(screen.getByText(/Momentum Breakout/)).toBeInTheDocument();
    expect(screen.getByText(/\$12,500/)).toBeInTheDocument();
    expect(screen.getByText(/\$1,500/)).toBeInTheDocument();
  });

  it("test_renders_positions_list", () => {
    render(
      <DeploymentDetail
        deployment={mockDeployment}
        positions={mockPositions}
        orders={mockOrders}
        isLoading={false}
        onFreeze={vi.fn()}
        onUnfreeze={vi.fn()}
      />,
    );

    expect(screen.getByText("AAPL")).toBeInTheDocument();
    expect(screen.getByText("MSFT")).toBeInTheDocument();
    expect(screen.getByText(/\$150/)).toBeInTheDocument();
    expect(screen.getByText(/\$160/)).toBeInTheDocument();
  });

  it("test_renders_orders_list", () => {
    render(
      <DeploymentDetail
        deployment={mockDeployment}
        positions={mockPositions}
        orders={mockOrders}
        isLoading={false}
        onFreeze={vi.fn()}
        onUnfreeze={vi.fn()}
      />,
    );

    expect(screen.getByText("TSLA")).toBeInTheDocument();
    expect(screen.getByText(/pending/i)).toBeInTheDocument();
  });

  it("test_renders_freeze_button_for_active", () => {
    render(
      <DeploymentDetail
        deployment={mockDeployment}
        positions={mockPositions}
        orders={mockOrders}
        isLoading={false}
        onFreeze={vi.fn()}
        onUnfreeze={vi.fn()}
      />,
    );

    const freezeButton = screen.getByRole("button", { name: /freeze/i });
    expect(freezeButton).toBeInTheDocument();
    expect(freezeButton).not.toBeDisabled();
  });

  it("test_renders_unfreeze_button_for_frozen", () => {
    const frozenDeploy: PaperDeploymentSummary = {
      ...mockDeployment,
      status: PAPER_DEPLOYMENT_STATUS.FROZEN,
    };

    render(
      <DeploymentDetail
        deployment={frozenDeploy}
        positions={mockPositions}
        orders={mockOrders}
        isLoading={false}
        onFreeze={vi.fn()}
        onUnfreeze={vi.fn()}
      />,
    );

    const unfreezeButton = screen.getByRole("button", { name: /unfreeze/i });
    expect(unfreezeButton).toBeInTheDocument();
    expect(unfreezeButton).not.toBeDisabled();
  });

  it("test_freeze_button_disabled_while_loading", () => {
    render(
      <DeploymentDetail
        deployment={mockDeployment}
        positions={mockPositions}
        orders={mockOrders}
        isLoading={true}
        onFreeze={vi.fn()}
        onUnfreeze={vi.fn()}
      />,
    );

    const freezeButton = screen.getByRole("button", { name: /freeze/i });
    expect(freezeButton).toBeDisabled();
  });

  it("test_unfreeze_button_disabled_while_loading", () => {
    const frozenDeploy: PaperDeploymentSummary = {
      ...mockDeployment,
      status: PAPER_DEPLOYMENT_STATUS.FROZEN,
    };

    render(
      <DeploymentDetail
        deployment={frozenDeploy}
        positions={mockPositions}
        orders={mockOrders}
        isLoading={true}
        onFreeze={vi.fn()}
        onUnfreeze={vi.fn()}
      />,
    );

    const unfreezeButton = screen.getByRole("button", { name: /unfreeze/i });
    expect(unfreezeButton).toBeDisabled();
  });

  it("test_click_freeze_calls_onFreeze", async () => {
    const onFreeze = vi.fn();
    render(
      <DeploymentDetail
        deployment={mockDeployment}
        positions={mockPositions}
        orders={mockOrders}
        isLoading={false}
        onFreeze={onFreeze}
        onUnfreeze={vi.fn()}
      />,
    );

    const freezeButton = screen.getByRole("button", { name: /freeze/i });
    await userEvent.click(freezeButton);
    expect(onFreeze).toHaveBeenCalled();
  });

  it("test_click_unfreeze_calls_onUnfreeze", async () => {
    const onUnfreeze = vi.fn();
    const frozenDeploy: PaperDeploymentSummary = {
      ...mockDeployment,
      status: PAPER_DEPLOYMENT_STATUS.FROZEN,
    };

    render(
      <DeploymentDetail
        deployment={frozenDeploy}
        positions={mockPositions}
        orders={mockOrders}
        isLoading={false}
        onFreeze={vi.fn()}
        onUnfreeze={onUnfreeze}
      />,
    );

    const unfreezeButton = screen.getByRole("button", { name: /unfreeze/i });
    await userEvent.click(unfreezeButton);
    expect(onUnfreeze).toHaveBeenCalled();
  });

  it("test_renders_empty_positions_state", () => {
    render(
      <DeploymentDetail
        deployment={mockDeployment}
        positions={[]}
        orders={mockOrders}
        isLoading={false}
        onFreeze={vi.fn()}
        onUnfreeze={vi.fn()}
      />,
    );

    expect(screen.getByText(/no open positions/i)).toBeInTheDocument();
  });

  it("test_renders_empty_orders_state", () => {
    render(
      <DeploymentDetail
        deployment={mockDeployment}
        positions={mockPositions}
        orders={[]}
        isLoading={false}
        onFreeze={vi.fn()}
        onUnfreeze={vi.fn()}
      />,
    );

    expect(screen.getByText(/no orders/i)).toBeInTheDocument();
  });

  it("test_renders_different_position_sides", () => {
    const mixedPositions: PaperPosition[] = [
      {
        symbol: "SPY",
        side: "long",
        quantity: 10,
        entry_price: 450.0,
        current_price: 455.0,
        unrealized_pnl: 50.0,
        pnl_pct: 1.11,
      },
      {
        symbol: "QQQ",
        side: "short",
        quantity: 5,
        entry_price: 350.0,
        current_price: 345.0,
        unrealized_pnl: 25.0,
        pnl_pct: 1.43,
      },
    ];

    render(
      <DeploymentDetail
        deployment={mockDeployment}
        positions={mixedPositions}
        orders={mockOrders}
        isLoading={false}
        onFreeze={vi.fn()}
        onUnfreeze={vi.fn()}
      />,
    );

    // Check that both symbols appear (which imply their sides are shown)
    expect(screen.getByText("SPY")).toBeInTheDocument();
    expect(screen.getByText("QQQ")).toBeInTheDocument();
    const longElements = screen.getAllByText(/long/i);
    const shortElements = screen.getAllByText(/short/i);
    expect(longElements.length).toBeGreaterThan(0);
    expect(shortElements.length).toBeGreaterThan(0);
  });
});
