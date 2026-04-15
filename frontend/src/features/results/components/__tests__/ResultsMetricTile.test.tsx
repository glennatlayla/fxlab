/**
 * Tests for ResultsMetricTile component.
 *
 * AC-1: Tile renders label and value.
 * AC-2: Sentiment prop controls color: positive=green, negative=red, neutral=default, warning=amber.
 * AC-3: Icon from lucide-react renders when provided; omitted when not.
 */

import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { TrendingUp, TrendingDown } from "lucide-react";
import { ResultsMetricTile } from "../ResultsMetricTile";

describe("ResultsMetricTile", () => {
  // AC-1: Renders label and value
  it("renders label and value", () => {
    render(
      <ResultsMetricTile
        label="Total Return"
        value="+12.5%"
        sentiment="positive"
      />
    );
    expect(screen.getByText("Total Return")).toBeInTheDocument();
    expect(screen.getByText("+12.5%")).toBeInTheDocument();
  });

  // AC-2: Sentiment colors
  it("applies green color for positive sentiment", () => {
    const { container } = render(
      <ResultsMetricTile
        label="Sharpe Ratio"
        value="1.85"
        sentiment="positive"
      />
    );
    const tile = container.querySelector("[data-sentiment='positive']");
    expect(tile).toBeInTheDocument();
    // Color is applied to the value span inside the tile
    const valueSpan = tile?.querySelector("span:nth-child(2)");
    expect(valueSpan).toHaveClass("text-green-400");
  });

  it("applies red color for negative sentiment", () => {
    const { container } = render(
      <ResultsMetricTile
        label="Max Drawdown"
        value="-15.2%"
        sentiment="negative"
      />
    );
    const tile = container.querySelector("[data-sentiment='negative']");
    expect(tile).toBeInTheDocument();
    const valueSpan = tile?.querySelector("span:nth-child(2)");
    expect(valueSpan).toHaveClass("text-red-400");
  });

  it("applies default color for neutral sentiment", () => {
    const { container } = render(
      <ResultsMetricTile
        label="Trade Count"
        value="42"
        sentiment="neutral"
      />
    );
    const tile = container.querySelector("[data-sentiment='neutral']");
    expect(tile).toBeInTheDocument();
    const valueSpan = tile?.querySelector("span:nth-child(2)");
    expect(valueSpan).toHaveClass("text-surface-700");
  });

  it("applies amber color for warning sentiment", () => {
    const { container } = render(
      <ResultsMetricTile
        label="Win Rate"
        value="45%"
        sentiment="warning"
      />
    );
    const tile = container.querySelector("[data-sentiment='warning']");
    expect(tile).toBeInTheDocument();
    const valueSpan = tile?.querySelector("span:nth-child(2)");
    expect(valueSpan).toHaveClass("text-amber-400");
  });

  // AC-3: Icon rendering
  it("renders icon when provided", () => {
    render(
      <ResultsMetricTile
        label="Total Return"
        value="+12.5%"
        sentiment="positive"
        icon={TrendingUp}
      />
    );
    const icon = screen.getByTestId("metric-tile-icon");
    expect(icon).toBeInTheDocument();
  });

  it("does not render icon when omitted", () => {
    render(
      <ResultsMetricTile
        label="Total Return"
        value="+12.5%"
        sentiment="positive"
      />
    );
    const icon = screen.queryByTestId("metric-tile-icon");
    expect(icon).not.toBeInTheDocument();
  });

  it("renders custom icon correctly", () => {
    const { container } = render(
      <ResultsMetricTile
        label="Decline"
        value="-8.3%"
        sentiment="negative"
        icon={TrendingDown}
      />
    );
    const svgIcon = container.querySelector("svg");
    expect(svgIcon).toBeInTheDocument();
  });
});
