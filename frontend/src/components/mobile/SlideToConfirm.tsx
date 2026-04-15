/**
 * SlideToConfirm — Swipe-to-confirm gesture component.
 *
 * Purpose:
 *   Provide a mobile-friendly gesture for confirming destructive actions
 *   (kill switch activation, order cancellation) through a drag-to-threshold
 *   interaction pattern. Requires deliberate, continuous motion to prevent
 *   accidental activation.
 *
 * Responsibilities:
 *   - Track touch and mouse drag on the thumb (draggable circle).
 *   - Calculate thumb position as a percentage of track width.
 *   - Fire onConfirm callback when thumb crosses 90% threshold.
 *   - Reset thumb position when released before threshold.
 *   - Apply visual feedback (color, opacity) based on variant and drag state.
 *   - Manage keyboard / accessibility for screen readers.
 *
 * Does NOT:
 *   - Execute any business logic (deletion, kill switch activation).
 *   - Modify data directly; only calls callbacks.
 *   - Handle keyboard-only interaction (slider is touch/mouse only).
 *
 * Dependencies:
 *   - React (useState, useRef, useEffect).
 *   - Tailwind CSS (via className prop).
 *   - lucide-react (ChevronRight icon).
 *
 * Error conditions:
 *   - None; malformed props default to sensible values.
 *
 * Example:
 *   <SlideToConfirm
 *     label="Slide to activate kill switch"
 *     variant="danger"
 *     onConfirm={() => killSwitchService.activate()}
 *   />
 */

import React, { useState, useRef, useEffect } from "react";
import { ChevronRight } from "lucide-react";
import clsx from "clsx";

export interface SlideToConfirmProps {
  /** Label displayed on the track (e.g., "Slide to activate kill switch"). */
  label: string;
  /** Callback when slide completes (thumb reaches end). */
  onConfirm: () => void;
  /** Visual variant — "danger" for destructive, "default" for normal. */
  variant?: "default" | "danger";
  /** Whether the component is disabled. */
  disabled?: boolean;
  /** Optional additional CSS classes. */
  className?: string;
}

/**
 * SlideToConfirm component.
 *
 * Renders a horizontal track with a draggable thumb. When the thumb is dragged
 * to the right and crosses 90% of the track width, onConfirm fires. Releasing
 * before 90% causes the thumb to animate back to the start.
 *
 * Touch and mouse events are both supported for maximum compatibility.
 *
 * Example:
 *   <SlideToConfirm
 *     label="Slide to activate kill switch"
 *     variant="danger"
 *     onConfirm={() => activateKillSwitch()}
 *   />
 */
export function SlideToConfirm({
  label,
  onConfirm,
  variant = "default",
  disabled = false,
  className,
}: SlideToConfirmProps): React.ReactElement {
  const [thumbPosition, setThumbPosition] = useState<number>(0);
  const [isDragging, setIsDragging] = useState<boolean>(false);
  const trackRef = useRef<HTMLDivElement>(null);
  const thumbRef = useRef<HTMLDivElement>(null);

  // Compute label opacity based on thumb position (fade as thumb moves right).
  const labelOpacity = Math.max(0, 1 - thumbPosition / 100);

  // Threshold: 90% (at which point onConfirm fires).
  const THRESHOLD = 90;

  /**
   * Calculate thumb position (0–100) from mouse/touch X coordinate.
   * Clamps to [0, 100].
   */
  const calculatePosition = (clientX: number): number => {
    if (!trackRef.current) return 0;

    const rect = trackRef.current.getBoundingClientRect();
    const relativeX = clientX - rect.left;
    const percentage = (relativeX / rect.width) * 100;

    return Math.max(0, Math.min(100, percentage));
  };

  /**
   * Handle drag start (mouse or touch).
   */
  const handleDragStart = (e: React.MouseEvent | React.TouchEvent) => {
    if (disabled) return;

    setIsDragging(true);
    const clientX = "touches" in e ? e.touches[0].clientX : e.clientX;
    const newPosition = calculatePosition(clientX);
    setThumbPosition(newPosition);
  };

  /**
   * Handle drag move (mouse or touch).
   * Called on mousemove/touchmove at document level.
   */
  const handleDragMove = (e: MouseEvent | TouchEvent) => {
    if (!isDragging || disabled) return;

    const clientX = "touches" in e ? e.touches[0].clientX : e.clientX;
    const newPosition = calculatePosition(clientX);
    setThumbPosition(newPosition);

    // If threshold crossed, fire confirmation and reset.
    if (newPosition >= THRESHOLD) {
      onConfirm();
      setIsDragging(false);
      setThumbPosition(0);
    }
  };

  /**
   * Handle drag end (mouse or touch).
   * If position < threshold, animate back to 0.
   */
  const handleDragEnd = () => {
    if (!isDragging) return;

    setIsDragging(false);

    // Only reset if below threshold (if at threshold, onConfirm already fired).
    if (thumbPosition < THRESHOLD) {
      setThumbPosition(0);
    }
  };

  /**
   * Attach document-level listeners for drag tracking.
   * Note: handlers are omitted from dependency array because they are
   * created fresh on each render and adding them would cause constant
   * attachment/detachment. The listeners will capture the current
   * handler values via closure.
   */
  useEffect(() => {
    if (!isDragging) return;

    document.addEventListener("mousemove", handleDragMove);
    document.addEventListener("touchmove", handleDragMove);
    document.addEventListener("mouseup", handleDragEnd);
    document.addEventListener("touchend", handleDragEnd);

    return () => {
      document.removeEventListener("mousemove", handleDragMove);
      document.removeEventListener("touchmove", handleDragMove);
      document.removeEventListener("mouseup", handleDragEnd);
      document.removeEventListener("touchend", handleDragEnd);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [isDragging, thumbPosition]);

  // Determine colors and styles based on variant.
  const trackBgClass = variant === "danger" ? "bg-red-100" : "bg-gray-200";
  const thumbBgClass = variant === "danger" ? "bg-red-600" : "bg-brand-500";

  return (
    <div className={clsx("w-full", className)}>
      {/* Track container */}
      <div
        ref={trackRef}
        className={clsx(
          "relative h-14 w-full rounded-full transition-colors",
          trackBgClass,
          disabled && "pointer-events-none opacity-50",
        )}
        role="slider"
        aria-valuenow={Math.round(thumbPosition)}
        aria-valuemin={0}
        aria-valuemax={100}
        aria-label={label}
        aria-disabled={disabled}
      >
        {/* Label (centered, fades as thumb moves) */}
        <div
          className="pointer-events-none absolute inset-0 flex items-center justify-center transition-opacity"
          style={{ opacity: labelOpacity }}
        >
          <span
            className={clsx(
              "text-sm font-medium",
              variant === "danger" ? "text-red-600" : "text-surface-600",
            )}
          >
            {label}
          </span>
        </div>

        {/* Thumb (draggable circle) */}
        <div
          ref={thumbRef}
          className={clsx(
            "absolute top-1/2 h-12 w-12 -translate-y-1/2 rounded-full transition-all",
            thumbBgClass,
            "flex cursor-grab items-center justify-center active:cursor-grabbing",
            "shadow-md",
            isDragging && "shadow-lg",
          )}
          style={{
            left: `${thumbPosition}%`,
            transform: "translate(-50%, -50%)",
          }}
          onMouseDown={handleDragStart}
          onTouchStart={handleDragStart}
        >
          <ChevronRight className="h-5 w-5 text-white" />
        </div>
      </div>
    </div>
  );
}
