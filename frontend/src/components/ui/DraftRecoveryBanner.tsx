/**
 * DraftRecoveryBanner — notification that a previous draft autosave exists.
 *
 * Shown at the top of the Strategy Studio when an unsaved draft is detected.
 *
 * Example:
 *   <DraftRecoveryBanner savedAt="2026-04-03T10:30:00Z" onRestore={restore} onDiscard={discard} />
 */

import { FileWarning } from "lucide-react";

interface DraftRecoveryBannerProps {
  /** ISO-8601 timestamp of the draft. */
  savedAt: string;
  /** Restore the draft into the editor. */
  onRestore: () => void;
  /** Discard the draft permanently. */
  onDiscard: () => void;
}

export function DraftRecoveryBanner({ savedAt, onRestore, onDiscard }: DraftRecoveryBannerProps) {
  const formattedDate = new Date(savedAt).toLocaleString();

  return (
    <div className="flex items-center gap-3 rounded-md border border-info/30 bg-blue-50 px-4 py-3">
      <FileWarning className="h-5 w-5 flex-shrink-0 text-info" />
      <div className="flex-1 text-sm text-blue-800">
        Unsaved draft found from <span className="font-medium">{formattedDate}</span>.
      </div>
      <div className="flex gap-2">
        <button
          onClick={onRestore}
          className="rounded-md bg-brand-600 px-3 py-1 text-sm font-medium text-white hover:bg-brand-700"
        >
          Restore
        </button>
        <button
          onClick={onDiscard}
          className="rounded-md border border-surface-300 px-3 py-1 text-sm font-medium
            text-surface-600 hover:bg-surface-100"
        >
          Discard
        </button>
      </div>
    </div>
  );
}
