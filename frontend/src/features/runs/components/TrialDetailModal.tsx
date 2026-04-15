/**
 * TrialDetailModal — full trial information overlay.
 *
 * Purpose:
 *   Display complete trial details including parameters, seed,
 *   metrics, fold metrics, and objective value in a modal overlay.
 *
 * Responsibilities:
 *   - Render trial parameters as a key-value table.
 *   - Display metrics and fold metrics.
 *   - Show objective value prominently.
 *   - Handle close via escape key and backdrop click.
 *   - Trap focus within the modal when open (WCAG 2.1 AA).
 *   - Lock body scroll when modal is open.
 *   - Respect prefers-reduced-motion for animations.
 *
 * Does NOT:
 *   - Fetch trial data (receives TrialRecord as prop).
 *   - Manage open/close state (parent controls isOpen).
 */

import { useEffect, useCallback, useRef } from "react";
import type { TrialDetailModalProps } from "../types";

/**
 * Focusable element selector for focus trap.
 * Matches interactive elements that can receive keyboard focus.
 */
const FOCUSABLE_SELECTOR =
  'a[href], button:not([disabled]), textarea, input, select, [tabindex]:not([tabindex="-1"])';

/**
 * Render a trial detail modal with focus trap and scroll lock.
 *
 * Args:
 *   trial: Trial record to display (null to close).
 *   isOpen: Whether the modal is visible.
 *   onClose: Callback to close the modal.
 */
