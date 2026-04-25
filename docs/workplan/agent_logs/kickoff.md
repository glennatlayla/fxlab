# FXLab Strategy Execution Buildout — Kickoff Log

**Source workplan:** `docs/workplan/2026-04-25-strategy-execution-agent-orchestration.md` (v2.3)
**Operator:** Glenn Johnson <glennrjohnson@gmail.com>

---

## Kickoff SHA

```
5d31e46ef3b690242acdb32a00e1cd71da97766b
```

Captured: 2026-04-25 (post Tranche M-prep verify-green commit).

Each agent reads this SHA at startup and rebases its working branch
off it. Per the kickoff checklist (`2026-04-25-strategy-execution-kickoff.md`
§3), this SHA represents the agreed starting point for the overnight
run; if any agent finds a divergent main HEAD, it halts and writes
to `BLOCKED.md`.

## Pre-flight status (as of kickoff SHA)

| # | Item | Status | Notes |
|---|---|---|---|
| 1 | Oanda fxpractice creds in .env | **BLOCKED** | Oanda signup site was unreachable on 2026-04-25 when operator attempted. Track E will fail fast at M4.E1 until OANDA_API_TOKEN / OANDA_ACCOUNT_ID / OANDA_ENVIRONMENT=fxpractice are set. Tracks A, B, C, D may proceed; integration gates M3.X1 and M3.X2 cannot pass without FX bars. |
| 2 | 7 locked defaults reviewed | **CONFIRMED** | Operator confirmed all 7 v2.1 defaults as-is on 2026-04-25. Agents do not pause on any of them. |
| 3 | Kickoff SHA captured | **DONE** | This file. |
| 4 | `make verify` green on main | **DONE** | Required Linux-clone bootstrap (python3.12-venv apt install, .venv creation, requirements-dev install, nodeenv + frontend npm install) plus the Tranche M-prep commit (`5d31e46`) to fix 3 pre-existing slip-throughs from Tranche L. |

## Locked defaults (operator-confirmed 2026-04-25)

| # | Topic | Default |
|---|---|---|
| 1 | FX data + broker | Oanda v20 — fxpractice → fxtrade |
| 2 | FX business calendar (M1.B5) | `pandas_market_calendars` 24/5 |
| 3 | `dataset_ref` syntax (M2.C2) | Existing string format (e.g. `fx-eurusd-15m-certified-v3`) |
| 4 | Phase 4 paper-trading start | Deferred; M5 stretch only if budget remains after M3.X2 |
| 5 | Coexistence with draft form | `source: "ir_upload" \| "draft_form"` flag on strategy record |
| 6 | Migrations | Alembic, agent-owned per-tranche |
| 7 | Backfill concurrency | Sequential |

If any agent reads a tranche referencing a "decision gate" (legacy
v1 phrasing), it consults this table and proceeds without pausing.
