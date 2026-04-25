/**
 * Tests for IrDetailView — the read-only Strategy IR detail renderer.
 *
 * The 5 production IRs under `Strategy Repo/` are loaded from disk at
 * test time and snapshotted; if the rendered HTML changes for any reason
 * (component layout edit, schema change, fixture drift) the snapshot
 * diff will surface that and force review.
 *
 * In addition to the 5 snapshot tests, this file includes targeted
 * behavioural assertions that verify:
 *   - an indicator id renders inside the indicators table
 *   - the exit-logic `same_bar_priority` ordering renders as a numbered
 *     list in the exact order declared in the IR
 */

import { readFileSync } from "node:fs";
import path from "node:path";
import { render } from "@testing-library/react";
import { describe, it, expect } from "vitest";
import { IrDetailView } from "./IrDetailView";
import type { StrategyIR } from "@/types/strategy_ir";

// ---------------------------------------------------------------------------
// Fixture loading
// ---------------------------------------------------------------------------

/**
 * Resolve the absolute path to a production IR file, relative to the
 * repo root. We compute the repo root by walking up from `process.cwd()`,
 * which is `frontend/` when vitest is invoked via `npx vitest`.
 */
function repoRoot(): string {
  const cwd = process.cwd();
  // Frontend tests run with cwd = `<repo>/frontend`.
  if (path.basename(cwd) === "frontend") return path.resolve(cwd, "..");
  return cwd;
}

function loadIr(relPath: string): StrategyIR {
  const full = path.join(repoRoot(), relPath);
  const raw = readFileSync(full, "utf8");
  // The on-disk JSON is the parsed-IR serialization. We trust the backend
  // Pydantic model as the source of truth; the cast simply reflects that
  // the file's shape matches the StrategyIR TS interface.
  return JSON.parse(raw) as StrategyIR;
}

const PRODUCTION_IRS: Array<{ name: string; relPath: string }> = [
  {
    name: "FX_DoubleBollinger_TrendZone",
    relPath:
      "Strategy Repo/fxlab_kathy_lien_public_strategy_pack/FX_DoubleBollinger_TrendZone.strategy_ir.json",
  },
  {
    name: "FX_MTF_DailyTrend_H1Pullback",
    relPath:
      "Strategy Repo/fxlab_kathy_lien_public_strategy_pack/FX_MTF_DailyTrend_H1Pullback.strategy_ir.json",
  },
  {
    name: "FX_SingleAsset_MeanReversion_H1",
    relPath:
      "Strategy Repo/fxlab_chan_next3_strategy_pack/FX_SingleAsset_MeanReversion_H1.strategy_ir.json",
  },
  {
    name: "FX_TimeSeriesMomentum_Breakout_D1",
    relPath:
      "Strategy Repo/fxlab_chan_next3_strategy_pack/FX_TimeSeriesMomentum_Breakout_D1.strategy_ir.json",
  },
  {
    name: "FX_TurnOfMonth_USDSeasonality_D1",
    relPath:
      "Strategy Repo/fxlab_chan_next3_strategy_pack/FX_TurnOfMonth_USDSeasonality_D1.strategy_ir.json",
  },
];

// ---------------------------------------------------------------------------
// Snapshot tests — one per production IR
// ---------------------------------------------------------------------------

describe("IrDetailView — production IR snapshots", () => {
  for (const fixture of PRODUCTION_IRS) {
    it(`renders ${fixture.name} stably`, () => {
      const ir = loadIr(fixture.relPath);
      const { container } = render(<IrDetailView ir={ir} />);
      expect(container.firstChild).toMatchSnapshot();
    });
  }
});

// ---------------------------------------------------------------------------
// Targeted behavioural assertions
// ---------------------------------------------------------------------------

describe("IrDetailView — content correctness", () => {
  it("renders every indicator id from the DoubleBollinger IR", () => {
    const ir = loadIr(PRODUCTION_IRS[0].relPath);
    const { getByTestId } = render(<IrDetailView ir={ir} />);
    const table = getByTestId("ir-indicators-table");
    for (const ind of ir.indicators) {
      expect(table.textContent).toContain(ind.id);
    }
    // Spot-check that the `bb_upper_2` Bollinger upper @ 2σ is present:
    expect(table.textContent).toContain("bb_upper_2");
    expect(table.textContent).toContain("bollinger_upper");
  });

  it("renders same_bar_priority entries in the exact declared order", () => {
    const ir = loadIr(PRODUCTION_IRS[2].relPath); // MeanReversion has 5 entries
    const { getByTestId } = render(<IrDetailView ir={ir} />);
    const block = getByTestId("ir-same-bar-priority");
    const items = Array.from(block.querySelectorAll("li")).map(
      (li) => li.textContent?.trim() ?? "",
    );
    expect(items).toEqual([
      "initial_stop",
      "catastrophic_zscore_stop",
      "primary_exit",
      "time_exit",
      "friday_close_exit",
    ]);
  });

  it("renders basket templates only when present", () => {
    const irWithBasket = loadIr(PRODUCTION_IRS[4].relPath); // TurnOfMonth
    const { queryByTestId, rerender } = render(<IrDetailView ir={irWithBasket} />);
    expect(queryByTestId("ir-section-basket-templates")).not.toBeNull();
    expect(queryByTestId("ir-basket-usd_short_tom_basket")).not.toBeNull();

    const irWithoutBasket = loadIr(PRODUCTION_IRS[0].relPath); // DoubleBollinger
    rerender(<IrDetailView ir={irWithoutBasket} />);
    expect(queryByTestId("ir-section-basket-templates")).toBeNull();
  });

  it("renders derived fields only when present", () => {
    const irWithDerived = loadIr(PRODUCTION_IRS[1].relPath); // MTF DailyTrend has fib_*
    const { getByTestId } = render(<IrDetailView ir={irWithDerived} />);
    const sec = getByTestId("ir-section-derived-fields");
    expect(sec.textContent).toContain("fib_38_long");
    expect(sec.textContent).toContain("fib_61_long");
  });
});
