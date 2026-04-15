/**
 * Tests for TradesTruncatedBanner component.
 *
 * Verifies that the trades truncation warning renders when trades
 * were truncated (AC-3), shows the total count, and includes a
 * download callback.
 */

import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { TradesTruncatedBanner } from "./TradesTruncatedBanner";

describe("TradesTruncatedBanner", () => {
  it("renders warning when trades_truncated is true", () => {
    render(
      <TradesTruncatedBanner tradesTruncated={true} totalTradeCount={8000} onDownload={vi.fn()} />,
    );
    const banner = screen.getByTestId("trades-truncated-banner");
    expect(banner).toBeInTheDocument();
    expect(banner).toHaveTextContent(/8,?000/);
  });

  it("does not render when trades_truncated is false", () => {
    render(
      <TradesTruncatedBanner tradesTruncated={false} totalTradeCount={500} onDownload={vi.fn()} />,
    );
    expect(screen.queryByTestId("trades-truncated-banner")).not.toBeInTheDocument();
  });

  it("includes a download button that calls onDownload", async () => {
    const user = userEvent.setup();
    const onDownload = vi.fn();
    render(
      <TradesTruncatedBanner
        tradesTruncated={true}
        totalTradeCount={6000}
        onDownload={onDownload}
      />,
    );
    const btn = screen.getByRole("button", { name: /download/i });
    await user.click(btn);
    expect(onDownload).toHaveBeenCalledOnce();
  });

  it("includes role='alert' for accessibility", () => {
    render(
      <TradesTruncatedBanner tradesTruncated={true} totalTradeCount={7000} onDownload={vi.fn()} />,
    );
    expect(screen.getByRole("alert")).toBeInTheDocument();
  });
});
