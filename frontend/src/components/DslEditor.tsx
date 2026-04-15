/**
 * DslEditor — Strategy condition editor with live DSL validation (M10).
 *
 * Purpose:
 *   Provide an enhanced textarea for entering FXLab strategy DSL conditions
 *   with live syntax validation, error markers, line numbers, and
 *   auto-completion hints for indicator names.
 *
 * Responsibilities:
 *   - Render a styled textarea with line numbers.
 *   - Debounce user input and call the DSL validation API.
 *   - Display inline validation errors with line/column positions.
 *   - Show suggestions for fixing syntax errors.
 *   - Display a list of detected indicators and variables.
 *   - Provide auto-completion dropdown for indicator names.
 *
 * Does NOT:
 *   - Execute or evaluate DSL conditions (backend responsibility).
 *   - Persist draft data (parent component responsibility).
 *   - Manage auth state.
 *
 * Dependencies:
 *   - strategyApi.validateDsl from @/features/strategy/api.
 *   - React hooks: useState, useEffect, useCallback, useRef, useMemo.
 *
 * Props:
 *   value: Current DSL expression string.
 *   onChange: Callback when expression changes.
 *   label: Display label (e.g. "Entry Condition", "Exit Condition").
 *   placeholder: Placeholder text for the textarea.
 *   testId: data-testid prefix for testing.
 *
 * Example:
 *   <DslEditor
 *     value={entryCondition}
 *     onChange={setEntryCondition}
 *     label="Entry Condition"
 *     placeholder="e.g., RSI(14) < 30 AND price > SMA(200)"
 *     testId="entry-dsl"
 *   />
 */

import { useState, useEffect, useCallback, useRef, useMemo } from "react";
import { strategyApi } from "@/features/strategy/api";
import type { DslValidationResult, DslValidationError } from "@/features/strategy/api";

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

/** Debounce delay for validation API calls (milliseconds). */
const VALIDATION_DEBOUNCE_MS = 500;

/** Supported indicator names for auto-completion hints. */
const INDICATOR_NAMES = [
  "RSI",
  "SMA",
  "EMA",
  "MACD",
  "BBANDS",
  "ATR",
  "STOCH",
  "VWAP",
  "ADX",
  "CCI",
  "MFI",
  "OBV",
  "WILLR",
  "ROC",
];

/** Built-in variable names for auto-completion hints. */
const VARIABLE_NAMES = ["price", "open", "high", "low", "close", "volume"];

/** Logical operators for auto-completion. */
const OPERATOR_KEYWORDS = ["AND", "OR", "NOT"];

// ---------------------------------------------------------------------------
// Props
// ---------------------------------------------------------------------------

