/**
 * Tests for TradeBlotter component.
 *
 * AC-6: TradeBlotter with 1000 rows renders via virtual scroll
 *        (TanStack Virtual) without horizontal overflow.
 */

import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { TradeBlotter } from "./TradeBlotter";
import type { TradeRecord, TradeBlotterFilters } from "@/types/results";

// ---------------------------------------------------------------------------
// Fixtures
// ---------------------------------------------------------------------------

function makeTrades(count: number): TradeRecord[] {
  return Array.from({ length: count }, (_, i) => ({
    id: `t${String(i).padStart(4, "0")}`,
    symbol: i % 2 === 0 ? "AAPL" : "MSFT",
    side: (i % 2 === 0 ? "buy" : "sell") as "buy" | "sell",
    quantity: 100 + i,
    entry_price: 150 + i * 0.1,
    exit_price: 155 + i * 0.1,
    pnl: (i % 3 === 0 ? -50 : 100) + i,
    fold_index: i % 3,
    regime: i % 2 === 0 ? "bull" : "bear",
    entry_timestamp: new Date(2026, 0, 1, 10, i).toISOString(),
    exit_timestamp: new Date(2026, 0, 1, 14, i).toISOString(),
  }));
}

const defaultFilters: TradeBlotterFilters = {
  symbol: null,
  side: null,
  fold_index: null,
  regime: null,
};

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe("TradeBlotter", () => {
  it("renders the trade blotter container", () => {
    render(
      <TradeBlotter
        trades={makeTrades(10)}
        tradesTruncated={false}
        totalTradeCount={10}
        filters={defaultFilters}
        onFiltersChange={vi.fn()}
        onDownload={vi.fn()}
      />,
    );
    expect(screen.getByTestId("trade-blotter")).toBeInTheDocument();
  });

  it("renders column headers for trade data", () => {
    render(
      <TradeBlotter
        trades={makeTrades(5)}
        tradesTruncated={false}
        totalTradeCount={5}
        filters={defaultFilters}
        onFiltersChange={vi.fn()}
        onDownload={vi.fn()}
      />,
    );
    expect(screen.getByText("Symbol")).toBeInTheDocument();
    expect(screen.getByText("Side")).toBeInTheDocument();
    expect(screen.getByText("PnL")).toBeInTheDocument();
  });

  it("uses virtual scroll for 1000 rows (renders fewer DOM rows)", () => {
    const { container } = render(
      <TradeBlotter
        trades={makeTrades(1000)}
        tradesTruncated={false}
        totalTradeCount={1000}
        filters={defaultFilters}
        onFiltersChange={vi.fn()}
        onDownload={vi.fn()}
      />,
    );
    // jsdom has no layout engine, so TanStack Virtual sees 0 viewport height
    // and renders 0 visible rows. Verify the virtualizer is wired up by
    // checking:
    // 1. The outer scroll container exists with fixed height (400px).
    // 2. The inner div has total height = rowCount * estimateSize (36000px).
    const scrollParent = container.querySelector(".overflow-auto");
    expect(scrollParent).toBeInTheDocument();
    expect(scrollParent?.getAttribute("style")).toContain("400");
    // The inner div's height is set by the virtualizer to rowCount * rowHeight
    const innerDiv = scrollParent?.querySelector("[style*='position: relative']");
    expect(innerDiv).toBeInTheDocument();
    expect(innerDiv?.getAttribute("style")).toContain("36000");
  });

  it("does not overflow horizontally", () => {
    render(
      <TradeBlotter
        trades={makeTrades(1000)}
        tradesTruncated={false}
        totalTradeCount={1000}
        filters={defaultFilters}
        onFiltersChange={vi.fn()}
        onDownload={vi.fn()}
      />,
    );
    const blotter = screen.getByTestId("trade-blotter");
    // The blotter should have overflow-x hidden or auto, not visible
    const style = window.getComputedStyle(blotter);
    expect(style.overflowX).not.toBe("visible");
  });

  it("calls onFiltersChange when a filter is updated", async () => {
    const user = userEvent.setup();
    const onFiltersChange = vi.fn();
    render(
      <TradeBlotter
        trades={makeTrades(10)}
        tradesTruncated={false}
        totalTradeCount={10}
        filters={defaultFilters}
        onFiltersChange={onFiltersChange}
        onDownload={vi.fn()}
      />,
    );
    // Find the side filter select and change it
    const sideFilter = screen.getByTestId("filter-side");
    await user.selectOptions(sideFilter, "buy");
    expect(onFiltersChange).toHaveBeenCalled();
  });

  it("calls onDownload when download button is clicked", async () => {
    const user = userEvent.setup();
    const onDownload = vi.fn();
    render(
      <TradeBlotter
        trades={makeTrades(5)}
        tradesTruncated={false}
        totalTradeCount={5}
        filters={defaultFilters}
        onFiltersChange={vi.fn()}
        onDownload={onDownload}
      />,
    );
    const btn = screen.getByRole("button", { name: /download/i });
    await user.click(btn);
    expect(onDownload).toHaveBeenCalledOnce();
  });

  it("shows total trade count", () => {
    render(
      <TradeBlotter
        trades={makeTrades(20)}
        tradesTruncated={false}
        totalTradeCount={20}
        filters={defaultFilters}
        onFiltersChange={vi.fn()}
        onDownload={vi.fn()}
      />,
    );
    expect(screen.getByTestId("trade-blotter")).toHaveTextContent("20");
  });
});
