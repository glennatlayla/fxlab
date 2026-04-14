/**
 * Strategy Studio page — M25 design and configuration interface.
 *
 * Purpose:
 *   Wire together the draft wizard form, autosave persistence, and
 *   draft recovery into a single page. This is the primary entry
 *   point for creating a new trading strategy.
 *
 * Responsibilities:
 *   - Detect recoverable drafts (localStorage + backend) via useDraftRecovery.
 *   - Persist draft edits via useDraftAutosave (debounced local + periodic backend).
 *   - Render DraftRecoveryBanner when an abandoned draft is found.
 *   - Render StrategyDraftForm with autosave and submit callbacks.
 *   - Show loading state while checking for drafts.
 *
 * Does NOT:
 *   - Execute or backtest strategies (delegated to Runs).
 *   - Manage strategy approval workflows (delegated to Approvals).
 *   - Store compiled artifacts (delegated to Artifacts).
 *   - Contain business logic — delegates to hooks and child components.
 *
 * Dependencies:
 *   - useDraftRecovery: draft detection and restore/discard callbacks.
 *   - useDraftAutosave: localStorage + backend persistence.
 *   - StrategyDraftForm: multi-step wizard component.
 *   - DraftRecoveryBanner: UI banner for draft restoration.
 *   - LoadingState: centered spinner for loading states.
 *   - useAuth: authentication context.
 */

import { useCallback, useState } from "react";
import { useNavigate } from "react-router-dom";
import { useAuth } from "@/auth/useAuth";
import { DraftRecoveryBanner } from "@/components/ui/DraftRecoveryBanner";
import { LoadingState } from "@/components/ui/LoadingState";
import { StrategyDraftForm } from "@/features/strategy/components/StrategyDraftForm";
import { strategyApi, StrategyApiError } from "@/features/strategy/api";
import { useDraftAutosave } from "@/features/strategy/useDraftAutosave";
import { useDraftRecovery } from "@/features/strategy/useDraftRecovery";
import type { StrategyDraftFormData, StrategyWizardStep } from "@/types/strategy";

// ---------------------------------------------------------------------------
// Default form data — clean slate for new strategies
// ---------------------------------------------------------------------------

const DEFAULT_FORM_DATA: StrategyDraftFormData = {
  name: "",
  description: "",
  instrument: "",
  timeframe: "",
  entryCondition: "",
  exitCondition: "",
  maxPositionSize: 10_000,
  stopLossPercent: 2,
  takeProfitPercent: 5,
  parameters: [],
};

// ---------------------------------------------------------------------------
// Page component
// ---------------------------------------------------------------------------

export default function StrategyStudio() {
  useAuth();
  const navigate = useNavigate();

  // ---- Submission state ----
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [submitError, setSubmitError] = useState<string | null>(null);

  // ---- Draft recovery (check for abandoned drafts on mount) ----
  const {
    recoverableDraft,
    isChecking,
    restoreDraft,
    discardDraft: discardRecovery,
  } = useDraftRecovery();

  // ---- Form data state ----
  const [formData, setFormData] = useState<StrategyDraftFormData>(DEFAULT_FORM_DATA);
  const [currentStep, setCurrentStep] = useState<StrategyWizardStep>("basics");

  // ---- Autosave persistence ----
  const {
    saveToLocal,
    syncToBackend,
    discardDraft: discardAutosave,
  } = useDraftAutosave({ formStep: currentStep });

  // ---- Recovery handlers ----
  const handleRestore = useCallback(() => {
    const restored = restoreDraft();
    if (restored) {
      setFormData({ ...DEFAULT_FORM_DATA, ...restored });
    }
  }, [restoreDraft]);

  const handleDiscard = useCallback(async () => {
    await discardRecovery();
  }, [discardRecovery]);

  // ---- Autosave handler (called by StrategyDraftForm on field changes) ----
  const handleAutosave = useCallback(
    (data: Partial<StrategyDraftFormData> & { form_step?: string }) => {
      // Track current step from the form callback
      if (data.form_step) {
        setCurrentStep(data.form_step as StrategyWizardStep);
      }
      saveToLocal(data);
    },
    [saveToLocal],
  );

  // ---- Submit handler ----
  const handleSubmit = useCallback(
    async (data: StrategyDraftFormData) => {
      setIsSubmitting(true);
      setSubmitError(null);

      try {
        // Force a final backend sync before submission
        await syncToBackend(data);

        // Create the strategy via the backend API
        const result = await strategyApi.createStrategy({
          name: data.name,
          entry_condition: data.entryCondition,
          exit_condition: data.exitCondition,
          description: data.description || undefined,
          instrument: data.instrument || undefined,
          timeframe: data.timeframe || undefined,
          max_position_size: data.maxPositionSize,
          stop_loss_percent: data.stopLossPercent,
          take_profit_percent: data.takeProfitPercent,
        });

        // Discard autosave data after successful creation
        await discardAutosave();

        // Navigate to the newly created strategy detail page
        navigate(`/strategies/${result.strategy.id}`);
      } catch (err) {
        // Surface user-friendly error message from the API
        const message =
          err instanceof StrategyApiError
            ? err.message
            : "An unexpected error occurred while creating the strategy.";
        setSubmitError(message);
      } finally {
        setIsSubmitting(false);
      }
    },
    [syncToBackend, discardAutosave, navigate],
  );

  // ---- Loading state while checking for recoverable drafts ----
  if (isChecking) {
    return (
      <div className="space-y-6">
        <div>
          <h1 className="text-2xl font-bold text-surface-900">Strategy Studio</h1>
          <p className="mt-1 text-sm text-surface-500">
            Design, configure, and manage trading strategies.
          </p>
        </div>
        <LoadingState message="Checking for recoverable drafts…" />
      </div>
    );
  }

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold text-surface-900">Strategy Studio</h1>
        <p className="mt-1 text-sm text-surface-500">
          Design, configure, and manage trading strategies.
        </p>
      </div>

      {/* Draft recovery banner — shown only when an abandoned draft is detected */}
      {recoverableDraft && (
        <DraftRecoveryBanner
          savedAt={recoverableDraft.savedAt}
          onRestore={handleRestore}
          onDiscard={handleDiscard}
        />
      )}

      {/* Submission error banner */}
      {submitError && (
        <div
          className="rounded-md border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700"
          data-testid="strategy-submit-error"
        >
          <strong>Error:</strong> {submitError}
        </div>
      )}

      {/* Strategy draft wizard */}
      <StrategyDraftForm
        initialData={formData}
        uncertainties={[]}
        onAutosave={handleAutosave}
        onSubmit={handleSubmit}
        isSubmitting={isSubmitting}
      />
    </div>
  );
}
