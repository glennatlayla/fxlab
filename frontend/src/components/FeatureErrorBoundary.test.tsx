/**
 * FeatureErrorBoundary tests.
 *
 * Verifies:
 *   - Renders children when no error occurs.
 *   - Catches render errors and shows inline error UI.
 *   - Displays the feature name in the error message.
 *   - Retry button resets the boundary.
 *   - Reports error to Sentry with featureName tag.
 */

import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { FeatureErrorBoundary } from "./FeatureErrorBoundary";

vi.mock("@/infrastructure/sentry", () => ({
  Sentry: {
    captureException: vi.fn(),
  },
}));

// Import after mocking
import { Sentry } from "@/infrastructure/sentry";

let shouldThrow = false;
function ThrowingChild() {
  if (shouldThrow) {
    throw new Error("Feature render failed");
  }
  return <div>Feature content</div>;
}

describe("FeatureErrorBoundary", () => {
  beforeEach(() => {
    shouldThrow = false;
    vi.clearAllMocks();
    vi.spyOn(console, "error").mockImplementation(() => {});
  });

  it("renders children when no error occurs", () => {
    render(
      <FeatureErrorBoundary featureName="Test Feature">
        <div>Feature works</div>
      </FeatureErrorBoundary>,
    );

    expect(screen.getByText("Feature works")).toBeInTheDocument();
  });

  it("shows inline error UI when a child throws", () => {
    shouldThrow = true;

    render(
      <FeatureErrorBoundary featureName="Strategy Studio">
        <ThrowingChild />
      </FeatureErrorBoundary>,
    );

    expect(screen.getByText(/Strategy Studio/i)).toBeInTheDocument();
    expect(screen.getByText(/failed to load/i)).toBeInTheDocument();
  });

  it("shows the error message in fallback UI", () => {
    shouldThrow = true;

    render(
      <FeatureErrorBoundary featureName="Test Feature">
        <ThrowingChild />
      </FeatureErrorBoundary>,
    );

    expect(screen.getByText("Feature render failed")).toBeInTheDocument();
  });

  it("renders a retry button that resets the boundary", async () => {
    const user = userEvent.setup();
    shouldThrow = true;

    render(
      <FeatureErrorBoundary featureName="Test Feature">
        <ThrowingChild />
      </FeatureErrorBoundary>,
    );

    expect(screen.getByText(/failed to load/i)).toBeInTheDocument();

    shouldThrow = false;

    await user.click(screen.getByRole("button", { name: /try again/i }));

    expect(screen.getByText("Feature content")).toBeInTheDocument();
    expect(screen.queryByText(/failed to load/i)).not.toBeInTheDocument();
  });

  it("shows custom fallback when provided", () => {
    shouldThrow = true;

    render(
      <FeatureErrorBoundary featureName="Test" fallback={<div>Custom error UI</div>}>
        <ThrowingChild />
      </FeatureErrorBoundary>,
    );

    expect(screen.getByText("Custom error UI")).toBeInTheDocument();
  });

  it("reports error to Sentry with featureName tag", () => {
    shouldThrow = true;

    render(
      <FeatureErrorBoundary featureName="Approvals">
        <ThrowingChild />
      </FeatureErrorBoundary>,
    );

    expect(Sentry.captureException).toHaveBeenCalledWith(
      expect.any(Error),
      expect.objectContaining({
        tags: {
          feature: "Approvals",
        },
      }),
    );
  });
});
