/**
 * MfaChallenge — Multi-factor authentication code entry form.
 *
 * Purpose:
 *   Provide a user-friendly interface for entering 6-digit MFA codes
 *   (PIN or TOTP). Used as the core component within MfaGate or any
 *   high-risk operation requiring re-authentication.
 *
 * Responsibilities:
 *   - Display a labeled 6-digit numeric input field.
 *   - Validate input: digits only, exactly 6 characters to enable submit.
 *   - Call onSubmit callback with the entered code (parent verifies).
 *   - Display error messages and apply error styling to input.
 *   - Auto-focus the input on mount.
 *   - Support Enter key to submit.
 *   - Show loading spinner when verification is in progress.
 *   - Provide a cancel button.
 *
 * Does NOT:
 *   - Verify codes against a backend; parent handles verification.
 *   - Manage verification state; parent controls isVerifying prop.
 *   - Manage error state beyond displaying the error prop.
 *
 * Dependencies:
 *   - React (useState, useRef, useEffect, useCallback)
 *   - Tailwind CSS, clsx
 *   - lucide-react (CheckCircle2 for loading state)
 *
 * Error conditions:
 *   - None; invalid props default to sensible values (e.g., empty error).
 *
 * Example:
 *   const [error, setError] = useState<string | null>(null);
 *   const [isVerifying, setIsVerifying] = useState(false);
 *
 *   const handleSubmit = async (code: string) => {
 *     setIsVerifying(true);
 *     setError(null);
 *     try {
 *       await verifyMfaCode(code);
 *       // Success — parent handles closing the challenge
 *     } catch (err) {
 *       setError((err as Error).message);
 *       setIsVerifying(false);
 *     }
 *   };
 *
 *   return (
 *     <MfaChallenge
 *       onSubmit={handleSubmit}
 *       onCancel={() => {}}
 *       isVerifying={isVerifying}
 *       error={error}
 *       title="Verify Your Identity"
 *       description="Enter your 6-digit authentication code"
 *     />
 *   );
 */

import React, { useState, useRef, useEffect, useCallback } from "react";
import { Loader } from "lucide-react";
import clsx from "clsx";

export interface MfaChallengeProps {
  /** Callback when user submits a valid 6-digit code. Parent verifies via API. */
  onSubmit: (code: string) => void;
  /** Callback when user cancels the challenge. */
  onCancel: () => void;
  /** Whether verification is currently in progress. Disables input and submit. */
  isVerifying?: boolean;
  /** Error message from a failed verification attempt. Displayed below input. */
  error?: string | null;
  /** Title displayed at the top. Default: "Verify Your Identity" */
  title?: string;
  /** Description displayed below the title. Default: "Enter your 6-digit authentication code" */
  description?: string;
  /** Optional callback when user starts typing (for clearing error state). */
  onInputChange?: () => void;
}

/**
 * MfaChallenge component.
 *
 * Renders a centered, large 6-digit code entry form with:
 *   - Numeric input field (max 6 digits)
 *   - Submit button (enabled only when code is complete and not verifying)
 *   - Cancel button
 *   - Error message display (when error prop is set)
 *   - Loading spinner (when isVerifying is true)
 *
 * Auto-focuses the input on mount. Supports Enter key to submit.
 *
 * Example:
 *   <MfaChallenge
 *     onSubmit={handleSubmit}
 *     onCancel={handleCancel}
 *     isVerifying={isVerifying}
 *     error={error}
 *   />
 */
