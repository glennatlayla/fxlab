# Incident Response Runbook

**Owner:** FXLab Operations Team
**Last Updated:** 2026-04-11
**Severity Classification:** S1 (Critical), S2 (Major), S3 (Minor)

---

## 1. Kill Switch Activation

### When to Activate

Activate the global kill switch when any of the following occur:

- Uncontrolled loss exceeding the daily loss limit on any deployment.
- Broker API returning unexpected data (fills at wrong prices, phantom orders).
- Data feed corruption detected by reconciliation (≥ 2 CRITICAL discrepancies).
- Market regime change detected by the risk gate (e.g., flash crash, circuit breaker).
- Manual operator judgment that continued execution poses unacceptable risk.

### Activation Procedure

1. **Assess scope.** Determine whether the issue is global, strategy-specific, or symbol-specific.
2. **Activate via API:**
   - Global: `POST /kill-switch/global` with `{"reason": "<description>", "activated_by": "<operator_id>"}`
   - Strategy: `POST /kill-switch/strategy/{strategy_id}` with same body.
   - Symbol: `POST /kill-switch/symbol/{symbol}` with same body.
3. **Verify MTTH.** The response includes `mtth_ms` — confirm it is within the SLA (target < 500 ms for paper, < 200 ms for live).
4. **Confirm order cancellation.** Check `orders_cancelled` in the response. Cross-reference with `GET /paper/{deployment_id}/open-orders` or broker dashboard.
5. **Notify stakeholders.** Post to the #fxlab-incidents channel with: scope, reason, MTTH, orders cancelled.
6. **Log the event.** The system records a `HaltEvent` automatically. No manual logging required.

### Deactivation Procedure

1. **Root cause identified and resolved.** Do not deactivate until the cause is confirmed.
2. **Deactivate via API:** `DELETE /kill-switch/{scope}/{target_id}`
3. **Run reconciliation:** `POST /reconciliation/{deployment_id}/run` with trigger `manual`.
4. **Verify clean report.** No unresolved discrepancies before resuming.

---

## 2. Escalation Matrix

| Severity | Response Time | Escalation Path | Communication |
|----------|--------------|-----------------|---------------|
| S1 — Critical (live capital at risk) | Immediate | On-call → Team Lead → CTO | #fxlab-incidents + phone |
| S2 — Major (paper/shadow degraded) | 15 minutes | On-call → Team Lead | #fxlab-incidents |
| S3 — Minor (non-blocking issue) | 1 hour | On-call ticket | #fxlab-ops |

### S1 Triggers

- Live deployment with unexpected fills or positions.
- Kill switch MTTH exceeding SLA.
- Broker API authentication failure during market hours.
- Reconciliation showing missing orders or phantom positions.

### S2 Triggers

- Paper deployment reconciliation discrepancies > 5.
- Risk gate rejecting valid orders (false positives).
- Data feed staleness > 30 seconds during market hours.
- Drift analysis showing CRITICAL severity metrics.

### S3 Triggers

- Shadow mode P&L divergence > 10% from expected.
- Non-critical deployment transition failure.
- Test environment connectivity issues.

---

## 3. Post-Incident Review

### Timeline (within 48 hours of resolution)

1. **Gather timeline.** Use `GET /execution-analysis/search?correlation_id=<incident_corr_id>` to reconstruct the event sequence.
2. **Collect drill data.** If a drill was run during or after the incident, retrieve via `GET /drills/{deployment_id}/history`.
3. **Reconciliation report.** Retrieve via `GET /reconciliation/reports?deployment_id={id}`.
4. **Draft incident report** including:
   - Detection time (how long before the issue was noticed).
   - Response time (time from detection to kill switch activation).
   - MTTH (from HaltEvent).
   - Root cause analysis.
   - What went well, what could improve.
   - Action items with owners and deadlines.
5. **Review meeting.** Schedule within 48 hours. Blameless — focus on systemic improvements.
6. **Update runbooks.** If the incident revealed a gap, update the relevant runbook immediately.

---

## 4. Emergency Posture Execution

When a deployment's emergency posture must be invoked:

1. `POST /kill-switch/emergency-posture/{deployment_id}` with `{"trigger": "<trigger_type>", "reason": "<description>"}`.
2. Posture types:
   - `flatten_all` — Cancel all open orders, then close all positions at market. Use when capital must be fully de-risked.
   - `cancel_open` — Cancel open orders only, leave positions intact. Use when positions are acceptable but new orders are not.
   - `hold` — No automated action. Use when human judgment is required before acting.
3. Verify the response: `orders_cancelled`, `positions_flattened`, `duration_ms`.