export interface DslEditorProps {
  /** Current DSL expression value. */
  value: string;
  /** Callback when expression changes. */
  onChange: (value: string) => void;
  /** Display label for the editor (e.g. "Entry Condition"). */
  label: string;
  /** Placeholder text shown when editor is empty. */
  placeholder?: string;
  /** data-testid prefix for testing. */
  testId?: string;
  /** Whether the editor is disabled. */
  disabled?: boolean;
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export function DslEditor({
  value,
  onChange,
  label,
  placeholder = "e.g., RSI(14) < 30 AND price > SMA(200)",
  testId = "dsl-editor",
  disabled = false,
}: DslEditorProps) {
  const [validation, setValidation] = useState<DslValidationResult | null>(null);
  const [isValidating, setIsValidating] = useState(false);
  const [showCompletions, setShowCompletions] = useState(false);
  const [completionFilter, setCompletionFilter] = useState("");
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  // Filtered completion suggestions based on current typing context
  const completionItems = useMemo(() => {
    const filter = completionFilter.toUpperCase();
    if (!filter) return [];

    const allItems = [
      ...INDICATOR_NAMES.map((name) => ({ label: name, type: "indicator" as const })),
      ...VARIABLE_NAMES.map((name) => ({ label: name, type: "variable" as const })),
      ...OPERATOR_KEYWORDS.map((name) => ({ label: name, type: "keyword" as const })),
    ];

    return allItems.filter((item) => item.label.toUpperCase().startsWith(filter)).slice(0, 8);
  }, [completionFilter]);

  /**
   * Trigger DSL validation after debounce delay.
   *
   * Cancels any pending validation and schedules a new one.
   * Does not validate empty expressions — clears validation state instead.
   */
  const triggerValidation = useCallback((expression: string) => {
    if (debounceRef.current) {
      clearTimeout(debounceRef.current);
    }

    if (!expression.trim()) {
      setValidation(null);
      setIsValidating(false);
      return;
    }

    setIsValidating(true);
    debounceRef.current = setTimeout(async () => {
      try {
        const result = await strategyApi.validateDsl(expression);
        setValidation(result);
      } catch {
        // Network error — clear validation state silently
        setValidation(null);
      } finally {
        setIsValidating(false);
      }
    }, VALIDATION_DEBOUNCE_MS);
  }, []);

  // Trigger validation when value changes
  useEffect(() => {
    triggerValidation(value);
    return () => {
      if (debounceRef.current) clearTimeout(debounceRef.current);
    };
  }, [value, triggerValidation]);

  /**
   * Handle text input changes.
   *
   * Updates the parent value and extracts the current word being typed
   * for auto-completion filtering.
   */
  const handleChange = useCallback(
    (e: React.ChangeEvent<HTMLTextAreaElement>) => {
      const newValue = e.target.value;
      onChange(newValue);

      // Extract current word for auto-completion
      const cursorPos = e.target.selectionStart ?? newValue.length;
      const textBeforeCursor = newValue.slice(0, cursorPos);
      const match = textBeforeCursor.match(/([a-zA-Z_]\w*)$/);

      if (match && match[1].length >= 2) {
        setCompletionFilter(match[1]);
        setShowCompletions(true);
      } else {
        setShowCompletions(false);
        setCompletionFilter("");
      }
    },
    [onChange],
  );

  /**
   * Apply an auto-completion selection.
   *
   * Replaces the current partial word with the selected completion.
   */
  const applyCompletion = useCallback(
    (completionLabel: string) => {
      const textarea = textareaRef.current;
      if (!textarea) return;

      const cursorPos = textarea.selectionStart ?? value.length;
      const textBefore = value.slice(0, cursorPos);
      const textAfter = value.slice(cursorPos);
      const match = textBefore.match(/([a-zA-Z_]\w*)$/);

      if (match) {
        const replacement = textBefore.slice(0, -match[1].length) + completionLabel;
        onChange(replacement + textAfter);
      }

      setShowCompletions(false);
      setCompletionFilter("");
      textarea.focus();
    },
    [value, onChange],
  );

  // Determine validation state for styling
  const isValid = validation?.is_valid === true;
  const hasErrors = validation !== null && !validation.is_valid;

  // Border color based on validation state
  const borderColor = hasErrors
    ? "border-red-400 focus:border-red-500 focus:ring-red-500"
    : isValid
      ? "border-green-400 focus:border-green-500 focus:ring-green-500"
      : "border-surface-300 focus:border-blue-500 focus:ring-blue-500";

  // Count lines for the line number gutter
  const lineCount = Math.max(value.split("\n").length, 3);

  return (
    <div className="space-y-2" data-testid={testId}>
      {/* Label and validation indicator */}
      <div className="flex items-center justify-between">
        <label htmlFor={`${testId}-input`} className="block text-sm font-medium text-surface-700">
          {label}
        </label>
        <div className="flex items-center gap-2">
          {isValidating && (
            <span className="text-xs text-surface-400" data-testid={`${testId}-validating`}>
              Validating...
            </span>
          )}
          {isValid && !isValidating && (
            <span className="text-xs text-green-600" data-testid={`${testId}-valid`}>
              Valid
            </span>
          )}
          {hasErrors && !isValidating && (
            <span className="text-xs text-red-600" data-testid={`${testId}-invalid`}>
              {validation.errors.length} error{validation.errors.length !== 1 ? "s" : ""}
            </span>
          )}
        </div>
      </div>

      {/* Editor area with line numbers */}
      <div className="relative">
        <div className="flex rounded-md border shadow-sm">
          {/* Line numbers gutter */}
          <div
            className="select-none rounded-l-md border-r border-surface-200 bg-surface-50 px-2 py-2 text-right font-mono text-xs text-surface-400"
            data-testid={`${testId}-line-numbers`}
            aria-hidden
          >
            {Array.from({ length: lineCount }, (_, i) => (
              <div key={i + 1} className="leading-5">
                {i + 1}
              </div>
            ))}
          </div>

          {/* Textarea */}
          <textarea
            ref={textareaRef}
            id={`${testId}-input`}
            value={value}
            onChange={handleChange}
            onBlur={() => setShowCompletions(false)}
            placeholder={placeholder}
            disabled={disabled}
            rows={Math.max(lineCount, 3)}
            className={`w-full resize-y rounded-r-md border-0 px-3 py-2 font-mono text-sm leading-5 focus:outline-none focus:ring-1 ${borderColor} ${
              disabled ? "cursor-not-allowed bg-surface-50" : "bg-white"
            }`}
            data-testid={`${testId}-textarea`}
            spellCheck={false}
            autoComplete="off"
          />
        </div>

        {/* Auto-completion dropdown */}
        {showCompletions && completionItems.length > 0 && (
          <div
            className="absolute left-8 top-full z-10 mt-1 max-h-48 overflow-y-auto rounded-md border border-surface-200 bg-white shadow-lg"
            data-testid={`${testId}-completions`}
          >
            {completionItems.map((item) => (
              <button
                key={item.label}
                type="button"
                className="flex w-full items-center gap-2 px-3 py-1.5 text-left text-sm hover:bg-surface-50"
                onMouseDown={(e) => {
                  e.preventDefault(); // Prevent textarea blur
                  applyCompletion(item.label);
                }}
                data-testid={`${testId}-completion-${item.label}`}
              >
                <span
                  className={`inline-block h-2 w-2 rounded-full ${
                    item.type === "indicator"
                      ? "bg-blue-400"
                      : item.type === "variable"
                        ? "bg-green-400"
                        : "bg-purple-400"
                  }`}
                />
                <span className="font-mono">{item.label}</span>
                <span className="text-xs text-surface-400">{item.type}</span>
              </button>
            ))}
          </div>
        )}
      </div>

      {/* Validation errors */}
      {hasErrors && (
        <div className="space-y-1" data-testid={`${testId}-errors`}>
          {validation.errors.map((error: DslValidationError, index: number) => (
            <div
              key={`${error.line}-${error.column}-${index}`}
              className="rounded border border-red-200 bg-red-50 px-3 py-1.5 text-sm"
              data-testid={`${testId}-error-${index}`}
            >
              <span className="font-medium text-red-700">
                Line {error.line}, Col {error.column}:
              </span>{" "}
              <span className="text-red-600">{error.message}</span>
              {error.suggestion && <span className="ml-2 text-red-400">({error.suggestion})</span>}
            </div>
          ))}
        </div>
      )}

      {/* Detected indicators and variables */}
      {isValid && validation && (
        <div className="flex flex-wrap gap-2" data-testid={`${testId}-metadata`}>
          {validation.indicators_used.map((ind) => (
            <span
              key={ind}
              className="inline-flex items-center rounded-full bg-blue-50 px-2.5 py-0.5 text-xs font-medium text-blue-700"
              data-testid={`${testId}-indicator-${ind}`}
            >
              {ind}
            </span>
          ))}
          {validation.variables_used.map((v) => (
            <span
              key={v}
              className="inline-flex items-center rounded-full bg-green-50 px-2.5 py-0.5 text-xs font-medium text-green-700"
              data-testid={`${testId}-variable-${v}`}
            >
              {v}
            </span>
          ))}
        </div>
      )}
    </div>
  );
}
