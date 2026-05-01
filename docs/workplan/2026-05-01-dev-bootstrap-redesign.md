# Dev-Bootstrap Redesign — Fast Healthcheck vs Refresh

**Status:** DRAFT — awaiting operator review.
**Author:** Claude (assisted) under operator direction.
**Date:** 2026-05-01.
**Supersedes:** ad-hoc smart-skip in `scripts/bootstrap.sh` (commit `15a54cb`).

---

## 1. Problem Statement

`scripts/bootstrap.sh` currently fuses two unrelated jobs:

1. **Install / refresh** — heavy, slow, only needed when something has actually
   changed (pip install, npm install, frontend build, alembic migrations, full
   pytest unit suite).
2. **Health verification** — fast, must run every session start (postgres
   reachable, redis reachable, keycloak realm right, `.env` complete, alembic
   head matches DB).

The operator runs `start.sh` at the start of every dev session. Today this
costs ~35 minutes (pytest 32:30 + frontend build 53s + keycloak realm setup
+ alembic + smoke). That cost is paid even when literally nothing has changed
since the last green run.

The smart-skip on the pytest step (commit `15a54cb`) is a band-aid — the same
pattern (skip work when fingerprint is unchanged) applies to every heavy step,
and conflating "is the box healthy?" with "is the box installed?" is the
structural problem behind the symptoms.

Visible secondary bugs:

- Exit code 2 reported as `[err] scripts/bootstrap.sh failed` despite every
  step being OK or WARN. The exit-code policy treats WARN as failure.
- The "What's next" hint tells the operator to run `./scripts/bootstrap.sh`
  directly, contradicting the start.sh-only directive (CLAUDE.md §17).
- No way to inspect "what does the script think the system state is" without
  running the entire pipeline.

---

## 2. Design Goals

1. **One entry point.** Operator only ever invokes `./scripts/start.sh`.
   No public knowledge of `bootstrap.sh` or any other helper script.
2. **Default invocation is fast.** Session-start path completes in ≤10s when
   the box is healthy.
3. **Heavy work is auto-triggered when needed**, not on every invocation.
4. **Heavy work is opt-in via a single flag** when the operator wants to
   force a refresh.
5. **Idempotent in cost, not just correctness.** Re-running a green run
   does no work the second time.
6. **Honest exit codes.** Exit 0 = healthy, exit non-zero = something the
   operator must address. WARN is exit 0.
7. **Inspectable state.** A `start.sh --status` flag prints the current
   stamp/fingerprint state without running anything.

---

## 3. Architecture

### 3.1 Modes

`start.sh` operates in exactly one of three modes per invocation, decided
in this order:

