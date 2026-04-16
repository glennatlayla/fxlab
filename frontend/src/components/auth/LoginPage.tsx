/**
 * Login page — password grant authentication form with rate limiting.
 *
 * Purpose:
 *   Collect email + password and submit to the auth provider's login()
 *   method. Redirects to the intended page on success. Implements
 *   client-side rate limiting to slow brute-force attempts.
 *
 * Responsibilities:
 *   - Render email + password form with validation.
 *   - Delegate authentication to AuthProvider.login().
 *   - Redirect to intended destination on success.
 *   - Display error messages on failure.
 *   - Lock out after MAX_ATTEMPTS consecutive failures for LOCKOUT_DURATION.
 *
 * Does NOT:
 *   - Make API calls directly (delegates to AuthProvider).
 *   - Store credentials (form state only).
 *   - Replace server-side rate limiting (this is a UX guard, not security).
 *
 * Dependencies:
 *   - useAuth() for login method.
 *   - react-router-dom for navigation and location state.
 *   - @/config/env for lockout configuration.
 *
 * Example:
 *   <Route path="/login" element={<LoginPage />} />
 */

import { useState, useEffect, useRef, type FormEvent } from "react";
import { useNavigate, useLocation } from "react-router-dom";
import { useAuth } from "@/auth/useAuth";
import { getConfig } from "@/config/env";

export default function LoginPage() {
  const { login, isLoading } = useAuth();
  const navigate = useNavigate();
  const location = useLocation();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);

  // Rate limiting state
  const [failedAttempts, setFailedAttempts] = useState(0);
  const [lockoutUntil, setLockoutUntil] = useState<number | null>(null);
  const [lockoutRemaining, setLockoutRemaining] = useState(0);
  const lockoutTimerRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const config = getConfig();
  const isLockedOut = lockoutUntil !== null && Date.now() < lockoutUntil;

  // Redirect target after login (defaults to /).
  const from = (location.state as { from?: { pathname: string } })?.from?.pathname || "/";

  // Countdown timer for lockout display
  useEffect(() => {
    if (!lockoutUntil) return;

    function tick() {
      const remaining = Math.max(0, Math.ceil((lockoutUntil! - Date.now()) / 1000));
      setLockoutRemaining(remaining);
      if (remaining <= 0) {
        setLockoutUntil(null);
        setFailedAttempts(0);
        setError(null);
        if (lockoutTimerRef.current) {
          clearInterval(lockoutTimerRef.current);
          lockoutTimerRef.current = null;
        }
      }
    }

    tick(); // Immediately set the initial value
    lockoutTimerRef.current = setInterval(tick, 1000);

    return () => {
      if (lockoutTimerRef.current) {
        clearInterval(lockoutTimerRef.current);
        lockoutTimerRef.current = null;
      }
    };
  }, [lockoutUntil]);

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    if (isLockedOut) return;

    setError(null);
    try {
      await login(email, password);
      // Reset rate limiting on success
      setFailedAttempts(0);
      navigate(from, { replace: true });
    } catch (err: unknown) {
      // Log the actual error to the console so operators can diagnose login
      // failures. The catch-all previously swallowed all errors (network,
      // JWT decode, session storage, etc.) and displayed the same generic
      // "Invalid email or password" message, making debugging impossible.
      console.error("[FXLab] Login failed:", err);

      const newAttempts = failedAttempts + 1;
      setFailedAttempts(newAttempts);

      // Determine the appropriate user-facing error message based on the
      // actual error type, rather than showing a generic message for all
      // failure modes.
      let message: string;
      const isAxiosError =
        err != null &&
        typeof err === "object" &&
        "response" in err &&
        typeof (err as Record<string, unknown>).response === "object";

      const status = isAxiosError
        ? ((err as Record<string, unknown>).response as Record<string, unknown>)?.status
        : undefined;

      if (status === 401) {
        const remaining = config.auth.maxLoginAttempts - newAttempts;
        message = `Invalid email or password. ${remaining} attempt${remaining === 1 ? "" : "s"} remaining.`;
      } else if (status === 429) {
        message = "Too many login attempts. Please wait and try again.";
      } else if (isAxiosError) {
        message = `Login request failed (HTTP ${status}). Check the browser console for details.`;
      } else {
        // Non-HTTP error — could be JWT decode failure, session storage
        // quota, network error, or a bug in post-login processing.
        message = `Login error: ${err instanceof Error ? err.message : String(err)}. Check the browser console for details.`;
      }

      if (newAttempts >= config.auth.maxLoginAttempts) {
        const lockoutMs = config.auth.lockoutDurationSeconds * 1000;
        setLockoutUntil(Date.now() + lockoutMs);
        message = `Too many failed attempts. Please wait ${config.auth.lockoutDurationSeconds} seconds before trying again.`;
      }

      setError(message);
    }
  }

  return (
    <div className="flex min-h-screen items-center justify-center bg-surface-50">
      <div className="w-full max-w-sm">
        <div className="card">
          <div className="mb-6 text-center">
            <h1 className="text-2xl font-bold text-surface-900">FXLab</h1>
            <p className="mt-1 text-sm text-surface-500">Sign in to your account</p>
          </div>

          <form onSubmit={handleSubmit} className="space-y-4">
            {error && (
              <div
                role="alert"
                className="rounded-md border border-danger/20 bg-danger/5 px-3 py-2 text-sm text-danger"
              >
                {error}
              </div>
            )}

            <div>
              <label htmlFor="email" className="mb-1 block text-sm font-medium text-surface-700">
                Email
              </label>
              <input
                id="email"
                type="email"
                autoComplete="username"
                required
                disabled={isLockedOut}
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                className="w-full rounded-md border border-surface-300 px-3 py-2 text-sm focus:border-brand-500 focus:outline-none focus:ring-1 focus:ring-brand-500 disabled:cursor-not-allowed disabled:opacity-50"
                placeholder="you@company.com"
              />
            </div>

            <div>
              <label htmlFor="password" className="mb-1 block text-sm font-medium text-surface-700">
                Password
              </label>
              <input
                id="password"
                type="password"
                autoComplete="current-password"
                required
                disabled={isLockedOut}
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                className="w-full rounded-md border border-surface-300 px-3 py-2 text-sm focus:border-brand-500 focus:outline-none focus:ring-1 focus:ring-brand-500 disabled:cursor-not-allowed disabled:opacity-50"
                placeholder="••••••••"
              />
            </div>

            <button
              type="submit"
              disabled={isLoading || isLockedOut}
              className="w-full rounded-md bg-brand-600 px-4 py-2 text-sm font-medium text-white hover:bg-brand-700 focus:outline-none focus:ring-2 focus:ring-brand-500 focus:ring-offset-2 disabled:cursor-not-allowed disabled:opacity-50"
            >
              {isLockedOut
                ? `Locked (${lockoutRemaining}s)`
                : isLoading
                  ? "Signing in…"
                  : "Sign in"}
            </button>
          </form>
        </div>
      </div>
    </div>
  );
}
