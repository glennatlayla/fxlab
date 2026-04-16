# FXLab Minitux Install Failure — Remediation Plan v2

**Date:** 2026-04-15
**Author:** Claude (remediation session)
**Status:** PROPOSED — awaiting Glenn's approval before any code changes

---

## Why v2 Exists

The v1 remediation plan (12 commits: B1–B3, D1–D4, C1–C2, N1–N3) was
developed and committed in-sandbox with passing unit and YAML-contract
tests. When install.sh ran on minitux, five of the six distinct failure
symptoms persisted or were new. Post-mortem deep dive identified two
structural failures in v1's approach:

1. **Verification gap.** Every v1 commit was validated by sandbox unit
   tests. None was validated by a real-container smoke test. The
   `feedback_install_smoke_required` memory explicitly required this and
   was not followed.

2. **Deployment gap.** install.sh in `INSTALL_MODE=fresh` with an
   existing `.git` directory skips `pull_latest()` (line 1328–1331).
   Minitux had the repo pre-cloned, so install.sh built from the stale
   checkout, not from the branch tip containing the v1 fixes. N1, N2,
   N3, and C2 likely never ran on minitux.

v2 addresses both the original symptoms AND these structural failures.

---

## Complete Issue Inventory (minitux install log 2026-04-15)

| # | Severity | Symptom | Root Cause | v1 Status |
|---|----------|---------|------------|-----------|
| 1 | BLOCKER | `CorsOriginPolicyError` on `http://192.168.1.5` at module import → uvicorn respawn loop | C2 validator fires at import time (not lifespan); install.sh sets `ENVIRONMENT=production` + auto-detects LAN HTTP origins; `CorsOriginPolicyError` subclasses `RuntimeError` not `ConfigError` so exit(3) handler never catches it | **v1 INTRODUCED this bug** |
| 2 | HIGH | node-exporter "connection reset by peer" flood in Prometheus | N2 compose changes committed but never deployed (install.sh skipped `pull_latest`) | v1 fix exists but didn't deploy |
| 3 | HIGH | cadvisor prints usage/help text and exits | N1 compose changes committed but never deployed (same deployment gap) | v1 fix exists but didn't deploy |
| 4 | MEDIUM | postgres `sh: locale: not found` / `no usable system locales were found` | Different warning than N3 fixed. Alpine musl doesn't ship the `locale` binary; postgres entrypoint probes it. N3's `LANG=C.UTF-8` + `--locale=C.UTF-8` fix is correct for the `en_US.UTF-8 is not installed` warning but doesn't suppress the `locale` binary probe. | v1 fix is correct for its target; residual noise is a separate cosmetic issue |
| 5 | BLOCKER | install.sh fresh-mode with pre-cloned repo deploys stale code | `INSTALL_MODE=fresh` + existing `.git` → skip clone, skip `pull_latest()` → builds whatever commit is on disk | **Not in v1 scope — structural gap** |
| 6 | HIGH | Module-import-time crash bypasses lifespan exit(3) → infinite uvicorn respawn | `CorsOriginPolicyError` inherits `RuntimeError`; lifespan catch block only handles `ConfigError`; crash happens before lifespan runs anyway because validation is at module scope | **v1 architectural error** |

---

## Remediation Phases (execution order)

### Phase 0 — Verify deployment state (0 code changes, 5 minutes)

**Goal:** Confirm whether N1/N2/N3 code actually ran on minitux.

**Action:** Glenn runs on minitux:
```bash
cd /opt/fxlab && git log --oneline -5
docker inspect fxlab-cadvisor --format '{{.Config.Cmd}}' 2>/dev/null
docker inspect fxlab-node-exporter --format '{{.Config.Cmd}}' 2>/dev/null
docker inspect fxlab-postgres --format '{{.Config.Env}}' 2>/dev/null
```

**Expected outcome:** If `git log` shows commits older than the N1/N2/N3
series, the deployment gap is confirmed and Phase 1 is the critical path.
If the commits ARE present and the containers still fail, the v1
diagnoses were wrong and we need to re-diagnose from container logs.

