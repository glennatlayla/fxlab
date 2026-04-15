/**
 * Shared constants for the Strategy feature.
 *
 * Purpose:
 *   Centralise magic strings and timing values used across hooks,
 *   components, and tests in the strategy domain. Prevents drift
 *   when the same key or delay appears in multiple files.
 *
 * Does NOT:
 *   - Contain business logic or runtime behaviour.
 *   - Export React components or hooks.
 */

// ---------------------------------------------------------------------------
// Persistence
// ---------------------------------------------------------------------------

/** localStorage key for draft autosave data. Shared by useDraftAutosave and useDraftRecovery. */
export const DRAFT_LOCAL_STORAGE_KEY = "fxlab:strategy_draft";

// ---------------------------------------------------------------------------
// Timing
// ---------------------------------------------------------------------------

/** Debounce delay for localStorage writes in useDraftAutosave (ms). */
export const LOCAL_SAVE_DEBOUNCE_MS = 500;

/** Interval for periodic backend sync in useDraftAutosave (ms). */
export const BACKEND_SYNC_INTERVAL_MS = 30_000;

/** Debounce delay for the wizard form autosave callback (ms). */
export const FORM_AUTOSAVE_DEBOUNCE_MS = 1_000;

// ---------------------------------------------------------------------------
// Wizard step labels — maps StrategyWizardStep to display text
// ---------------------------------------------------------------------------

/** Human-readable labels for each wizard step, displayed in the progress bar. */
export const STEP_LABELS: Record<string, string> = {
  basics: "Basics",
  conditions: "Conditions",
  risk: "Risk",
  parameters: "Parameters",
  review: "Review",
} as const;
