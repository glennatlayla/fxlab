# FXLab Strategy Execution Buildout — Kickoff Checklist

**Source workplan:** `docs/workplan/2026-04-25-strategy-execution-agent-orchestration.md` (v2)
**Created:** 2026-04-25

---

## PURPOSE

This is the **only** document the operator (Glenn) must act on before
launching the five agents for the overnight run. Everything else is
either decided in the workplan itself or handled by the agents.

If you can complete this checklist, you can start the run.

---

## OPERATOR PRE-FLIGHT — required actions

### 1. Forex data API key (operator action)

- Go to <https://twelvedata.com/pricing>.
- Sign up for the **free tier**. No credit card required.
- Copy the API key from the dashboard.
- Add it to minitux's `.env` (and your dev-Mac smoke `.env` if you
  test locally) as:

  ```
  TWELVEDATA_API_KEY=your-real-key-here
  ```

- **Why this is required:** the Track E agent's first step is to
  verify this env var is set. Without it, the forex data adapter
  fails fast with a clear error and Track E blocks. The other four
  tracks proceed but cannot reach their M3.X1 integration gate
  without FX bars in the database.

- **If you'd rather not sign up for TwelveData** and prefer
  HistData.com CSVs only (slower backfill, more manual but truly
  zero-key):
  - Set `FXLAB_FOREX_PROVIDER=histdata` in `.env`.
  - The Track E agent will skip TwelveData and use HistData
    exclusively.

### 2. Confirm or override the locked defaults (operator review)

Open `docs/workplan/2026-04-25-strategy-execution-agent-orchestration.md`,
find the section "DEFAULTS LOCKED (v2 autonomy revision)", and skim
the seven defaults. If you want to change any, edit that table BEFORE
launching agents.

The defaults are:
1. Forex source: TwelveData primary, HistData fallback.
2. FX calendar: `pandas_market_calendars` 24/5.
3. dataset_ref syntax: existing string format.
4. Phase 4 paper trading: deferred (stretch only).
5. Coexistence with draft form: `source` flag.
6. Migrations: Alembic per-tranche.
7. Backfill concurrency: sequential.

If you change a default, update the rationale column too so the
agents can read your reasoning.

### 3. Capture the kickoff SHA (operator action)

Before launching any agent:

```bash
cd /Users/gjohnson/Documents/Coding\ Projects/fxlab     # or wherever your dev-Mac clone is
git checkout main
git pull origin main
git rev-parse HEAD                                       # capture this SHA
```

Write the SHA into `docs/workplan/agent_logs/kickoff.md` (the
agents will create this file if it doesn't exist; you can pre-seed
it). Each agent reads the SHA at startup and rebases its branch off
it.

### 4. Verify the dev-Mac is healthy (operator action)

```bash
cd /Users/gjohnson/Documents/Coding\ Projects/fxlab
make verify                                              # must be green
```

If `make verify` fails on main, fix it before launching agents.
Agents start by running `make verify` themselves and stop if it's
not green — a broken main poisons every track simultaneously.

### 5. Launch the five agents (operator action)

Use whatever orchestration platform you prefer (Claude Code Task
agents, your own subagent setup, separate terminal windows, etc.).
Each agent's launch command is identical except for the track letter:

```
Read docs/workplan/2026-04-25-strategy-execution-agent-orchestration.md
and docs/workplan/2026-04-25-strategy-execution-kickoff.md.

You are the agent for Track <X> (where X ∈ {A, B, C, D, E}).

Execute every tranche in your track in order, following the agent
coordination protocol exactly. Branch: agent/<X>. Commit per tranche.
Append progress to docs/workplan/agent_logs/<X>.md.

Do not ask the operator any questions. Use the locked defaults in
the workplan. If you encounter a true blocker that the workplan does
not resolve, follow the failure protocol — commit partial work,
write to agent_logs/BLOCKED.md, stop.

After your final tranche, do nothing else. The integration gates
M3.X1 and M3.X2 are run by a separate integration agent.

Begin.
```

### 6. (Optional) Launch an integration agent

After agents A, B, E reach their final tranches (or after all five
if you prefer), launch one more agent with this assignment:

```
Read the workplan. You are the integration agent. Run the M3.X1
gate, then M3.X2. Merge each track's branch to main in the order
specified in the workplan's "Branching" section. Resolve conflicts
per the rules. Run the e2e acceptance test. Append to
docs/workplan/agent_logs/integration.md.
```

If you do not launch an integration agent, run the integration
manually after wake-up.

---

## OPERATOR INACTION — what NOT to do

- **Don't prompt agents mid-run.** They are designed to run without
  human input. If you give one of them a clarification mid-run, it
  may diverge from the others.
- **Don't `git push` from the dev Mac while agents are running.**
  Wait until integration is complete. Agents push their own branches.
- **Don't restart minitux** while agents are running — the database
  has live state agents are reading and writing.
- **Don't manually edit files agents own.** See the file-ownership
  table in the workplan.

---

## SUCCESS CRITERIA AT WAKE-TIME

In order of priority:

1. **`docs/workplan/agent_logs/BLOCKED.md` does not exist or is empty.**
2. **`docs/workplan/agent_logs/integration.md` shows M3.X2 = DONE.**
3. **Browser flow:** Strategy Studio → Import → Backtest → Results
   works for FX_TimeSeriesMomentum_Breakout_D1.
4. **`make verify` on the dev Mac is green** after agents merge.

If 1-3 are true, you have a viable candidate for testing — the
"hard floor" of the M3.X2 acceptance. Stretch goals (other 4
strategies, walk-forward, Monte Carlo, paper trading) may or may
not have landed; the track logs tell you.

---

## ESTIMATED RUN TIME

| Phase | Duration |
|---|---|
| Five agents kickoff to M3.X1 | 6–8 hours |
| Forex backfill (Track E, sequential) | 4–6 hours (parallel with above) |
| M3.X1 → M3.X2 integration | 1–2 hours |
| **Total wall-clock to hard floor** | **~8–10 hours** |
| Stretch tranches (if budget remains) | +2–6 hours |

Overnight (12 hours) is comfortable for hard floor. A long sleep
(16+ hours) gives stretch tranches room.

---

## WHAT TO REVIEW IN THE MORNING

See the workplan's **WAKE-TIME REVIEW PROTOCOL FOR GLENN** section.
Six steps, ~5 minutes if green, longer if red.

---

## END

If this checklist is done, you can start the run. Anything not on
this checklist is not your problem — it's the agents' problem,
specified in the workplan.
