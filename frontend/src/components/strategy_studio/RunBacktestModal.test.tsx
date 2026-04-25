/**
 * Tests for RunBacktestModal (M2.D3).
 *
 * Verifies:
 *   1. All required form fields render when ``open=true``.
 *   2. Submit button is disabled until every required field is valid.
 *   3. A valid submission POSTs the correct body to ``/runs/from-ir``
 *      (mocked) and navigates to ``/runs/{run_id}`` on 201.
 *   4. A backend 422 response surfaces the validation error inline at
 *      the form level and (when the loc path matches) on the field.
 *
 * The modal is the only DOM under test — the parent strategy-detail
 * page is owned by a sibling tranche, so we mount the modal directly.
 */

import { describe, it, expect, vi, beforeEach } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import type { ReactElement } from "react";
import type { ExperimentPlan } from "@/types/experiment_plan";
import { RunBacktestModal } from "./RunBacktestModal";

// ---------------------------------------------------------------------------
// Mocks
// ---------------------------------------------------------------------------

const mockNavigate = vi.fn();
vi.mock("react-router-dom", () => ({
  useNavigate: () => mockNavigate,
}));

const mockSubmit = vi.fn();
vi.mock("@/api/runs", () => ({
  submitRunFromIr: (...args: unknown[]) => mockSubmit(...args),
}));

// ---------------------------------------------------------------------------
// Fixtures
// ---------------------------------------------------------------------------

function makeValidPlan(): ExperimentPlan {
  return {
    schema_version: "0.1-inferred",
    artifact_type: "experiment_plan",
    strategy_ref: { strategy_name: "FX_Sample", strategy_version: "1.0.0" },
    run_metadata: { run_purpose: "baseline_research", owner: "OpenAI", random_seed: 42 },
    data_selection: {
      dataset_ref: "fx-majors-d1-certified-v1",
      dataset_version: "2026.04",
      spread_dataset_ref: "fx-majors-spread-certified-v1",
      calendar_ref: "global_fx_business_calendar_v1",
    },
    cost_models: {
      commission_model_ref: "retail_fx_commission_v1",
      slippage_model_ref: "fx_major_default_v1",
      swap_model_ref: "broker_swap_default_v1",
    },
    splits: {
      in_sample: { start: "2010-01-01", end: "2019-12-31" },
      out_of_sample: { start: "2020-01-01", end: "2023-12-31" },
      holdout: { start: "2024-01-01", end: "2026-03-31" },
    },
    validation: {
      walk_forward: {
        enabled: true,
        train_window_months: 60,
        test_window_months: 12,
        step_months: 6,
      },
      monte_carlo: { enabled: true, iterations: 500, method: "trade_sequence_resampling" },
      regime_segmentation: { enabled: true, dimensions: ["risk_on_off"] },
    },
    ranking: {
      primary_metric: "out_of_sample_sharpe",
      secondary_metrics: ["profit_factor", "net_profit"],
    },
    acceptance_thresholds: {
      min_trade_count: 60,
      min_profit_factor: 1.05,
      max_drawdown_pct: 10.0,
      min_out_of_sample_sharpe: 0.6,
      min_holdout_profit_factor: 1.0,
    },
    outputs: {
      required: ["run_summary", "trade_blotter"],
      persist_artifacts: true,
    },
    notes: [],
  };
}

const STRATEGY_ID = "01HZ0000000000000000000001";

