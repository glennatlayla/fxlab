/**
 * Parity feature barrel exports.
 *
 * Provides a unified import point for the entire parity feature:
 * - Error types and classification
 * - API client and operations
 * - Logging utilities
 * - Constants and styling
 * - Retry utilities
 *
 * Example:
 *   import { parityApi, ParityCriticalError, parityLogger } from "@/features/parity";
 */

// Errors
export {
  ParityError,
  ParityNotFoundError,
  ParityAuthError,
  ParityValidationError,
  ParityNetworkError,
  isTransientParityError,
} from "./errors";

// API
export { parityApi } from "./api";
export type { ListEventsParams } from "./api";

// Logger
export { parityLogger } from "./logger";

// Constants
export {
  PARITY_SEVERITY_BADGE_CLASSES,
  PARITY_SEVERITY_LABELS,
  PARITY_DEFAULT_PAGE_SIZE,
  PARITY_MAX_PAGE_SIZE,
  PARITY_API_MAX_RETRIES,
  PARITY_API_RETRY_BASE_DELAY_MS,
  PARITY_API_JITTER_FACTOR,
  OP_LIST_EVENTS,
  OP_GET_EVENT,
  OP_GET_SUMMARY,
  OP_RETRY_ATTEMPT,
  OP_VALIDATION_FAILURE,
} from "./constants";

// Retry
export { retryWithBackoff, computeBackoffDelayMs } from "./retry";
export type { RetryOptions, RetryLogCallback } from "./retry";
