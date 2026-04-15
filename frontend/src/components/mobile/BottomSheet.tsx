/**
 * BottomSheet — Mobile bottom-anchored slide-up drawer.
 *
 * Purpose:
 *   Provide a mobile-optimized overlay for secondary content, actions, or
 *   configuration. Anchored to the bottom of the viewport, slides up from
 *   below, supports dismissal via backdrop click or Escape key.
 *
 * Responsibilities:
 *   - Render a semi-transparent backdrop that dismisses on click.
 *   - Manage bottom-sheet visibility and animations.
 *   - Trap focus inside the sheet when open.
 *   - Lock body scroll while open.
 *   - Handle Escape key for dismissal.
 *   - Render content to a portal (document.body).
 *   - Respect safe-area insets for notched devices.
 *
 * Does NOT:
 *   - Manage state; receives isOpen as a prop.
 *   - Execute business logic; only calls onClose callback.
 *   - Handle horizontal gestures (swipe-to-dismiss left/right).
 *
 * Dependencies:
 *   - React (useState, useEffect, useRef, ReactNode, createPortal).
 *   - Tailwind CSS.
 *   - lucide-react (X icon).
 *
 * Error conditions:
 *   - None; malformed props default to sensible values.
 *
 * Example:
 *   <BottomSheet isOpen={isOpen} onClose={handleClose} title="Settings">
 *     <SettingsForm />
 *   </BottomSheet>
 */

import React, { useEffect, useRef } from "react";
import { createPortal } from "react-dom";
import { X } from "lucide-react";
import clsx from "clsx";

export interface BottomSheetProps {
  /** Whether the sheet is visible. */
  isOpen: boolean;
  /** Callback when the sheet should close. */
  onClose: () => void;
  /** Sheet title displayed in the header. */
  title: string;
  /** Content to render inside the sheet. */
  children: React.ReactNode;
  /** Maximum height as percentage of viewport. Default: 85. */
  maxHeightVh?: number;
  /** Optional additional CSS classes for the content container. */
  className?: string;
}

/**
 * BottomSheet component.
 *
 * Renders a bottom-anchored, draggable sheet overlay. When open, a backdrop
 * appears behind the sheet. Clicking the backdrop or pressing Escape closes
 * the sheet. Body scroll is locked while the sheet is open.
 *
 * The sheet uses a portal to render at document.body level, ensuring it
 * layers above all other content.
 *
 * Example:
 *   const [isOpen, setIsOpen] = useState(false);
 *   return (
 *     <>
 *       <button onClick={() => setIsOpen(true)}>Open Sheet</button>
 *       <BottomSheet
 *         isOpen={isOpen}
 *         onClose={() => setIsOpen(false)}
 *         title="My Sheet"
 *       >
 *         <p>Content goes here</p>
 *       </BottomSheet>
 *     </>
 *   );
 */
export function BottomSheet({
  isOpen,
  onClose,
  title,
  children,
  maxHeightVh = 85,
  className,
}: BottomSheetProps): React.ReactElement | null {
  const sheetRef = useRef<HTMLDivElement>(null);

  /**
   * Lock/unlock body scroll based on sheet open state.
   */
  useEffect(() => {
    if (isOpen) {
      document.body.style.overflow = "hidden";
    } else {
      document.body.style.overflow = "";
    }

    return () => {
      document.body.style.overflow = "";
    };
  }, [isOpen]);

  /**
   * Handle Escape key to close sheet.
   */
  useEffect(() => {
    if (!isOpen) return;

    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        onClose();
      }
    };

    document.addEventListener("keydown", handleKeyDown);
    return () => {
      document.removeEventListener("keydown", handleKeyDown);
    };
  }, [isOpen, onClose]);

  /**
   * Implement focus trap: focus should stay within the sheet.
   */
  useEffect(() => {
    if (!isOpen || !sheetRef.current) return;

    const sheetElement = sheetRef.current;
    const focusableElements = sheetElement.querySelectorAll(
      'button, [href], input, select, textarea, [tabindex]:not([tabindex="-1"])',
    );

    if (focusableElements.length === 0) {
      // If no focusable elements, trap focus on the sheet itself.
      sheetElement.focus();
      return;
    }

    const firstElement = focusableElements[0] as HTMLElement;
    const lastElement = focusableElements[focusableElements.length - 1] as HTMLElement;

    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key !== "Tab") return;

      if (e.shiftKey) {
        // Shift+Tab: move focus backward
        if (document.activeElement === firstElement) {
          e.preventDefault();
          lastElement.focus();
        }
      } else {
        // Tab: move focus forward
        if (document.activeElement === lastElement) {
          e.preventDefault();
          firstElement.focus();
        }
      }
    };

    sheetElement.addEventListener("keydown", handleKeyDown);
    firstElement.focus();

    return () => {
      sheetElement.removeEventListener("keydown", handleKeyDown);
    };
  }, [isOpen]);

  if (!isOpen) {
    return null;
  }

  return createPortal(
    <>
      {/* Backdrop */}
      <div
        className="fixed inset-0 z-40 bg-black/50 transition-opacity"
        onClick={onClose}
        aria-hidden="true"
      />

      {/* Sheet */}
      <div
        ref={sheetRef}
        className={clsx(
          "fixed bottom-0 left-0 right-0 z-50 flex flex-col rounded-t-2xl bg-white transition-transform",
        )}
        style={{
          maxHeight: `${maxHeightVh}vh`,
          paddingBottom: "env(safe-area-inset-bottom)",
          transform: isOpen ? "translateY(0)" : "translateY(100%)",
        }}
        role="dialog"
        aria-modal="true"
        aria-labelledby="bottom-sheet-title"
      >
        {/* Header with drag handle and close button */}
        <div className="flex flex-col items-center border-b border-surface-200 px-4 py-3">
          {/* Drag handle (small gray bar) */}
          <div className="mb-3 h-1 w-8 rounded-full bg-surface-300" />

          {/* Title row */}
          <div className="flex w-full items-center justify-between">
            <h2 id="bottom-sheet-title" className="text-lg font-semibold text-surface-900">
              {title}
            </h2>
            <button
              onClick={onClose}
              className="flex h-8 w-8 items-center justify-center rounded-lg hover:bg-surface-100 active:bg-surface-200"
              aria-label="Close"
            >
              <X className="h-5 w-5 text-surface-600" />
            </button>
          </div>
        </div>

        {/* Content */}
        <div className={clsx("flex-1 overflow-y-auto px-4 py-4", className)}>{children}</div>
      </div>
    </>,
    document.body,
  );
}
