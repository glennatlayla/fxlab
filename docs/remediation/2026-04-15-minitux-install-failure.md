# Remediation Plan — `fxlab-reinstall.sh` failure on minitux (2026-04-15)

## Scope

Addresses every issue enumerated from the minitux install log:

- **Blockers**: B1 (redis setsockopt EINVAL), B2 (no retry on transient redis failure), B3 (container cascade on api unhealthy)
- **Diagnostics**: D1 (uvicorn respawn loop), D2 (misleading ConfigError message), D3 (redis health phase logging gap), D4 (interleaved install logs)
- **Config / policy smells**: C1 (`sslmode=prefer` escapes prod secret validation), C2 (CORS origins auto-detected as plaintext LAN)
- **Noise**: N1 (cadvisor `--help`), N2 (node-exporter reset-by-peer flood), N3 (postgres locale warning)
- **Process**: P1 (declared "no regressions" from sandbox tests), P2 (jumped to first error in log), P3 (phase logging gap I introduced myself)

## Exit criterion

`./fxlab-reinstall.sh` on minitux completes with every compose service reporting `healthy`, API `/healthz` and `/readyz` returning 200, and `docker compose logs api` containing the full chain of `startup.phase_begin` → `phase_complete` events and zero `phase_failed`.

**No individual fix is "done" until its behaviour is exercised against a real Redis container and a real PostgreSQL container — unit tests alone are not sufficient (see P-track).**

---

## Ordering principle

Commit-sized units, ordered by what unblocks the install first. Each unit is RED → GREEN → REFACTOR per CLAUDE.md §5. Each unit has a verification criterion that would have failed BEFORE the fix — that is the only test worth writing.

---

## Commit 1 — B1: Redis keepalive options rejected by kernel 6.17

### Root cause

`services/api/infrastructure/redis_health.py` lines 101-104:

```python
socket_keepalive=True,
socket_keepalive_options={
    1: 1,  # TCP_KEEPIDLE
    2: 1,  # TCP_KEEPINTVL
},
```

Two defects:

1. Magic integer keys (`1`, `2`) instead of `socket.TCP_KEEPIDLE` / `socket.TCP_KEEPINTVL`. These values are correct on Linux x86_64 by coincidence, but unreadable and portable only by accident.
2. **Value `1` second** is below what the Linux 6.17 kernel accepts for TCP_KEEPIDLE / TCP_KEEPINTVL in Docker's default network namespace. `setsockopt(IPPROTO_TCP, TCP_KEEPIDLE, 1)` returns `EINVAL` (errno 22), which bubbles up as `OSError: [Errno 22] Invalid argument` → `redis.ConnectionError("Error 22 connecting to redis:6379")` → our wrapper converts it to the misleading `ConfigError("Cannot connect to Redis... Ensure Redis is running")`.

Redis is actually running and reachable. The client-side socket setup crashes before the first PING.

### Decision required from user before coding

**Two viable fixes — I need your call (infra decision, per your "ask first" rule):**

| Option | Behaviour | Trade-off |
|---|---|---|
| **A (recommended)** | Drop `socket_keepalive_options` entirely. Keep `socket_keepalive=True` so the OS applies its own tuned defaults (typically 7200 s idle, 75 s intvl, 9 probes). | Simpler, portable across kernels, still gives keepalive detection. Loses the aggressive "detect dead peer in ~2 s" behaviour we never actually relied on. |
| **B** | Use `socket.TCP_KEEPIDLE`, `socket.TCP_KEEPINTVL`, `socket.TCP_KEEPCNT` with kernel-sane values (e.g., `60, 30, 3`). | Explicit; keeps aggressive tuning; still portable by importing symbols; matches what the comment in code implied was intended. |

Both are production-grade. Option A is the smaller attack surface. Option B preserves intent.

### TDD

RED first: `tests/integration/test_redis_health_real_container.py::test_verify_redis_connection_against_real_redis_succeeds` — spins up a redis:7 container (testcontainers-python or docker-compose fixture), calls `verify_redis_connection`, asserts success. **This test fails today** on a 6.17-host because of the bug we are fixing. It is the proof B1 is fixed.

