/**
 * Queues feature barrel exports.
 *
 * Re-exports types, errors, constants, logger, API client, and retry helpers
 * for convenient feature-level imports.
 *
 * Example:
 *   import { queuesApi, QueuesNetworkError } from "@/features/queues";
 */

// Types
export type { QueueSnapshot, QueueContention, QueueListResponse } from "@/types/queues";
export {
  QueueSnapshotSchema,
  QueueContentionSchema,
  QueueListResponseSchema,
} from "@/types/queues";

// Errors
export {
  QueuesError,
  QueuesNotFoundError,
  QueuesAuthError,
  QueuesValidationError,
  QueuesNetworkError,
  isTransientQueuesError,
} from "./errors";

// Constants
export {
  CONTENTION_SCORE_LOW_MAX,
  CONTENTION_SCORE_MEDIUM_MAX,
  CONTENTION_SCORE_HIGH_MIN,
  CONTENTION_BADGE_CLASSES,
  CONTENTION_LEVEL_LABELS,
  getContentionLevel,
  QUEUES_API_MAX_RETRIES,
  QUEUES_API_RETRY_BASE_DELAY_MS,
  QUEUES_API_JITTER_FACTOR,
  OP_LIST_QUEUES,
  OP_GET_CONTENTION,
  OP_RETRY_ATTEMPT,
  OP_VALIDATION_FAILURE,
} from "./constants";

// Retry
export { retryWithBackoff, computeBackoffDelayMs } from "./retry";
export type { RetryOptions, RetryLogCallback } from "./retry";

// Logger
export { queuesLogger } from "./logger";

// API
export { queuesApi } from "./api";
