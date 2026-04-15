/**
 * Tests for ErrorState component.
 */

import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, it, expect, vi } from "vitest";
import { ErrorState } from "./ErrorState";

describe("ErrorState", () => {
  it("renders error message", () => {
    render(<ErrorState message="Connection failed" />);
    expect(screen.getByText("Connection failed")).toBeInTheDocument();
  });

  it("has role='alert' for accessibility", () => {
    render(<ErrorState message="Error" />);
    expect(screen.getByRole("alert")).toBeInTheDocument();
  });

  it("renders Retry button when onRetry is provided", () => {
    render(<ErrorState message="Error" onRetry={() => {}} />);
    expect(screen.getByRole("button", { name: "Retry" })).toBeInTheDocument();
  });

  it("does not render Retry button when onRetry is omitted", () => {
    render(<ErrorState message="Error" />);
    expect(screen.queryByRole("button", { name: "Retry" })).not.toBeInTheDocument();
  });

  it("calls onRetry when Retry button is clicked", async () => {
    const onRetry = vi.fn();
    render(<ErrorState message="Error" onRetry={onRetry} />);
    await userEvent.click(screen.getByRole("button", { name: "Retry" }));
    expect(onRetry).toHaveBeenCalledTimes(1);
  });
});
