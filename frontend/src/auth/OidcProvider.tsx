/**
 * OIDC authentication provider using oidc-client-ts.
 *
 * Purpose:
 *   Authenticate users via Keycloak's OIDC Authorization Code Flow with PKCE.
 *   Provides the same AuthContextValue interface as the local JWT provider,
 *   allowing seamless switching between auth modes.
 *
 * Responsibilities:
 *   - Configure oidc-client-ts UserManager with PKCE code flow.
 *   - Handle OIDC redirect callback (parse authorization code from URL).
 *   - Provide login (redirect to Keycloak), logout (RP-initiated), and
 *     silent token renewal.
 *   - Decode OIDC access token to extract user identity and scopes.
 *   - Expose unified AuthContextValue (user, isAuthenticated, logout, etc.).
 *
 * Does NOT:
 *   - Store tokens in localStorage (all state is in-memory per security policy).
 *   - Contain business logic beyond auth state management.
 *   - Fall back to local JWT (that is AuthGate's responsibility).
 *
 * Dependencies:
 *   - oidc-client-ts: UserManager, User, WebStorageStateStore.
 *   - jwt-decode: For parsing OIDC access token claims.
 *   - React context via AuthContext.
 *
 * Error conditions:
 *   - OIDC redirect failure: user shown error, stays unauthenticated.
 *   - Silent renewal failure: user logged out (same as local provider).
 *   - Missing OIDC config: ConfigError logged, stays unauthenticated.
 *
 * Example:
 *   <OidcProvider>
 *     <App />
 *   </OidcProvider>
 */

import { useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { UserManager, type User, WebStorageStateStore } from "oidc-client-ts";
import { jwtDecode } from "jwt-decode";
import { AuthContext, type AuthContextValue } from "./AuthContext";
import type { AuthUser, JwtPayload } from "@/types/auth";

// ---------------------------------------------------------------------------
// In-memory storage adapter — no localStorage, no sessionStorage.
// oidc-client-ts requires a WebStorage-compatible store for PKCE state and
// nonce values. This adapter keeps everything in memory, satisfying the
// security policy of "no persistent browser storage for tokens."
// ---------------------------------------------------------------------------

class InMemoryWebStorage implements Storage {
  private _store: Map<string, string> = new Map();

  get length(): number {
    return this._store.size;
  }

  clear(): void {
    this._store.clear();
  }

  getItem(key: string): string | null {
    return this._store.get(key) ?? null;
  }

  key(index: number): string | null {
    const keys = Array.from(this._store.keys());
    return keys[index] ?? null;
  }

  removeItem(key: string): void {
    this._store.delete(key);
  }

  setItem(key: string, value: string): void {
    this._store.set(key, value);
  }
}

// ---------------------------------------------------------------------------
// Token helpers
// ---------------------------------------------------------------------------

/**
 * Decode an OIDC access token into an AuthUser identity.
 *
 * OIDC access tokens from Keycloak contain the same claims as our local JWTs:
 * sub, email, role (via realm_access or custom claim), scope.
 *
 * Args:
 *   token: Raw JWT access token string.
 *
 * Returns:
 *   AuthUser with userId, email, role, and scopes.
 */
function decodeOidcUser(token: string): AuthUser {
  const payload = jwtDecode<JwtPayload>(token);
  return {
    userId: payload.sub,
    email: payload.email,
    role: payload.role,
    scopes: payload.scope ? payload.scope.split(" ") : [],
  };
}

// ---------------------------------------------------------------------------
// OIDC configuration from environment
// ---------------------------------------------------------------------------

interface OidcConfig {
  authority: string;
  clientId: string;
  redirectUri: string;
  postLogoutRedirectUri: string;
  scope: string;
}

function getOidcConfig(): OidcConfig {
  const authority = import.meta.env.VITE_OIDC_AUTHORITY || "";
  const clientId = import.meta.env.VITE_OIDC_CLIENT_ID || "";
  const redirectUri =
    import.meta.env.VITE_OIDC_REDIRECT_URI || `${window.location.origin}/callback`;
  const postLogoutRedirectUri =
    import.meta.env.VITE_OIDC_POST_LOGOUT_REDIRECT_URI || window.location.origin;
  const scope = import.meta.env.VITE_OIDC_SCOPE || "openid profile email";

  return { authority, clientId, redirectUri, postLogoutRedirectUri, scope };
}

// ---------------------------------------------------------------------------
// Provider component
// ---------------------------------------------------------------------------

interface OidcProviderProps {
  children: ReactNode;
  /** Optional UserManager override for testing. */
  userManager?: UserManager;
}

export function OidcProvider({ children, userManager: injectedManager }: OidcProviderProps) {
  const [user, setUser] = useState<AuthUser | null>(null);
  const [accessToken, setAccessToken] = useState<string | null>(null);
  const [isLoading, setIsLoading] = useState(true);

  const managerRef = useRef<UserManager | null>(null);

  // Initialize UserManager once — either injected (tests) or from config.
  useEffect(() => {
    if (injectedManager) {
      managerRef.current = injectedManager;
    } else {
      const config = getOidcConfig();
      if (!config.authority || !config.clientId) {
        console.error("[OidcProvider] VITE_OIDC_AUTHORITY and VITE_OIDC_CLIENT_ID are required.");
        setIsLoading(false);
        return;
      }

      const store = new InMemoryWebStorage();
      managerRef.current = new UserManager({
        authority: config.authority,
        client_id: config.clientId,
        redirect_uri: config.redirectUri,
        post_logout_redirect_uri: config.postLogoutRedirectUri,
        scope: config.scope,
        response_type: "code",
        // PKCE is enabled by default in oidc-client-ts for code flow
        userStore: new WebStorageStateStore({ store }),
        stateStore: new WebStorageStateStore({ store }),
        automaticSilentRenew: true,
        silent_redirect_uri: config.redirectUri,
      });
    }

    const manager = managerRef.current;
    if (!manager) return;

    // Register event handlers for token lifecycle
    manager.events.addUserLoaded(handleUserLoaded);
    manager.events.addUserUnloaded(handleUserUnloaded);
    manager.events.addSilentRenewError(handleRenewError);
    manager.events.addAccessTokenExpired(handleTokenExpired);

    // Check if this is a redirect callback (URL contains code= or error=)
    const params = new URLSearchParams(window.location.search);
    if (params.has("code") || params.has("error")) {
      manager
        .signinRedirectCallback()
        .then((oidcUser) => {
          // Clean the URL after callback processing
          window.history.replaceState({}, "", window.location.pathname);
          if (oidcUser?.access_token) {
            setAccessToken(oidcUser.access_token);
            setUser(decodeOidcUser(oidcUser.access_token));
          }
        })
        .catch((err) => {
          console.error("[OidcProvider] Redirect callback failed:", err);
        })
        .finally(() => {
          setIsLoading(false);
        });
    } else {
      // Not a callback — check for existing session
      manager
        .getUser()
        .then((oidcUser) => {
          if (oidcUser && !oidcUser.expired) {
            setAccessToken(oidcUser.access_token);
            setUser(decodeOidcUser(oidcUser.access_token));
          }
        })
        .catch(() => {
          // No session — user is unauthenticated
        })
        .finally(() => {
          setIsLoading(false);
        });
    }

    return () => {
      manager.events.removeUserLoaded(handleUserLoaded);
      manager.events.removeUserUnloaded(handleUserUnloaded);
      manager.events.removeSilentRenewError(handleRenewError);
      manager.events.removeAccessTokenExpired(handleTokenExpired);
    };
  }, [injectedManager]);

  // -------------------------------------------------------------------------
  // Event handlers
  // -------------------------------------------------------------------------

  function handleUserLoaded(oidcUser: User) {
    setAccessToken(oidcUser.access_token);
    setUser(decodeOidcUser(oidcUser.access_token));
  }

  function handleUserUnloaded() {
    setAccessToken(null);
    setUser(null);
  }

  function handleRenewError() {
    // Silent renewal failed — clear session.
    setAccessToken(null);
    setUser(null);
  }

  function handleTokenExpired() {
    setAccessToken(null);
    setUser(null);
  }

  // -------------------------------------------------------------------------
  // Public API — matches AuthContextValue
  // -------------------------------------------------------------------------

  const login = useCallback(async () => {
    const manager = managerRef.current;
    if (!manager) throw new Error("UserManager not initialized");
    // Redirect to Keycloak login page
    await manager.signinRedirect();
  }, []);

  const logout = useCallback(() => {
    const manager = managerRef.current;
    if (!manager) return;
    // RP-initiated logout → Keycloak end_session_endpoint
    manager.signoutRedirect().catch((err) => {
      console.error("[OidcProvider] Logout failed:", err);
      // Even if Keycloak is unreachable, clear local state
      setAccessToken(null);
      setUser(null);
    });
  }, []);

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
      // OIDC login doesn't take email/password — it redirects.
      // The signature matches AuthContextValue for compatibility.

      login: async (_email?: string, _password?: string) => {
        await login();
      },
      logout,
      hasScope,
      accessToken,
    }),
    [user, isLoading, accessToken, login, logout, hasScope],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}
