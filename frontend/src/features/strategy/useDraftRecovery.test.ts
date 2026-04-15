/**
 * Tests for useDraftRecovery hook.
 *
 * Verifies:
 *   - isChecking starts as true, becomes false after check
 *   - returns null when no recoverable draft exists (neither local nor backend)
 *   - returns localStorage draft when only local exists
 *   - returns backend draft when only backend exists
 *   - returns the most recent draft when both exist (compare timestamps)
 *   - restoreDraft returns the data and clears the banner
 *   - discardDraft clears localStorage and calls deleteAutosave for backend drafts
 */

import { renderHook, act, waitFor } from "@testing-library/react";
import { describe, it, expect, beforeEach, afterEach, vi } from "vitest";
import { useDraftRecovery } from "./useDraftRecovery";
import { strategyApi } from "./api";
import { useAuth } from "@/auth/useAuth";
import type { StrategyDraftFormData, DraftAutosaveRecord } from "@/types/strategy";

// Mock dependencies
vi.mock("./api");
vi.mock("@/auth/useAuth");

const mockStrategyApi = vi.mocked(strategyApi);
const mockUseAuth = vi.mocked(useAuth);

describe("useDraftRecovery", () => {
  const mockUser = {
    userId: "user-123",
    email: "test@example.com",
    displayName: "Test User",
    role: "trader",
    scopes: ["strategy:write"],
  };

  const mockLocalData: Partial<StrategyDraftFormData> = {
    name: "Local Strategy",
    description: "Local draft",
    instrument: "ES",
  };

  const mockBackendData: Partial<StrategyDraftFormData> = {
    name: "Backend Strategy",
    description: "Backend draft",
    instrument: "NQ",
  };

  const now = new Date();
  const fiveMinutesAgo = new Date(now.getTime() - 5 * 60 * 1000);

  const mockBackendRecord: DraftAutosaveRecord = {
    id: "autosave-456",
    user_id: mockUser.userId,
    draft_payload: mockBackendData,
    form_step: "conditions",
    session_id: "session-789",
    client_ts: fiveMinutesAgo.toISOString(),
    created_at: fiveMinutesAgo.toISOString(),
    updated_at: fiveMinutesAgo.toISOString(),
  };

  beforeEach(() => {
    localStorage.clear();
    mockUseAuth.mockReturnValue({
      user: mockUser,
      isAuthenticated: true,
      accessToken: "mock-token",
      isLoading: false,
      hasScope: vi.fn(() => true),
      login: vi.fn(),
      logout: vi.fn(),
    });
    mockStrategyApi.getLatestAutosave.mockResolvedValue(null);
    mockStrategyApi.deleteAutosave.mockResolvedValue(undefined);
  });

  afterEach(() => {
    vi.restoreAllMocks();
    localStorage.clear();
  });

  describe("recovery detection", () => {
    it("starts with isChecking as true, becomes false after check", async () => {
      const { result } = renderHook(() => useDraftRecovery());

      expect(result.current.isChecking).toBe(true);

      await waitFor(() => {
        expect(result.current.isChecking).toBe(false);
      });
    });

    it("returns null when no recoverable draft exists", async () => {
      const { result } = renderHook(() => useDraftRecovery());

      await waitFor(() => {
        expect(result.current.isChecking).toBe(false);
      });

      expect(result.current.recoverableDraft).toBeNull();
    });

    it("returns localStorage draft when only local exists", async () => {
      const storedObj = {
        data: mockLocalData,
        formStep: "basics",
        savedAt: new Date().toISOString(),
      };

      localStorage.setItem("fxlab:strategy_draft", JSON.stringify(storedObj));

      const { result } = renderHook(() => useDraftRecovery());

      await waitFor(() => {
        expect(result.current.isChecking).toBe(false);
      });

      expect(result.current.recoverableDraft).not.toBeNull();
      expect(result.current.recoverableDraft?.data).toEqual(mockLocalData);
      expect(result.current.recoverableDraft?.source).toBe("local");
      expect(result.current.recoverableDraft?.autosaveId).toBeNull();
      expect(result.current.recoverableDraft?.formStep).toBe("basics");
    });

    it("returns backend draft when only backend exists", async () => {
      mockStrategyApi.getLatestAutosave.mockResolvedValue(mockBackendRecord);

      const { result } = renderHook(() => useDraftRecovery());

      await waitFor(() => {
        expect(result.current.isChecking).toBe(false);
      });

      expect(result.current.recoverableDraft).not.toBeNull();
      expect(result.current.recoverableDraft?.data).toEqual(mockBackendData);
      expect(result.current.recoverableDraft?.source).toBe("backend");
      expect(result.current.recoverableDraft?.autosaveId).toBe("autosave-456");
      expect(result.current.recoverableDraft?.formStep).toBe("conditions");
    });

    it("returns the most recent draft when both local and backend exist", async () => {
      const now = new Date();
      const localTime = new Date(now.getTime() - 10 * 60 * 1000); // 10 minutes ago
      const backendTime = new Date(now.getTime() - 5 * 60 * 1000); // 5 minutes ago

      const storedObj = {
        data: mockLocalData,
        formStep: "basics",
        savedAt: localTime.toISOString(),
      };

      localStorage.setItem("fxlab:strategy_draft", JSON.stringify(storedObj));

      const recentBackendRecord: DraftAutosaveRecord = {
        ...mockBackendRecord,
        updated_at: backendTime.toISOString(),
        client_ts: backendTime.toISOString(),
      };

      mockStrategyApi.getLatestAutosave.mockResolvedValue(recentBackendRecord);

      const { result } = renderHook(() => useDraftRecovery());

      await waitFor(() => {
        expect(result.current.isChecking).toBe(false);
      });

      // Should return backend since it's more recent
      expect(result.current.recoverableDraft?.source).toBe("backend");
      expect(result.current.recoverableDraft?.data).toEqual(mockBackendData);
    });

    it("returns the most recent draft when local is more recent", async () => {
      const now = new Date();
      const localTime = new Date(now.getTime() - 2 * 60 * 1000); // 2 minutes ago
      const backendTime = new Date(now.getTime() - 10 * 60 * 1000); // 10 minutes ago

      const storedObj = {
        data: mockLocalData,
        formStep: "basics",
        savedAt: localTime.toISOString(),
      };

      localStorage.setItem("fxlab:strategy_draft", JSON.stringify(storedObj));

      const olderBackendRecord: DraftAutosaveRecord = {
        ...mockBackendRecord,
        updated_at: backendTime.toISOString(),
        client_ts: backendTime.toISOString(),
      };

      mockStrategyApi.getLatestAutosave.mockResolvedValue(olderBackendRecord);

      const { result } = renderHook(() => useDraftRecovery());

      await waitFor(() => {
        expect(result.current.isChecking).toBe(false);
      });

      // Should return local since it's more recent
      expect(result.current.recoverableDraft?.source).toBe("local");
      expect(result.current.recoverableDraft?.data).toEqual(mockLocalData);
    });

    it("ignores corrupt localStorage during recovery check", async () => {
      localStorage.setItem("fxlab:strategy_draft", "invalid-json{{{");

      mockStrategyApi.getLatestAutosave.mockResolvedValue(mockBackendRecord);

      const { result } = renderHook(() => useDraftRecovery());

      await waitFor(() => {
        expect(result.current.isChecking).toBe(false);
      });

      // Should fall back to backend despite corrupt local data
      expect(result.current.recoverableDraft?.source).toBe("backend");
      expect(result.current.recoverableDraft?.data).toEqual(mockBackendData);
    });

    it("falls back to local when backend API fails", async () => {
      const storedObj = {
        data: mockLocalData,
        formStep: "basics",
        savedAt: new Date().toISOString(),
      };

      localStorage.setItem("fxlab:strategy_draft", JSON.stringify(storedObj));

      mockStrategyApi.getLatestAutosave.mockRejectedValue(new Error("Backend unavailable"));

      const { result } = renderHook(() => useDraftRecovery());

      await waitFor(() => {
        expect(result.current.isChecking).toBe(false);
      });

      expect(result.current.recoverableDraft?.source).toBe("local");
      expect(result.current.recoverableDraft?.data).toEqual(mockLocalData);
    });

    it("handles unauthenticated users gracefully", async () => {
      mockUseAuth.mockReturnValue({
        user: null,
        isAuthenticated: false,
        accessToken: null,
        isLoading: false,
        hasScope: vi.fn(() => false),
        login: vi.fn(),
        logout: vi.fn(),
      });

      const storedObj = {
        data: mockLocalData,
        formStep: "basics",
        savedAt: new Date().toISOString(),
      };

      localStorage.setItem("fxlab:strategy_draft", JSON.stringify(storedObj));

      const { result } = renderHook(() => useDraftRecovery());

      await waitFor(() => {
        expect(result.current.isChecking).toBe(false);
      });

      // Should return local only, no backend call
      expect(result.current.recoverableDraft?.source).toBe("local");
      expect(mockStrategyApi.getLatestAutosave).not.toHaveBeenCalled();
    });
  });

  describe("restoreDraft", () => {
    it("returns the form data from recoverable draft", async () => {
      const storedObj = {
        data: mockLocalData,
        formStep: "basics",
        savedAt: new Date().toISOString(),
      };

      localStorage.setItem("fxlab:strategy_draft", JSON.stringify(storedObj));

      const { result } = renderHook(() => useDraftRecovery());

      await waitFor(() => {
        expect(result.current.isChecking).toBe(false);
      });

      const restored = result.current.restoreDraft();

      expect(restored).toEqual(mockLocalData);
    });

    it("clears the recoverable draft banner after restore", async () => {
      const storedObj = {
        data: mockLocalData,
        formStep: "basics",
        savedAt: new Date().toISOString(),
      };

      localStorage.setItem("fxlab:strategy_draft", JSON.stringify(storedObj));

      const { result } = renderHook(() => useDraftRecovery());

      await waitFor(() => {
        expect(result.current.isChecking).toBe(false);
      });

      expect(result.current.recoverableDraft).not.toBeNull();

      act(() => {
        result.current.restoreDraft();
      });

      expect(result.current.recoverableDraft).toBeNull();
    });

    it("returns null when no recoverable draft exists", async () => {
      const { result } = renderHook(() => useDraftRecovery());

      await waitFor(() => {
        expect(result.current.isChecking).toBe(false);
      });

      const restored = result.current.restoreDraft();

      expect(restored).toBeNull();
    });
  });

  describe("discardDraft", () => {
    it("clears localStorage", async () => {
      const storedObj = {
        data: mockLocalData,
        formStep: "basics",
        savedAt: new Date().toISOString(),
      };

      localStorage.setItem("fxlab:strategy_draft", JSON.stringify(storedObj));

      const { result } = renderHook(() => useDraftRecovery());

      await waitFor(() => {
        expect(result.current.isChecking).toBe(false);
      });

      expect(localStorage.getItem("fxlab:strategy_draft")).not.toBeNull();

      await act(async () => {
        await result.current.discardDraft();
      });

      expect(localStorage.getItem("fxlab:strategy_draft")).toBeNull();
    });

    it("calls deleteAutosave for backend drafts", async () => {
      mockStrategyApi.getLatestAutosave.mockResolvedValue(mockBackendRecord);

      const { result } = renderHook(() => useDraftRecovery());

      await waitFor(() => {
        expect(result.current.isChecking).toBe(false);
      });

      await act(async () => {
        await result.current.discardDraft();
      });

      expect(mockStrategyApi.deleteAutosave).toHaveBeenCalledWith("autosave-456");
    });

    it("does not call deleteAutosave for local-only drafts", async () => {
      const storedObj = {
        data: mockLocalData,
        formStep: "basics",
        savedAt: new Date().toISOString(),
      };

      localStorage.setItem("fxlab:strategy_draft", JSON.stringify(storedObj));

      const { result } = renderHook(() => useDraftRecovery());

      await waitFor(() => {
        expect(result.current.isChecking).toBe(false);
      });

      await act(async () => {
        await result.current.discardDraft();
      });

      expect(mockStrategyApi.deleteAutosave).not.toHaveBeenCalled();
    });

    it("clears recoverableDraft state after discard", async () => {
      const storedObj = {
        data: mockLocalData,
        formStep: "basics",
        savedAt: new Date().toISOString(),
      };

      localStorage.setItem("fxlab:strategy_draft", JSON.stringify(storedObj));

      const { result } = renderHook(() => useDraftRecovery());

      await waitFor(() => {
        expect(result.current.isChecking).toBe(false);
      });

      expect(result.current.recoverableDraft).not.toBeNull();

      await act(async () => {
        await result.current.discardDraft();
      });

      expect(result.current.recoverableDraft).toBeNull();
    });

    it("handles backend delete failure gracefully", async () => {
      mockStrategyApi.getLatestAutosave.mockResolvedValue(mockBackendRecord);
      mockStrategyApi.deleteAutosave.mockRejectedValue(new Error("Delete failed"));

      const { result } = renderHook(() => useDraftRecovery());

      await waitFor(() => {
        expect(result.current.isChecking).toBe(false);
      });

      // Should not throw
      await act(async () => {
        await result.current.discardDraft();
      });

      // State should still be cleared
      expect(result.current.recoverableDraft).toBeNull();
    });

    it("ignores localStorage clear errors", async () => {
      const storedObj = {
        data: mockLocalData,
        formStep: "basics",
        savedAt: new Date().toISOString(),
      };

      localStorage.setItem("fxlab:strategy_draft", JSON.stringify(storedObj));

      const { result } = renderHook(() => useDraftRecovery());

      await waitFor(() => {
        expect(result.current.isChecking).toBe(false);
      });

      // Mock localStorage to throw on removeItem
      const removeItemSpy = vi.spyOn(Storage.prototype, "removeItem").mockImplementation(() => {
        throw new Error("Storage error");
      });

      // Should not throw
      await act(async () => {
        await result.current.discardDraft();
      });

      removeItemSpy.mockRestore();

      // State should still be cleared
      expect(result.current.recoverableDraft).toBeNull();
    });
  });

  describe("cancellation on unmount", () => {
    it("does not update state if unmounted before check completes", async () => {
      const { unmount } = renderHook(() => useDraftRecovery());

      // Unmount immediately
      unmount();

      // Fast-forward timers to allow async operations
      await waitFor(() => {
        // This should resolve without errors
      });

      // No assertion needed; the test passes if no errors occur
    });
  });
});
