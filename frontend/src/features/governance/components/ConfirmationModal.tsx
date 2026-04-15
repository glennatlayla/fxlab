/**
 * ConfirmationModal — accessible modal dialog for governance action confirmation.
 *
 * Purpose:
 *   Provide a reusable confirmation modal with focus trap, escape-to-close,
 *   backdrop click-to-close, and body scroll lock. Used for approve/reject
 *   confirmations in governance workflows.
 *
 * Responsibilities:
 *   - Trap focus within the modal (WCAG 2.1 AA).
 *   - Close on Escape key or backdrop click.
 *   - Lock body scroll while open.
 *   - Restore focus to the triggering element on close.
 *
 * Does NOT:
 *   - Execute any business logic.
 *   - Manage its own open/close state (controlled by parent).
 *
 * Dependencies:
 *   - React (useEffect, useRef, useCallback).
 *
 * Example:
 *   <ConfirmationModal isOpen={showModal} onClose={close} title="Approve Request?">
 *     <p>Are you sure?</p>
 *     <button onClick={handleApprove}>Confirm</button>
 *   </ConfirmationModal>
 */

import { memo, useEffect, useRef, useCallback } from "react";
import type { ReactNode } from "react";

/** Selector for all focusable elements within the modal. */
const FOCUSABLE_SELECTOR =
  'a[href], button:not([disabled]), textarea:not([disabled]), input:not([disabled]), select:not([disabled]), [tabindex]:not([tabindex="-1"])';

export interface ConfirmationModalProps {
  /** Whether the modal is open. */
  isOpen: boolean;
  /** Callback when the modal should close. */
  onClose: () => void;
  /** Modal title displayed in the header. */
  title: string;
  /** Modal content (form fields, buttons, etc.). */
  children: ReactNode;
}

/**
 * Accessible confirmation modal with focus trap and keyboard handling.
 *
 * Args:
 *   isOpen: Whether the modal is visible.
 *   onClose: Called when user presses Escape or clicks backdrop.
 *   title: Header text.
 *   children: Modal body content.
 *
 * Returns:
 *   Portal-rendered modal overlay, or null when closed.
 */
export const ConfirmationModal = memo(function ConfirmationModal({
  isOpen,
  onClose,
  title,
  children,
}: ConfirmationModalProps) {
  const dialogRef = useRef<HTMLDivElement>(null);
  const previousFocusRef = useRef<HTMLElement | null>(null);

  // Focus trap: cycle focus within the modal.
  const handleKeyDown = useCallback(
    (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        onClose();
        return;
      }

      if (e.key === "Tab" && dialogRef.current) {
        const focusable = dialogRef.current.querySelectorAll(FOCUSABLE_SELECTOR);
        if (focusable.length === 0) return;

        const first = focusable[0] as HTMLElement;
        const last = focusable[focusable.length - 1] as HTMLElement;

        if (e.shiftKey && document.activeElement === first) {
          e.preventDefault();
          last.focus();
        } else if (!e.shiftKey && document.activeElement === last) {
          e.preventDefault();
          first.focus();
        }
      }
    },
    [onClose],
  );

  // Manage body scroll lock, focus, and keyboard listeners.
  useEffect(() => {
    if (!isOpen) return;

    // Save current focus for restoration.
    previousFocusRef.current = document.activeElement as HTMLElement;

    // Lock body scroll.
    const originalOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";

    // Focus the first focusable element in the modal.
    const timer = setTimeout(() => {
      if (dialogRef.current) {
        const first = dialogRef.current.querySelector(FOCUSABLE_SELECTOR) as HTMLElement | null;
        first?.focus();
      }
    }, 0);

    // Register keyboard handler.
    document.addEventListener("keydown", handleKeyDown);

    return () => {
      clearTimeout(timer);
      document.body.style.overflow = originalOverflow;
      document.removeEventListener("keydown", handleKeyDown);
      // Restore focus.
      previousFocusRef.current?.focus();
    };
  }, [isOpen, handleKeyDown]);

  if (!isOpen) return null;

  return (
    <div
      data-testid="confirmation-modal-backdrop"
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/50"
      onClick={(e) => {
        // Close only when clicking the backdrop itself, not modal content.
        if (e.target === e.currentTarget) onClose();
      }}
      role="presentation"
    >
      <div
        ref={dialogRef}
        data-testid="confirmation-modal"
        role="dialog"
        aria-modal="true"
        aria-label={title}
        className="mx-4 w-full max-w-lg rounded-xl bg-white p-6 shadow-xl"
      >
        <h2 data-testid="confirmation-modal-title" className="text-lg font-semibold text-slate-900">
          {title}
        </h2>
        <div className="mt-4">{children}</div>
      </div>
    </div>
  );
});