Unit test: `test_verify_redis_connection_does_not_pass_invalid_keepalive_values` — inspect the kwargs passed to `redis.Redis.from_url` (via `patch`) and assert we do not pass any `socket_keepalive_options` with sub-kernel-minimum values.

### Verification criterion

- Integration test green against real redis container on Linux 6.17.
- `docker compose up api` on minitux reaches `startup.phase_complete phase=redis_health_check`.

---

## Commit 2 — D3: Fill the phase-logging gap around Redis health check

### Root cause (my defect)

In commit `cb4814b` I wrapped pydantic init, secret validation, periodic reconciliation, and LiveExecutionService wiring in `_startup_phase(...)` blocks, but I did NOT wrap `verify_redis_connection(...)`. That is why the minitux log showed a raw stack trace to stderr instead of a `startup.phase_failed phase=redis_health_check ...` structured event. Phase logging is only valuable if it covers every phase that can fail at startup. It doesn't.

### Fix

Wrap the redis health call in `_startup_phase("redis_health_check", redis_url_scheme=...)`. Same for any other pre-lifespan check I missed: DB migration gate, filesystem writability check, artifact store probe. I will audit lifespan top-to-bottom and list them inline in the commit message.

### TDD

Extend `tests/unit/test_api_startup_phases.py::TestPeriodicReconciliationBlockIsolation`-style structural test: assert that the source of `services/api/main.py` contains `phase="redis_health_check"` inside an active `_startup_phase(` call, not merely as a string somewhere.

Add a regex test that enumerates every top-level `try:` or external-IO call in lifespan and asserts each has an enclosing `_startup_phase(`. Failure list is printed so the next gap is named by the test, not discovered on install.

### Verification criterion

Install on minitux (with B1 still broken for a moment) produces `{"event":"startup.phase_failed","phase":"redis_health_check",...}` in JSON logs instead of a bare traceback. Then B1 fix flips it to `phase_complete`.

---

## Commit 3 — D2: Stop lying in the error message when the cause is client-side

### Root cause

`redis_health.py` line 129-133:

```python
raise ConfigError(
    f"Cannot connect to Redis at {_strip_credentials(redis_url)}. "
    f"Error: {str(exc)}. "
    f"Ensure Redis is running and reachable. "
    f"Check REDIS_URL environment variable."
) from exc
```

`redis.ConnectionError` fires for client-side setup failures (setsockopt, SSL handshake, DNS) — not just unreachable servers. Telling an operator "ensure Redis is running" when Redis is running is the reason the minitux debug took as long as it did.

### Fix

Inspect the underlying `OSError.errno` and the exception chain. Three branches:

- `errno == ECONNREFUSED`, `EHOSTUNREACH`, `ETIMEDOUT`, or DNS failure → keep current "ensure Redis is running" copy.
- `errno == EINVAL`, `ENOPROTOOPT`, or any other local kernel/syscall error → new message: "Redis client configuration rejected by the local kernel/socket layer (errno=X). This is a client-side defect, not a Redis availability problem. Check keepalive / SSL options."
- SSL-related (`ssl.SSLError`) → its own branch.

No bare `except Exception` catch-all re-wrapping into a single message.

### TDD

Unit: inject fake `redis.Redis.from_url` that raises `OSError(22, "Invalid argument")`. Assert `ConfigError.args[0]` contains the words "client-side defect" and `errno=22`. Second case: inject `ConnectionRefusedError`. Assert message contains "ensure Redis is running".

### Verification criterion

If B1 regresses in the future (kernel change, new option, etc.), the operator log on minitux will state the actual nature of the failure without requiring a human to decode a libc errno.

---

## Commit 4 — B2: Retry transient Redis failures before failing startup

### Root cause

Redis is sometimes slow to accept connections on a cold `docker compose up` (the container is up, PING responds, but for ~1-3 s at the start it intermittently drops first connect). Per CLAUDE.md §9, transient failures (`redis.TimeoutError`, `redis.ConnectionError` where `errno in {ECONNRESET, ECONNREFUSED, ETIMEDOUT}`) must retry with exponential backoff. Current code fails on first attempt.

### Fix

