/**
 * useDraftRecovery — hook for detecting and restoring recoverable drafts.
 *
 * Purpose:
 *   On page load, check both localStorage and the backend for recoverable
 *   drafts. Surface the most recent one via DraftRecoveryBanner.
 *
 * Responsibilities:
 *   - Check localStorage for a saved draft on mount.
 *   - Call GET /strategies/draft/autosave/latest for backend recovery.
 *   - Return the most recent recoverable draft (local or backend).
 *   - Provide restore and discard callbacks for the banner.
 *
 * Does NOT:
 *   - Apply recovered data to the form (caller does that).
 *   - Manage form state.
 *   - Auto-restore without user consent (spec: explicit "Restore" / "Start fresh").
 *
 * Dependencies:
 *   - @/features/strategy/api for backend recovery.
 *   - @/auth/useAuth for user identity.
 *
 * Example:
 *   const { recoverableDraft, restoreDraft, discardDraft, isChecking } = useDraftRecovery();
 *   if (recoverableDraft) {
 *     return <DraftRecoveryBanner savedAt={recoverableDraft.savedAt} ... />;
 *   }
 */

import { useCallback, useEffect, useState } from "react";
import { useAuth } from "@/auth/useAuth";
import { strategyApi } from "./api";
import { DRAFT_LOCAL_STORAGE_KEY } from "./constants";
import type { StrategyDraftFormData } from "@/types/strategy";

// ---------------------------------------------------------------------------
// Hook interface
// ---------------------------------------------------------------------------

export interface RecoverableDraft {
  /** Partial form data from the saved draft. */
  data: Partial<StrategyDraftFormData>;
  /** ISO timestamp of when the draft was saved. */
  savedAt: string;
  /** Wizard step the user was on. */
  formStep: string;
  /** Source of the recovered draft. */
  source: "local" | "backend";
  /** Backend autosave ID (for deletion on discard). Null for local-only. */
  autosaveId: string | null;
}

export interface UseDraftRecoveryResult {
  /** The recoverable draft, or null if none found. */
  recoverableDraft: RecoverableDraft | null;
  /** True while checking for recoverable drafts. */
  isChecking: boolean;
  /** Restore the draft — returns the form data for the caller to apply. */
  restoreDraft: () => Partial<StrategyDraftFormData> | null;
  /** Discard the draft from both localStorage and backend. */
  discardDraft: () => Promise<void>;
}

// ---------------------------------------------------------------------------
// Hook implementation
// ---------------------------------------------------------------------------

export function useDraftRecovery(): UseDraftRecoveryResult {
  const { user } = useAuth();
  const [recoverableDraft, setRecoverableDraft] = useState<RecoverableDraft | null>(null);
  const [isChecking, setIsChecking] = useState(true);

  useEffect(() => {
    let cancelled = false;

    async function checkForRecoverableDrafts() {
      // 1. Check localStorage first (instant, no network)
      let localDraft: RecoverableDraft | null = null;
      try {
        const raw = localStorage.getItem(DRAFT_LOCAL_STORAGE_KEY);
        if (raw) {
          const parsed = JSON.parse(raw) as {
            data: Partial<StrategyDraftFormData>;
            formStep: string;
            savedAt: string;
          };
          localDraft = {
            data: parsed.data,
            savedAt: parsed.savedAt,
            formStep: parsed.formStep,
            source: "local",
            autosaveId: null,
          };
        }
      } catch {
        // Corrupt localStorage — ignore it
      }

      // 2. Check backend (if user is authenticated)
      let backendDraft: RecoverableDraft | null = null;
      if (user) {
        try {
          const record = await strategyApi.getLatestAutosave(user.userId);
          if (record) {
            backendDraft = {
              data: record.draft_payload,
              savedAt: record.updated_at,
              formStep: record.form_step,
              source: "backend",
              autosaveId: record.id,
            };
          }
        } catch {
          // Backend unavailable — fall back to local only
        }
      }

      if (cancelled) return;

      // 3. Use the most recent draft (compare timestamps)
      if (localDraft && backendDraft) {
        const localTime = new Date(localDraft.savedAt).getTime();
        const backendTime = new Date(backendDraft.savedAt).getTime();
        setRecoverableDraft(localTime >= backendTime ? localDraft : backendDraft);
      } else {
        setRecoverableDraft(localDraft || backendDraft);
      }

      setIsChecking(false);
    }

    checkForRecoverableDrafts();

    return () => {
      cancelled = true;
    };
  }, [user]);

  const restoreDraft = useCallback((): Partial<StrategyDraftFormData> | null => {
    if (!recoverableDraft) return null;
    // Clear the banner after restore
    setRecoverableDraft(null);
    return recoverableDraft.data;
  }, [recoverableDraft]);

  const discardDraft = useCallback(async () => {
    // Clear localStorage
    try {
      localStorage.removeItem(DRAFT_LOCAL_STORAGE_KEY);
    } catch {
      // Ignore
    }

    // Delete from backend if applicable
    if (recoverableDraft?.autosaveId) {
      try {
        await strategyApi.deleteAutosave(recoverableDraft.autosaveId);
      } catch {
        console.warn("[useDraftRecovery] Backend delete failed");
      }
    }

    setRecoverableDraft(null);
  }, [recoverableDraft]);

  return {
    recoverableDraft,
    isChecking,
    restoreDraft,
    discardDraft,
  };
}
