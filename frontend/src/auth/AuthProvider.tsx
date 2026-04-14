/**
 * Authentication context provider.
 *
 * Purpose:
 *   Manage JWT-based authentication state for the entire application.
 *   Provides login, logout, silent refresh, and scope checking via React
 *   context. Wraps the app in <AuthProvider> so all children can call
 *   useAuth().
 *
 * Responsibilities:
 *   - Store access token in memory, refresh token in sessionStorage.
 *   - Decode JWT claims to extract user identity and scopes.
 *   - Automatically refresh tokens before expiry (percentage-based buffer).
 *   - Register token provider with apiClient for Bearer header injection.
 *   - Listen for 401 events from apiClient to trigger automatic logout.
 *   - Attempt session restore from sessionStorage on mount.
 *   - Expose hasScope() for fine-grained permission checks.
 *
 * Does NOT:
 *   - Store access tokens in localStorage/sessionStorage (XSS risk).
 *   - Make API calls directly (delegates to apiClient).
 *   - Contain business logic beyond auth state management.
 *
 * Dependencies:
 *   - jwt-decode for token parsing.
 *   - @/api/client for token endpoint calls and token provider registration.
 *   - @/config/env for auth configuration (refresh buffer, lockout settings).
 *   - React context for state distribution.
 *
 * Error conditions:
 *   - Login failure: error propagated to caller (LoginPage shows message).
 *   - Refresh failure: user silently logged out, sessionStorage cleared.
 *   - Session restore failure: user starts unauthenticated, no error shown.
 *
 * Example:
 *   <AuthProvider>
 *     <App />
 *   </AuthProvider>
 *
 *   // In any child component:
 *   const { user, login, logout, hasScope } = useAuth();
 */

import { useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { jwtDecode } from "jwt-decode";
import { apiClient, registerTokenProvider } from "@/api/client";
import { AuthContext, type AuthContextValue } from "./AuthContext";
import { getConfig } from "@/config/env";
import type { AuthUser, JwtPayload, TokenResponse } from "@/types/auth";

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

/** sessionStorage key for the refresh token. Tab-scoped, cleared on tab close. */
const REFRESH_TOKEN_KEY = "fxlab:refresh_token";

/** Custom event name dispatched by apiClient on 401 responses. */
const UNAUTHORIZED_EVENT = "fxlab:auth:unauthorized";

// ---------------------------------------------------------------------------
// Token helpers
// ---------------------------------------------------------------------------

/**
 * Decode a JWT access token into an AuthUser identity.
 *
 * Args:
 *   token: Raw JWT string from the auth endpoint.
 *
 * Returns:
 *   AuthUser with userId, email, role, and scopes extracted from claims.
 */
function decodeUser(token: string): AuthUser {
  const payload = jwtDecode<JwtPayload>(token);
  return {
    userId: payload.sub,
    email: payload.email,
    role: payload.role,
    scopes: payload.scope ? payload.scope.split(" ") : [],
  };
}

/**
 * Calculate milliseconds until a JWT access token expires.
 *
 * Args:
 *   token: Raw JWT string.
 *
 * Returns:
 *   Milliseconds until expiry (negative if already expired).
 */
function tokenExpiresInMs(token: string): number {
  const payload = jwtDecode<JwtPayload>(token);
  return (payload.exp - Date.now() / 1000) * 1000;
}

// ---------------------------------------------------------------------------
// Provider component
// ---------------------------------------------------------------------------

interface AuthProviderProps {
  children: ReactNode;
}

export function AuthProvider({ children }: AuthProviderProps) {
  const [user, setUser] = useState<AuthUser | null>(null);
  const [accessToken, setAccessToken] = useState<string | null>(null);
  const [isLoading, setIsLoading] = useState(() => {
    // Start in loading state if we have a refresh token to restore
    return !!sessionStorage.getItem(REFRESH_TOKEN_KEY);
  });

  // Refs for values that need to be accessible from callbacks/interceptors
  // without causing re-renders or stale closures.
  const accessTokenRef = useRef<string | null>(null);
  const refreshTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  // Keep the ref in sync with state so the token provider callback always
  // returns the current token.
  useEffect(() => {
    accessTokenRef.current = accessToken;
  }, [accessToken]);

  // -------------------------------------------------------------------------
  // Fix #3a: Register token provider with apiClient on mount.
  // This allows the axios request interceptor to inject Bearer tokens
  // without a direct import of auth state (avoids circular dependencies).
  // -------------------------------------------------------------------------
  useEffect(() => {
    registerTokenProvider(() => accessTokenRef.current);
  }, []);

  // -------------------------------------------------------------------------
  // Fix #3b: Listen for 401 events from apiClient's response interceptor.
  // When a 401 is received, the token is invalid/expired — force logout.
  // -------------------------------------------------------------------------
  useEffect(() => {
    const handleUnauthorized = () => {
      clearAuth();
    };

    window.addEventListener(UNAUTHORIZED_EVENT, handleUnauthorized);
    return () => {
      window.removeEventListener(UNAUTHORIZED_EVENT, handleUnauthorized);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // -------------------------------------------------------------------------
  // Shared auth state clear — used by logout, 401 handler, and refresh failure.
  // -------------------------------------------------------------------------
  const clearAuth = useCallback(() => {
    if (refreshTimerRef.current) clearTimeout(refreshTimerRef.current);
    setUser(null);
    setAccessToken(null);
    accessTokenRef.current = null;
    sessionStorage.removeItem(REFRESH_TOKEN_KEY);
  }, []);

  // -------------------------------------------------------------------------
  // Silent refresh scheduling.
  // Uses a percentage of token lifetime as buffer instead of a fixed value,
  // so it works correctly for both short-lived (5 min) and long-lived (1 hr)
  // tokens.
  // -------------------------------------------------------------------------
  const scheduleRefresh = useCallback(
    (token: string) => {
      if (refreshTimerRef.current) clearTimeout(refreshTimerRef.current);

      const config = getConfig();
      const msUntilExpiry = tokenExpiresInMs(token);
      const bufferMs = msUntilExpiry * config.auth.refreshBufferPercent;
      const refreshIn = Math.max(msUntilExpiry - bufferMs, 0);

      refreshTimerRef.current = setTimeout(async () => {
        const storedRefreshToken = sessionStorage.getItem(REFRESH_TOKEN_KEY);
        if (!storedRefreshToken) return;

        try {
          const resp = await apiClient.post<TokenResponse>("/auth/token", {
            grant_type: "refresh_token",
            refresh_token: storedRefreshToken,
          });
          const data = resp.data;
          setAccessToken(data.access_token);
          accessTokenRef.current = data.access_token;
          sessionStorage.setItem(REFRESH_TOKEN_KEY, data.refresh_token);
          setUser(decodeUser(data.access_token));
          scheduleRefresh(data.access_token);
        } catch {
          // Refresh failed — force re-login. No toast here; the redirect to
          // /login via AuthGuard is the UX signal.
          clearAuth();
        }
      }, refreshIn);
    },
    [clearAuth],
  );

  // -------------------------------------------------------------------------
  // Fix #1: Session restore from sessionStorage on mount.
  // If a refresh token exists, attempt a silent refresh to restore the
  // session without requiring re-login after page reload.
  // -------------------------------------------------------------------------
  useEffect(() => {
    const storedRefreshToken = sessionStorage.getItem(REFRESH_TOKEN_KEY);
    if (!storedRefreshToken) return;

    let cancelled = false;

    async function restoreSession() {
      try {
        const resp = await apiClient.post<TokenResponse>("/auth/token", {
          grant_type: "refresh_token",
          refresh_token: storedRefreshToken,
        });

        if (cancelled) return;

        const data = resp.data;
        setAccessToken(data.access_token);
        accessTokenRef.current = data.access_token;
        sessionStorage.setItem(REFRESH_TOKEN_KEY, data.refresh_token);
        setUser(decodeUser(data.access_token));
        scheduleRefresh(data.access_token);
      } catch {
        if (cancelled) return;
        // Restore failed — clear stale token and proceed as unauthenticated.
        sessionStorage.removeItem(REFRESH_TOKEN_KEY);
      } finally {
        if (!cancelled) {
          setIsLoading(false);
        }
      }
    }

    restoreSession();

    return () => {
      cancelled = true;
    };
  }, [scheduleRefresh]);

  // Clean up timer on unmount.
  useEffect(() => {
    return () => {
      if (refreshTimerRef.current) clearTimeout(refreshTimerRef.current);
    };
  }, []);

  // -------------------------------------------------------------------------
  // Public API
  // -------------------------------------------------------------------------

  const login = useCallback(
    async (email: string, password: string) => {
      setIsLoading(true);
      try {
        const resp = await apiClient.post<TokenResponse>("/auth/token", {
          grant_type: "password",
          username: email,
          password,
        });
        const data = resp.data;
        setAccessToken(data.access_token);
        accessTokenRef.current = data.access_token;
        sessionStorage.setItem(REFRESH_TOKEN_KEY, data.refresh_token);
        setUser(decodeUser(data.access_token));
        scheduleRefresh(data.access_token);
      } finally {
        setIsLoading(false);
      }
    },
    [scheduleRefresh],
  );

  const logout = useCallback(() => {
    clearAuth();
  }, [clearAuth]);

  const hasScope = useCallback(
    (scope: string): boolean => {
      if (!user) return false;
      return user.scopes.includes(scope);
    },
    [user],
  );

  const value = useMemo<AuthContextValue>(
    () => ({
      user,
      isLoading,
      isAuthenticated: !!user && !!accessToken,
      login,
      logout,
      hasScope,
      accessToken,
    }),
    [user, isLoading, accessToken, login, logout, hasScope],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}
