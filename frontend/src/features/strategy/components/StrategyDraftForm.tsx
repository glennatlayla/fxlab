/**
 * StrategyDraftForm — Multi-step wizard for creating trading strategies.
 *
 * Purpose:
 *   Capture strategy definition through a guided form wizard, validate input,
 *   autosave drafts, and surface unresolved uncertainties.
 *
 * Responsibilities:
 *   - Render 5-step wizard (basics, conditions, risk, parameters, review).
 *   - Validate required fields (e.g., name) before advancing.
 *   - Call onAutosave callback on field change (debounced 1000ms).
 *   - Show "blocked paper" badge when material uncertainties are unresolved.
 *   - Handle form submission with complete data.
 *   - Display progress indicators showing current step position.
 *
 * Does NOT:
 *   - Contain business logic (orchestration belongs in services/hooks).
 *   - Make API calls directly (autosave callback is injected).
 *   - Persist data (persistence is the responsibility of the onAutosave callback).
 *
 * Dependencies (injected):
 *   - onAutosave: callback invoked on field change (debounced).
 *   - onSubmit: callback invoked on form submission.
 *
 * Raises:
 *   - No direct exceptions; validation errors are displayed in-form.
 *
 * Example:
 *   <StrategyDraftForm
 *     initialData={{ name: "", description: "", ... }}
 *     uncertainties={[]}
 *     onAutosave={(data, step) => { ... }}
 *     onSubmit={(data) => { ... }}
 *   />
 */

import { useEffect, useState, useRef } from "react";
import { AlertCircle, ChevronLeft, ChevronRight, Loader2 } from "lucide-react";
import type { StrategyDraftFormData, UncertaintyEntry, StrategyWizardStep } from "@/types/strategy";
import { STRATEGY_WIZARD_STEPS } from "@/types/strategy";
import { FORM_AUTOSAVE_DEBOUNCE_MS, STEP_LABELS } from "@/features/strategy/constants";
import { DslEditor } from "@/components/DslEditor";

interface StrategyDraftFormProps {
  /** Initial form data (partial, may be incomplete). */
  initialData?: Partial<StrategyDraftFormData>;
  /** Uncertainties from validation (used to determine blocking status). */
  uncertainties?: UncertaintyEntry[];
  /** Callback when field changes (debounced ~1000ms). Receives data with form_step. */
  onAutosave?: (data: Partial<StrategyDraftFormData> & { form_step?: string }) => void;
  /** Callback when form is submitted with complete data. */
  onSubmit?: (data: StrategyDraftFormData) => void;
  /** Whether the form submission is in progress (disables submit button). */
  isSubmitting?: boolean;
}

/**
 * Checks if there are any unresolved material uncertainties.
 *
 * @param uncertainties - List of uncertainty entries from validation.
 * @returns true if any uncertainty has severity "material" and resolved=false.
 */
function hasUnresolvedMaterialUncertainties(
  uncertainties: UncertaintyEntry[] | undefined,
): boolean {
  if (!uncertainties || uncertainties.length === 0) return false;
  return uncertainties.some((u) => u.severity === "material" && !u.resolved);
}

/**
 * Validates required fields for a given wizard step.
 *
 * @param data - Current form data.
 * @param step - Wizard step being validated.
 * @returns object with { isValid, errors } where errors is a Record<string, string>.
 */
function validateStep(
  data: Partial<StrategyDraftFormData>,
  step: StrategyWizardStep,
): { isValid: boolean; errors: Record<string, string> } {
  const errors: Record<string, string> = {};

  switch (step) {
    case "basics":
      if (!data.name || data.name.trim() === "") {
        errors.name = "Strategy name is required";
      }
      break;
    case "conditions":
      // Conditions are optional in this implementation
      break;
    case "risk":
      // Risk fields have defaults, no validation needed
      break;
    case "parameters":
      // Parameters are optional
      break;
    case "review":
      // Review step doesn't validate, just displays
      break;
  }

  return {
    isValid: Object.keys(errors).length === 0,
    errors,
  };
}

