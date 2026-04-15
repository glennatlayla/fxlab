/**
 * Tests for GradeBadge component.
 *
 * AC-2: A-F grade badges use correct color mapping.
 */

import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { GradeBadge } from "./GradeBadge";

describe("GradeBadge", () => {
  it("renders the grade letter", () => {
    render(<GradeBadge grade="A" />);
    expect(screen.getByText("A")).toBeInTheDocument();
  });

  it("applies emerald classes for grade A", () => {
    render(<GradeBadge grade="A" />);
    const badge = screen.getByTestId("grade-badge");
    expect(badge.className).toContain("emerald");
  });

  it("applies blue classes for grade B", () => {
    render(<GradeBadge grade="B" />);
    const badge = screen.getByTestId("grade-badge");
    expect(badge.className).toContain("blue");
  });

  it("applies yellow classes for grade C", () => {
    render(<GradeBadge grade="C" />);
    const badge = screen.getByTestId("grade-badge");
    expect(badge.className).toContain("yellow");
  });

  it("applies orange classes for grade D", () => {
    render(<GradeBadge grade="D" />);
    const badge = screen.getByTestId("grade-badge");
    expect(badge.className).toContain("orange");
  });

  it("applies red classes for grade F", () => {
    render(<GradeBadge grade="F" />);
    const badge = screen.getByTestId("grade-badge");
    expect(badge.className).toContain("red");
  });

  it("renders sm size variant", () => {
    render(<GradeBadge grade="A" size="sm" />);
    const badge = screen.getByTestId("grade-badge");
    expect(badge.className).toContain("text-sm");
  });

  it("renders lg size variant", () => {
    render(<GradeBadge grade="A" size="lg" />);
    const badge = screen.getByTestId("grade-badge");
    expect(badge.className).toContain("text-3xl");
  });
});
