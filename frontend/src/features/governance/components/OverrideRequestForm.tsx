/**
 * OverrideRequestForm — modal form for submitting governance override requests.
 *
 * Purpose:
 *   Collect override request data with client-side Zod validation.
 *   Enforces evidence_link as required URI (AC-3) with url() validation (AC-4).
 *
 * Responsibilities:
 *   - Governance gate selector (blocker_waiver / grade_override).
 *   - Target object ID and type inputs.
 *   - Rationale text (min 20 chars, SOC 2).
 *   - Evidence link field with Zod .url() validation and inline help.
 *   - Client-side validation before submission.
 *
 * Does NOT:
 *   - Execute API calls (parent provides onSubmit callback).
 *   - Manage its own open/close state (controlled by parent).
 *
 * Dependencies:
 *   - ConfirmationModal for modal shell.
 *   - OverrideRequestFormSchema for client-side validation.
 *
 * Example:
 *   <OverrideRequestForm isOpen={show} onClose={close} onSubmit={handleSubmit} />
 */

import { memo, useState, useCallback } from "react";
import type { OverrideRequestForm as OverrideRequestFormType } from "@/types/governance";
import { OverrideRequestFormSchema } from "@/types/governance";
import { OVERRIDE_RATIONALE_MIN_LENGTH, OVERRIDE_TYPE_FILTER_OPTIONS } from "../constants";
import { ConfirmationModal } from "./ConfirmationModal";

export interface OverrideRequestFormProps {
  /** Whether the form modal is open. */
  isOpen: boolean;
  /** Callback to close the form. */
  onClose: () => void;
  /** Callback with validated form data. */
  onSubmit: (data: OverrideRequestFormType) => void;
  /** Whether submission is in progress. */
  isSubmitting?: boolean;
}

/** Initial form state. */
const INITIAL_STATE = {
  object_id: "",
  object_type: "candidate" as const,
  override_type: "grade_override" as const,
  original_state: {},
  new_state: {},
  evidence_link: "",
  rationale: "",
};

/**
 * Render override request form in a modal.
 */