| Mode | Trigger | Work performed |
|------|---------|----------------|
| `status` | `--status` | Print stamp/fingerprint state, exit 0 |
| `refresh` | `--refresh` flag, OR auto-trigger fires | Full install pipeline (today's `bootstrap.sh`) |
| `healthcheck` | default | Probes only — under 10s |

`start.sh` always runs the `git pull --ff-only` pre-flight first (existing
behaviour); the mode dispatch happens after the pull settles.

### 3.2 Auto-trigger for refresh mode

Refresh mode fires automatically when ANY of the following is true:

1. **No global refresh stamp** at `.git/fxlab-refresh.stamp`. (First run
   after clone.)
2. **A "structural" tracked file changed** since the last green refresh
   stamp:
   - `requirements.txt`, `requirements-dev.txt`, `pyproject.toml`
     (Python deps moved → must `pip install`).
   - `frontend/package.json`, `frontend/package-lock.json`
     (npm deps moved → must `npm install` and rebuild).
   - `alembic/versions/*.py` (new migration → must `alembic upgrade`).
   - `docker-compose*.yml` (compose stack changed → may need rebuild).
   - `scripts/bootstrap.sh` itself (the install logic changed).
   - `.env.example` (new required vars).
3. **Operator passes `--refresh`** explicitly.

If none of the above triggers, healthcheck mode runs.

The structural-change detection is a `git diff --name-only <stamp_sha>..HEAD`
plus a `git diff --name-only` for unstaged changes, intersected with the
glob list above. Cheap (one git call, ~50ms).

### 3.3 Healthcheck mode (`scripts/healthcheck.sh` — new)

Runs in parallel where safe. Each probe has a budget; total budget ≤10s.

| Probe | Budget | Failure semantics |
|-------|--------|-------------------|
| `.venv/` exists and `.venv/bin/python --version` works | 1s | refresh-required |
| `frontend/node_modules/` exists | 0.1s | refresh-required |
| `frontend/dist/` exists (last build present) | 0.1s | refresh-required |
| `.env` complete (key set match `.env.example` keys) | 0.5s | hard-fail (operator action) |
| postgres reachable (`pg_isready` against `DATABASE_URL`) | 2s | hard-fail (compose down?) |
| redis reachable (`redis-cli ping`) | 2s | hard-fail |
| keycloak realm reachable (HTTP GET on .well-known) | 2s | hard-fail |
| alembic head matches DB (`alembic current` vs `alembic heads`) | 3s | refresh-required |
| Last refresh stamp exists and is younger than 30 days | 0s | warn (suggest `--refresh`) |

**`refresh-required`** result: healthcheck prints what's missing and
auto-escalates into refresh mode. Operator does not need to re-invoke.

**`hard-fail`** result: healthcheck prints the failure and exits 1. The
operator likely needs to start the compose stack, fix `.env`, or similar —
refresh won't help.

### 3.4 Refresh mode

Today's `scripts/bootstrap.sh`, with these changes:

1. **Per-step fingerprints**, each gating its step. After a successful run
   of a step, write its stamp under `.git/fxlab-refresh-<step>.stamp`. On
   the next refresh, skip the step if its fingerprint matches.

   | Step | Fingerprint inputs | Stamp file |
   |------|--------------------|------------|
   | `make bootstrap` (pip + npm install) | sha256 of `requirements.txt` + `requirements-dev.txt` + `pyproject.toml` + `frontend/package.json` + `frontend/package-lock.json` | `python-deps.stamp`, `npm-deps.stamp` (separate so a frontend-only change doesn't reinstall pip) |
   | Compose up (postgres/redis/keycloak) | sha256 of `docker-compose*.yml` + `.env` keys-only | `compose.stamp` (skip if stack already healthy AND fingerprint matches) |
   | Keycloak realm setup | sha256 of `infra/keycloak/realm-fxlab.json` (or wherever the realm config lives) + `KEYCLOAK_*` env keys | `keycloak.stamp` |
   | Alembic migrations | `alembic heads` output (new migration ID changes the fingerprint) | `alembic.stamp` |
   | Pytest unit gate | existing fingerprint from `15a54cb` (HEAD + diff + untracked) | `tests.stamp` (rename from current name for consistency) |
   | Frontend build | sha256 of `frontend/src/**` + `frontend/package.json` + `frontend/vite.config.*` + `frontend/tsconfig*.json` | `frontend-build.stamp` |
   | Backend smoke | always run (it's the final go/no-go) | n/a |

   Stamps live under `.git/fxlab-refresh-*.stamp` — per-clone, never committed.

2. **Global refresh stamp** at `.git/fxlab-refresh.stamp` is updated only
   when ALL steps in the refresh pipeline finished green. Healthcheck mode
   reads this to know the last fully-green refresh.

3. **`--force` overrides every per-step fingerprint** (re-run every step
   regardless of cache). For surgical overrides: `--force-tests`,
   `--force-frontend-build`, `--force-deps`.

4. **The `bootstrap.sh` script becomes internal.** `start.sh` is the only
   caller. `bootstrap.sh`'s own help text and "What's next" block are
   updated to point at `start.sh`. Direct invocation still works (it's a
   shell script, can't be hidden), but is no longer documented.

### 3.5 Status mode (`start.sh --status`)

Prints a one-screen summary without running any check:

```
FXLab dev environment status (./scripts/start.sh --status)

Last refresh:        2026-05-01 14:23 UTC  (HEAD 15a54cb, 4h ago)
Refresh stamps:
  python-deps        ✓ matches  (last: 2026-05-01 14:23)
  npm-deps           ✓ matches  (last: 2026-05-01 14:23)
  compose            ✓ matches
  keycloak           ✓ matches
  alembic            ✓ matches  (head: 0042_user_schema)
  tests              ✓ matches
  frontend-build     ✗ STALE    (frontend/src/Strategy.tsx modified)

Next start.sh would: REFRESH  (frontend-build fingerprint changed)
Next start.sh ETA:  ~60s  (only frontend-build needs rerun)
```

This is the inspectable state surface. Crucial for debugging "why does
start.sh keep doing X?".

---

## 4. Exit-Code Policy

Single source of truth, applied uniformly across `start.sh`, healthcheck,
and refresh:

| Outcome per row in summary | Affects exit code? |
|----------------------------|---------------------|
| OK | exit 0 |
| SKIP | exit 0 |
| WARN | exit 0 (yellow flag in summary, no failure) |
| FAIL | exit 1 |

`start.sh` reduces all subprocess exit codes via OR — any FAIL anywhere
makes `start.sh` exit 1.

Today's behaviour where `validate-env` WARN causes exit 2 is incorrect and
must be removed. WARN means "we couldn't verify but it's not blocking";
the operator should see it but not be paged.

---

## 5. File Layout

```
scripts/
  start.sh              # entry point — pull, dispatch, status
  healthcheck.sh        # NEW — fast probes only
  bootstrap.sh          # refresh mode — internal, called by start.sh
  _lib.sh               # shared logging, summary, fingerprint helpers
  _fingerprint.sh       # NEW — extracted from bootstrap.sh, shared
  _stamps.sh            # NEW — read/write/compare per-step stamps
```

The `_fingerprint.sh` and `_stamps.sh` extraction lets healthcheck read
the same stamps that refresh writes, without duplicating logic.

---

## 6. start.sh Public Contract (Final)

```
$ ./scripts/start.sh --help
Usage: ./scripts/start.sh [OPTIONS]

By default: pulls origin (fast-forward only), then runs a fast healthcheck.
If healthcheck detects the box needs reinstall/migration/rebuild, it
auto-escalates into a refresh and runs only the steps that changed.

Options:
  --no-pull              Skip the git fetch + pull (just check / refresh).
  --refresh              Force refresh mode (ignore healthcheck result).
  --force                In refresh mode, ignore all per-step fingerprints
                         and run every step. Implies --refresh.
  --force-tests          In refresh mode, re-run pytest unit gate even if
                         fingerprint matches. Other steps still cached.
  --force-frontend-build In refresh mode, re-run frontend build only.
  --force-deps           In refresh mode, re-run pip + npm install only.
  --status               Print stamp/fingerprint state and exit. No work.
  --skip-tests           In refresh mode, do not run pytest gate at all.
  -h, --help             Show this help.

Exit codes:
  0  healthy (or refresh completed green)
  1  one or more checks failed; operator action required
```

No mention of `bootstrap.sh`, no mention of `healthcheck.sh`.

---

## 7. Migration Plan

Two commits, each green and reversible:

**Commit 1 — refactor without behavioural change:**
- Extract `_fingerprint.sh` and `_stamps.sh` from `bootstrap.sh`.
- Per-step stamps wired into bootstrap.sh (replace the single tests-only
  stamp with a per-step model).
- Fix WARN-as-FAIL exit-code bug.
- Update bootstrap.sh "What's next" block to point at `start.sh`.
- All existing flags continue to work.
- Verified by: existing run path produces identical output minus the
  exit-code fix.

**Commit 2 — introduce healthcheck and dispatch:**
- Add `scripts/healthcheck.sh`.
- Modify `start.sh` to dispatch: pull → healthcheck → (auto-escalate to
  refresh) | (print healthy + exit 0).
- Add `--refresh`, `--force`, `--status`, `--force-*` flags.
- Verified by:
  - `start.sh --status` on a green box prints all-green and exits 0.
  - `start.sh` on a green box completes in ≤10s.
  - `start.sh --refresh` runs the full pipeline.
  - `start.sh` after editing `frontend/src/X.tsx` auto-escalates and
    reruns only the frontend build step.

---

## 8. Test Plan

Bash-level tests under `tests/shell/`:

1. `test_healthcheck_green_exits_zero.sh` — given all probes pass, exit 0
   in under 10s.
2. `test_healthcheck_compose_down_exits_one.sh` — given compose stopped,
   healthcheck exits 1 with a clear message.
3. `test_auto_escalate_on_requirements_change.sh` — touch
   `requirements.txt`, run start.sh, assert refresh fires.
4. `test_per_step_fingerprint_skips.sh` — refresh twice in a row; second
   run skips every step.
5. `test_force_tests_overrides_skip.sh` — `--force-tests` makes pytest run
   even when fingerprint matches.
6. `test_status_no_work.sh` — `--status` invocation does not write any
   files, does not call docker, does not call pytest.
7. `test_warn_does_not_fail.sh` — induce a WARN in validate-env, assert
   exit 0.

---

## 9. Open Questions for Operator Review

1. **Healthcheck and untracked files.** Should an untracked test file
   trigger refresh? My instinct is no — untracked files are operator
   scratch. But if they touch `frontend/src/`, vite picks them up at
   `npm run dev`, so leaving them out of the build fingerprint is
   correct, but leaving them out of the test fingerprint may miss
   intended changes. Lean: track them like commit `15a54cb` does today.
2. **Stamp invalidation on branch switch.** When the operator switches
   branches, every fingerprint changes (HEAD differs, file content
   differs). That's correct. But the global refresh stamp going stale
   means even a `git checkout` between two known-green branches forces a
   refresh. Acceptable, but worth noting.
3. **Compose health probe vs compose-up step.** Healthcheck probes that
   compose services are up. Refresh's compose-up step ensures they are
   up. If healthcheck finds them down, it should auto-escalate to refresh
   (which brings them up). Confirm that's the right semantic, vs. a
   separate "start compose" path that doesn't drag in the rest of refresh.
4. **`scripts/bootstrap.sh` direct invocation.** Should it print a
   deprecation hint (`use ./scripts/start.sh instead`) but still work?
   Or refuse with a hard error? Lean: hint + work, since it's used by
   anyone who looked at past commit messages.
5. **Refresh stamp time-decay.** Should a stamp older than N days
   auto-invalidate? Argues for: external state drifts (postgres minor
   version, system packages). Argues against: operators on vacation
   shouldn't be punished. Lean: 30 days, configurable; warn but don't
   force.

---

## 10. What This Does NOT Do

- It does not change `install.sh` (production install). Production stays
  on its current Docker/systemd path.
- It does not change CI. CI continues to call `make test` directly; it
  doesn't go through `start.sh`.
- It does not change the production deploy path on minitux. The
  `make minitux-*` targets are unaffected.
- It does not change what gets tested or how — just when and how often.

---

## 11. Acceptance Criteria

This redesign is **DONE** when:

- [ ] On a green box, `./scripts/start.sh` completes in ≤10s.
- [ ] On a green box, `./scripts/start.sh --status` prints all stamps as
      matching and exits 0 in <1s with no side effects.
- [ ] After editing one frontend file, `./scripts/start.sh` runs ONLY the
      frontend-build step (skipping pytest, deps, alembic, etc.).
- [ ] After adding a new alembic migration, `./scripts/start.sh` runs
      ONLY the alembic step + dependent verifications.
- [ ] `./scripts/start.sh --refresh` runs the full pipeline regardless
      of fingerprints.
- [ ] WARN rows in the summary do not cause non-zero exit.
- [ ] `bootstrap.sh`'s "What's next" block points at `start.sh` only.
- [ ] All shell tests in §8 pass.
- [ ] Operator (glennrjohnson@gmail.com) signs off.
