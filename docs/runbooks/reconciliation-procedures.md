# Reconciliation Procedures Runbook

**Owner:** FXLab Operations Team
**Last Updated:** 2026-04-11

---

## 1. Scheduled Reconciliation

Reconciliation runs automatically at the following intervals:
- **On startup:** Every deployment runs reconciliation when the service starts.
- **On reconnect:** After any broker adapter reconnection event.
- **Scheduled:** Every 15 minutes during market hours (configurable).

Manual reconciliation can be triggered at any time.

---

## 2. Running Manual Reconciliation

```
POST /reconciliation/{deployment_id}/run
{
    "trigger": "manual"
}
```

Valid triggers: `startup`, `reconnect`, `scheduled`, `manual`.

The response is a `ReconciliationReport` with:
- `report_id` — ULID for future reference.
- `discrepancies` — list of detected issues.
- `resolved_count` — auto-resolved safe status lags.
- `unresolved_count` — issues requiring operator action.
- `status` — `clean` (no discrepancies), `resolved` (all auto-resolved), or `discrepancies_found`.

---

## 3. Discrepancy Types

| Type | Description | Auto-Resolvable? |
|------|-------------|-------------------|
| `missing_order` | Order exists internally but not at broker | No |
| `extra_order` | Order exists at broker but not internally | No |
| `quantity_mismatch` | Order quantity differs between internal and broker | No |
| `price_mismatch` | Order price differs between internal and broker | No |
| `status_mismatch` | Order status differs (may be safe lag) | Sometimes |
| `missing_position` | Position expected but not at broker | No |
| `extra_position` | Position at broker not tracked internally | No |

### Safe Status Lags (Auto-Resolved)

The system recognizes these status transitions as normal propagation delays:
- `submitted → filled` — Order was filled before internal state updated.
- `submitted → partial_fill` — Partial fill arrived before internal state updated.
- `submitted → cancelled` — Cancellation confirmed before internal state updated.
- `pending → submitted` — Broker accepted order before internal state updated.
- `pending → filled` — Broker filled order very quickly.
- `pending → partial_fill` — Fast partial fill.
- `pending → cancelled` — Fast cancellation.
- `partial_fill → filled` — Remaining quantity filled.

These are logged as resolved discrepancies but do not trigger alerts.

---

## 4. Handling Unresolved Discrepancies

### Priority Classification

- **CRITICAL:** `missing_order` or `extra_order` — indicates a synchronization failure.
- **HIGH:** `missing_position` or `extra_position` — indicates a P&L tracking error.
- **MEDIUM:** `quantity_mismatch` or `price_mismatch` — indicates partial state corruption.
- **LOW:** `status_mismatch` (not auto-resolved) — indicates a stuck state.

### Resolution Procedures

**Missing Order (internal exists, broker doesn't):**
1. Check if the order was rejected by the broker (API logs).
2. If rejected: update internal state to `rejected`.
3. If order was never sent: investigate submission path, check for network errors.
4. If order was sent but broker has no record: escalate to broker support.

**Extra Order (broker has it, internal doesn't):**
1. Check if this is a manual order placed outside the system.
2. If manual: decide whether to import into internal tracking or cancel.
3. If system-originated but untracked: investigate event loss, check for dropped events.

**Position Mismatch:**
1. Compare fill history: `GET /execution-analysis/timeline/{order_id}`.
2. If fills are missing internally: replay from broker fill history.
3. If fills are extra internally: investigate double-counting.
4. For live: freeze the deployment until resolved.

---

## 5. Viewing Reports

```
GET /reconciliation/reports/{report_id}          # Single report
GET /reconciliation/reports?deployment_id={id}    # All reports for deployment
GET /reconciliation/reports?deployment_id={id}&limit=10  # Latest 10
```

---

## 6. Escalation

- **0-2 unresolved discrepancies (MEDIUM/LOW):** Resolve in next business hour.
- **3+ unresolved discrepancies:** Freeze the deployment, investigate immediately.
- **Any CRITICAL discrepancy:** Activate kill switch, notify on-call, follow incident-response runbook.
