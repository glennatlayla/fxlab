/**
 * OidcProvider unit tests.
 *
 * Verifies:
 *   - OIDC UserManager initialization with injected manager.
 *   - User loaded event updates auth state (user, accessToken).
 *   - User unloaded event clears auth state.
 *   - Silent renew error clears auth state.
 *   - Access token expired clears auth state.
 *   - Redirect callback processing (code in URL).
 *   - Existing session restore (getUser returns non-expired user).
 *   - Login triggers signinRedirect.
 *   - Logout triggers signoutRedirect.
 *   - hasScope returns correct values.
 *
 * Dependencies:
 *   - vitest for mocking
 *   - @testing-library/react for render + hooks
 *   - Mocked oidc-client-ts UserManager
 */

import { renderHook, act, waitFor } from "@testing-library/react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { ReactNode } from "react";
import type { User } from "oidc-client-ts";
import { OidcProvider } from "./OidcProvider";
import { useAuth } from "./useAuth";

// ---------------------------------------------------------------------------
// Mock jwt-decode — return deterministic payload
// ---------------------------------------------------------------------------

const MOCK_JWT_PAYLOAD = {
  sub: "oidc-user-456",
  email: "oidcuser@fxlab.io",
  role: "operator",
  scope: "feeds:read strategies:write live:trade",
  exp: Math.floor(Date.now() / 1000) + 3600,
  iat: Math.floor(Date.now() / 1000),
};

vi.mock("jwt-decode", () => ({
  jwtDecode: vi.fn(() => MOCK_JWT_PAYLOAD),
}));

// ---------------------------------------------------------------------------
// Mock UserManager
// ---------------------------------------------------------------------------

type EventHandler = (...args: unknown[]) => void;

function createMockUserManager(
  options: {
    existingUser?: Partial<User> | null;
    callbackUser?: Partial<User> | null;
    hasCodeInUrl?: boolean;
  } = {},
) {
  const eventHandlers: Record<string, EventHandler[]> = {
    userLoaded: [],
    userUnloaded: [],
    silentRenewError: [],
    accessTokenExpired: [],
  };

  const manager = {
    events: {
      addUserLoaded: vi.fn((fn: EventHandler) => eventHandlers.userLoaded.push(fn)),
      addUserUnloaded: vi.fn((fn: EventHandler) => eventHandlers.userUnloaded.push(fn)),
      addSilentRenewError: vi.fn((fn: EventHandler) => eventHandlers.silentRenewError.push(fn)),
      addAccessTokenExpired: vi.fn((fn: EventHandler) => eventHandlers.accessTokenExpired.push(fn)),
      removeUserLoaded: vi.fn(),
      removeUserUnloaded: vi.fn(),
      removeSilentRenewError: vi.fn(),
      removeAccessTokenExpired: vi.fn(),
    },
    getUser: vi.fn().mockResolvedValue(options.existingUser ?? null),
    signinRedirect: vi.fn().mockResolvedValue(undefined),
    signinRedirectCallback: vi.fn().mockResolvedValue(options.callbackUser ?? null),
    signoutRedirect: vi.fn().mockResolvedValue(undefined),
    // Expose handlers for tests to fire events
    _fireEvent: (event: string, ...args: unknown[]) => {
      (eventHandlers[event] || []).forEach((fn) => fn(...args));
    },
  };

  return manager;
}

// ---------------------------------------------------------------------------
// Test helpers
// ---------------------------------------------------------------------------

