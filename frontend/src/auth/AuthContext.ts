/**
 * AuthContext — React context definition for authentication state.
 *
 * Separated from AuthProvider.tsx to satisfy react-refresh's requirement
 * that files exporting React components should not also export non-component
 * values (contexts, constants).
 */

import { createContext } from "react";
import type { AuthUser } from "@/types/auth";

export interface AuthContextValue {
  /** Currently authenticated user, or null if logged out. */
  user: AuthUser | null;
  /** True while a login or refresh operation is in flight. */
  isLoading: boolean;
  /** True when user holds a valid, non-expired access token. */
  isAuthenticated: boolean;
  /** Authenticate with email + password. */
  login: (email: string, password: string) => Promise<void>;
  /** Revoke tokens and clear auth state. */
  logout: () => void;
  /** Check whether the user holds a specific RBAC scope. */
  hasScope: (scope: string) => boolean;
  /** Raw access token for injecting into API requests. */
  accessToken: string | null;
}

export const AuthContext = createContext<AuthContextValue | undefined>(undefined);