export function MfaChallenge({
  onSubmit,
  onCancel,
  isVerifying = false,
  error = null,
  title = "Verify Your Identity",
  description = "Enter your 6-digit authentication code",
  onInputChange,
}: MfaChallengeProps): React.ReactElement {
  const [code, setCode] = useState("");
  const inputRef = useRef<HTMLInputElement>(null);
  const errorIdRef = useRef(`mfa-error-${Math.random().toString(36).slice(2)}`);

  /**
   * Auto-focus the input on mount.
   */
  useEffect(() => {
    if (inputRef.current) {
      inputRef.current.focus();
    }
  }, []);

  /**
   * Handle input change: accept only digits, enforce maxLength in real time.
   * Notify parent if onInputChange callback is provided (for error clearing).
   */
  const handleInputChange = useCallback(
    (e: React.ChangeEvent<HTMLInputElement>) => {
      const value = e.currentTarget.value;
      // Keep only digits
      const digitsOnly = value.replace(/\D/g, "");
      // Enforce max length
      const truncated = digitsOnly.slice(0, 6);
      setCode(truncated);
      // Notify parent that input has changed
      onInputChange?.();
    },
    [onInputChange],
  );

  /**
   * Check if code is valid (exactly 6 digits).
   */
  const isCodeValid = code.length === 6;

  /**
   * Handle form submission on button click or Enter key.
   */
  const handleSubmit = useCallback(
    (e: React.FormEvent<HTMLFormElement>) => {
      e.preventDefault();
      if (isCodeValid && !isVerifying) {
        onSubmit(code);
      }
    },
    [code, isCodeValid, isVerifying, onSubmit],
  );

  return (
    <div className="flex flex-col items-center justify-center gap-6 px-4 py-8">
      {/* Title and description */}
      <div className="flex flex-col items-center gap-2 text-center">
        <h2 className="text-2xl font-semibold text-surface-900">{title}</h2>
        <p className="text-sm text-surface-600">{description}</p>
      </div>

      {/* Form */}
      <form onSubmit={handleSubmit} className="w-full max-w-sm space-y-6">
        {/* Input field */}
        <div className="space-y-2">
          <label htmlFor="mfa-code-input" className="block text-sm font-medium text-surface-700">
            Authentication Code
          </label>
          <input
            ref={inputRef}
            id="mfa-code-input"
            type="text"
            inputMode="numeric"
            pattern="[0-9]*"
            maxLength={6}
            value={code}
            onChange={handleInputChange}
            disabled={isVerifying}
            aria-describedby={error ? errorIdRef.current : undefined}
            className={clsx(
              "w-full rounded-lg border-2 bg-white px-4 py-3",
              "text-center font-mono text-2xl tracking-widest",
              "transition-colors duration-200",
              "placeholder:text-surface-400",
              "disabled:bg-surface-100 disabled:text-surface-500",
              error
                ? "border-red-500 focus:border-red-600 focus:outline-none"
                : "border-surface-200 focus:border-brand-500 focus:outline-none",
            )}
            placeholder="000000"
          />
          {/* Error message */}
          {error && (
            <div id={errorIdRef.current} className="text-sm font-medium text-red-600">
              {error}
            </div>
          )}
        </div>

        {/* Submit button */}
        <button
          type="submit"
          disabled={!isCodeValid || isVerifying}
          className={clsx(
            "w-full rounded-lg px-4 py-3 font-semibold transition-all duration-200",
            isCodeValid && !isVerifying
              ? "bg-brand-600 text-white hover:bg-brand-700 active:bg-brand-800"
              : "cursor-not-allowed bg-surface-200 text-surface-400",
          )}
        >
          {isVerifying ? (
            <div className="flex items-center justify-center gap-2">
              <Loader className="h-5 w-5 animate-spin" data-testid="verify-spinner" />
              <span>Verifying...</span>
            </div>
          ) : (
            "Verify"
          )}
        </button>
      </form>

      {/* Cancel button */}
      <button
        onClick={onCancel}
        disabled={isVerifying}
        className={clsx(
          "text-sm font-medium transition-colors duration-200",
          isVerifying
            ? "cursor-not-allowed text-surface-400"
            : "text-surface-600 hover:text-surface-900 active:text-surface-700",
        )}
      >
        Cancel
      </button>
    </div>
  );
}
