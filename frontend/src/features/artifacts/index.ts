/**
 * Artifacts feature barrel exports.
 *
 * Public API for the artifacts feature. Components, services, and other
 * modules import from this file rather than from individual submodules.
 */

// API
export { artifactApi, type ListArtifactsParams } from "./api";

// Errors
export {
  ArtifactError,
  ArtifactNotFoundError,
  ArtifactAuthError,
  ArtifactValidationError,
  ArtifactNetworkError,
  isTransientArtifactError,
} from "./errors";

// Constants
export {
  ARTIFACT_TYPE_LABELS,
  ARTIFACT_TYPE_BADGE_CLASSES,
  DEFAULT_PAGE_SIZE,
  MAX_PAGE_SIZE,
  ARTIFACTS_API_MAX_RETRIES,
  ARTIFACTS_API_RETRY_BASE_DELAY_MS,
  ARTIFACTS_API_JITTER_FACTOR,
  OP_LIST_ARTIFACTS,
  OP_DOWNLOAD_ARTIFACT,
  OP_RETRY_ATTEMPT,
  OP_VALIDATION_FAILURE,
  formatFileSize,
} from "./constants";

// Logger
export { artifactLogger } from "./logger";

// Retry
export { retryWithBackoff, computeBackoffDelayMs, type RetryOptions } from "./retry";

// Components
export { ArtifactBrowser } from "./components/ArtifactBrowser";
