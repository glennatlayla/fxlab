/**
 * Risk settings feature exports.
 *
 * Purpose:
 *   Provide a clean, unified export surface for all risk settings components,
 *   APIs, and utilities.
 *
 * Exports:
 *   - RiskSettingsEditor: Main orchestrator component.
 *   - RiskSettingsCard: Display and edit card.
 *   - RiskChangeDiff: Change review component.
 *   - riskApi: API client module.
 *   - types: All TypeScript types and interfaces.
 *   - utils: Utility functions.
 *
 * Example:
 *   import { RiskSettingsEditor, riskApi } from "@/features/risk";
 */

// Components
export { RiskSettingsEditor } from "./components/RiskSettingsEditor";
export { RiskSettingsCard } from "./components/RiskSettingsCard";
export { RiskChangeDiff } from "./components/RiskChangeDiff";

// API
export { riskApi } from "./api";

// Types
export type { RiskSettings, RiskSettingsUpdate, RiskSettingsDiff } from "./types";

// Utils
export { calculateDiffs, calculateChangePercent } from "./utils";
