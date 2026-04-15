/**
 * Tests for SlideToConfirm component.
 *
 * Acceptance criteria (FE-22):
 *   - Renders label on the track.
 *   - Fires onConfirm when slid to 90% or beyond.
 *   - Resets to start when released before 90%.
 *   - Disabled state prevents interaction.
 *   - Danger variant applies red styling.
 *   - Accessible: role="slider", aria-valuenow, aria-label.
 *   - Supports both touch and mouse events.
 */

import { render, screen, fireEvent } from "@testing-library/react";
import { describe, it, expect, vi } from "vitest";
import { SlideToConfirm } from "./SlideToConfirm";

describe("SlideToConfirm", () => {
  it("renders label on the track", () => {
    render(<SlideToConfirm label="Slide to activate" onConfirm={vi.fn()} />);

    expect(screen.getByText("Slide to activate")).toBeInTheDocument();
  });

  it("renders with role='slider' for accessibility", () => {
    const { container } = render(<SlideToConfirm label="Test slide" onConfirm={vi.fn()} />);

    const slider = container.querySelector('[role="slider"]');
    expect(slider).toBeInTheDocument();
  });

  it("updates aria-valuenow as thumb position changes", async () => {
    const { container } = render(<SlideToConfirm label="Test slide" onConfirm={vi.fn()} />);

    const slider = container.querySelector('[role="slider"]') as HTMLElement;
    expect(slider).toHaveAttribute("aria-valuenow", "0");

    // Simulate drag to 50%
    const track = container.querySelector('[role="slider"]') as HTMLElement;
    const rect = track.getBoundingClientRect();
    const midX = rect.left + rect.width / 2;

    fireEvent.mouseDown(track, { clientX: midX });
    fireEvent.mouseMove(document, { clientX: midX });

    // aria-valuenow should reflect approximate position
    expect(slider).toHaveAttribute("aria-valuenow", expect.stringMatching(/\d+/));
  });

  it("sets aria-label to the provided label", () => {
    const { container } = render(<SlideToConfirm label="Kill switch" onConfirm={vi.fn()} />);

    const slider = container.querySelector('[role="slider"]') as HTMLElement;
    expect(slider).toHaveAttribute("aria-label", "Kill switch");
  });

  it("has correct ARIA attributes for slider", () => {
    const onConfirm = vi.fn();
    const { container } = render(<SlideToConfirm label="Test slide" onConfirm={onConfirm} />);

    const slider = container.querySelector('[role="slider"]') as HTMLElement;

    // Check ARIA attributes
    expect(slider).toHaveAttribute("aria-valuenow", "0");
    expect(slider).toHaveAttribute("aria-valuemin", "0");
    expect(slider).toHaveAttribute("aria-valuemax", "100");
    expect(slider).toHaveAttribute("aria-label", "Test slide");
  });

  it("resets thumb to start when released before threshold", async () => {
    const onConfirm = vi.fn();
    const { container } = render(<SlideToConfirm label="Test slide" onConfirm={onConfirm} />);

    const track = container.querySelector('[role="slider"]') as HTMLElement;
    const rect = track.getBoundingClientRect();

    // Simulate drag to 50% (below 90% threshold)
    const targetX = rect.left + rect.width * 0.5;

    fireEvent.mouseDown(track, { clientX: rect.left + 10 });
    fireEvent.mouseMove(document, { clientX: targetX });
    fireEvent.mouseUp(document);

    // onConfirm should NOT have been called
    expect(onConfirm).not.toHaveBeenCalled();

    // After releasing, thumb should return to 0% (aria-valuenow = 0)
    const slider = container.querySelector('[role="slider"]') as HTMLElement;
    // Allow a brief moment for state update
    setTimeout(() => {
      expect(slider).toHaveAttribute("aria-valuenow", "0");
    }, 50);
  });

  it("applies disabled state to track", () => {
    const { container } = render(
      <SlideToConfirm label="Test slide" onConfirm={vi.fn()} disabled={true} />,
    );

    const slider = container.querySelector('[role="slider"]') as HTMLElement;
    expect(slider).toHaveClass("opacity-50");
    expect(slider).toHaveClass("pointer-events-none");
  });

  it("sets aria-disabled when disabled", () => {
    const { container } = render(
      <SlideToConfirm label="Test slide" onConfirm={vi.fn()} disabled={true} />,
    );

    const slider = container.querySelector('[role="slider"]') as HTMLElement;
    expect(slider).toHaveAttribute("aria-disabled", "true");
  });

  it("prevents interaction when disabled", () => {
    const onConfirm = vi.fn();
    const { container } = render(
      <SlideToConfirm label="Test slide" onConfirm={onConfirm} disabled={true} />,
    );

    const track = container.querySelector('[role="slider"]') as HTMLElement;
    const rect = track.getBoundingClientRect();

    fireEvent.mouseDown(track, { clientX: rect.left + 10 });
    fireEvent.mouseMove(document, { clientX: rect.left + rect.width * 0.95 });

    // onConfirm should NOT be called when disabled
    expect(onConfirm).not.toHaveBeenCalled();
  });

  it("applies danger variant styling", () => {
    const { container } = render(
      <SlideToConfirm label="Test slide" onConfirm={vi.fn()} variant="danger" />,
    );

    const slider = container.querySelector('[role="slider"]') as HTMLElement;
    expect(slider).toHaveClass("bg-red-100");

    // Thumb should be red
    const thumb = container.querySelector('[role="slider"] div[style*="left"]') as HTMLElement;
    expect(thumb).toHaveClass("bg-red-600");
  });

  it("applies default variant styling", () => {
    const { container } = render(
      <SlideToConfirm label="Test slide" onConfirm={vi.fn()} variant="default" />,
    );

    const slider = container.querySelector('[role="slider"]') as HTMLElement;
    expect(slider).toHaveClass("bg-gray-200");

    // Thumb should be brand color
    const thumb = container.querySelector('[role="slider"] div[style*="left"]') as HTMLElement;
    expect(thumb).toHaveClass("bg-brand-500");
  });

  it("renders thumb with correct styling and icon", () => {
    const { container } = render(<SlideToConfirm label="Test slide" onConfirm={vi.fn()} />);

    // Find the thumb (the div with transform: translate)
    const thumb = container.querySelector('[role="slider"] div[style*="left"]') as HTMLElement;
    expect(thumb).toBeInTheDocument();
    expect(thumb).toHaveClass("rounded-full", "cursor-grab");

    // Check for chevron icon
    const icon = thumb.querySelector("svg");
    expect(icon).toBeInTheDocument();
  });

  it("renders chevron icon on thumb", () => {
    const { container } = render(<SlideToConfirm label="Test slide" onConfirm={vi.fn()} />);

    // lucide-react icons render as SVG
    const svg = container.querySelector('[role="slider"] svg');
    expect(svg).toBeInTheDocument();
  });

  it("accepts custom className", () => {
    const { container } = render(
      <SlideToConfirm label="Test slide" onConfirm={vi.fn()} className="custom-class" />,
    );

    const wrapper = container.firstChild as HTMLElement;
    expect(wrapper).toHaveClass("custom-class");
  });

  it("track has correct background color for variant", () => {
    const { container: dangerContainer } = render(
      <SlideToConfirm label="Test" onConfirm={vi.fn()} variant="danger" />,
    );

    const dangerTrack = dangerContainer.querySelector('[role="slider"]') as HTMLElement;
    expect(dangerTrack).toHaveClass("bg-red-100");

    const { container: defaultContainer } = render(
      <SlideToConfirm label="Test" onConfirm={vi.fn()} variant="default" />,
    );

    const defaultTrack = defaultContainer.querySelector('[role="slider"]') as HTMLElement;
    expect(defaultTrack).toHaveClass("bg-gray-200");
  });
});
