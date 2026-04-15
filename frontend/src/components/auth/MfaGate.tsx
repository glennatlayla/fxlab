/**
 * MfaGate — Re-authentication gate for high-risk operations.
 *
 * Purpose:
 *   Wrap content that requires MFA verification. When isRequired=true,
 *   displays the MfaChallenge; when isRequired=false, renders children.
 *   Handles verification state, errors, and presentation (modal on desktop,
 *   bottom sheet on mobile).
 *
 * Responsibilities:
 *   - Show/hide MfaChallenge based on isRequired prop.
 *   - Call onVerify with the entered code and handle promise resolution.
 *   - Display verification errors and support retry.
 *   - Clear error when user starts typing a new code.
 *   - Render children when verification succeeds.
 *   - Manage presentation: BottomSheet on mobile, modal on desktop.
 *   - Handle cancellation via onCancel callback.
 *
 * Does NOT:
 *   - Own the isRequired state; parent controls this.
 *   - Make API calls directly; parent provides onVerify callback.
 *   - Store verification results; parent handles post-verification logic.
 *
 * Dependencies:
 *   - React (useState, useCallback)
 *   - MfaChallenge component
 *   - BottomSheet component
 *   - useIsMobile hook
 *   - Tailwind CSS, clsx
 *
 * Error conditions:
 *   - onVerify rejects: caught, error message displayed to user.
 *
 * Example:
 *   const [requiresMfa, setRequiresMfa] = useState(true);
 *
 *   const handleVerify = async (code: string) => {
 *     const response = await api.post("/auth/mfa/verify", { code });
 *     if (!response.ok) {
 *       throw new Error("Invalid code");
 *     }
 *     // Verification succeeded — parent can clear requiresMfa
 *   };
 *
 *   return (
 *     <MfaGate
 *       isRequired={requiresMfa}
 *       onVerify={handleVerify}
 *       onCancel={() => setRequiresMfa(false)}
 *     >
 *       <HighRiskOperation />
 *     </MfaGate>
 *   );
 */

import React, { useState, useCallback } from "react";
import { MfaChallenge } from "./MfaChallenge";
import { BottomSheet } from "../mobile/BottomSheet";
import { useIsMobile } from "@/hooks/useMediaQuery";

export interface MfaGateProps {
  /** Whether MFA is currently required. When true, shows challenge; when false, renders children. */
  isRequired: boolean;
  /** Callback to verify the code. Should return a promise that resolves on success, rejects with error on failure. */
  onVerify: (code: string) => Promise<void>;
  /** Content to render when MFA is not required or after verification succeeds. */
  children: React.ReactNode;
  /** Callback when user cancels MFA. Parent should set isRequired=false. */
  onCancel: () => void;
}

/**
 * MfaGate component.
 *
 * Gates its children behind an MFA challenge. Chooses presentation based on
 * viewport size (BottomSheet on mobile, centered modal on desktop).
 * Handles verification state, error display, and retry logic.
 *
 * Example:
 *   <MfaGate
 *     isRequired={requiresMfa}
 *     onVerify={verifyMfaCode}
 *     onCancel={() => setRequiresMfa(false)}
 *   >
 *     <KillSwitch />
 *   </MfaGate>
 */
export function MfaGate({
  isRequired,
  onVerify,
  children,
  onCancel,
}: MfaGateProps): React.ReactElement {
  const isMobile = useIsMobile();
  const [isVerifying, setIsVerifying] = useState(false);
  const [error, setError] = useState<string | null>(null);

  /**
   * Handle MFA code submission.
   * Calls onVerify, shows loading state, and displays errors.
   */
  const handleSubmit = useCallback(
    async (code: string) => {
      setIsVerifying(true);
      setError(null);

      try {
        await onVerify(code);
        // Verification succeeded — parent handles clearing isRequired
      } catch (err) {
        // Verification failed — show error message
        const message = err instanceof Error ? err.message : "Verification failed";
        setError(message);
        setIsVerifying(false);
      }
    },
    [onVerify],
  );

  /**
   * Handle user input: clear error when they start typing a new code.
   */
  const handleInputChange = useCallback(() => {
    setError(null);
  }, []);

  if (!isRequired) {
    return <>{children}</>;
  }

  // Mobile presentation: BottomSheet
  if (isMobile) {
    return (
      <BottomSheet isOpen={isRequired} onClose={onCancel} title="Multi-Factor Authentication">
        <MfaChallenge
          onSubmit={handleSubmit}
          onCancel={onCancel}
          isVerifying={isVerifying}
          error={error}
          onInputChange={handleInputChange}
        />
      </BottomSheet>
    );
  }

  // Desktop presentation: centered modal with backdrop
  return (
    <>
      {/* Backdrop */}
      <div
        className="fixed inset-0 z-40 bg-black/50 transition-opacity"
        onClick={onCancel}
        aria-hidden="true"
      />

      {/* Modal */}
      <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
        <div className="w-full max-w-md rounded-lg bg-white shadow-xl">
          {/* Content */}
          <MfaChallenge
            onSubmit={handleSubmit}
            onCancel={onCancel}
            isVerifying={isVerifying}
            error={error}
            onInputChange={handleInputChange}
          />
        </div>
      </div>
    </>
  );
}
