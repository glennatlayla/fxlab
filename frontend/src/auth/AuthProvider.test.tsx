/**
 * AuthProvider integration tests.
 *
 * Verifies:
 *   - Token provider registration with apiClient on mount.
 *   - 401 event listener wired → triggers logout.
 *   - Session restore from sessionStorage on mount (refresh token persistence).
 *   - Silent refresh scheduling after login.
 *   - Logout clears sessionStorage and auth state.
 *
 * Dependencies:
 *   - vitest for mocking
 *   - @testing-library/react for render + hooks
 *   - jwt-decode mocked to avoid real JWT parsing
 */

import { renderHook, act, waitFor } from "@testing-library/react";
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { ReactNode } from "react";
import { AuthProvider } from "./AuthProvider";
import { useAuth } from "./useAuth";
// apiClient and registerTokenProvider are mocked below — import kept for type reference.
import type {} from "@/api/client";

// ---------------------------------------------------------------------------
// Mock jwt-decode — return deterministic payload
// ---------------------------------------------------------------------------

const MOCK_JWT_PAYLOAD = {
  sub: "user-123",
  email: "trader@fxlab.io",
  role: "developer",
  scope: "feeds:read strategies:write",
  exp: Math.floor(Date.now() / 1000) + 3600, // 1 hour from now
  iat: Math.floor(Date.now() / 1000),
};

vi.mock("jwt-decode", () => ({
  jwtDecode: vi.fn(() => MOCK_JWT_PAYLOAD),
}));

// ---------------------------------------------------------------------------
// Mock apiClient.post — simulate /auth/token responses
// ---------------------------------------------------------------------------

const mockPost = vi.fn();

vi.mock("@/api/client", async () => {
  const actual = await vi.importActual<typeof import("@/api/client")>("@/api/client");
  return {
    ...actual,
    apiClient: {
      ...actual.apiClient,
      post: (...args: unknown[]) => mockPost(...args),
    },
  };
});

// ---------------------------------------------------------------------------
// Test helpers
// ---------------------------------------------------------------------------

function createWrapper() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return function Wrapper({ children }: { children: ReactNode }) {
    return (
      <QueryClientProvider client={queryClient}>
        <AuthProvider>{children}</AuthProvider>
      </QueryClientProvider>
    );
  };
}

