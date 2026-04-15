/**
 * ParameterTuning — form for tuning strategy parameters.
 *
 * Purpose:
 *   Render a form with fields for each parameter definition, supporting
 *   int/float numeric inputs with bounds validation, choice dropdowns,
 *   and boolean checkboxes. Validates that numeric ranges are valid and
 *   calls onSubmit with collected parameter values.
 *
 * Responsibilities:
 *   - Render appropriate input type for each parameter (number, select, checkbox).
 *   - Apply min/max/step constraints to numeric inputs.
 *   - Validate that numeric values are within bounds.
 *   - Show validation errors and disable submit when bounds are invalid.
 *   - Collect and pass parameter values to onSubmit callback.
 *   - Display default values in all fields.
 *
 * Does NOT:
 *   - Persist parameter values (handled by parent component).
 *   - Manage global parameter state.
 *
 * Dependencies:
 *   - ParameterDefinition type from @/types/strategy
 *
 * Example:
 *   const params: ParameterDefinition[] = [
 *     {
 *       name: "lookback_period",
 *       label: "Lookback Period",
 *       type: "int",
 *       defaultValue: 20,
 *       min: 5,
 *       max: 500,
 *       step: 1,
 *     },
 *   ];
 *   <ParameterTuning parameters={params} onSubmit={(values) => console.log(values)} />
 */

import { useState } from "react";
import type { ParameterDefinition } from "@/types/strategy";

interface ParameterTuningProps {
  /** List of parameter definitions to render form fields for. */
  parameters: ParameterDefinition[];
  /** Callback invoked with parameter name→value map on valid submission. */
  onSubmit: (values: Record<string, number | string | boolean>) => void;
}

export function ParameterTuning({ parameters, onSubmit }: ParameterTuningProps) {
  const [values, setValues] = useState<Record<string, number | string | boolean>>(() => {
    const initial: Record<string, number | string | boolean> = {};
    parameters.forEach((param) => {
      initial[param.name] = param.defaultValue;
    });
    return initial;
  });

  const [validationError, setValidationError] = useState<string>("");

  const validateValue = (paramName: string, value: number | string | boolean): string => {
    const param = parameters.find((p) => p.name === paramName);
    if (!param || (param.type !== "int" && param.type !== "float")) {
      return "";
    }

    const numValue = value as number;
    if (param.max !== undefined && numValue > param.max) {
      return `${param.label} exceeds maximum value of ${param.max}.`;
    }
    if (param.min !== undefined && numValue < param.min) {
      return `${param.label} is below minimum value of ${param.min}.`;
    }
    return "";
  };

  const handleChange = (name: string, newValue: number | string | boolean) => {
    setValues((prev) => ({ ...prev, [name]: newValue }));
    const error = validateValue(name, newValue);
    setValidationError(error);
  };

  const validateForm = (): boolean => {
    for (const param of parameters) {
      if (param.type === "int" || param.type === "float") {
        const value = values[param.name] as number;
        if (param.min !== undefined && param.max !== undefined) {
          if (value > param.max) {
            setValidationError(`${param.label} exceeds maximum value of ${param.max}.`);
            return false;
          }
          if (value < param.min) {
            setValidationError(`${param.label} is below minimum value of ${param.min}.`);
            return false;
          }
        }
      }
    }
    setValidationError("");
    return true;
  };

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (validateForm()) {
      onSubmit(values);
    }
  };

  const isSubmitDisabled = validationError.length > 0;

  return (
    <form onSubmit={handleSubmit} className="space-y-6">
      {parameters.map((param) => (
        <div key={param.name} className="flex flex-col gap-2">
          {param.type === "bool" ? (
            <div className="flex items-center gap-2">
              <input
                type="checkbox"
                id={param.name}
                checked={values[param.name] as boolean}
                onChange={(e) => handleChange(param.name, e.target.checked)}
                className="h-4 w-4 rounded border-surface-300 text-brand-600
                  focus:ring-2 focus:ring-brand-500"
              />
              <label htmlFor={param.name} className="text-sm font-medium text-surface-900">
                {param.label}
              </label>
              {param.description && <p className="text-xs text-surface-500">{param.description}</p>}
            </div>
          ) : param.type === "choice" ? (
            <>
              <label htmlFor={param.name} className="text-sm font-medium text-surface-900">
                {param.label}
              </label>
              <select
                id={param.name}
                value={values[param.name] as string}
                onChange={(e) => handleChange(param.name, e.target.value)}
                className="rounded-md border border-surface-300 bg-white px-3 py-2 text-sm
                  text-surface-900 focus:outline-none focus:ring-2 focus:ring-brand-500"
              >
                {param.choices?.map((choice) => (
                  <option key={choice} value={choice}>
                    {choice}
                  </option>
                ))}
              </select>
              {param.description && <p className="text-xs text-surface-500">{param.description}</p>}
            </>
          ) : (
            <>
              <label htmlFor={param.name} className="text-sm font-medium text-surface-900">
                {param.label}
              </label>
              <input
                type="number"
                id={param.name}
                min={param.min}
                max={param.max}
                step={param.step}
                value={String(values[param.name])}
                onChange={(e) => {
                  const val =
                    param.type === "int"
                      ? parseInt(e.target.value, 10)
                      : parseFloat(e.target.value);
                  handleChange(param.name, val);
                }}
                className="rounded-md border border-surface-300 bg-white px-3 py-2 text-sm
                  text-surface-900 focus:outline-none focus:ring-2 focus:ring-brand-500"
              />
              {param.description && <p className="text-xs text-surface-500">{param.description}</p>}
            </>
          )}
        </div>
      ))}

      {validationError && (
        <div className="rounded-md bg-danger/10 p-3 text-sm text-danger">{validationError}</div>
      )}

      <button
        type="submit"
        disabled={isSubmitDisabled}
        className={`w-full rounded-md px-4 py-2 text-sm font-medium text-white
          ${
            isSubmitDisabled
              ? "cursor-not-allowed bg-surface-300 text-surface-500"
              : "bg-brand-600 hover:bg-brand-700"
          }`}
      >
        Apply Parameters
      </button>
    </form>
  );
}
