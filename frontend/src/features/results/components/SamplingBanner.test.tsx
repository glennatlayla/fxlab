/**
 * Tests for SamplingBanner component.
 *
 * Verifies that the LTTB downsampling banner renders when sampling was
 * applied (AC-2) and hides when it was not.
 */

import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { SamplingBanner } from "./SamplingBanner";

describe("SamplingBanner", () => {
  it("renders warning when sampling_applied is true", () => {
    render(
      <SamplingBanner samplingApplied={true} rawPointCount={5000} displayedPointCount={2000} />,
    );
    const banner = screen.getByTestId("sampling-banner");
    expect(banner).toBeInTheDocument();
    expect(banner).toHaveTextContent(/5,?000/);
    expect(banner).toHaveTextContent(/2,?000/);
  });

  it("does not render when sampling_applied is false", () => {
    render(
      <SamplingBanner samplingApplied={false} rawPointCount={400} displayedPointCount={400} />,
    );
    expect(screen.queryByTestId("sampling-banner")).not.toBeInTheDocument();
  });

  it("includes role='alert' for accessibility", () => {
    render(
      <SamplingBanner samplingApplied={true} rawPointCount={3000} displayedPointCount={2000} />,
    );
    expect(screen.getByRole("alert")).toBeInTheDocument();
  });

  it("includes LTTB reference in the message text", () => {
    render(
      <SamplingBanner samplingApplied={true} rawPointCount={8000} displayedPointCount={2000} />,
    );
    expect(screen.getByTestId("sampling-banner")).toHaveTextContent(/LTTB|downsample/i);
  });
});