**This phase gates everything else.** Do not proceed to code changes
until we know what minitux is actually running.

---

### Phase 1 — Fix the deployment gap in install.sh (1 commit)

**Problem:** `INSTALL_MODE=fresh` with a pre-existing `.git` directory
(lines 1327–1335) skips both `clone_repo()` and `pull_latest()`. The
operator gets "Repository already cloned — skipping clone" and the build
uses whatever commit was last checked out, which may be days or weeks old.

**Fix:** When `.git` exists in fresh mode, call `pull_latest()` to
fetch+reset to the branch tip before building. The log message changes
from "skipping clone" to "Repository exists — pulling latest from
{FXLAB_BRANCH}."

**Code change:** install.sh lines 1328–1331:
```bash
# BEFORE (broken):
if [[ -d "${FXLAB_HOME}/.git" ]]; then
    log INFO "Repository already cloned at ${FXLAB_HOME} — skipping clone."

# AFTER (fixed):
if [[ -d "${FXLAB_HOME}/.git" ]]; then
    log INFO "Repository already cloned at ${FXLAB_HOME} — pulling latest."
    pull_latest
```

**Test:** The install.sh script has a source-guard at line 1349–1352
(`if [[ "${BASH_SOURCE[0]}" == "${0}" ]]`) which means functions can be
sourced and tested individually. Write a shell test that:
- Creates a temp git repo with a known commit
- Adds a second commit on origin
- Runs the fresh-mode path with existing `.git`
- Asserts HEAD matches origin tip, not the stale commit

**Why this is Phase 1:** Until the deployment pipeline delivers code to
the host, every other fix is academic. This is the cheapest change with
the highest leverage.

---

### Phase 2 — Move CORS validation to lifespan + fix error hierarchy (1 commit)

**Problem (two layers):**

2a. `_validate_cors_origins()` is called at module scope (main.py line
1436). This means it fires during `import services.api.main`, before
FastAPI's lifespan runs, before the `ConfigError → exit(3)` handler is
active. Any exception here is an unhandled import-time crash.

2b. `CorsOriginPolicyError` subclasses `RuntimeError`, not `ConfigError`.
Even if the validator ran inside lifespan, the exit(3) handler at line
1257 only catches `ConfigError`. The exception would still escape.

**Fix:**

1. Make `CorsOriginPolicyError` a subclass of `ConfigError` (from
   `libs.contracts.errors`), not `RuntimeError`. This is the correct
   taxonomy: a CORS policy violation IS a configuration error.

2. Move the entire CORS validation block (lines 1420–1454) into the
   lifespan function, as a new startup phase:
   ```python
   with _startup_phase("cors_origin_policy"):
       _validate_cors_origins(
           origins=_cors_origins,
           environment=os.environ.get("ENVIRONMENT", ""),
           allow_plaintext_lan=_cors_allow_plaintext_lan,
           plaintext_justification=_cors_plaintext_justification,
       )
   ```
   The `_cors_origins` list and the `app.add_middleware(CORSMiddleware, ...)`
   registration stay at module scope — they don't raise. Only the
   policy enforcement moves.

3. Update the `CorsOriginPolicyError` docstring to accurately describe
   the error flow (it currently claims lifespan catches it, which was
   false).

**Test updates:**
- Existing `test_cors_production_enforcement.py` tests call
  `_validate_cors_origins()` directly — those stay unchanged.
- Add a new test: import `app`, confirm that `CorsOriginPolicyError`
  is a subclass of `ConfigError`.
- Add a test that verifies `_validate_cors_origins` is NOT called at
  module import time (mock it, import the module, assert not called).

**Why Phase 2:** This is the current BLOCKER — the api container cannot
start on minitux. Must be fixed before any other service-level
verification is possible.

---

### Phase 3 — Fix install.sh environment designation for LAN installs (1 commit)