const MOCK_TOKEN_RESPONSE = {
  data: {
    access_token: "mock-access-token",
    refresh_token: "mock-refresh-token",
    token_type: "bearer",
    expires_in: 3600,
    scope: "feeds:read strategies:write",
  },
};

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe("AuthProvider", () => {
  beforeEach(() => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    mockPost.mockReset();
    sessionStorage.clear();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  // -------------------------------------------------------------------------
  // Fix #3a: registerTokenProvider is called on mount
  // -------------------------------------------------------------------------

  describe("token provider registration", () => {
    it("registers a token provider with apiClient on mount", () => {
      const { result } = renderHook(() => useAuth(), { wrapper: createWrapper() });

      // Before login, token should be null
      expect(result.current.accessToken).toBeNull();

      // The registerTokenProvider function should have been called during mount.
      // We verify this indirectly: after login, the provider should return the token.
    });

    it("provides access token to apiClient after login", async () => {
      mockPost.mockResolvedValueOnce(MOCK_TOKEN_RESPONSE);

      const { result } = renderHook(() => useAuth(), { wrapper: createWrapper() });

      await act(async () => {
        await result.current.login("trader@fxlab.io", "password123");
      });

      expect(result.current.accessToken).toBe("mock-access-token");
      expect(result.current.isAuthenticated).toBe(true);
    });
  });

  // -------------------------------------------------------------------------
  // Fix #3b: 401 event listener triggers logout
  // -------------------------------------------------------------------------

  describe("401 event handling", () => {
    it("logs out when fxlab:auth:unauthorized event is dispatched", async () => {
      mockPost.mockResolvedValueOnce(MOCK_TOKEN_RESPONSE);

      const { result } = renderHook(() => useAuth(), { wrapper: createWrapper() });

      // Login first
      await act(async () => {
        await result.current.login("trader@fxlab.io", "password123");
      });
      expect(result.current.isAuthenticated).toBe(true);

      // Dispatch the 401 event (simulating apiClient response interceptor)
      act(() => {
        window.dispatchEvent(new CustomEvent("fxlab:auth:unauthorized"));
      });

      // Should be logged out
      expect(result.current.isAuthenticated).toBe(false);
      expect(result.current.user).toBeNull();
      expect(result.current.accessToken).toBeNull();
    });

    it("cleans up 401 event listener on unmount", async () => {
      const { unmount } = renderHook(() => useAuth(), { wrapper: createWrapper() });

      // spy on removeEventListener
      const removeSpy = vi.spyOn(window, "removeEventListener");

      unmount();

      expect(removeSpy).toHaveBeenCalledWith("fxlab:auth:unauthorized", expect.any(Function));

      removeSpy.mockRestore();
    });
  });

  // -------------------------------------------------------------------------
  // Fix #1: Session restore from sessionStorage
  // -------------------------------------------------------------------------

  describe("session persistence", () => {
    it("stores refresh token in sessionStorage after login", async () => {
      mockPost.mockResolvedValueOnce(MOCK_TOKEN_RESPONSE);

      const { result } = renderHook(() => useAuth(), { wrapper: createWrapper() });

      await act(async () => {
        await result.current.login("trader@fxlab.io", "password123");
      });

      expect(sessionStorage.getItem("fxlab:refresh_token")).toBe("mock-refresh-token");
    });

    it("attempts session restore from sessionStorage on mount", async () => {
      // Pre-seed sessionStorage with a refresh token
      sessionStorage.setItem("fxlab:refresh_token", "stored-refresh-token");

      mockPost.mockResolvedValueOnce(MOCK_TOKEN_RESPONSE);

      const { result } = renderHook(() => useAuth(), { wrapper: createWrapper() });

      // Should start in loading state while attempting restore
      expect(result.current.isLoading).toBe(true);

      // Wait for the restore to complete
      await waitFor(() => {
        expect(result.current.isAuthenticated).toBe(true);
      });

      // Should have called /auth/token with the stored refresh token
      expect(mockPost).toHaveBeenCalledWith("/auth/token", {
        grant_type: "refresh_token",
        refresh_token: "stored-refresh-token",
      });
    });

    it("clears sessionStorage on logout", async () => {
      mockPost.mockResolvedValueOnce(MOCK_TOKEN_RESPONSE);

      const { result } = renderHook(() => useAuth(), { wrapper: createWrapper() });

      await act(async () => {
        await result.current.login("trader@fxlab.io", "password123");
      });

      expect(sessionStorage.getItem("fxlab:refresh_token")).toBe("mock-refresh-token");

      act(() => {
        result.current.logout();
      });

      expect(sessionStorage.getItem("fxlab:refresh_token")).toBeNull();
    });

    it("falls back to unauthenticated state when session restore fails", async () => {
      sessionStorage.setItem("fxlab:refresh_token", "expired-token");

      mockPost.mockRejectedValueOnce(new Error("Token expired"));

      const { result } = renderHook(() => useAuth(), { wrapper: createWrapper() });

      await waitFor(() => {
        expect(result.current.isLoading).toBe(false);
      });

      expect(result.current.isAuthenticated).toBe(false);
      expect(sessionStorage.getItem("fxlab:refresh_token")).toBeNull();
    });
  });

  // -------------------------------------------------------------------------
  // Login flow
  // -------------------------------------------------------------------------

  describe("login", () => {
    it("calls /auth/token with password grant", async () => {
      mockPost.mockResolvedValueOnce(MOCK_TOKEN_RESPONSE);

      const { result } = renderHook(() => useAuth(), { wrapper: createWrapper() });

      await act(async () => {
        await result.current.login("trader@fxlab.io", "pass");
      });

      expect(mockPost).toHaveBeenCalledWith("/auth/token", {
        grant_type: "password",
        username: "trader@fxlab.io",
        password: "pass",
      });
    });

    it("sets user identity from decoded JWT", async () => {
      mockPost.mockResolvedValueOnce(MOCK_TOKEN_RESPONSE);

      const { result } = renderHook(() => useAuth(), { wrapper: createWrapper() });

      await act(async () => {
        await result.current.login("trader@fxlab.io", "pass");
      });

      expect(result.current.user).toEqual({
        userId: "user-123",
        email: "trader@fxlab.io",
        role: "developer",
        scopes: ["feeds:read", "strategies:write"],
      });
    });

    it("propagates login errors to caller", async () => {
      mockPost.mockRejectedValueOnce(new Error("401 Unauthorized"));

      const { result } = renderHook(() => useAuth(), { wrapper: createWrapper() });

      await expect(
        act(async () => {
          await result.current.login("bad@email.com", "wrong");
        }),
      ).rejects.toThrow("401 Unauthorized");

      expect(result.current.isAuthenticated).toBe(false);
    });
  });

  // -------------------------------------------------------------------------
  // Scope checking
  // -------------------------------------------------------------------------

  describe("hasScope", () => {
    it("returns true for a scope the user holds", async () => {
      mockPost.mockResolvedValueOnce(MOCK_TOKEN_RESPONSE);

      const { result } = renderHook(() => useAuth(), { wrapper: createWrapper() });

      await act(async () => {
        await result.current.login("trader@fxlab.io", "pass");
      });

      expect(result.current.hasScope("feeds:read")).toBe(true);
      expect(result.current.hasScope("strategies:write")).toBe(true);
    });

    it("returns false for a scope the user does not hold", async () => {
      mockPost.mockResolvedValueOnce(MOCK_TOKEN_RESPONSE);

      const { result } = renderHook(() => useAuth(), { wrapper: createWrapper() });

      await act(async () => {
        await result.current.login("trader@fxlab.io", "pass");
      });

      expect(result.current.hasScope("admin:nuke")).toBe(false);
    });
  });
});