function renderModal(props?: { presetExperimentPlan?: ExperimentPlan; onClose?: () => void }): {
  onClose: ReturnType<typeof vi.fn>;
  rerender: (ui: ReactElement) => void;
} {
  const onClose = props?.onClose ? vi.fn(props.onClose) : vi.fn();
  const view = render(
    <RunBacktestModal
      open={true}
      onClose={onClose}
      strategyId={STRATEGY_ID}
      presetExperimentPlan={props?.presetExperimentPlan}
    />,
  );
  return { onClose, rerender: view.rerender };
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe("RunBacktestModal", () => {
  beforeEach(() => {
    mockNavigate.mockReset();
    mockSubmit.mockReset();
  });

  it("renders every section's required fields when open=true", () => {
    renderModal();

    // Header
    expect(screen.getByRole("dialog", { name: /execute backtest/i })).toBeInTheDocument();

    // Spot-check one field per fieldset to confirm full coverage.
    expect(screen.getByTestId("field-strategy_ref.strategy_name")).toBeInTheDocument();
    expect(screen.getByTestId("field-strategy_ref.strategy_version")).toBeInTheDocument();
    expect(screen.getByTestId("field-run_metadata.run_purpose")).toBeInTheDocument();
    expect(screen.getByTestId("field-run_metadata.owner")).toBeInTheDocument();
    expect(screen.getByTestId("field-run_metadata.random_seed")).toBeInTheDocument();
    expect(screen.getByTestId("field-data_selection.dataset_ref")).toBeInTheDocument();
    expect(screen.getByTestId("field-data_selection.dataset_version")).toBeInTheDocument();
    expect(screen.getByTestId("field-data_selection.spread_dataset_ref")).toBeInTheDocument();
    expect(screen.getByTestId("field-data_selection.calendar_ref")).toBeInTheDocument();
    expect(screen.getByTestId("field-cost_models.commission_model_ref")).toBeInTheDocument();
    expect(screen.getByTestId("field-cost_models.slippage_model_ref")).toBeInTheDocument();
    expect(screen.getByTestId("field-cost_models.swap_model_ref")).toBeInTheDocument();
    expect(screen.getByTestId("field-splits.in_sample.start")).toBeInTheDocument();
    expect(screen.getByTestId("field-splits.in_sample.end")).toBeInTheDocument();
    expect(screen.getByTestId("field-splits.out_of_sample.start")).toBeInTheDocument();
    expect(screen.getByTestId("field-splits.out_of_sample.end")).toBeInTheDocument();
    expect(screen.getByTestId("field-splits.holdout.start")).toBeInTheDocument();
    expect(screen.getByTestId("field-splits.holdout.end")).toBeInTheDocument();
    expect(screen.getByTestId("field-validation.walk_forward.enabled")).toBeInTheDocument();
    expect(
      screen.getByTestId("field-validation.walk_forward.train_window_months"),
    ).toBeInTheDocument();
    expect(screen.getByTestId("field-validation.monte_carlo.iterations")).toBeInTheDocument();
    expect(
      screen.getByTestId("field-validation.regime_segmentation.dimensions"),
    ).toBeInTheDocument();
    expect(screen.getByTestId("field-ranking.primary_metric")).toBeInTheDocument();
    expect(screen.getByTestId("field-ranking.secondary_metrics")).toBeInTheDocument();
    expect(screen.getByTestId("field-acceptance_thresholds.min_trade_count")).toBeInTheDocument();
    expect(screen.getByTestId("field-outputs.required")).toBeInTheDocument();
    expect(screen.getByTestId("field-outputs.persist_artifacts")).toBeInTheDocument();
    expect(screen.getByTestId("run-backtest-submit")).toBeInTheDocument();
  });

  it("disables the submit button until the plan passes client-side validation", () => {
    // Empty plan: submit must be disabled.
    renderModal();
    const submit = screen.getByTestId("run-backtest-submit") as HTMLButtonElement;
    expect(submit.disabled).toBe(true);
  });

  it("enables the submit button when a complete preset plan is supplied", () => {
    renderModal({ presetExperimentPlan: makeValidPlan() });
    const submit = screen.getByTestId("run-backtest-submit") as HTMLButtonElement;
    expect(submit.disabled).toBe(false);
  });

  it("submits the plan to /runs/from-ir and navigates to /runs/{run_id} on 201", async () => {
    const newRunId = "01HZ9999999999999999999999";
    mockSubmit.mockResolvedValueOnce({ run_id: newRunId, status: "pending" });

    const { onClose } = renderModal({ presetExperimentPlan: makeValidPlan() });

    fireEvent.click(screen.getByTestId("run-backtest-submit"));

    await waitFor(() => {
      expect(mockSubmit).toHaveBeenCalledTimes(1);
    });

    // Body shape matches the backend's _FromIrRequest exactly.
    expect(mockSubmit).toHaveBeenCalledWith(STRATEGY_ID, makeValidPlan());

    // Modal closes and we navigate to the run monitor.
    await waitFor(() => {
      expect(onClose).toHaveBeenCalledTimes(1);
      expect(mockNavigate).toHaveBeenCalledWith(`/runs/${newRunId}`);
    });
  });

  it("surfaces a backend 422 validation error inline (form banner + field message)", async () => {
    // Build an axios-error-shaped object that matches the runtime check
    // ``axios.isAxiosError(err)``. We import axios lazily and use its
    // ``AxiosError`` constructor so the type guard returns true.
    const { AxiosError } = await import("axios");
    const axiosErr = new AxiosError("Unprocessable Entity");
    axiosErr.response = {
      status: 422,
      statusText: "Unprocessable Entity",
      headers: {},
      // FastAPI shape: detail is a list of {loc, msg, type}.
      data: {
        detail: [
          {
            loc: ["body", "experiment_plan", "data_selection", "dataset_ref"],
            msg: "dataset reference rejected by backend",
            type: "value_error",
          },
        ],
      },
      config: { headers: {} } as never,
    };

    mockSubmit.mockRejectedValueOnce(axiosErr);

    renderModal({ presetExperimentPlan: makeValidPlan() });

    fireEvent.click(screen.getByTestId("run-backtest-submit"));

    await waitFor(() => {
      // Form-level banner shown.
      expect(screen.getByTestId("form-error")).toBeInTheDocument();
      // Field-level error pinned to the loc path.
      expect(screen.getByTestId("error-data_selection.dataset_ref")).toHaveTextContent(
        "dataset reference rejected by backend",
      );
    });

    // We did not navigate — submission failed.
    expect(mockNavigate).not.toHaveBeenCalled();
  });
});
