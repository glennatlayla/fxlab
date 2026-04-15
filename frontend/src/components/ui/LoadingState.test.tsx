/**
 * Tests for LoadingState component.
 */

import { render, screen } from "@testing-library/react";
import { describe, it, expect } from "vitest";
import { LoadingState } from "./LoadingState";

describe("LoadingState", () => {
  it("renders with default message", () => {
    render(<LoadingState />);
    expect(screen.getByText("Loading…")).toBeInTheDocument();
  });

  it("renders with custom message", () => {
    render(<LoadingState message="Fetching feeds…" />);
    expect(screen.getByText("Fetching feeds…")).toBeInTheDocument();
  });

  it("has role='status' for accessibility", () => {
    render(<LoadingState />);
    expect(screen.getByRole("status")).toBeInTheDocument();
  });
});