export const OverrideRequestForm = memo(function OverrideRequestForm({
  isOpen,
  onClose,
  onSubmit,
  isSubmitting = false,
}: OverrideRequestFormProps) {
  const [formData, setFormData] = useState(INITIAL_STATE);
  const [errors, setErrors] = useState<Record<string, string>>({});

  const handleChange = useCallback((field: string, value: string) => {
    setFormData((prev) => ({ ...prev, [field]: value }));
    // Clear error on change.
    setErrors((prev) => {
      const next = { ...prev };
      delete next[field];
      return next;
    });
  }, []);

  const handleSubmit = useCallback(() => {
    const result = OverrideRequestFormSchema.safeParse(formData);
    if (!result.success) {
      const fieldErrors: Record<string, string> = {};
      for (const issue of result.error.issues) {
        const key = issue.path.join(".");
        if (!fieldErrors[key]) {
          fieldErrors[key] = issue.message;
        }
      }
      setErrors(fieldErrors);
      return;
    }

    onSubmit(result.data);
  }, [formData, onSubmit]);

  const handleClose = useCallback(() => {
    setFormData(INITIAL_STATE);
    setErrors({});
    onClose();
  }, [onClose]);

  return (
    <ConfirmationModal isOpen={isOpen} onClose={handleClose} title="Request Governance Override">
      <div className="space-y-4">
        {/* Object ID */}
        <div>
          <label htmlFor="override-object-id" className="block text-sm font-medium text-slate-700">
            Target Object ID
          </label>
          <input
            id="override-object-id"
            data-testid="override-object-id-input"
            type="text"
            value={formData.object_id}
            onChange={(e) => handleChange("object_id", e.target.value)}
            disabled={isSubmitting}
            placeholder="ULID of the candidate or deployment"
            className="mt-1 w-full rounded-md border border-slate-300 px-3 py-2 text-sm text-slate-900 placeholder:text-slate-400 focus:border-emerald-500 focus:outline-none focus:ring-1 focus:ring-emerald-500 disabled:opacity-50"
          />
          {errors.object_id && <p className="mt-1 text-xs text-red-600">{errors.object_id}</p>}
        </div>

        {/* Object Type */}
        <div>
          <label
            htmlFor="override-object-type"
            className="block text-sm font-medium text-slate-700"
          >
            Object Type
          </label>
          <select
            id="override-object-type"
            data-testid="override-object-type-select"
            value={formData.object_type}
            onChange={(e) => handleChange("object_type", e.target.value)}
            disabled={isSubmitting}
            className="mt-1 w-full rounded-md border border-slate-300 px-3 py-2 text-sm text-slate-900 focus:border-emerald-500 focus:outline-none focus:ring-1 focus:ring-emerald-500 disabled:opacity-50"
          >
            <option value="candidate">Candidate</option>
            <option value="deployment">Deployment</option>
          </select>
        </div>

        {/* Override Type */}
        <div>
          <label
            htmlFor="override-type-select"
            className="block text-sm font-medium text-slate-700"
          >
            Override Type
          </label>
          <select
            id="override-type-select"
            data-testid="override-type-select"
            value={formData.override_type}
            onChange={(e) => handleChange("override_type", e.target.value)}
            disabled={isSubmitting}
            className="mt-1 w-full rounded-md border border-slate-300 px-3 py-2 text-sm text-slate-900 focus:border-emerald-500 focus:outline-none focus:ring-1 focus:ring-emerald-500 disabled:opacity-50"
          >
            {OVERRIDE_TYPE_FILTER_OPTIONS.filter((o) => o.value !== "all").map((opt) => (
              <option key={opt.value} value={opt.value}>
                {opt.label}
              </option>
            ))}
          </select>
        </div>

        {/* Evidence Link (AC-3, AC-4) */}
        <div>
          <label
            htmlFor="override-evidence-link"
            className="block text-sm font-medium text-slate-700"
          >
            Evidence Link
          </label>
          <input
            id="override-evidence-link"
            data-testid="override-evidence-link-input"
            type="url"
            value={formData.evidence_link}
            onChange={(e) => handleChange("evidence_link", e.target.value)}
            disabled={isSubmitting}
            placeholder="https://jira.example.com/browse/FX-123"
            aria-describedby="evidence-link-help"
            className="mt-1 w-full rounded-md border border-slate-300 px-3 py-2 text-sm text-slate-900 placeholder:text-slate-400 focus:border-emerald-500 focus:outline-none focus:ring-1 focus:ring-emerald-500 disabled:opacity-50"
          />
          <p id="evidence-link-help" className="mt-1 text-xs text-slate-500">
            Paste a link to your Jira ticket, Confluence doc, or GitHub issue
          </p>
          {errors.evidence_link && (
            <p data-testid="evidence-link-error" className="mt-1 text-xs text-red-600">
              {errors.evidence_link}
            </p>
          )}
        </div>

        {/* Rationale */}
        <div>
          <label htmlFor="override-rationale" className="block text-sm font-medium text-slate-700">
            Rationale
          </label>
          <textarea
            id="override-rationale"
            data-testid="override-rationale-input"
            value={formData.rationale}
            onChange={(e) => handleChange("rationale", e.target.value)}
            disabled={isSubmitting}
            placeholder="Describe the override justification (minimum 20 characters, SOC 2 requirement)..."
            rows={3}
            className="mt-1 w-full rounded-md border border-slate-300 px-3 py-2 text-sm text-slate-900 placeholder:text-slate-400 focus:border-emerald-500 focus:outline-none focus:ring-1 focus:ring-emerald-500 disabled:opacity-50"
          />
          <p className="mt-1 text-xs text-slate-500">
            {formData.rationale.trim().length}/{OVERRIDE_RATIONALE_MIN_LENGTH} characters minimum
          </p>
          {errors.rationale && (
            <p data-testid="rationale-error" className="mt-1 text-xs text-red-600">
              {errors.rationale}
            </p>
          )}
        </div>

        {/* Actions */}
        <div className="flex justify-end gap-3 pt-2">
          <button
            type="button"
            onClick={handleClose}
            disabled={isSubmitting}
            data-testid="override-form-cancel"
            className="rounded-md border border-slate-300 bg-white px-4 py-2 text-sm font-medium text-slate-700 hover:bg-slate-50 disabled:opacity-50"
          >
            Cancel
          </button>
          <button
            type="button"
            onClick={handleSubmit}
            disabled={isSubmitting}
            data-testid="override-form-submit"
            className="rounded-md bg-emerald-600 px-4 py-2 text-sm font-medium text-white hover:bg-emerald-700 disabled:cursor-not-allowed disabled:opacity-50"
          >
            {isSubmitting ? "Submitting..." : "Submit Override Request"}
          </button>
        </div>
      </div>
    </ConfirmationModal>
  );
});