export function TrialDetailModal({ trial, isOpen, onClose }: TrialDetailModalProps) {
  const modalRef = useRef<HTMLDivElement>(null);
  const previousActiveElement = useRef<HTMLElement | null>(null);
  const rafIdRef = useRef<number | null>(null);

  // Close on Escape key
  const handleKeyDown = useCallback(
    (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        onClose();
        return;
      }

      // Focus trap: Tab and Shift+Tab cycle within the modal
      if (event.key === "Tab" && modalRef.current) {
        const focusableElements = modalRef.current.querySelectorAll(FOCUSABLE_SELECTOR);
        const firstFocusable = focusableElements[0] as HTMLElement | undefined;
        const lastFocusable = focusableElements[focusableElements.length - 1] as
          | HTMLElement
          | undefined;

        if (!firstFocusable || !lastFocusable) return;

        if (event.shiftKey) {
          // Shift+Tab: if focus is on first element, wrap to last
          if (document.activeElement === firstFocusable) {
            event.preventDefault();
            lastFocusable.focus();
          }
        } else {
          // Tab: if focus is on last element, wrap to first
          if (document.activeElement === lastFocusable) {
            event.preventDefault();
            firstFocusable.focus();
          }
        }
      }
    },
    [onClose],
  );

  // Focus trap + scroll lock management
  useEffect(() => {
    if (isOpen) {
      // Save currently focused element to restore on close
      previousActiveElement.current = document.activeElement as HTMLElement | null;

      // Lock body scroll
      const originalOverflow = document.body.style.overflow;
      document.body.style.overflow = "hidden";

      // Add keyboard listener
      document.addEventListener("keydown", handleKeyDown);

      // Focus the first focusable element inside the modal (or the close button)
      // Use requestAnimationFrame to ensure DOM is rendered; store ID for cleanup
      rafIdRef.current = requestAnimationFrame(() => {
        rafIdRef.current = null;
        if (modalRef.current) {
          const firstFocusable = modalRef.current.querySelector(
            FOCUSABLE_SELECTOR,
          ) as HTMLElement | null;
          if (firstFocusable) {
            firstFocusable.focus();
          }
        }
      });

      return () => {
        // Cancel pending rAF if modal unmounts before frame fires
        if (rafIdRef.current !== null) {
          cancelAnimationFrame(rafIdRef.current);
          rafIdRef.current = null;
        }

        // Restore scroll
        document.body.style.overflow = originalOverflow;

        // Remove keyboard listener
        document.removeEventListener("keydown", handleKeyDown);

        // Restore focus to previously active element
        if (previousActiveElement.current && previousActiveElement.current.focus) {
          previousActiveElement.current.focus();
        }
      };
    }
  }, [isOpen, handleKeyDown]);

  if (!isOpen || !trial) return null;

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 motion-safe:animate-fadeIn"
      onClick={(e) => {
        if (e.target === e.currentTarget) onClose();
      }}
      data-testid="trial-detail-modal"
      role="dialog"
      aria-modal="true"
      aria-label={`Trial #${trial.trial_index} details`}
    >
      <div
        ref={modalRef}
        className="max-h-[80vh] w-full max-w-lg overflow-y-auto rounded-lg border border-gray-700 bg-gray-800 p-6 shadow-xl motion-safe:animate-scaleIn"
      >
        {/* Header */}
        <div className="mb-4 flex items-center justify-between">
          <h2 className="text-lg font-semibold text-white">Trial #{trial.trial_index}</h2>
          <button
            type="button"
            className="rounded-md p-1 text-gray-400 transition-colors hover:bg-gray-700 hover:text-white"
            onClick={onClose}
            aria-label="Close modal"
            data-testid="trial-modal-close"
          >
            <svg className="h-5 w-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path
                strokeLinecap="round"
                strokeLinejoin="round"
                strokeWidth={2}
                d="M6 18L18 6M6 6l12 12"
              />
            </svg>
          </button>
        </div>

        {/* Status & Seed */}
        <div className="mb-4 flex items-center gap-4 text-sm">
          <span className="text-gray-400">
            Status: <span className="text-gray-200">{trial.status}</span>
          </span>
          {trial.seed !== undefined && (
            <span className="text-gray-400">
              Seed: <span className="font-mono text-gray-200">{trial.seed}</span>
            </span>
          )}
        </div>

        {/* Objective Value */}
        {trial.objective_value !== undefined && trial.objective_value !== null && (
          <div className="mb-4 rounded-md bg-blue-900/30 px-4 py-3">
            <div className="text-xs text-blue-400">Objective Value</div>
            <div className="text-xl font-bold text-white">{trial.objective_value.toFixed(6)}</div>
          </div>
        )}

        {/* Parameters */}
        <div className="mb-4">
          <h3 className="mb-2 text-sm font-semibold text-gray-300">Parameters</h3>
          <div className="rounded-md border border-gray-700 bg-gray-900">
            <table className="w-full text-sm" data-testid="trial-params-table">
              <tbody>
                {Object.entries(trial.parameters).map(([key, value]) => (
                  <tr key={key} className="border-b border-gray-800 last:border-0">
                    <td className="px-3 py-2 font-mono text-gray-400">{key}</td>
                    <td className="px-3 py-2 text-right font-mono text-gray-200">
                      {String(value)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>

        {/* Metrics */}
        {trial.metrics && Object.keys(trial.metrics).length > 0 && (
          <div className="mb-4">
            <h3 className="mb-2 text-sm font-semibold text-gray-300">Metrics</h3>
            <div className="rounded-md border border-gray-700 bg-gray-900">
              <table className="w-full text-sm" data-testid="trial-metrics-table">
                <tbody>
                  {Object.entries(trial.metrics).map(([key, value]) => (
                    <tr key={key} className="border-b border-gray-800 last:border-0">
                      <td className="px-3 py-2 font-mono text-gray-400">{key}</td>
                      <td className="px-3 py-2 text-right font-mono text-gray-200">
                        {typeof value === "number" ? value.toFixed(6) : String(value)}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        )}

        {/* Fold Metrics */}
        {trial.fold_metrics && Object.keys(trial.fold_metrics).length > 0 && (
          <div>
            <h3 className="mb-2 text-sm font-semibold text-gray-300">Fold Metrics</h3>
            {Object.entries(trial.fold_metrics).map(([foldName, foldMetrics]) => (
              <div key={foldName} className="mb-2">
                <div className="mb-1 text-xs font-medium text-gray-400">{foldName}</div>
                <div className="rounded-md border border-gray-700 bg-gray-900">
                  <table className="w-full text-sm">
                    <tbody>
                      {Object.entries(foldMetrics).map(([key, value]) => (
                        <tr key={key} className="border-b border-gray-800 last:border-0">
                          <td className="px-3 py-1.5 font-mono text-gray-400">{key}</td>
                          <td className="px-3 py-1.5 text-right font-mono text-gray-200">
                            {value.toFixed(6)}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
