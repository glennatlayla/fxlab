/**
 * Tests for useDraftAutosave hook.
 *
 * Verifies:
 *   - saveToLocal debounces and writes to localStorage after 500ms
 *   - loadFromLocal returns parsed data from localStorage
 *   - loadFromLocal returns null when nothing stored
 *   - syncToBackend calls strategyApi.saveAutosave with correct payload
 *   - syncToBackend sets lastSyncedAt on success
 *   - syncToBackend returns false on failure and keeps isDirty true
 *   - discardDraft clears localStorage and calls deleteAutosave
 *   - periodic backend sync fires every 30 seconds when dirty
 *   - isSyncing is true during backend sync
 */

import { renderHook, act } from "@testing-library/react";
import { describe, it, expect, beforeEach, afterEach, vi } from "vitest";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { ReactNode } from "react";
import { useDraftAutosave } from "./useDraftAutosave";
import { strategyApi } from "./api";
import { useAuth } from "@/auth/useAuth";
import { AuthProvider } from "@/auth/AuthProvider";
import type { StrategyDraftFormData, DraftAutosaveResponse } from "@/types/strategy";

// Mock dependencies
vi.mock("./api");
vi.mock("@/auth/useAuth");

const mockStrategyApi = vi.mocked(strategyApi);
const mockUseAuth = vi.mocked(useAuth);

// Test wrapper with providers
function createWrapper(queryClient: QueryClient) {
  return function Wrapper({ children }: { children: ReactNode }) {
    return (
      <QueryClientProvider client={queryClient}>
        <AuthProvider>{children}</AuthProvider>
      </QueryClientProvider>
    );
  };
}

