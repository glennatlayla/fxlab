/**
 * Strategy domain types — mirrors backend contracts from
 * libs/contracts/strategy.py, strategy_draft.py, and governance.py.
 *
 * Purpose:
 *   Provide TypeScript interfaces for all strategy-related data flowing
 *   between the frontend and backend. These are the source of truth for
 *   the frontend; the backend Pydantic models are the source of truth
 *   for the wire format.
 *
 * Does NOT:
 *   - Contain validation logic (Zod schemas in form components).
 *   - Contain business logic.
 *   - Contain React-specific code.
 */

// ---------------------------------------------------------------------------
// Parameter definitions (mirrors libs/contracts/strategy_draft.py)
// ---------------------------------------------------------------------------

/** Parameter types supported by the strategy compiler. */
export type ParameterType = "int" | "float" | "bool" | "string" | "choice";

/**
 * A single tunable parameter definition in a strategy.
 *
 * Defines constraints, default values, and UI hints for the parameter
 * tuning form.
 */
export interface ParameterDefinition {
  /** Machine-readable parameter name (e.g., "lookback_period"). */
  name: string;
  /** Human-readable label for the form field. */
  label: string;
  /** Parameter data type. */
  type: ParameterType;
  /** Default value when creating a new draft. */
  defaultValue: number | string | boolean;
  /** Minimum value (numeric types only). */
  min?: number;
  /** Maximum value (numeric types only). */
  max?: number;
  /** Step increment for numeric inputs. */
  step?: number;
  /** Allowed values for "choice" type parameters. */
  choices?: string[];
  /** Help text shown below the form field. */
  description?: string;
  /** Whether this parameter is required for compilation. */
  required: boolean;
}

// ---------------------------------------------------------------------------
// Draft lifecycle (mirrors libs/contracts/strategy_draft.py)
// ---------------------------------------------------------------------------

/** Draft status in the editing→compilation pipeline. */
export type StrategyDraftStatus = "editing" | "validating" | "valid" | "invalid" | "submitted";

/**
 * Strategy draft form data — the shape of data captured by StrategyDraftForm.
 *
 * This matches the user-facing form, NOT the API payload directly.
 * The form→API mapping happens in the autosave manager.
 */
export interface StrategyDraftFormData {
  /** Strategy display name. */
  name: string;
  /** Free-text description of the strategy's intent. */
  description: string;
  /** Instrument or market to trade (e.g., "ES", "NQ", "SPY"). */
  instrument: string;
  /** Timeframe for primary signal (e.g., "1m", "5m", "1h", "1d"). */
  timeframe: string;
  /** Entry condition expression (human-readable or DSL). */
  entryCondition: string;
  /** Exit condition expression. */
  exitCondition: string;
  /** Risk rules: max position size. */
  maxPositionSize: number;
  /** Risk rules: stop loss percentage (0–100). */
  stopLossPercent: number;
  /** Risk rules: take profit percentage (0–100). */
  takeProfitPercent: number;
  /** Tunable parameters for optimization. */
  parameters: ParameterDefinition[];
}

// ---------------------------------------------------------------------------
// Autosave (mirrors libs/contracts/governance.py DraftAutosavePayload)
// ---------------------------------------------------------------------------

/**
 * Payload sent to POST /strategies/draft/autosave.
 *
 * Matches the backend DraftAutosavePayload contract.
 */
export interface DraftAutosavePayload {
  /** ULID of the user owning this draft. */
  user_id: string;
  /** Partial form data — may be incomplete. */
  draft_payload: Partial<StrategyDraftFormData>;
  /** Wizard step at time of autosave (e.g., "basics", "parameters", "risk"). */
  form_step: string;
  /** Client-side ISO timestamp at the moment of autosave. */
  client_ts: string;
  /** Browser session identifier for recovery disambiguation. */
  session_id: string;
}

/**
 * Response from POST /strategies/draft/autosave.
 */
export interface DraftAutosaveResponse {
  /** Server-assigned ULID for this autosave record. */
  autosave_id: string;
  /** Server-side persistence timestamp (ISO 8601). */
  saved_at: string;
}

/**
 * Response from GET /strategies/draft/autosave/latest.
 * Returns the full autosave record for recovery.
 */