Introduce `verify_redis_connection(..., max_retries=5, backoff_base_seconds=1.0, backoff_max_seconds=16.0)`. Retry only on transient subset. Never retry on auth (`NOAUTH`, `WRONGPASS`), version-too-old, or client-side (EINVAL). Log each attempt with `attempt`, `delay_seconds`, `error_type`. After final failure, raise the post-D2 differentiated `ConfigError`.

Retry policy values: `1 s, 2 s, 4 s, 8 s, 16 s` (matches §9). Max total wait: ~31 s. Configurable via env `REDIS_HEALTH_MAX_RETRIES` / `REDIS_HEALTH_BACKOFF_MAX_SECONDS`.

### TDD

- `test_verify_redis_connection_retries_on_transient_connection_error` — fake client raises `ConnectionRefusedError` twice then succeeds; assert 3 attempts, assert `startup.redis.retry_attempt` events emitted with correct `attempt` and `delay_seconds`.
- `test_verify_redis_connection_does_not_retry_on_auth_error` — fake client raises `redis.AuthenticationError`; assert exactly 1 attempt, `ConfigError` raised immediately.
- `test_verify_redis_connection_does_not_retry_on_client_side_einval` — guards against undoing Commit 3's classification.

### Verification criterion

Integration: cold-start compose stack, timing the API container to come up concurrently with redis. Before fix: intermittent fail. After fix: always succeeds within the retry window.

---

## Commit 5 — D1: Kill the uvicorn silent respawn loop on lifespan failure

### Root cause

`install.sh` / the compose `api` service runs uvicorn with a policy that respawns on crash. FastAPI's lifespan raising propagates out of uvicorn, which exits non-zero, which triggers docker restart policy (`unless-stopped` or similar) — three attempts in the log. Each attempt prints the same stack trace. This both wastes 30 s on every failed install and visually drowns the actual root cause in the second and third repeats.

### Fix

Two-part:

1. Change the api container's restart policy on a **fatal startup failure** (ConfigError raised before lifespan enters the `yield`) to `on-failure:0` semantics — i.e., do not restart when exit code indicates an unrecoverable config problem. Uvicorn exit codes: 3 = app startup failure. Docker Compose `restart: unless-stopped` restarts on any non-zero exit; switch to `restart: on-failure` and set a `stop_grace_period` to let the phase logging flush.
2. In `services/api/main.py` lifespan, catch `ConfigError` at the outermost scope, emit a single `startup.aborted` structured event with `exit_code=3`, and `sys.exit(3)` immediately so uvicorn stops cleanly instead of raising through its reloader.

### Decision required

Compose restart policy change is an infra change. Recommend `on-failure:3` (retry 3 times for genuinely transient crashes like OOM, but not infinitely). Need your sign-off.

### TDD

- Unit: `test_lifespan_on_config_error_exits_with_code_3_and_emits_startup_aborted_event`. Patch `verify_redis_connection` to raise `ConfigError`. Run lifespan. Assert `SystemExit(3)` and one `startup.aborted` event.
- Integration: `docker compose up api` with deliberately broken REDIS_URL. Assert container exits once, does not restart, logs contain one copy of the traceback.

### Verification criterion

On a broken-config minitux install the log contains exactly one `phase_failed` + one `startup.aborted` event, not three repeats.

---

## Commit 6 — B3: Break the container cascade

### Root cause

`docker-compose.yml` services downstream of `api` use `depends_on: api: condition: service_healthy`. When api fails startup, every dependent container (worker, scheduler, etc.) hangs in "created" state and compose reports the whole stack as failed. This is correct behaviour during steady-state but during installation it obscures which service is the root cause.

### Fix

