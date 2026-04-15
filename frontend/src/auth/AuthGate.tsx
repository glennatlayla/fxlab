/**
 * AuthGate — auth mode switch between OIDC and local JWT.
 *
 * Purpose:
 *   Select the authentication provider based on VITE_AUTH_MODE environment
 *   variable. This allows the application to seamlessly switch between
 *   Keycloak OIDC (production) and local JWT (development/testing) without
 *   changing application code.
 *
 * Responsibilities:
 *   - Read VITE_AUTH_MODE from environment ("oidc" | "local").
 *   - Render OidcProvider when mode is "oidc".
 *   - Render AuthProvider (local JWT) when mode is "local" (default).
 *   - Log the selected auth mode at mount for debugging.
 *
 * Does NOT:
 *   - Contain authentication logic (delegates to providers).
 *   - Make API calls.
 *   - Handle auth errors (providers handle their own errors).
 *
 * Dependencies:
 *   - OidcProvider: OIDC authentication provider.
 *   - AuthProvider: Local JWT authentication provider.
 *
 * Example:
 *   // In main.tsx or App.tsx:
 *   <AuthGate>
 *     <App />
 *   </AuthGate>
 *
 *   // With VITE_AUTH_MODE=oidc → renders OidcProvider
 *   // With VITE_AUTH_MODE=local or unset → renders AuthProvider
 */

import type { ReactNode } from "react";
import { AuthProvider } from "./AuthProvider";
import { OidcProvider } from "./OidcProvider";

export type AuthMode = "oidc" | "local";

/**
 * Get the configured auth mode from environment.
 *
 * Returns:
 *   "oidc" or "local" (default).
 */
export function getAuthMode(): AuthMode {
  const mode = import.meta.env.VITE_AUTH_MODE || "local";
  if (mode === "oidc") return "oidc";
  return "local";
}

interface AuthGateProps {
  children: ReactNode;
  /** Override auth mode for testing. */
  mode?: AuthMode;
}

export function AuthGate({ children, mode: overrideMode }: AuthGateProps) {
  const authMode = overrideMode ?? getAuthMode();

  if (authMode === "oidc") {
    return <OidcProvider>{children}</OidcProvider>;
  }

  return <AuthProvider>{children}</AuthProvider>;
}