**Problem:** `.env.production.template` hardcodes `ENVIRONMENT=production`
(line 41). install.sh copies this template to `.env` during `setup_env()`.
install.sh then auto-detects CORS origins as `http://{LAN_IP},...`
(lines 568–584). The combination — production environment + LAN HTTP
origins — is exactly what C2's validator rejects.

The project memory (`project_environment_designation.md`) designates
minitux as development and only the future Azure cluster as production.
install.sh should respect this.

**Fix:** Add environment detection to install.sh's `setup_env()`:
```bash
# Detect LAN-only install vs cloud/public install.
# If the server's primary IP is RFC 1918 (10.x, 172.16-31.x, 192.168.x),
# default ENVIRONMENT to "development" unless explicitly overridden.
local server_ip
server_ip="$(hostname -I 2>/dev/null | awk '{print $1}')" || server_ip="localhost"

if [[ -z "${ENVIRONMENT:-}" ]]; then
    if [[ "$server_ip" =~ ^(10\.|172\.(1[6-9]|2[0-9]|3[01])\.|192\.168\.) ]]; then
        log INFO "Detected private/LAN IP (${server_ip}) — defaulting ENVIRONMENT=development."
        log INFO "Override with ENVIRONMENT=production if this is a production deployment."
        sed -i "s|^ENVIRONMENT=.*|ENVIRONMENT=development|" "$env_file"
    else
        log INFO "Detected public IP (${server_ip}) — ENVIRONMENT=production."
    fi
fi
```

This aligns install.sh with the project's designation policy: LAN hosts
get development mode by default (C2 skips enforcement), public-IP hosts
get production mode (C2 enforces HTTPS + non-private origins).

Operators can still force `ENVIRONMENT=production` on a LAN host by
setting it before running install.sh — the detection only fires when
unset.

**Test:** Shell test that:
- Mocks `hostname -I` to return `192.168.1.5` → asserts `.env` gets
  `ENVIRONMENT=development`
- Mocks `hostname -I` to return `20.42.0.50` → asserts `.env` keeps
  `ENVIRONMENT=production`
- Sets `ENVIRONMENT=production` in env before running → asserts no
  override (explicit wins)

**Why Phase 3:** With Phase 2 moving CORS validation to lifespan and
Phase 3 setting the right ENVIRONMENT, minitux stops hitting the C2
policy entirely. The combination eliminates the BLOCKER.

---

### Phase 4 — Re-verify N1/N2/N3 on minitux after deployment fix (0 code changes)

**Goal:** With Phase 1 fixing the deployment gap, re-run install.sh on
minitux and confirm:

- cadvisor starts without usage-text dump (N1 fix lands)
- node-exporter serves metrics without RST flood (N2 fix lands)
- postgres boot log shows no `en_US.UTF-8` warning (N3 fix lands)
- postgres boot log may still show `sh: locale: not found` (known
  cosmetic, see Phase 6)

**Action:** Glenn runs:
```bash
sudo -E bash install.sh  # or: INSTALL_MODE=update sudo -E bash install.sh
docker compose -f docker-compose.prod.yml logs --tail=50 cadvisor
docker compose -f docker-compose.prod.yml logs --tail=50 node-exporter
docker compose -f docker-compose.prod.yml logs --tail=50 postgres
```

**If N1/N2/N3 hold:** Move to Phase 5.
**If any still fail:** The v1 diagnosis was wrong for that service. We
re-diagnose from real container logs, not from assumption. That becomes
a new fix commit with a real-container-verified test.

---

### Phase 5 — Add install-smoke Make target (1 commit)

**Problem:** Every v1 commit was verified by sandbox tests that parse
YAML or call Python functions. None verified that the changes work in a
running container. This is the structural gap that let us ship five
commits that didn't survive contact with minitux.

**Fix:** Create `make install-smoke` target that:
1. Runs `docker compose -f docker-compose.prod.yml up -d`
2. Waits for healthchecks (with timeout)
3. Verifies each service responds:
   - `curl http://localhost:8000/health` (api)
   - `curl http://localhost:9100/metrics` (node-exporter)
   - `curl http://localhost:8080/healthz` (cadvisor)
   - `pg_isready` via docker exec (postgres)
   - `redis-cli ping` via docker exec (redis)