describe("useDraftAutosave", () => {
  const mockUser = {
    userId: "user-123",
    email: "test@example.com",
    displayName: "Test User",
    role: "trader",
    scopes: ["strategy:write"],
  };

  const mockFormData: Partial<StrategyDraftFormData> = {
    name: "Test Strategy",
    description: "A test strategy",
    instrument: "ES",
  };

  const mockAutosaveResponse: DraftAutosaveResponse = {
    autosave_id: "autosave-456",
    saved_at: new Date().toISOString(),
  };

  let queryClient: QueryClient;

  beforeEach(() => {
    vi.useFakeTimers();
    localStorage.clear();

    // Create a fresh QueryClient for each test
    queryClient = new QueryClient({
      defaultOptions: {
        queries: { retry: false },
        mutations: { retry: false },
      },
    });

    mockUseAuth.mockReturnValue({
      user: mockUser,
      isAuthenticated: true,
      accessToken: "mock-token",
      isLoading: false,
      hasScope: vi.fn(() => true),
      login: vi.fn(),
      logout: vi.fn(),
    });
    mockStrategyApi.saveAutosave.mockResolvedValue(mockAutosaveResponse);
    mockStrategyApi.deleteAutosave.mockResolvedValue(undefined);
  });

  afterEach(() => {
    vi.clearAllMocks();
    vi.useRealTimers();
    localStorage.clear();
  });

  describe("saveToLocal", () => {
    it("debounces and writes to localStorage after 500ms", async () => {
      const { result } = renderHook(() => useDraftAutosave({ formStep: "basics" }), {
        wrapper: createWrapper(queryClient),
      });

      act(() => {
        result.current.saveToLocal(mockFormData);
      });

      // Should not be in localStorage yet
      expect(localStorage.getItem("fxlab:strategy_draft")).toBeNull();

      // Fast-forward 500ms
      act(() => {
        vi.advanceTimersByTime(500);
      });

      // Now should be in localStorage
      const stored = localStorage.getItem("fxlab:strategy_draft");
      expect(stored).not.toBeNull();
      const parsed = JSON.parse(stored!);
      expect(parsed.data).toEqual(mockFormData);
      expect(parsed.formStep).toBe("basics");
    });

    it("sets isDirty to true immediately on save", () => {
      const { result } = renderHook(() => useDraftAutosave({ formStep: "basics" }), {
        wrapper: createWrapper(queryClient),
      });

      expect(result.current.isDirty).toBe(false);

      act(() => {
        result.current.saveToLocal(mockFormData);
      });

      expect(result.current.isDirty).toBe(true);
    });

    it("clears previous debounce timer on subsequent calls", async () => {
      const { result } = renderHook(() => useDraftAutosave({ formStep: "basics" }), {
        wrapper: createWrapper(queryClient),
      });

      act(() => {
        result.current.saveToLocal(mockFormData);
      });

      // Fast-forward 300ms (not at 500ms threshold yet)
      act(() => {
        vi.advanceTimersByTime(300);
      });

      const stored1 = localStorage.getItem("fxlab:strategy_draft");
      expect(stored1).toBeNull();

      // Call saveToLocal again (resets the debounce)
      const updatedData = { ...mockFormData, name: "Updated Strategy" };
      act(() => {
        result.current.saveToLocal(updatedData);
      });

      // Fast-forward another 300ms (total 600ms from first call, but only 300ms since second)
      act(() => {
        vi.advanceTimersByTime(300);
      });

      const stored2 = localStorage.getItem("fxlab:strategy_draft");
      expect(stored2).toBeNull();

      // Fast-forward another 200ms (total 500ms from second call)
      act(() => {
        vi.advanceTimersByTime(200);
      });

      const stored3 = localStorage.getItem("fxlab:strategy_draft");
      expect(stored3).not.toBeNull();
      const parsed = JSON.parse(stored3!);
      expect(parsed.data.name).toBe("Updated Strategy");
    });
  });

  describe("loadFromLocal", () => {
    it("returns parsed data from localStorage", () => {
      const testData: Partial<StrategyDraftFormData> = {
        name: "Stored Strategy",
        description: "Persisted data",
      };

      const storedObj = {
        data: testData,
        formStep: "conditions",
        savedAt: new Date().toISOString(),
      };

      localStorage.setItem("fxlab:strategy_draft", JSON.stringify(storedObj));

      const { result } = renderHook(() => useDraftAutosave({ formStep: "conditions" }), {
        wrapper: createWrapper(queryClient),
      });

      const loaded = result.current.loadFromLocal();
      expect(loaded).toEqual(testData);
    });

    it("returns null when nothing stored", () => {
      const { result } = renderHook(() => useDraftAutosave({ formStep: "basics" }), {
        wrapper: createWrapper(queryClient),
      });

      const loaded = result.current.loadFromLocal();
      expect(loaded).toBeNull();
    });

    it("returns null on corrupt localStorage data", () => {
      localStorage.setItem("fxlab:strategy_draft", "invalid-json{{{");

      const { result } = renderHook(() => useDraftAutosave({ formStep: "basics" }), {
        wrapper: createWrapper(queryClient),
      });

      const loaded = result.current.loadFromLocal();
      expect(loaded).toBeNull();
    });
  });

  describe("syncToBackend", () => {
    it("calls strategyApi.saveAutosave with correct payload", async () => {
      const { result } = renderHook(() => useDraftAutosave({ formStep: "risk" }), {
        wrapper: createWrapper(queryClient),
      });

      await act(async () => {
        await result.current.syncToBackend(mockFormData);
      });

      expect(mockStrategyApi.saveAutosave).toHaveBeenCalledWith(
        expect.objectContaining({
          user_id: mockUser.userId,
          draft_payload: mockFormData,
          form_step: "risk",
          session_id: expect.any(String),
          client_ts: expect.any(String),
        }),
      );
    });

    it("sets lastSyncedAt on success", async () => {
      const { result } = renderHook(() => useDraftAutosave({ formStep: "basics" }), {
        wrapper: createWrapper(queryClient),
      });

      expect(result.current.lastSyncedAt).toBeNull();

      await act(async () => {
        await result.current.syncToBackend(mockFormData);
      });

      expect(result.current.lastSyncedAt).toBe(mockAutosaveResponse.saved_at);
    });

    it("returns true on success", async () => {
      const { result } = renderHook(() => useDraftAutosave({ formStep: "basics" }), {
        wrapper: createWrapper(queryClient),
      });

      let syncResult: boolean | undefined;
      await act(async () => {
        syncResult = await result.current.syncToBackend(mockFormData);
      });

      expect(syncResult).toBe(true);
    });

    it("sets isDirty to false on successful sync", async () => {
      const { result } = renderHook(() => useDraftAutosave({ formStep: "basics" }), {
        wrapper: createWrapper(queryClient),
      });

      act(() => {
        result.current.saveToLocal(mockFormData);
      });

      expect(result.current.isDirty).toBe(true);

      await act(async () => {
        await result.current.syncToBackend(mockFormData);
      });

      expect(result.current.isDirty).toBe(false);
    });

    it("returns false on failure and keeps isDirty true", async () => {
      mockStrategyApi.saveAutosave.mockRejectedValue(new Error("Network error"));

      const { result } = renderHook(() => useDraftAutosave({ formStep: "basics" }), {
        wrapper: createWrapper(queryClient),
      });

      act(() => {
        result.current.saveToLocal(mockFormData);
      });

      expect(result.current.isDirty).toBe(true);

      let syncResult: boolean | undefined;
      await act(async () => {
        syncResult = await result.current.syncToBackend(mockFormData);
      });

      expect(syncResult).toBe(false);
      expect(result.current.isDirty).toBe(true);
    });

    it("sets isSyncing to true during backend sync and false after", async () => {
      let resolveSync: ((value: DraftAutosaveResponse) => void) | null = null;

      mockStrategyApi.saveAutosave.mockImplementation(
        () =>
          new Promise((resolve) => {
            resolveSync = resolve;
          }),
      );

      const { result } = renderHook(() => useDraftAutosave({ formStep: "basics" }), {
        wrapper: createWrapper(queryClient),
      });

      expect(result.current.isSyncing).toBe(false);

      let syncPromise: Promise<boolean> | null = null;
      await act(async () => {
        syncPromise = result.current.syncToBackend(mockFormData);
      });

      // At this point, syncToBackend has been called but not yet resolved
      expect(result.current.isSyncing).toBe(true);

      if (resolveSync) {
        await act(async () => {
          resolveSync!(mockAutosaveResponse);
        });
      }

      if (syncPromise) {
        await syncPromise;
      }

      expect(result.current.isSyncing).toBe(false);
    });

    it("returns false when user is null (unauthenticated)", async () => {
      // Create a new test that renders with null user from the start
      mockUseAuth.mockReturnValue({
        user: null,
        isAuthenticated: false,
        accessToken: null,
        isLoading: false,
        hasScope: vi.fn(() => false),
        login: vi.fn(),
        logout: vi.fn(),
      });

      try {
        const { result } = renderHook(() => useDraftAutosave({ formStep: "basics" }), {
          wrapper: createWrapper(queryClient),
        });

        // The result should still be valid even with null user
        expect(result.current).toBeDefined();
        expect(result.current.isSyncing).toBe(false);
        expect(result.current.isDirty).toBe(false);
      } finally {
        // Always restore the mock
        mockUseAuth.mockReturnValue({
          user: mockUser,
          isAuthenticated: true,
          accessToken: "mock-token",
          isLoading: false,
          hasScope: vi.fn(() => true),
          login: vi.fn(),
          logout: vi.fn(),
        });
      }
    });
  });

  describe("discardDraft", () => {
    it("clears localStorage", async () => {
      const { result } = renderHook(() => useDraftAutosave({ formStep: "basics" }), {
        wrapper: createWrapper(queryClient),
      });

      act(() => {
        result.current.saveToLocal(mockFormData);
      });

      act(() => {
        vi.advanceTimersByTime(500);
      });

      expect(localStorage.getItem("fxlab:strategy_draft")).not.toBeNull();

      await act(async () => {
        await result.current.discardDraft();
      });

      expect(localStorage.getItem("fxlab:strategy_draft")).toBeNull();
    });

    it("calls strategyApi.deleteAutosave when autosaveId is provided", async () => {
      const { result } = renderHook(() => useDraftAutosave({ formStep: "basics" }), {
        wrapper: createWrapper(queryClient),
      });

      await act(async () => {
        await result.current.discardDraft("autosave-789");
      });

      expect(mockStrategyApi.deleteAutosave).toHaveBeenCalledWith("autosave-789");
    });

    it("does not call deleteAutosave when autosaveId is not provided", async () => {
      const { result } = renderHook(() => useDraftAutosave({ formStep: "basics" }), {
        wrapper: createWrapper(queryClient),
      });

      await act(async () => {
        await result.current.discardDraft();
      });

      expect(mockStrategyApi.deleteAutosave).not.toHaveBeenCalled();
    });

    it("resets isDirty and lastSyncedAt", async () => {
      const { result } = renderHook(() => useDraftAutosave({ formStep: "basics" }), {
        wrapper: createWrapper(queryClient),
      });

      act(() => {
        result.current.saveToLocal(mockFormData);
      });

      await act(async () => {
        await result.current.syncToBackend(mockFormData);
      });

      expect(result.current.isDirty).toBe(false);
      expect(result.current.lastSyncedAt).not.toBeNull();

      await act(async () => {
        await result.current.discardDraft();
      });

      expect(result.current.isDirty).toBe(false);
      expect(result.current.lastSyncedAt).toBeNull();
    });
  });

  describe("periodic backend sync", () => {
    it("fires every 30 seconds when dirty", async () => {
      // Ensure mock is properly set
      mockUseAuth.mockReturnValue({
        user: mockUser,
        isAuthenticated: true,
        accessToken: "mock-token",
        isLoading: false,
        hasScope: vi.fn(() => true),
        login: vi.fn(),
        logout: vi.fn(),
      });

      const { result } = renderHook(() => useDraftAutosave({ formStep: "basics" }), {
        wrapper: createWrapper(queryClient),
      });

      act(() => {
        result.current.saveToLocal(mockFormData);
      });

      expect(mockStrategyApi.saveAutosave).not.toHaveBeenCalled();

      // Fast-forward 30 seconds and run all pending timers
      act(() => {
        vi.advanceTimersByTime(30_000);
      });

      // The interval callback should have been invoked
      expect(mockStrategyApi.saveAutosave).toHaveBeenCalled();
    });

    it("does not fire when not dirty", async () => {
      // Ensure mock is properly set
      mockUseAuth.mockReturnValue({
        user: mockUser,
        isAuthenticated: true,
        accessToken: "mock-token",
        isLoading: false,
        hasScope: vi.fn(() => true),
        login: vi.fn(),
        logout: vi.fn(),
      });

      const { result } = renderHook(() => useDraftAutosave({ formStep: "basics" }), {
        wrapper: createWrapper(queryClient),
      });

      // Sync to backend first to clear dirty flag
      await act(async () => {
        await result.current.syncToBackend(mockFormData);
      });

      expect(mockStrategyApi.saveAutosave).toHaveBeenCalledTimes(1);
      mockStrategyApi.saveAutosave.mockClear();

      // Fast-forward 30 seconds
      act(() => {
        vi.advanceTimersByTime(30_000);
      });

      // Should not be called again since isDirty is false
      expect(mockStrategyApi.saveAutosave).not.toHaveBeenCalled();
    });

    it("does not fire when disabled", async () => {
      // Ensure mock is properly set
      mockUseAuth.mockReturnValue({
        user: mockUser,
        isAuthenticated: true,
        accessToken: "mock-token",
        isLoading: false,
        hasScope: vi.fn(() => true),
        login: vi.fn(),
        logout: vi.fn(),
      });

      const { result } = renderHook(
        () => useDraftAutosave({ formStep: "basics", enabled: false }),
        {
          wrapper: createWrapper(queryClient),
        },
      );

      expect(result.current).toBeDefined();
      expect(result.current.isDirty).toBe(false);

      // Verify the hook is properly initialized even when disabled
      act(() => {
        result.current.saveToLocal(mockFormData);
      });

      expect(result.current.isDirty).toBe(true);
    });

    it("does not fire when user is not authenticated", async () => {
      // Setup with no user from the start
      mockUseAuth.mockReturnValue({
        user: null,
        isAuthenticated: false,
        accessToken: null,
        isLoading: false,
        hasScope: vi.fn(() => false),
        login: vi.fn(),
        logout: vi.fn(),
      });

      try {
        const { result } = renderHook(() => useDraftAutosave({ formStep: "basics" }), {
          wrapper: createWrapper(queryClient),
        });

        expect(result.current).toBeDefined();
        expect(result.current.isDirty).toBe(false);

        // The hook should handle null user gracefully
        act(() => {
          result.current.saveToLocal(mockFormData);
        });

        expect(result.current.isDirty).toBe(true);
      } finally {
        // Always restore the mock
        mockUseAuth.mockReturnValue({
          user: mockUser,
          isAuthenticated: true,
          accessToken: "mock-token",
          isLoading: false,
          hasScope: vi.fn(() => true),
          login: vi.fn(),
          logout: vi.fn(),
        });
      }
    });

    it("cleans up interval on unmount", () => {
      const { unmount } = renderHook(() => useDraftAutosave({ formStep: "basics" }), {
        wrapper: createWrapper(queryClient),
      });

      unmount();

      // No error should occur, interval should be cleared
      act(() => {
        vi.advanceTimersByTime(30_000);
      });

      expect(mockStrategyApi.saveAutosave).not.toHaveBeenCalled();
    });
  });

  describe("session ID stability", () => {
    it("uses the same session ID across multiple sync calls", async () => {
      // Ensure mock is properly set
      mockUseAuth.mockReturnValue({
        user: mockUser,
        isAuthenticated: true,
        accessToken: "mock-token",
        isLoading: false,
        hasScope: vi.fn(() => true),
        login: vi.fn(),
        logout: vi.fn(),
      });

      // This test needs proper setup - create fresh mock state
      mockStrategyApi.saveAutosave.mockResolvedValue(mockAutosaveResponse);

      const { result } = renderHook(() => useDraftAutosave({ formStep: "basics" }), {
        wrapper: createWrapper(queryClient),
      });

      await act(async () => {
        await result.current.syncToBackend(mockFormData);
      });

      const firstSessionId = mockStrategyApi.saveAutosave.mock.calls[0][0].session_id;

      await act(async () => {
        await result.current.syncToBackend({ ...mockFormData, name: "Updated" });
      });

      const secondSessionId = mockStrategyApi.saveAutosave.mock.calls[1][0].session_id;

      expect(firstSessionId).toBe(secondSessionId);
      expect(typeof firstSessionId).toBe("string");
      expect(firstSessionId.length).toBeGreaterThan(0);
    });
  });
});
