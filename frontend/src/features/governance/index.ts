/**
 * Governance feature public API — barrel exports.
 *
 * Purpose:
 *   Single entry point for all governance feature exports.
 *   Consumers import from "@/features/governance" rather than
 *   reaching into internal modules.
 *
 * Does NOT:
 *   - Export internal implementation details.
 */

export { governanceApi } from "./api";
export {
  GovernanceError,
  GovernanceNotFoundError,
  GovernanceAuthError,
  GovernanceValidationError,
  GovernanceNetworkError,
  GovernanceSoDError,
  isTransientError,
} from "./errors";
export { governanceLogger } from "./logger";
export * from "./constants";
export { sanitizeUrl } from "./utils";
export { PromotionHistory } from "./components/PromotionHistory";
