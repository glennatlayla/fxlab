/**
 * useDraftAutosave — hook managing periodic draft persistence.
 *
 * Purpose:
 *   Debounce field changes (500ms) and periodically sync to backend (30s).
 *   Manages localStorage for instant recovery and backend autosave for
 *   cross-device / cross-session recovery.
 *
 * Responsibilities:
 *   - Debounce form changes to localStorage (500ms after last change).
 *   - Periodically POST to /strategies/draft/autosave (every 30s).
 *   - Track dirty state (unsaved changes since last backend sync).
 *   - Provide save/restore/discard functions for DraftRecoveryBanner.
 *   - Clear localStorage on successful form submission or discard.
 *
 * Does NOT:
 *   - Validate form data (form components handle validation).
 *   - Manage form state (React Hook Form owns that).
 *   - Handle compilation (separate concern).
 *
 * Dependencies:
 *   - @/features/strategy/api for backend calls.
 *   - @/auth/useAuth for user identity.
 *   - @/types/strategy for typed payloads.
 *
 * Error conditions:
 *   - Backend sync failure: logs warning, keeps localStorage copy, retries next interval.
 *   - localStorage unavailable: falls back to backend-only persistence.
 *
 * Example:
 *   const { saveToLocal, syncToBackend, isDirty, lastSyncedAt } = useDraftAutosave({
 *     formStep: "parameters",
 *   });
 */

import { useCallback, useEffect, useRef, useState } from "react";
import { useAuth } from "@/auth/useAuth";
import { strategyApi } from "./api";
import {
  DRAFT_LOCAL_STORAGE_KEY,
  LOCAL_SAVE_DEBOUNCE_MS,
  BACKEND_SYNC_INTERVAL_MS,
} from "./constants";
import type { StrategyDraftFormData, StrategyWizardStep } from "@/types/strategy";
import { randomUUID } from "@/utils/uuid";

// ---------------------------------------------------------------------------
// Session ID — stable per browser tab
// ---------------------------------------------------------------------------

let _sessionId: string | null = null;

function getSessionId(): string {
  if (!_sessionId) {
    _sessionId = randomUUID();
  }
  return _sessionId;
}

// ---------------------------------------------------------------------------
// Hook interface
// ---------------------------------------------------------------------------

export interface UseDraftAutosaveOptions {
  /** Current wizard step for recovery context. */
  formStep: StrategyWizardStep;
  /** Whether autosave is enabled (disable during form submission). */
  enabled?: boolean;
}

export interface UseDraftAutosaveResult {
  /** Save form data to localStorage (debounced). Called on every field change. */
  saveToLocal: (data: Partial<StrategyDraftFormData>) => void;
  /** Force immediate backend sync. Returns true if successful. */
  syncToBackend: (data: Partial<StrategyDraftFormData>) => Promise<boolean>;
  /** Discard draft from both localStorage and backend. */
  discardDraft: (autosaveId?: string) => Promise<void>;
  /** Load draft from localStorage. Returns null if none exists. */
  loadFromLocal: () => Partial<StrategyDraftFormData> | null;
  /** True when localStorage has changes not yet synced to backend. */
  isDirty: boolean;
  /** ISO timestamp of last successful backend sync, or null. */
  lastSyncedAt: string | null;
  /** True while a backend sync is in progress. */
  isSyncing: boolean;
}

// ---------------------------------------------------------------------------
// Hook implementation
// ---------------------------------------------------------------------------

export function useDraftAutosave({
  formStep,
  enabled = true,
}: UseDraftAutosaveOptions): UseDraftAutosaveResult {
  const { user } = useAuth();
  const [isDirty, setIsDirty] = useState(false);
  const [lastSyncedAt, setLastSyncedAt] = useState<string | null>(null);
  const [isSyncing, setIsSyncing] = useState(false);

  const debounceTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const syncIntervalRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const latestDataRef = useRef<Partial<StrategyDraftFormData> | null>(null);

  // -------------------------------------------------------------------------
  // localStorage operations
  // -------------------------------------------------------------------------

  const saveToLocal = useCallback(
    (data: Partial<StrategyDraftFormData>) => {
      latestDataRef.current = data;
      setIsDirty(true);

      if (debounceTimerRef.current) clearTimeout(debounceTimerRef.current);

      debounceTimerRef.current = setTimeout(() => {
        try {
          localStorage.setItem(
            DRAFT_LOCAL_STORAGE_KEY,
            JSON.stringify({
              data,
              formStep,
              savedAt: new Date().toISOString(),
            }),
          );
        } catch {
          // localStorage unavailable or full — silently degrade.
          // Backend sync is the durable fallback.
          console.warn("[useDraftAutosave] localStorage write failed");
        }
      }, LOCAL_SAVE_DEBOUNCE_MS);
    },
    [formStep],
  );

  const loadFromLocal = useCallback((): Partial<StrategyDraftFormData> | null => {
    try {
      const raw = localStorage.getItem(DRAFT_LOCAL_STORAGE_KEY);
      if (!raw) return null;
      const parsed = JSON.parse(raw) as {
        data: Partial<StrategyDraftFormData>;
        formStep: string;
        savedAt: string;
      };
      return parsed.data;
    } catch {
      return null;
    }
  }, []);

  // -------------------------------------------------------------------------
  // Backend sync
  // -------------------------------------------------------------------------

  const syncToBackend = useCallback(
    async (data: Partial<StrategyDraftFormData>): Promise<boolean> => {
      if (!user) return false;

      setIsSyncing(true);
      try {
        const resp = await strategyApi.saveAutosave({
          user_id: user.userId,
          draft_payload: data,
          form_step: formStep,
          client_ts: new Date().toISOString(),
          session_id: getSessionId(),
        });
        setLastSyncedAt(resp.saved_at);
        setIsDirty(false);
        return true;
      } catch {
        console.warn("[useDraftAutosave] Backend sync failed, will retry next interval");
        return false;
      } finally {
        setIsSyncing(false);
      }
    },
    [user, formStep],
  );

  // -------------------------------------------------------------------------
  // Discard draft
  // -------------------------------------------------------------------------

  const discardDraft = useCallback(async (autosaveId?: string) => {
    // Clear localStorage
    try {
      localStorage.removeItem(DRAFT_LOCAL_STORAGE_KEY);
    } catch {
      // Ignore localStorage errors
    }

    // Delete from backend if we have an ID
    if (autosaveId) {
      try {
        await strategyApi.deleteAutosave(autosaveId);
      } catch {
        console.warn("[useDraftAutosave] Backend delete failed for", autosaveId);
      }
    }

    setIsDirty(false);
    setLastSyncedAt(null);
    latestDataRef.current = null;
  }, []);

  // -------------------------------------------------------------------------
  // Periodic backend sync interval
  // -------------------------------------------------------------------------

  useEffect(() => {
    if (!enabled || !user) return;

    syncIntervalRef.current = setInterval(() => {
      const data = latestDataRef.current;
      if (data && isDirty) {
        syncToBackend(data);
      }
    }, BACKEND_SYNC_INTERVAL_MS);

    return () => {
      if (syncIntervalRef.current) clearInterval(syncIntervalRef.current);
    };
  }, [enabled, user, isDirty, syncToBackend]);

  // Cleanup debounce on unmount
  useEffect(() => {
    return () => {
      if (debounceTimerRef.current) clearTimeout(debounceTimerRef.current);
    };
  }, []);

  return {
    saveToLocal,
    syncToBackend,
    discardDraft,
    loadFromLocal,
    isDirty,
    lastSyncedAt,
    isSyncing,
  };
}
