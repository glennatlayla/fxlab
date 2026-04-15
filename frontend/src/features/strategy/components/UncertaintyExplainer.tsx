/**
 * UncertaintyExplainer — displays strategy compilation uncertainties.
 *
 * Purpose:
 *   Render a list of uncertainty entries identified during strategy validation,
 *   with severity-based styling (info/warning/material). Provides resolution forms
 *   for unresolved entries and shows owner information for material uncertainties.
 *
 * Responsibilities:
 *   - Render severity badges with appropriate colors (danger for material, warning, info).
 *   - Display titles and descriptions for each uncertainty.
 *   - Show resolution forms for unresolved entries.
 *   - Render BlockerSummary for material unresolved entries with owner info.
 *   - Show "Resolved" badge for resolved entries.
 *   - Display empty state when no entries provided.
 *
 * Does NOT:
 *   - Fetch or manage uncertainty data (passed as prop).
 *   - Handle submission of resolution forms.
 *
 * Dependencies:
 *   - UncertaintyEntry type from @/types/strategy
 *   - BlockerSummary component from @/components/ui/BlockerSummary
 *   - lucide-react icons
 *
 * Example:
 *   const entries: UncertaintyEntry[] = [
 *     {
 *       id: "unc-1",
 *       severity: "material",
 *       title: "Material Ambiguity",
 *       description: "Entry signal is ambiguous",
 *       ownerDisplayName: "Alice Chen",
 *       resolved: false,
 *     },
 *   ];
 *   <UncertaintyExplainer entries={entries} />
 */

import type { UncertaintyEntry } from "@/types/strategy";
import { AlertCircle } from "lucide-react";

interface UncertaintyExplainerProps {
  /** List of uncertainty entries to display. */
  entries: UncertaintyEntry[];
}

export function UncertaintyExplainer({ entries }: UncertaintyExplainerProps) {
  if (entries.length === 0) {
    return (
      <div className="rounded-lg bg-surface-50 p-6 text-center">
        <p className="text-surface-600">No uncertainties to review.</p>
      </div>
    );
  }

  return (
    <div className="space-y-4">
      {entries.map((entry) => {
        const severityClasses = {
          info: "bg-info/10 border-l-4 border-info",
          warning: "bg-warning/10 border-l-4 border-warning",
          material: "bg-danger/10 border-l-4 border-danger",
        };

        const badgeClasses = {
          info: "bg-info/20 text-info",
          warning: "bg-warning/20 text-warning",
          material: "bg-danger/20 text-danger",
        };

        return (
          <div key={entry.id} className={`rounded-lg p-4 ${severityClasses[entry.severity]}`}>
            <div className="flex items-start gap-3">
              <div className="flex-shrink-0">
                {entry.severity === "material" ? (
                  <AlertCircle className="h-5 w-5 text-danger" />
                ) : entry.severity === "warning" ? (
                  <AlertCircle className="h-5 w-5 text-warning" />
                ) : (
                  <AlertCircle className="h-5 w-5 text-info" />
                )}
              </div>
              <div className={`flex-1 ${severityClasses[entry.severity]}`}>
                <h3 className="text-sm font-semibold text-surface-900">{entry.title}</h3>
                <div className="mt-2 flex items-center gap-2">
                  <span
                    className={`inline-block rounded px-2 py-0.5 text-xs font-medium ${badgeClasses[entry.severity]}`}
                  >
                    {entry.severity}
                  </span>
                  {entry.resolved && (
                    <span className="inline-block rounded bg-success/20 px-2 py-0.5 text-xs font-medium text-success">
                      resolved
                    </span>
                  )}
                </div>
                <p className="mt-2 text-sm text-surface-700">{entry.description}</p>

                {entry.resolved && entry.resolutionNote && (
                  <p className="mt-2 text-sm italic text-surface-600">
                    Resolution: {entry.resolutionNote}
                  </p>
                )}

                {!entry.resolved && (
                  <div className="mt-3 space-y-3">
                    <textarea
                      placeholder="Enter resolution note..."
                      className="w-full rounded-md border border-surface-300 bg-white px-3 py-2 text-sm
                        text-surface-900 placeholder-surface-400 focus:outline-none focus:ring-2 focus:ring-brand-500"
                      rows={2}
                    />
                    <button
                      className="rounded-md bg-brand-600 px-3 py-1.5 text-sm font-medium text-white
                        hover:bg-brand-700"
                    >
                      Resolve
                    </button>
                    {entry.severity === "material" && entry.ownerDisplayName && (
                      <div className="rounded-lg border border-surface-200 bg-white p-3">
                        <p className="text-sm text-surface-600">
                          Owner: <span className="font-medium">{entry.ownerDisplayName}</span>
                        </p>
                        <a
                          href={`?step=resolve_uncertainty&uncertaintyId=${entry.id}`}
                          className="mt-2 inline-block rounded-md bg-brand-600 px-3 py-1.5 text-sm font-medium
                            text-white hover:bg-brand-700"
                        >
                          Resolve Uncertainty
                        </a>
                      </div>
                    )}
                  </div>
                )}
              </div>
            </div>
          </div>
        );
      })}
    </div>
  );
}