Audit all `depends_on: condition: service_healthy` edges. Keep `service_healthy` only where an ordering constraint is genuine (worker cannot process without api's schema migration having landed). For diagnostic purposes, ensure each failing service's own log is prominent: install.sh should, on failure, print `docker compose ps` **followed by the logs of only the containers whose state is not `running (healthy)`**, not all containers interleaved.

### TDD

This is infra, but the test is scriptable: `tests/integration/test_install_diagnostics.sh` — break one service deliberately (broken env var), run install, assert the stderr output of install.sh contains the broken service's name and its log, and does NOT contain the logs of services that came up cleanly.

### Verification criterion

When any one service fails on minitux, install.sh output identifies it by name in the first 20 lines of its error report.

---

## Commit 7 — D4: Stop interleaving all containers' logs in install.sh error output

### Root cause

`fxlab-reinstall.sh` on failure runs `docker compose logs` (no service filter) and pipes all containers' stdout/stderr to the terminal. Timestamps are interleaved across services. For an operator reading the log, this is worse than no logs — the stack trace we actually need is mixed with cadvisor `--help` output and node-exporter reset-by-peer errors.

### Fix

Change install.sh to on-failure run:

```
docker compose ps --format json | jq '...' → list of unhealthy services
for svc in unhealthy_services: echo "=== $svc ==="; docker compose logs --no-log-prefix $svc; echo
```

So each service's log is contiguous, labeled, and only unhealthy ones are dumped by default. Add `--all-logs` flag for the full interleaved dump when explicitly requested.

### TDD

Bash test in `tests/scripts/test_reinstall_failure_output.bats` (bats-core). Launch a compose fixture with a known broken service. Run install.sh. Assert output contains `=== api ===` before the api traceback and does not contain node-exporter chatter.

### Verification criterion

The next failed minitux install takes me < 1 minute to diagnose from the log instead of > 10.

---

## Commit 8 — C1: `sslmode=prefer` silently escaping production secret validation

### Root cause

In the minitux log the DATABASE_URL contained `?sslmode=prefer`. `prefer` means "try SSL, fall back to plaintext on failure without error". In production this is indistinguishable from `sslmode=disable` if the server's SSL negotiation fails. Our secret-handling policy (per your memory: "enterprise-grade secret management") requires `sslmode=require` or stricter in production. The current validator only forbids `sslmode=disable`, not `prefer`.

### Fix

In `services/api/infrastructure/secret_validator.py` (or wherever the DATABASE_URL production check lives — grep first), extend the check: when `ENVIRONMENT=production`, require `sslmode in {require, verify-ca, verify-full}`. Reject `disable`, `allow`, `prefer`. Error message names the allowed values.

### TDD

Parametrized test over all 6 libpq sslmode values: the 3 strict ones pass in production, the 3 weak ones raise `ConfigError`. All 6 pass in non-production.

### Verification criterion

A minitux staging env with `sslmode=prefer` now fails startup loudly with a message pointing at this policy, instead of silently accepting plaintext.

---

## Commit 9 — C2: CORS origins auto-detected as plaintext LAN

### Root cause

In the install log, `CORS_ORIGINS` resolved to `http://192.168.x.x:3000` (plain HTTP, LAN IP). This was auto-detected by a host-discovery helper. In production this is a policy violation: allowing plaintext origins lets a MITM on the LAN set any `Origin` header and bypass CORS.

### Fix

When `ENVIRONMENT=production`, reject any CORS origin where scheme is not `https` OR host is a private-IP literal (10.x, 172.16-31.x, 192.168.x, 169.254.x, ::1, fe80::/10). Require explicit override via `CORS_ORIGINS_ALLOW_PLAINTEXT_LAN=true` which must be paired with a written justification env `CORS_PLAINTEXT_JUSTIFICATION` that ends up in startup logs.

minitux is a dev host, so the install script should set `ENVIRONMENT=development` (verify this — if it currently sets `production`, that is itself a bug).

### Decision required

Dev-vs-prod environment designation for minitux is an infra/policy call. Recommend: minitux = `development`, aks-prod-eastus = `production`. Sign-off needed.

### TDD

- Parametrized test over origin schemes × ip ranges × environment. Production + plaintext + private IP → `ConfigError`. Dev + anything → accepted.
- Assert the bypass flag works AND logs the justification at WARN level.

### Verification criterion

Production cluster cannot start with a plain-HTTP CORS origin; minitux can.

---

## Commit 10 — N1: cadvisor `--help` misconfiguration

### Root cause

In the compose file, cadvisor's `command:` is malformed — it's receiving a flag that causes it to print usage and exit 0. Container reports "running" briefly then restarts. Contributes to log noise and wastes restart budget.

### Fix

Read the compose definition; fix the command line to a valid cadvisor invocation. Likely a shell-quoting bug.

### TDD

Add `tests/integration/test_observability_stack.sh` that asserts cadvisor's `/healthz` returns 200 after compose up, and that its logs do not contain the word "Usage:".

### Verification criterion

cadvisor reports healthy in `docker compose ps`.

---

## Commit 11 — N2: node-exporter connection-reset-by-peer flood

### Root cause

Prometheus (or whatever is scraping node-exporter) hits node-exporter on an endpoint node-exporter isn't serving, or node-exporter is being scraped before it's ready, or network MTU issue inside the compose network.

### Fix

Diagnose with `docker compose logs node-exporter prometheus` after the stack is stable. Most likely: prometheus scrape interval starts before node-exporter's `/metrics` is ready, and Prometheus closes the connection on first-byte timeout. Fix by adding `scrape_timeout: 5s` (currently probably 1 s) and a `scrape_start_delay` equivalent via `honor_timestamps` and `scrape_interval` tuning.

### TDD

Integration: spin compose, wait 60 s, assert `grep -c "connection reset by peer" node-exporter.log` is zero for the last 30 s.

### Verification criterion

No reset-by-peer lines in steady-state.

---

## Commit 12 — N3: PostgreSQL locale warning

### Root cause

PostgreSQL container prints `WARNING: The locale "en_US.UTF-8" is not installed`. The postgres:16 alpine image does not bundle US locale by default. Harmless for us (we use UTF-8 byte-ordered comparisons everywhere) but adds noise.

### Fix

Either (a) switch base image to `postgres:16` (debian) which has the locale, or (b) explicitly set `LANG=C.UTF-8` which is present in alpine. Option (b) is smaller and sufficient for our workload.

### TDD

Integration: after `docker compose up db`, grep `docker compose logs db` for `WARNING: the locale` — must be zero matches.

### Verification criterion

Clean postgres startup log.

---

## Process commits (P-track) — must land before any further install-touching work ships

### P1 — Never declare install-touching work "done" from sandbox unit tests alone

**Change of practice**: for any commit that modifies `services/api/main.py` lifespan, `services/api/infrastructure/*`, compose files, or install scripts, the definition of done includes **a docker-compose-based integration smoke test** that exercises the lifespan end-to-end against real Redis and real PostgreSQL containers. No exceptions. No "I ran unit tests and they passed".

Tooling: introduce `make install-smoke` that runs `docker compose up -d`, waits for api `/readyz`, tails logs, exits non-zero on any `phase_failed`. Gated in CI on any change under the above paths.

### P2 — Triage discipline on failure logs

**Change of practice**: before proposing any fix to a failed install, produce an enumerated issue list covering the entire log file, grouped by severity. Only after the enumeration do I propose fixes. Forced by me pasting the full log and answering: "what is the complete list of issues?" before writing any code.

This is codified in `docs/process/triage-discipline.md` so it travels to future projects per CLAUDE.md §16.

### P3 — Phase-logging audit on every lifespan edit

**Change of practice**: whenever I add a new startup phase or external call in lifespan, I run a source-regex audit that enumerates every IO call site and asserts each is wrapped. Commit 2 of this plan creates that test; from that point forward, adding an unwrapped call fails CI.

---

## Execution order

I propose doing the commits in the listed order (1 → 12, then P-track in parallel where possible). Commits 1, 2, 3 unblock the install. Commits 4, 5, 6 harden it. Commits 7-12 clean up noise. P-track changes my own behaviour so this doesn't happen again.

## Decisions needed before I write any code

1. **B1 fix**: Option A (drop keepalive_options) or Option B (explicit socket.TCP_KEEPIDLE with 60/30/3)?
2. **D1/B3 compose restart policy**: `restart: on-failure` with max 3 attempts across api + dependents?
3. **C2 environment designation**: confirm minitux = `development`, future azure prod cluster = `production`?
4. **P1 CI cost**: `make install-smoke` adds ~60 s to CI. Acceptable for any lifespan/compose-touching PR?

Once I have those four answers I will proceed RED-first from Commit 1.