export interface DraftAutosaveRecord {
  /** ULID of this autosave record. */
  id: string;
  /** ULID of the user who owns this draft. */
  user_id: string;
  /** Partial form data at time of autosave. */
  draft_payload: Partial<StrategyDraftFormData>;
  /** Wizard step at time of autosave. */
  form_step: string;
  /** Browser session identifier. */
  session_id: string;
  /** Client-side timestamp (ISO 8601). */
  client_ts: string;
  /** Server-side creation timestamp (ISO 8601). */
  created_at: string;
  /** Server-side last update timestamp (ISO 8601). */
  updated_at: string;
}

// ---------------------------------------------------------------------------
// Blueprint / Compiled Strategy (mirrors libs/contracts/strategy.py)
// ---------------------------------------------------------------------------

/**
 * Compiled strategy build artifact reference.
 */
export interface StrategyBuild {
  /** ULID of the build. */
  id: string;
  /** Strategy name. */
  name: string;
  /** Semantic version string (e.g., "1.0.0"). */
  version: string;
  /** URI to the compiled artifact (S3 path or local). */
  artifact_uri: string;
  /** Hash of source strategy definition for integrity. */
  source_hash: string;
  /** ULID of the user who triggered compilation. */
  created_by: string;
  /** Creation timestamp (ISO 8601). */
  created_at: string;
  /** Optional override watermark for governance tracking. */
  override_watermark?: string;
}

// ---------------------------------------------------------------------------
// Uncertainty / Ambiguity (M25 spec: UncertaintyExplainer)
// ---------------------------------------------------------------------------

/** Severity levels for strategy uncertainties. */
export type UncertaintySeverity = "info" | "warning" | "material";

/**
 * A single uncertainty entry surfaced during strategy validation.
 *
 * Uncertainties are issues that may affect strategy behaviour but don't
 * necessarily prevent compilation — except for "material" severity, which
 * blocks paper-eligible compilation.
 */
export interface UncertaintyEntry {
  /** Unique identifier for this uncertainty. */
  id: string;
  /** Machine-readable code (e.g., "MATERIAL_AMBIGUITY", "PARAM_RANGE_WIDE"). */
  code: string;
  /** Severity level. "material" blocks compilation to paper-eligible. */
  severity: UncertaintySeverity;
  /** Human-readable title. */
  title: string;
  /** Plain-language description of the uncertainty. */
  description: string;
  /** Display name of the owner responsible for resolution. */
  ownerDisplayName?: string;
  /** Whether this uncertainty has been resolved. */
  resolved: boolean;
  /** Resolution note (set when resolved). */
  resolutionNote?: string;
}

// ---------------------------------------------------------------------------
// Compilation pipeline (M25 spec: CompilationStatus)
// ---------------------------------------------------------------------------

/** Status of a single compilation stage. */
export type CompilationStageStatus = "pending" | "running" | "completed" | "failed" | "skipped";

/**
 * A single stage in the strategy compilation pipeline.
 */
export interface CompilationStage {
  /** Machine-readable stage name (e.g., "parse", "validate", "compile", "package"). */
  name: string;
  /** Human-readable stage label. */
  label: string;
  /** Current status of this stage. */
  status: CompilationStageStatus;
  /** Duration in milliseconds (set when completed or failed). */
  durationMs?: number;
  /** Error message (set when failed). */
  error?: string;
}

/**
 * Overall compilation run status.
 */
export interface CompilationRun {
  /** ULID of the compilation run. */
  id: string;
  /** ULID of the strategy draft being compiled. */
  strategyId: string;
  /** Ordered list of pipeline stages. */
  stages: CompilationStage[];
  /** Overall status derived from individual stages. */
  overallStatus: CompilationStageStatus;
  /** Timestamp when compilation was initiated (ISO 8601). */
  startedAt: string;
  /** Timestamp when compilation completed (ISO 8601, null if still running). */
  completedAt?: string;
}

// ---------------------------------------------------------------------------
// Form wizard steps
// ---------------------------------------------------------------------------

/** Strategy Studio form wizard steps in order. */
export const STRATEGY_WIZARD_STEPS = [
  "basics",
  "conditions",
  "risk",
  "parameters",
  "review",
] as const;

export type StrategyWizardStep = (typeof STRATEGY_WIZARD_STEPS)[number];
