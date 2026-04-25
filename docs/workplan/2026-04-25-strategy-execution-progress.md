# FXLab Strategy Execution Buildout — Progress Tracker

**Source:** `docs/workplan/2026-04-25-strategy-execution-agent-orchestration.md` (v2.1)
**Total milestones:** 27
**Started:** (not yet)

Per CLAUDE.md §16 Rule 3, this file is seeded from the source
workplan's Milestone Index — every milestone appears here even when
status is `NOT_STARTED`.

Per §16 Rule 4, phase completion requires
`source_count == done_count + open_count` AND `open_count == 0`.

---

## Track A — Schema + Compiler (critical path)

| ID     | Milestone                                  | Status      | Commit | Owner |
|--------|--------------------------------------------|-------------|--------|-------|
| M1.A1  | Pydantic schema for strategy_ir.json       | NOT_STARTED |        |       |
| M1.A2  | Reference resolver                         | NOT_STARTED |        |       |
| M1.A3  | IR → SignalStrategy compiler               | NOT_STARTED |        |       |
| M1.A4  | Lookback notation handler                  | NOT_STARTED |        |       |
| M1.A5  | Risk model + sizing translation            | NOT_STARTED |        |       |

## Track B — Indicator coverage (parallel after A1)

| ID     | Milestone                                  | Status      | Commit | Owner |
|--------|--------------------------------------------|-------------|--------|-------|
| M1.B1  | ADX                                        | NOT_STARTED |        |       |
| M1.B2  | z-score indicator                          | NOT_STARTED |        |       |
| M1.B3  | Rolling extremes                           | NOT_STARTED |        |       |
| M1.B4  | Rolling stddev                             | NOT_STARTED |        |       |
| M1.B5  | Calendar indicators (DECISION GATE)        | NOT_STARTED |        |       |
| M1.B6  | Derived-fields formula evaluator           | NOT_STARTED |        |       |

## Track C — API + run plumbing (after A3)

| ID     | Milestone                                  | Status      | Commit | Owner |
|--------|--------------------------------------------|-------------|--------|-------|
| M2.C1  | POST /strategies/import-ir                 | NOT_STARTED |        |       |
| M2.C2  | POST /runs/from-ir (DECISION GATE: dataset_ref syntax) | NOT_STARTED |        |       |
| M2.C3  | Results endpoints expansion                | NOT_STARTED |        |       |
| M2.C4  | Strategy detail with parsed IR             | NOT_STARTED |        |       |

## Track D — Frontend (parallel after C contracts)

| ID     | Milestone                                  | Status      | Commit | Owner |
|--------|--------------------------------------------|-------------|--------|-------|
| M2.D1  | "Load from repo" panel                     | NOT_STARTED |        |       |
| M2.D2  | IR detail view                             | NOT_STARTED |        |       |
| M2.D3  | "Run backtest" flow                        | NOT_STARTED |        |       |
| M2.D4  | Results viewer page                        | NOT_STARTED |        |       |

## Track E — Oanda data + broker (independent)

| ID     | Milestone                                  | Status      | Commit | Owner |
|--------|--------------------------------------------|-------------|--------|-------|
| M4.E1  | Oanda account + token verification         | NOT_STARTED |        |       |
| M4.E2  | OandaMarketDataProvider adapter            | NOT_STARTED |        |       |
| M4.E3  | Dataset versioning + DatasetService        | NOT_STARTED |        |       |
| M4.E4  | Backfill all six majors via Oanda          | NOT_STARTED |        |       |
| M4.E5  | OandaBrokerAdapter (fxpractice/fxtrade)    | NOT_STARTED |        |       |
| M4.E6  | Broker registry + selection                | NOT_STARTED |        |       |

## Cross-track integration gates

| ID     | Milestone                                  | Status      | Commit | Owner |
|--------|--------------------------------------------|-------------|--------|-------|
| M3.X1  | Single-strategy CLI backtest end-to-end    | NOT_STARTED |        |       |
| M3.X2  | Five strategies via UI (final acceptance)  | NOT_STARTED |        |       |

---

## Reconciliation (per §16 Rule 4, run before declaring phase complete)

```
source_count = 27            (from Milestone Index above; v2.1)
done_count   = ?             (count rows where status == DONE)
open_count   = ?             (count rows where status in {NOT_STARTED, IN_PROGRESS})
assert source_count == done_count + open_count
assert open_count == 0       (for completion declaration)
```
