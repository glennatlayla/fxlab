/**
 * BlockerSummary — card showing what blocks an entity's progression.
 *
 * Displays the blocker owner's name and a next-step action button.
 * Falls back to a generic view for unknown blocker codes.
 *
 * Example:
 *   <BlockerSummary
 *     blockerCode="PENDING_APPROVAL"
 *     ownerDisplayName="Jane Doe"
 *     nextStepLabel="Request Approval"
 *     onNextStep={() => navigate("/approvals/new")}
 *   />
 */

import { ShieldAlert, HelpCircle } from "lucide-react";

/** Known blocker codes and their descriptions. */
const BLOCKER_DESCRIPTIONS: Record<string, string> = {
  PENDING_APPROVAL: "Waiting for governance approval before promotion.",
  PENDING_OVERRIDE_REVIEW: "Override request requires reviewer action.",
  PARITY_FAILURE: "Feed parity check failed — data divergence detected.",
  COVERAGE_BELOW_THRESHOLD: "Test coverage below required threshold.",
  READINESS_CHECK_FAILED: "Readiness assessment identified blocking issues.",
};

interface BlockerSummaryProps {
  /** Machine-readable blocker code. */
  blockerCode: string;
  /** Human-readable display name of the owner responsible for resolving. */
  ownerDisplayName: string;
  /** Label for the call-to-action button. */
  nextStepLabel: string;
  /** Callback when the next-step button is clicked. */
  onNextStep: () => void;
}

export function BlockerSummary({
  blockerCode,
  ownerDisplayName,
  nextStepLabel,
  onNextStep,
}: BlockerSummaryProps) {
  const description = BLOCKER_DESCRIPTIONS[blockerCode];
  const isKnown = !!description;

  return (
    <div className="card flex items-start gap-4">
      <div className="flex-shrink-0 rounded-full bg-warning/10 p-2">
        {isKnown ? (
          <ShieldAlert className="h-5 w-5 text-warning" />
        ) : (
          <HelpCircle className="h-5 w-5 text-surface-400" />
        )}
      </div>
      <div className="flex-1">
        <h4 className="text-sm font-medium text-surface-900">
          {isKnown ? blockerCode.replace(/_/g, " ") : `Unknown Blocker: ${blockerCode}`}
        </h4>
        <p className="mt-0.5 text-sm text-surface-500">
          {isKnown ? description : "This blocker code is not recognized. Check audit logs."}
        </p>
        <p className="mt-1 text-sm text-surface-600">
          Owner: <span className="font-medium">{ownerDisplayName}</span>
        </p>
      </div>
      <button
        onClick={onNextStep}
        className="flex-shrink-0 rounded-md bg-brand-600 px-3 py-1.5 text-sm font-medium
          text-white hover:bg-brand-700"
      >
        {nextStepLabel}
      </button>
    </div>
  );
}
