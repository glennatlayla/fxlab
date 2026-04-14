/**
 * useAuth hook — typed access to the authentication context.
 *
 * Purpose:
 *   Provide a type-safe hook for consuming AuthContextValue in any component.
 *   Throws if used outside <AuthProvider> to catch wiring bugs early.
 *
 * Example:
 *   const { user, hasScope, logout } = useAuth();
 *   if (hasScope("feeds:read")) { ... }
 */

import { useContext } from "react";
import { AuthContext, type AuthContextValue } from "./AuthContext";

export function useAuth(): AuthContextValue {
  const context = useContext(AuthContext);
  if (context === undefined) {
    throw new Error(
      "useAuth must be used within an <AuthProvider>. " +
        "Wrap your app in <AuthProvider> in main.tsx or App.tsx.",
    );
  }
  return context;
}
