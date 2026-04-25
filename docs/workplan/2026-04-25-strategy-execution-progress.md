# FXLab Strategy Execution Buildout — Progress Tracker

**Source:** `docs/workplan/2026-04-25-strategy-execution-agent-orchestration.md` (v2.3)
**Total milestones:** 28
**Started:** (not yet)

Per CLAUDE.md §16 Rule 3, this file is seeded from the source
workplan's Milestone Index — every milestone appears here even when
status is `NOT_STARTED`.

Per §16 Rule 4, phase completion requires
`source_count == done_count + open_count` AND `open_count == 0`.

---

## Track A — Schema + Compiler (critical path)

| ID     | Milestone                                  | Status      | Commit  | Owner       |
|--------|--------------------------------------------|-------------|---------|-------------|
| M1.A1  | Pydantic schema for strategy_ir.json       | DONE        | c64ab96 | orchestrator |
| M1.A2  | Reference resolver                         | DONE        | c684dd2 | orchestrator |
| M1.A3  | IR → SignalStrategy compiler               | DONE        | 3a3e453 | orchestrator |
| M1.A4  | Lookback notation handler                  | DONE        | 59b05a2 | orchestrator |
| M1.A5  | Risk model + sizing translation            | DONE        | ca96e3e | orchestrator |

A4+A5 compiler integration: `049e1dd`.

## Track B — Indicator coverage (parallel after A1)

| ID     | Milestone                                  | Status      | Commit  | Owner       |
|--------|--------------------------------------------|-------------|---------|-------------|
| M1.B1  | ADX                                        | DONE        | 0eedc82 | orchestrator |
| M1.B2  | z-score indicator                          | DONE        | 31ba84b | orchestrator |
| M1.B3  | Rolling extremes                           | DONE        | 50b604c | orchestrator |
| M1.B4  | Rolling stddev                             | DONE        | d7a5f68 | orchestrator |
| M1.B5  | Calendar indicators (resolved → mcal 4.x)  | DONE        | 6a204fb | orchestrator |
| M1.B6  | Derived-fields formula evaluator           | DONE        | 3701d87 | orchestrator |

Track B integration commit (default_registry wiring): `d11c83c`.

## Track C — API + run plumbing (after A3)

| ID     | Milestone                                  | Status      | Commit  | Owner       |
|--------|--------------------------------------------|-------------|---------|-------------|
| M2.C1  | POST /strategies/import-ir                 | DONE        | a4169c3 | orchestrator |
| M2.C2  | POST /runs/from-ir                         | DONE        | c43205f | orchestrator |
| M2.C3  | Results endpoints expansion                | DONE        | d8737d0 | orchestrator |
| M2.C4  | Strategy detail with parsed IR             | DONE        | e49a217 | orchestrator |

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
| M3.X1.5| Single Engine Mode Parity Test             | NOT_STARTED |        |       |
| M3.X2  | Five strategies via UI (final acceptance)  | NOT_STARTED |        |       |

---

## Reconciliation (per §16 Rule 4, run before declaring phase complete)

```
source_count = 28            (from Milestone Index above; v2.3)
done_count   = ?             (count rows where status == DONE)
open_count   = ?             (count rows where status in {NOT_STARTED, IN_PROGRESS})
assert source_count == done_count + open_count
assert open_count == 0       (for completion declaration)
```