4. Checks `docker compose logs` for zero CRITICAL/ERROR lines
5. Tears down

This becomes a **required gate** for any commit that touches
docker-compose.prod.yml, install.sh, Dockerfiles, or lifespan code.

**Why Phase 5 (not earlier):** The smoke test needs the deployment fix
(Phase 1) and the CORS fix (Phase 2) to exist before it can pass. But
once it exists, it retroactively validates everything.

---

### Phase 6 — Document postgres `locale` binary residual (1 commit, cosmetic)

**Problem:** postgres:15-alpine's entrypoint script calls the `locale`
binary to probe the system locale. Alpine musl doesn't ship `locale`.
This produces:

```
sh: locale: not found
warning: no usable system locales were found
```

This is distinct from the N3 warning (`the locale "en_US.UTF-8" is not
installed`), which N3 correctly fixed by setting `LANG=C.UTF-8`.

**Options (Glenn's call):**
- **Option A:** Accept the noise, add a comment in docker-compose.prod.yml
  documenting it as known-cosmetic, and add a test asserting the comment
  exists (prevents silent removal).
- **Option B:** Add `RUN apk add --no-cache musl-locales` to a custom
  postgres Dockerfile that extends `postgres:15-alpine`. This installs
  the `locale` binary and silences the warning, but adds a custom image
  build step.
- **Option C:** Suppress the entrypoint probe by overriding the
  entrypoint with a wrapper that sets `LANG=C.UTF-8` before calling the
  original. More invasive than Option A, less than Option B.

**Recommendation:** Option A. The warning is cosmetic, the locale is
correctly pinned, and adding a custom Dockerfile for postgres introduces
build complexity that isn't justified by a harmless startup message.

---

## Commit Sequence

| Order | Phase | Scope | Files | Test Type |
|-------|-------|-------|-------|-----------|
| 1 | Phase 1 | install.sh fresh-mode pull | install.sh | Shell test |
| 2 | Phase 2 | CORS to lifespan + error hierarchy | main.py, errors.py, test_cors_*.py | Unit test |
| 3 | Phase 3 | install.sh env detection | install.sh, .env.production.template | Shell test |
| 4 | Phase 4 | Verification gate | (no code) | Real-container on minitux |
| 5 | Phase 5 | install-smoke target | Makefile, tests/smoke/ | Integration |
| 6 | Phase 6 | Postgres locale docs | docker-compose.prod.yml | Contract test |

**Total new commits:** 4 code + 1 documentation/cosmetic
**Total verification gates:** 2 (Phase 0 before any code, Phase 4 after
deployment fix lands)

---

## What This Plan Does NOT Cover

These items from v1 are believed to be correctly implemented and will be
re-verified in Phase 4 rather than re-implemented:

- **B1** (Redis keepalive) — not implicated in install log
- **B2** (Redis retry backoff) — not implicated in install log
- **B3** (Container cascade depends_on) — not implicated in install log
- **D1–D4** (Diagnostic improvements) — not implicated in install log
- **C1** (sslmode enforcement) — not implicated in install log
- **N1** (cadvisor flags) — believed correct, blocked by deployment gap
- **N2** (node-exporter flags) — believed correct, blocked by deployment gap
- **N3** (postgres locale) — confirmed correct for its target symptom

If Phase 4 reveals that any of these did NOT hold on real hardware, they
become new fix commits inserted before Phase 5.

---

## Structural Guarantees (preventing a v3)

1. **No commit touching compose/installer/lifespan ships without
   install-smoke** (Phase 5 creates the gate).
2. **install.sh always pulls latest in fresh mode** (Phase 1 closes the
   deployment gap).
3. **All startup validators run inside lifespan, not at module scope**
   (Phase 2 establishes the pattern; any future validator follows it).
4. **LAN installs default to development** (Phase 3 aligns installer
   with project designation policy).
5. **Phase 0 and Phase 4 are human-verified gates** — not sandbox
   proxies. The operator confirms on the real host.
