/**
 * Paper trading feature barrel file.
 *
 * Exports public API for paper trading setup and monitoring.
 */

export { PaperTradingForm } from "./components/PaperTradingForm";
export { PaperTradingReview } from "./components/PaperTradingReview";
export { paperTradingApi } from "./api";
export { paperTradingConfigSchema, type PaperTradingConfigInput } from "./validation";
export type {
  PaperTradingConfig,
  PaperTradingRegisterRequest,
  PaperTradingRegisterResponse,
  PaperTradingReviewSummary,
  DeploymentMetadata,
  StrategyBuildMetadata,
  PaperDeploymentStatus,
  PaperDeploymentSummary,
  PaperPosition,
  PaperOrder,
} from "./types";
