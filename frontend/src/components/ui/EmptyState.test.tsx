/**
 * Tests for EmptyState component.
 */

import { render, screen } from "@testing-library/react";
import { describe, it, expect } from "vitest";
import { EmptyState } from "./EmptyState";

describe("EmptyState", () => {
  it("renders title", () => {
    render(<EmptyState title="No runs yet" />);
    expect(screen.getByText("No runs yet")).toBeInTheDocument();
  });

  it("renders description when provided", () => {
    render(<EmptyState title="Empty" description="Start a backtest to see results here." />);
    expect(screen.getByText("Start a backtest to see results here.")).toBeInTheDocument();
  });

  it("renders action button when provided", () => {
    render(<EmptyState title="Empty" action={<button>Create Run</button>} />);
    expect(screen.getByRole("button", { name: "Create Run" })).toBeInTheDocument();
  });

  it("does not render description when omitted", () => {
    const { container } = render(<EmptyState title="Empty" />);
    expect(container.querySelectorAll("p")).toHaveLength(0);
  });
});