export function StrategyDraftForm({
  initialData = {},
  uncertainties = [],
  onAutosave,
  onSubmit,
  isSubmitting = false,
}: StrategyDraftFormProps) {
  // ─────────────────────────────────────────────────────────────────────────
  // State Management
  // ─────────────────────────────────────────────────────────────────────────

  const [currentStepIndex, setCurrentStepIndex] = useState(0);
  const currentStep = STRATEGY_WIZARD_STEPS[currentStepIndex];

  const [formData, setFormData] = useState<Partial<StrategyDraftFormData>>({
    name: "",
    description: "",
    instrument: "",
    timeframe: "",
    entryCondition: "",
    exitCondition: "",
    maxPositionSize: 10000,
    stopLossPercent: 2,
    takeProfitPercent: 5,
    parameters: [],
    ...initialData,
  });

  const [validationErrors, setValidationErrors] = useState<Record<string, string>>({});

  // Autosave debounce timer
  const autosaveTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const hasBlockedPaper = hasUnresolvedMaterialUncertainties(uncertainties);

  // ─────────────────────────────────────────────────────────────────────────
  // Autosave Handler (Debounced)
  // ─────────────────────────────────────────────────────────────────────────

  // Trigger autosave when formData or currentStep changes (debounced)
  useEffect(() => {
    if (!onAutosave) return;

    // Clear any pending autosave timer
    if (autosaveTimerRef.current !== null) {
      clearTimeout(autosaveTimerRef.current);
    }

    // Schedule new autosave after debounce delay
    autosaveTimerRef.current = setTimeout(() => {
      onAutosave({ ...formData, form_step: currentStep });
    }, FORM_AUTOSAVE_DEBOUNCE_MS);

    // Cleanup: clear timer on unmount or when dependencies change
    return () => {
      if (autosaveTimerRef.current !== null) {
        clearTimeout(autosaveTimerRef.current);
      }
    };
  }, [formData, currentStep, onAutosave]);

  // Ensure timer is cleared on unmount
  useEffect(() => {
    return () => {
      if (autosaveTimerRef.current !== null) {
        clearTimeout(autosaveTimerRef.current);
      }
    };
  }, []);

  // ─────────────────────────────────────────────────────────────────────────
  // Navigation Handlers
  // ─────────────────────────────────────────────────────────────────────────

  const handleFieldChange = (field: keyof StrategyDraftFormData, value: unknown) => {
    setFormData((prev) => ({
      ...prev,
      [field]: value,
    }));
    // Clear error for this field once user starts typing
    if (validationErrors[field]) {
      setValidationErrors((prev) => {
        const next = { ...prev };
        delete next[field];
        return next;
      });
    }
  };

  const handleNext = () => {
    const validation = validateStep(formData, currentStep);
    if (!validation.isValid) {
      setValidationErrors(validation.errors);
      return;
    }
    if (currentStepIndex < STRATEGY_WIZARD_STEPS.length - 1) {
      setCurrentStepIndex(currentStepIndex + 1);
      setValidationErrors({});
    }
  };

  const handleBack = () => {
    if (currentStepIndex > 0) {
      setCurrentStepIndex(currentStepIndex - 1);
      setValidationErrors({});
    }
  };

  const handleSubmit = () => {
    if (!onSubmit) return;
    onSubmit(formData as StrategyDraftFormData);
  };

  // ─────────────────────────────────────────────────────────────────────────
  // Render Methods for Each Step
  // ─────────────────────────────────────────────────────────────────────────

  const renderBasicsStep = () => (
    <div className="space-y-4">
      <div>
        <label htmlFor="name" className="mb-1 block text-sm font-medium text-surface-700">
          Strategy Name
        </label>
        <input
          id="name"
          type="text"
          value={formData.name || ""}
          onChange={(e) => handleFieldChange("name", e.target.value)}
          className="w-full rounded-md border border-surface-300 px-3 py-2 focus:outline-none focus:ring-2 focus:ring-brand-500"
          placeholder="e.g., Mean Reversion RSI"
        />
        {validationErrors.name && (
          <p className="mt-1 text-sm text-danger">{validationErrors.name}</p>
        )}
      </div>

      <div>
        <label htmlFor="description" className="mb-1 block text-sm font-medium text-surface-700">
          Description
        </label>
        <textarea
          id="description"
          value={formData.description || ""}
          onChange={(e) => handleFieldChange("description", e.target.value)}
          className="w-full rounded-md border border-surface-300 px-3 py-2 focus:outline-none focus:ring-2 focus:ring-brand-500"
          placeholder="Describe your strategy's intent and approach"
          rows={3}
        />
      </div>

      <div className="grid grid-cols-2 gap-4">
        <div>
          <label htmlFor="instrument" className="mb-1 block text-sm font-medium text-surface-700">
            Instrument
          </label>
          <input
            id="instrument"
            type="text"
            value={formData.instrument || ""}
            onChange={(e) => handleFieldChange("instrument", e.target.value)}
            className="w-full rounded-md border border-surface-300 px-3 py-2 focus:outline-none focus:ring-2 focus:ring-brand-500"
            placeholder="e.g., ES, NQ, SPY"
          />
        </div>
        <div>
          <label htmlFor="timeframe" className="mb-1 block text-sm font-medium text-surface-700">
            Timeframe
          </label>
          <input
            id="timeframe"
            type="text"
            value={formData.timeframe || ""}
            onChange={(e) => handleFieldChange("timeframe", e.target.value)}
            className="w-full rounded-md border border-surface-300 px-3 py-2 focus:outline-none focus:ring-2 focus:ring-brand-500"
            placeholder="e.g., 1m, 5m, 1h, 1d"
          />
        </div>
      </div>
    </div>
  );

  const renderConditionsStep = () => (
    <div className="space-y-6">
      <DslEditor
        value={formData.entryCondition || ""}
        onChange={(val) => handleFieldChange("entryCondition", val)}
        label="Entry Condition"
        placeholder="e.g., RSI(14) < 30 AND price > SMA(200)"
        testId="entry-dsl"
      />

      <DslEditor
        value={formData.exitCondition || ""}
        onChange={(val) => handleFieldChange("exitCondition", val)}
        label="Exit Condition"
        placeholder="e.g., RSI(14) > 70 OR price < SMA(200)"
        testId="exit-dsl"
      />
    </div>
  );

  const renderRiskStep = () => (
    <div className="space-y-4">
      <div>
        <label
          htmlFor="maxPositionSize"
          className="mb-1 block text-sm font-medium text-surface-700"
        >
          Max Position Size
        </label>
        <input
          id="maxPositionSize"
          type="number"
          value={formData.maxPositionSize || 0}
          onChange={(e) => handleFieldChange("maxPositionSize", parseFloat(e.target.value))}
          className="w-full rounded-md border border-surface-300 px-3 py-2 focus:outline-none focus:ring-2 focus:ring-brand-500"
          placeholder="10000"
        />
      </div>

      <div>
        <label
          htmlFor="stopLossPercent"
          className="mb-1 block text-sm font-medium text-surface-700"
        >
          Stop Loss %
        </label>
        <input
          id="stopLossPercent"
          type="number"
          step="0.1"
          value={formData.stopLossPercent || 0}
          onChange={(e) => handleFieldChange("stopLossPercent", parseFloat(e.target.value))}
          className="w-full rounded-md border border-surface-300 px-3 py-2 focus:outline-none focus:ring-2 focus:ring-brand-500"
          placeholder="2"
        />
      </div>

      <div>
        <label
          htmlFor="takeProfitPercent"
          className="mb-1 block text-sm font-medium text-surface-700"
        >
          Take Profit %
        </label>
        <input
          id="takeProfitPercent"
          type="number"
          step="0.1"
          value={formData.takeProfitPercent || 0}
          onChange={(e) => handleFieldChange("takeProfitPercent", parseFloat(e.target.value))}
          className="w-full rounded-md border border-surface-300 px-3 py-2 focus:outline-none focus:ring-2 focus:ring-brand-500"
          placeholder="5"
        />
      </div>
    </div>
  );

  const renderParametersStep = () => (
    <div className="space-y-4">
      <p className="text-sm text-surface-600">
        Configure any tunable parameters for optimization. Tuning options: None yet.
      </p>
    </div>
  );

  const renderReviewStep = () => (
    <div className="space-y-4">
      <p className="mb-4 text-sm font-medium text-surface-700">
        Review your strategy before submission
      </p>

      <div className="space-y-3 rounded-md bg-surface-50 p-4 text-sm">
        <div>
          <span className="font-medium text-surface-700">Name:</span>
          <p className="text-surface-600">{formData.name || "(not provided)"}</p>
        </div>
        <div>
          <span className="font-medium text-surface-700">Description:</span>
          <p className="text-surface-600">{formData.description || "(not provided)"}</p>
        </div>
        <div>
          <span className="font-medium text-surface-700">Instrument:</span>
          <p className="text-surface-600">{formData.instrument || "(not provided)"}</p>
        </div>
        <div>
          <span className="font-medium text-surface-700">Timeframe:</span>
          <p className="text-surface-600">{formData.timeframe || "(not provided)"}</p>
        </div>
        <div>
          <span className="font-medium text-surface-700">Entry Condition:</span>
          <p className="text-surface-600">{formData.entryCondition || "(not provided)"}</p>
        </div>
        <div>
          <span className="font-medium text-surface-700">Exit Condition:</span>
          <p className="text-surface-600">{formData.exitCondition || "(not provided)"}</p>
        </div>
        <div>
          <span className="font-medium text-surface-700">Max Position Size:</span>
          <p className="text-surface-600">{formData.maxPositionSize || 0}</p>
        </div>
        <div>
          <span className="font-medium text-surface-700">Stop Loss:</span>
          <p className="text-surface-600">{formData.stopLossPercent || 0}%</p>
        </div>
        <div>
          <span className="font-medium text-surface-700">Take Profit:</span>
          <p className="text-surface-600">{formData.takeProfitPercent || 0}%</p>
        </div>
      </div>
    </div>
  );

  // ─────────────────────────────────────────────────────────────────────────
  // Render
  // ─────────────────────────────────────────────────────────────────────────

  const isFirstStep = currentStepIndex === 0;
  const isLastStep = currentStepIndex === STRATEGY_WIZARD_STEPS.length - 1;

  return (
    <div className="mx-auto w-full max-w-2xl p-6">
      {/* Blocked Paper Badge */}
      {hasBlockedPaper && (
        <div className="mb-6 flex items-center gap-2 rounded-md border border-danger/20 bg-danger/5 p-3">
          <AlertCircle className="h-5 w-5 text-danger" />
          <span className="text-sm text-danger">
            <strong>Blocked: Paper-ineligible.</strong> Material uncertainties unresolved.
          </span>
        </div>
      )}

      {/* Step Progress Indicator */}
      <div className="mb-6">
        <p className="text-sm font-medium text-surface-700">
          Step {currentStepIndex + 1} of {STRATEGY_WIZARD_STEPS.length}
        </p>
        <div className="mt-2 flex gap-2">
          {STRATEGY_WIZARD_STEPS.map((step, idx) => (
            <div
              key={step}
              title={step}
              className={`h-2 flex-1 rounded-full ${
                idx <= currentStepIndex ? "bg-brand-500" : "bg-surface-200"
              }`}
            />
          ))}
        </div>
        <div className="mt-2 flex justify-between text-xs text-surface-500">
          {STRATEGY_WIZARD_STEPS.map((step) => (
            <span key={step}>{STEP_LABELS[step] ?? step}</span>
          ))}
        </div>
      </div>

      {/* Form Content */}
      <div className="mb-8">
        {currentStep === "basics" && renderBasicsStep()}
        {currentStep === "conditions" && renderConditionsStep()}
        {currentStep === "risk" && renderRiskStep()}
        {currentStep === "parameters" && renderParametersStep()}
        {currentStep === "review" && renderReviewStep()}
      </div>

      {/* Navigation Buttons */}
      <div className="flex justify-between gap-3">
        {!isFirstStep ? (
          <button
            onClick={handleBack}
            className="flex items-center gap-2 rounded-md border border-surface-300 px-4 py-2 hover:bg-surface-50 focus:outline-none focus:ring-2 focus:ring-brand-500"
          >
            <ChevronLeft className="h-4 w-4" />
            Back
          </button>
        ) : (
          <div /> /* Spacer to keep buttons right-aligned on first step */
        )}

        {!isLastStep ? (
          <button
            onClick={handleNext}
            className="flex items-center gap-2 rounded-md bg-brand-600 px-4 py-2 text-white hover:bg-brand-700 focus:outline-none focus:ring-2 focus:ring-brand-500"
          >
            Next
            <ChevronRight className="h-4 w-4" />
          </button>
        ) : (
          <button
            onClick={handleSubmit}
            disabled={isSubmitting}
            className="flex items-center gap-2 rounded-md bg-success px-4 py-2 text-white hover:opacity-90 focus:outline-none focus:ring-2 focus:ring-success/50 disabled:cursor-not-allowed disabled:opacity-60"
            data-testid="strategy-submit-button"
          >
            {isSubmitting && <Loader2 className="h-4 w-4 animate-spin" />}
            {isSubmitting ? "Creating…" : "Submit Strategy"}
          </button>
        )}
      </div>
    </div>
  );
}
