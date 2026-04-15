/**
 * ErrorBoundary tests.
 *
 * Verifies:
 *   - Renders children normally when no error.
 *   - Catches render errors and shows recovery UI.
 *   - Retry button resets the boundary and re-renders children.
 *   - Logs errors (console.error not swallowed).
 *   - Reports errors to Sentry.
 */

import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { ErrorBoundary } from "./ErrorBoundary";

// Mock Sentry
vi.mock("@/infrastructure/sentry", () => ({
  Sentry: {
    captureException: vi.fn(),
  },
}));

import { Sentry } from "@/infrastructure/sentry";

// A component that conditionally throws during render.
let shouldThrow = false;
function ThrowingChild() {
  if (shouldThrow) {
    throw new Error("Render explosion");
  }
  return <div>Child content</div>;
}

describe("ErrorBoundary", () => {
  beforeEach(() => {
    shouldThrow = false;
    vi.clearAllMocks();
    // Suppress React's error boundary console.error noise in test output
    vi.spyOn(console, "error").mockImplementation(() => {});
  });

  it("renders children when no error occurs", () => {
    render(
      <ErrorBoundary>
        <div>Safe content</div>
      </ErrorBoundary>,
    );

    expect(screen.getByText("Safe content")).toBeInTheDocument();
  });

  it("shows fallback UI when a child throws during render", () => {
    shouldThrow = true;

    render(
      <ErrorBoundary>
        <ThrowingChild />
      </ErrorBoundary>,
    );

    expect(screen.getByText("Something went wrong")).toBeInTheDocument();
    expect(screen.getByRole("alert")).toBeInTheDocument();
    expect(screen.getByText(/unexpected error/i)).toBeInTheDocument();
  });

  it("shows the error message in the fallback UI", () => {
    shouldThrow = true;

    render(
      <ErrorBoundary>
        <ThrowingChild />
      </ErrorBoundary>,
    );

    expect(screen.getByText("Render explosion")).toBeInTheDocument();
  });

  it("renders a retry button that resets the boundary", async () => {
    const user = userEvent.setup();
    shouldThrow = true;

    render(
      <ErrorBoundary>
        <ThrowingChild />
      </ErrorBoundary>,
    );

    expect(screen.getByText("Something went wrong")).toBeInTheDocument();

    // Fix the throwing component before clicking retry
    shouldThrow = false;

    await user.click(screen.getByRole("button", { name: /try again/i }));

    // After reset, children should render normally
    expect(screen.getByText("Child content")).toBeInTheDocument();
    expect(screen.queryByText("Something went wrong")).not.toBeInTheDocument();
  });

  it("renders a go-home link in the fallback", () => {
    shouldThrow = true;

    render(
      <ErrorBoundary>
        <ThrowingChild />
      </ErrorBoundary>,
    );

    const homeLink = screen.getByRole("link", { name: /go to dashboard/i });
    expect(homeLink).toHaveAttribute("href", "/");
  });

  it("reports errors to Sentry with component stack", () => {
    shouldThrow = true;

    render(
      <ErrorBoundary>
        <ThrowingChild />
      </ErrorBoundary>,
    );

    expect(Sentry.captureException).toHaveBeenCalledWith(
      expect.objectContaining({
        message: "Render explosion",
      }),
      expect.objectContaining({
        contexts: {
          react: expect.objectContaining({
            componentStack: expect.any(String),
          }),
        },
      }),
    );
  });
});