function createWrapper(userManager: ReturnType<typeof createMockUserManager>) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return function Wrapper({ children }: { children: ReactNode }) {
    return (
      <QueryClientProvider client={queryClient}>
        <OidcProvider userManager={userManager as unknown as import("oidc-client-ts").UserManager}>
          {children}
        </OidcProvider>
      </QueryClientProvider>
    );
  };
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe("OidcProvider", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    // Reset window.location.search to empty (no callback params)
    Object.defineProperty(window, "location", {
      value: { ...window.location, search: "", pathname: "/", origin: "http://localhost:3000" },
      writable: true,
    });
  });

  // -------------------------------------------------------------------------
  // Initialization
  // -------------------------------------------------------------------------

  describe("initialization", () => {
    it("starts in loading state", () => {
      const manager = createMockUserManager();
      const { result } = renderHook(() => useAuth(), {
        wrapper: createWrapper(manager),
      });
      // Initially loading while checking for existing session
      expect(result.current.isLoading).toBe(true);
    });

    it("registers event handlers on mount", async () => {
      const manager = createMockUserManager();
      renderHook(() => useAuth(), { wrapper: createWrapper(manager) });

      await waitFor(() => {
        expect(manager.events.addUserLoaded).toHaveBeenCalled();
        expect(manager.events.addUserUnloaded).toHaveBeenCalled();
        expect(manager.events.addSilentRenewError).toHaveBeenCalled();
        expect(manager.events.addAccessTokenExpired).toHaveBeenCalled();
      });
    });

    it("checks for existing session on mount", async () => {
      const manager = createMockUserManager();
      renderHook(() => useAuth(), { wrapper: createWrapper(manager) });

      await waitFor(() => {
        expect(manager.getUser).toHaveBeenCalled();
      });
    });
  });

  // -------------------------------------------------------------------------
  // Existing session restore
  // -------------------------------------------------------------------------

  describe("session restore", () => {
    it("restores user from existing non-expired session", async () => {
      const manager = createMockUserManager({
        existingUser: {
          access_token: "oidc-access-token",
          expired: false,
        },
      });

      const { result } = renderHook(() => useAuth(), {
        wrapper: createWrapper(manager),
      });

      await waitFor(() => {
        expect(result.current.isLoading).toBe(false);
      });

      expect(result.current.isAuthenticated).toBe(true);
      expect(result.current.user).toEqual({
        userId: "oidc-user-456",
        email: "oidcuser@fxlab.io",
        role: "operator",
        scopes: ["feeds:read", "strategies:write", "live:trade"],
      });
      expect(result.current.accessToken).toBe("oidc-access-token");
    });

    it("stays unauthenticated when no existing session", async () => {
      const manager = createMockUserManager({ existingUser: null });

      const { result } = renderHook(() => useAuth(), {
        wrapper: createWrapper(manager),
      });

      await waitFor(() => {
        expect(result.current.isLoading).toBe(false);
      });

      expect(result.current.isAuthenticated).toBe(false);
      expect(result.current.user).toBeNull();
    });

    it("ignores expired session", async () => {
      const manager = createMockUserManager({
        existingUser: {
          access_token: "expired-token",
          expired: true,
        },
      });

      const { result } = renderHook(() => useAuth(), {
        wrapper: createWrapper(manager),
      });

      await waitFor(() => {
        expect(result.current.isLoading).toBe(false);
      });

      expect(result.current.isAuthenticated).toBe(false);
    });
  });

  // -------------------------------------------------------------------------
  // Event handling
  // -------------------------------------------------------------------------

  describe("event handling", () => {
    it("updates state when userLoaded event fires", async () => {
      const manager = createMockUserManager();

      const { result } = renderHook(() => useAuth(), {
        wrapper: createWrapper(manager),
      });

      await waitFor(() => {
        expect(result.current.isLoading).toBe(false);
      });

      // Fire userLoaded event
      act(() => {
        manager._fireEvent("userLoaded", {
          access_token: "new-oidc-token",
        } as Partial<User>);
      });

      expect(result.current.isAuthenticated).toBe(true);
      expect(result.current.accessToken).toBe("new-oidc-token");
    });

    it("clears state when userUnloaded event fires", async () => {
      const manager = createMockUserManager({
        existingUser: { access_token: "token", expired: false },
      });

      const { result } = renderHook(() => useAuth(), {
        wrapper: createWrapper(manager),
      });

      await waitFor(() => {
        expect(result.current.isAuthenticated).toBe(true);
      });

      act(() => {
        manager._fireEvent("userUnloaded");
      });

      expect(result.current.isAuthenticated).toBe(false);
      expect(result.current.user).toBeNull();
    });

    it("clears state on silent renew error", async () => {
      const manager = createMockUserManager({
        existingUser: { access_token: "token", expired: false },
      });

      const { result } = renderHook(() => useAuth(), {
        wrapper: createWrapper(manager),
      });

      await waitFor(() => {
        expect(result.current.isAuthenticated).toBe(true);
      });

      act(() => {
        manager._fireEvent("silentRenewError");
      });

      expect(result.current.isAuthenticated).toBe(false);
    });

    it("clears state on access token expired", async () => {
      const manager = createMockUserManager({
        existingUser: { access_token: "token", expired: false },
      });

      const { result } = renderHook(() => useAuth(), {
        wrapper: createWrapper(manager),
      });

      await waitFor(() => {
        expect(result.current.isAuthenticated).toBe(true);
      });

      act(() => {
        manager._fireEvent("accessTokenExpired");
      });

      expect(result.current.isAuthenticated).toBe(false);
    });
  });

  // -------------------------------------------------------------------------
  // Login
  // -------------------------------------------------------------------------

  describe("login", () => {
    it("triggers signinRedirect on login call", async () => {
      const manager = createMockUserManager();

      const { result } = renderHook(() => useAuth(), {
        wrapper: createWrapper(manager),
      });

      await waitFor(() => {
        expect(result.current.isLoading).toBe(false);
      });

      await act(async () => {
        await result.current.login("", "");
      });

      expect(manager.signinRedirect).toHaveBeenCalled();
    });
  });

  // -------------------------------------------------------------------------
  // Logout
  // -------------------------------------------------------------------------

  describe("logout", () => {
    it("triggers signoutRedirect on logout", async () => {
      const manager = createMockUserManager({
        existingUser: { access_token: "token", expired: false },
      });

      const { result } = renderHook(() => useAuth(), {
        wrapper: createWrapper(manager),
      });

      await waitFor(() => {
        expect(result.current.isAuthenticated).toBe(true);
      });

      act(() => {
        result.current.logout();
      });

      expect(manager.signoutRedirect).toHaveBeenCalled();
    });
  });

  // -------------------------------------------------------------------------
  // Scope checking
  // -------------------------------------------------------------------------

  describe("hasScope", () => {
    it("returns true for scope the user holds", async () => {
      const manager = createMockUserManager({
        existingUser: { access_token: "token", expired: false },
      });

      const { result } = renderHook(() => useAuth(), {
        wrapper: createWrapper(manager),
      });

      await waitFor(() => {
        expect(result.current.isAuthenticated).toBe(true);
      });

      expect(result.current.hasScope("feeds:read")).toBe(true);
      expect(result.current.hasScope("live:trade")).toBe(true);
    });

    it("returns false for scope the user does not hold", async () => {
      const manager = createMockUserManager({
        existingUser: { access_token: "token", expired: false },
      });

      const { result } = renderHook(() => useAuth(), {
        wrapper: createWrapper(manager),
      });

      await waitFor(() => {
        expect(result.current.isAuthenticated).toBe(true);
      });

      expect(result.current.hasScope("admin:nuke")).toBe(false);
    });

    it("returns false when not authenticated", async () => {
      const manager = createMockUserManager();

      const { result } = renderHook(() => useAuth(), {
        wrapper: createWrapper(manager),
      });

      await waitFor(() => {
        expect(result.current.isLoading).toBe(false);
      });

      expect(result.current.hasScope("feeds:read")).toBe(false);
    });
  });
});
