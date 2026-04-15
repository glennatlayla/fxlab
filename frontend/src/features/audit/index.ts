/**
 * Audit feature barrel exports.
 *
 * Purpose:
 *   Provide a single import point for all public audit feature APIs.
 *
 * Example:
 *   import { auditApi, AuditAuthError } from "@/features/audit";
 */

// Schemas and types
export type { AuditEventRecord, AuditExplorerResponse } from "@/types/audit";
export { AuditEventRecordSchema, AuditExplorerResponseSchema } from "@/types/audit";

// Errors
export {
  AuditError,
  AuditNotFoundError,
  AuditAuthError,
  AuditValidationError,
  AuditNetworkError,
  isTransientAuditError,
} from "./errors";

// Constants
export {
  ACTION_TYPE_LABELS,
  AUDIT_DEFAULT_PAGE_SIZE,
  AUDIT_MAX_PAGE_SIZE,
  AUDIT_API_MAX_RETRIES,
  AUDIT_API_RETRY_BASE_DELAY_MS,
  AUDIT_API_JITTER_FACTOR,
  OP_LIST_AUDIT,
  OP_GET_AUDIT_EVENT,
  OP_RETRY_ATTEMPT,
  OP_VALIDATION_FAILURE,
} from "./constants";

// Retry logic
export { retryWithBackoff, computeBackoffDelayMs } from "./retry";
export type { RetryOptions } from "./retry";

// Logger
export { auditLogger } from "./logger";

// API
export { auditApi } from "./api";
export type { ListAuditParams } from "./api";
