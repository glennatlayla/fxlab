# FXLab Phase 3 — Operator API Acceptance Pack

**Version:** Phase 3 v1.1
**Date:** 2026-03-28
**Milestone:** M12 — Operator API Docs + Acceptance Pack
**Base URL:** `http://localhost:8000` (adjust to your deployment host)

---

## Overview

This document is the operator-facing acceptance pack for the FXLab Phase 3 backend API.
It confirms that all Phase 3 UX domains have corresponding backend endpoints, documents
their request/response shapes, and provides cURL examples for happy-path and error cases.

All endpoints are served by the FastAPI application at `services/api/main.py`.
Auto-generated interactive documentation is available at:
- Swagger UI: `GET /docs`
- ReDoc: `GET /redoc`
- Raw OpenAPI JSON: `GET /openapi.json`

All IDs are ULIDs (26-character Crockford Base32 strings).

---

## Table of Contents

1. [Health Checks](#1-health-checks)
2. [Observability](#2-observability)
3. [Run Results & Readiness](#3-run-results--readiness)
4. [Charts](#4-charts)
5. [Promotions & Approvals](#5-promotions--approvals)
6. [Audit Explorer](#6-audit-explorer)
7. [Queue Monitoring](#7-queue-monitoring)
8. [Feed Registry](#8-feed-registry)
9. [Feed Health](#9-feed-health)
10. [Parity Dashboard](#10-parity-dashboard)
11. [Symbol Lineage](#11-symbol-lineage)
12. [Artifacts](#12-artifacts)
13. [Data Certification](#13-data-certification)
14. [Error Reference](#14-error-reference)

---

## 1. Health Checks

### `GET /health`

Container orchestration liveness/readiness probe.

**Response (200 OK):**
```json
{
  "success": true,
  "status": "ok",
  "version": "0.1.0-bootstrap",
  "service": "fxlab-api"
}
```

**cURL:**
```bash
curl -s http://localhost:8000/health | jq .
```

---

## 2. Observability

### `GET /health/dependencies`

Returns reachability status for all platform dependencies.
`overall_status` reflects the worst individual status (DOWN > DEGRADED > OK).

**Response (200 OK):**
```json
{
  "dependencies": [
    {"name": "database",           "status": "OK", "latency_ms": 0.0, "detail": ""},
    {"name": "queues",             "status": "OK", "latency_ms": 0.0, "detail": ""},
    {"name": "artifact_store",     "status": "OK", "latency_ms": 0.0, "detail": ""},
    {"name": "feed_health_service","status": "OK", "latency_ms": 0.0, "detail": ""}
  ],
  "overall_status": "OK",
  "generated_at": "2026-03-28T10:00:00.000000+00:00"
}
```

**Status values:** `OK` | `DEGRADED` | `DOWN`

**cURL:**
```bash
curl -s http://localhost:8000/health/dependencies | jq .
```

---

### `GET /health/diagnostics`

Returns platform-wide operational counts for operator dashboards.

**Response (200 OK):**
```json
{
  "queue_contention_count": 0,
  "feed_health_count": 0,
  "parity_critical_count": 0,
  "certification_blocked_count": 0,
  "generated_at": "2026-03-28T10:00:00.000000+00:00"
}
```

**cURL:**
```bash
curl -s http://localhost:8000/health/diagnostics | jq .
```

---

## 3. Run Results & Readiness

### `GET /runs/{run_id}/results`

Retrieve optimization results for a completed run.

**Parameters:**
- `run_id` (path): ULID of the run.

**Response (200 OK):**
```json
{
  "run_id": "01HQ7X9Z8K3M4N5P6Q7R8S9T0A",
  "metrics": {},
  "artifacts": []
}
```

**Error (404):** Run not found.

**cURL:**
```bash
# Happy path
curl -s http://localhost:8000/runs/01HQ7X9Z8K3M4N5P6Q7R8S9T0A/results | jq .
```

---

### `GET /runs/{run_id}/readiness`

Retrieve the readiness report for a completed run.

**Parameters:**
- `run_id` (path): ULID of the run.

**Response (200 OK):**
```json
{
  "run_id": "01HQ7X9Z8K3M4N5P6Q7R8S9T0A",
  "readiness_grade": "UNKNOWN",
  "blockers": [],
  "scoring_evidence": {}
}
```

**cURL:**
```bash
curl -s http://localhost:8000/runs/01HQ7X9Z8K3M4N5P6Q7R8S9T0A/readiness | jq .
```

---

## 4. Charts

### `GET /runs/{run_id}/charts`

List available charts for a run.

**cURL:**
```bash
curl -s http://localhost:8000/runs/01HQ7X9Z8K3M4N5P6Q7R8S9T0A/charts | jq .
```

### `GET /runs/{run_id}/charts/equity`

Retrieve the equity curve chart data. Supports LTTB downsampling via `?max_points=N`.

**Query parameters:**
- `max_points` (optional, int): Maximum chart points (LTTB applied when set and data exceeds this).

**Response (200 OK):**
```json
{
  "run_id": "01HQ7X9Z8K3M4N5P6Q7R8S9T0A",
  "points": [],
  "sampling_method": null,
  "original_count": 0,
  "returned_count": 0
}
```

**cURL:**
```bash
curl -s "http://localhost:8000/runs/01HQ7X9Z8K3M4N5P6Q7R8S9T0A/charts/equity?max_points=500" | jq .
```

### `GET /runs/{run_id}/charts/drawdown`

Retrieve the drawdown chart data.

**cURL:**
```bash
curl -s http://localhost:8000/runs/01HQ7X9Z8K3M4N5P6Q7R8S9T0A/charts/drawdown | jq .
```

---

## 5. Promotions & Approvals

### `POST /promotions/request`

Submit a promotion request for a candidate to a target environment.

**Request body:**
```json
{
  "candidate_id": "01HQ7X9Z8K3M4N5P6Q7R8S9T0B",
  "requester_id": "01HQ7X9Z8K3M4N5P6Q7R8S9T0C",
  "target_environment": "paper"
}
```

**Fields:**
- `candidate_id` (required): ULID of the candidate to promote.
- `requester_id` (required): ULID of the requesting user.
- `target_environment` (required): `paper` or `live`.

**Response (202 Accepted):**
```json
{
  "job_id": "01HQ7X9Z8K3M4N5P6Q7R8S9T0X",
  "status": "pending"
}
```

**Error (422):** Missing required fields.

**cURL:**
```bash
# Happy path
curl -s -X POST http://localhost:8000/promotions/request \
  -H "Content-Type: application/json" \
  -d '{
    "candidate_id": "01HQ7X9Z8K3M4N5P6Q7R8S9T0B",
    "requester_id": "01HQ7X9Z8K3M4N5P6Q7R8S9T0C",
    "target_environment": "paper"
  }' | jq .

# Validation error (missing requester_id)
curl -s -X POST http://localhost:8000/promotions/request \
  -H "Content-Type: application/json" \
  -d '{"candidate_id": "01HQ7X9Z8K3M4N5P6Q7R8S9T0B"}' | jq .
```

---

### `POST /approvals/{approval_id}/approve`

Approve a pending governance decision.

**Parameters:**
- `approval_id` (path): ULID of the approval record.

**Response (200 OK):**
```json
{
  "approval_id": "01HQ7X9Z8K3M4N5P6Q7R8S9T0D",
  "status": "approved"
}
```

**cURL:**
```bash
curl -s -X POST http://localhost:8000/approvals/01HQ7X9Z8K3M4N5P6Q7R8S9T0D/approve \
  -H "Content-Type: application/json" \
  -d '{}' | jq .
```

---

## 6. Audit Explorer

### `GET /audit`

List audit events with optional filters. All filter parameters default to empty string (no filter).

**Query parameters:**
- `actor` (str): Filter by actor ULID.
- `action_type` (str): Filter by action type string.
- `target_type` (str): Filter by target entity type.
- `target_id` (str): Filter by target entity ULID.
- `cursor` (str): Pagination cursor from previous response.
- `limit` (int, 1–500, default 50): Maximum events to return.

**Response (200 OK):**
```json
{
  "events": [],
  "next_cursor": ""
}
```

**cURL:**
```bash
# All events
curl -s http://localhost:8000/audit | jq .

# Filter by actor
curl -s "http://localhost:8000/audit?actor=01HQ7X9Z8K3M4N5P6Q7R8S9T0C&limit=20" | jq .

# Filter by action type
curl -s "http://localhost:8000/audit?action_type=PROMOTE_REQUEST" | jq .
```

---

### `GET /audit/{audit_event_id}`

Retrieve a single audit event by ULID.

**Response (200 OK):**
```json
{
  "id": "01HQAUDIT1000000000AAAA00001",
  "actor": "01HQ7X9Z8K3M4N5P6Q7R8S9T0C",
  "action_type": "PROMOTE_REQUEST",
  "target_type": "candidate",
  "target_id": "01HQ7X9Z8K3M4N5P6Q7R8S9T0B",
  "payload": {},
  "created_at": "2026-03-28T10:00:00+00:00"
}
```

**Error (404):** Audit event not found.

**cURL:**
```bash
# Happy path
curl -s http://localhost:8000/audit/01HQAUDIT1000000000AAAA00001 | jq .

# Not found
curl -s http://localhost:8000/audit/01HQZZZZZZZZZZZZZZZZZZZZZZ | jq .
```

---

## 7. Queue Monitoring

### `GET /queues/`

List all monitored queue classes with their current contention status.

**Response (200 OK):**
```json
{
  "queues": []
}
```

**cURL:**
```bash
curl -s http://localhost:8000/queues/ | jq .
```

---

### `GET /queues/{queue_class}/contention`

Get contention metrics for a specific queue class.

**Parameters:**
- `queue_class` (path): Queue class name (e.g. `default`, `research`, `high_priority`).

**Response (200 OK):**
```json
{
  "queue_class": "default",
  "active_workers": 0,
  "queued_tasks": 0,
  "contention_score": 0.0
}
```

**Error (404):** Queue class not found.

**cURL:**
```bash
# Known queue class
curl -s http://localhost:8000/queues/default/contention | jq .

# Unknown class (404)
curl -s http://localhost:8000/queues/nonexistent/contention | jq .
```

---

## 8. Feed Registry

### `GET /feeds`

List all registered data feeds with optional filters.

**Query parameters:**
- `status` (str): Filter by lifecycle status.
- `limit` (int, default 50): Maximum feeds to return.
- `offset` (int, default 0): Pagination offset.

**Response (200 OK):**
```json
{
  "feeds": [],
  "total": 0,
  "limit": 50,
  "offset": 0
}
```

**cURL:**
```bash
curl -s http://localhost:8000/feeds | jq .
curl -s "http://localhost:8000/feeds?limit=10&offset=0" | jq .
```

---

### `GET /feeds/{feed_id}`

Retrieve a single feed by ULID.

**Error (404):** Feed not found.

**cURL:**
```bash
# Happy path
curl -s http://localhost:8000/feeds/01HQFEED000000000000000001 | jq .

# Not found
curl -s http://localhost:8000/feeds/01HQZZZZZZZZZZZZZZZZZZZZZZ | jq .
```

---

## 9. Feed Health

### `GET /feed-health`

Retrieve current health snapshots for all feeds.

**Response (200 OK):**
```json
{
  "feeds": [],
  "generated_at": "2026-03-28T10:00:00+00:00"
}
```

Each entry in `feeds` contains: `feed_id`, `status`, `last_checked_at`, `message`.

**cURL:**
```bash
curl -s http://localhost:8000/feed-health | jq .
```

---

## 10. Parity Dashboard

### `GET /parity/events`

List parity events with optional filters.

**Query parameters:**
- `severity` (str): Filter by severity (`INFO`, `WARNING`, `CRITICAL`). Default: no filter.
- `instrument` (str): Filter by instrument symbol. Default: no filter.
- `feed_id` (str): Filter by official or shadow feed ULID. Default: no filter.

**Response (200 OK):**
```json
{
  "events": []
}
```

Each event contains: `id`, `instrument`, `official_feed_id`, `shadow_feed_id`, `severity`,
`delta`, `created_at`.

**cURL:**
```bash
# All events
curl -s http://localhost:8000/parity/events | jq .

# CRITICAL only
curl -s "http://localhost:8000/parity/events?severity=CRITICAL" | jq .

# Filter by instrument
curl -s "http://localhost:8000/parity/events?instrument=AAPL&severity=WARNING" | jq .
```

---

### `GET /parity/events/{parity_event_id}`

Retrieve a single parity event by ULID.

**Error (404):** Parity event not found.

**cURL:**
```bash
# Happy path
curl -s http://localhost:8000/parity/events/01HQPARITY10000000000AAAA1 | jq .

# Not found
curl -s http://localhost:8000/parity/events/01HQZZZZZZZZZZZZZZZZZZZZZZ | jq .
```

---

### `GET /parity/summary`

Retrieve per-instrument parity severity summary.

**Response (200 OK):**
```json
{
  "summaries": []
}
```

Each summary contains: `instrument`, `event_count`, `critical_count`, `warning_count`,
`info_count`, `worst_severity`.

**cURL:**
```bash
curl -s http://localhost:8000/parity/summary | jq .
```

---

## 11. Symbol Lineage

### `GET /symbols/{symbol}/lineage`

Retrieve data provenance information for a symbol — which feeds supply data
and which runs have consumed it.

**Parameters:**
- `symbol` (path): Instrument symbol (e.g. `AAPL`, `SPY`).

**Response (200 OK):**
```json
{
  "symbol": "AAPL",
  "feeds": [],
  "runs": []
}
```

Each entry in `feeds` contains: `feed_id`, `feed_name`, `role` (`official` or `shadow`).
Each entry in `runs` contains: `run_id`, `consumed_at`.

**Error (404):** Symbol not found.

**cURL:**
```bash
# Happy path
curl -s http://localhost:8000/symbols/AAPL/lineage | jq .

# Not found
curl -s http://localhost:8000/symbols/ZZZZZZZZZ/lineage | jq .
```

---

## 12. Artifacts

### `GET /artifacts`

List artifacts with optional filters.

**Query parameters:**
- `subject_id` (str): Filter by subject ULID (run_id, candidate_id, etc.).
- `artifact_type` (str): Filter by type (`model`, `report`, `dataset`, etc.).
- `limit` (int, default 50): Maximum artifacts to return.
- `offset` (int, default 0): Pagination offset.

**Response (200 OK):**
```json
{
  "artifacts": [],
  "total": 0,
  "limit": 50,
  "offset": 0
}
```

**cURL:**
```bash
curl -s http://localhost:8000/artifacts | jq .
curl -s "http://localhost:8000/artifacts?subject_id=01HQ7X9Z8K3M4N5P6Q7R8S9T0A" | jq .
```

---

### `GET /artifacts/{artifact_id}/download`

Download an artifact by ULID.

**Response (200):** Binary artifact content with appropriate `Content-Type` header.
- `.json` files: `application/json`
- `.csv` files: `text/csv`
- `.parquet` files: `application/vnd.apache.parquet`
- Other: `application/octet-stream`

**Error (404):** Artifact not found.

**cURL:**
```bash
# Download to file
curl -s http://localhost:8000/artifacts/01HQARTIFACT0000000AAAA001/download \
  -o output_file

# Not found
curl -s http://localhost:8000/artifacts/01HQZZZZZZZZZZZZZZZZZZZZZZ/download
```

---

## 13. Data Certification

### `GET /data/certification`

List feed certification records with optional filters.

**Response (200 OK):**
```json
{
  "certifications": []
}
```

Each record contains: `id`, `feed_id`, `status` (`ACTIVE`, `BLOCKED`, `SUSPENDED`),
`certified_at`, `certified_by`, `notes`.

**cURL:**
```bash
curl -s http://localhost:8000/data/certification | jq .
```

---

## 14. Error Reference

All error responses follow a consistent shape:

```json
{
  "detail": "Human-readable error message"
}
```

| Status Code | Meaning |
|-------------|---------|
| 200 | OK — Request succeeded |
| 201 | Created — Resource created |
| 202 | Accepted — Request accepted for async processing |
| 404 | Not Found — Resource does not exist |
| 422 | Unprocessable Entity — Validation error (malformed input) |
| 500 | Internal Server Error — Unexpected server failure |

### Common 422 causes

- Missing required body fields in POST requests.
- Invalid ULID format in path or query parameters.
- Invalid enum value in request body (e.g. `target_environment` must be `paper` or `live`).

---

## Acceptance Test Suite

The acceptance tests for this milestone live at:
```
tests/acceptance/test_m12_acceptance_pack.py
```

Run them with:
```bash
.venv/bin/pytest tests/acceptance/test_m12_acceptance_pack.py -v
```

All 40 tests must pass for M12 to be considered DONE.

---

## Endpoint Summary

| Method | Path | Description |
|--------|------|-------------|
| GET | `/health` | Service liveness probe |
| GET | `/health/dependencies` | Platform dependency health |
| GET | `/health/diagnostics` | Platform operational counts |
| GET | `/runs/{run_id}/results` | Run optimization results |
| GET | `/runs/{run_id}/readiness` | Run readiness report |
| GET | `/runs/{run_id}/charts` | List run charts |
| GET | `/runs/{run_id}/charts/equity` | Equity curve chart |
| GET | `/runs/{run_id}/charts/drawdown` | Drawdown chart |
| POST | `/promotions/request` | Submit promotion request |
| POST | `/approvals/{id}/approve` | Approve governance decision |
| GET | `/audit` | List audit events |
| GET | `/audit/{audit_event_id}` | Single audit event |
| GET | `/queues/` | List queue classes |
| GET | `/queues/{queue_class}/contention` | Queue contention metrics |
| GET | `/feeds` | List feed registry |
| GET | `/feeds/{feed_id}` | Single feed detail |
| GET | `/feed-health` | Feed health snapshots |
| GET | `/parity/events` | List parity events |
| GET | `/parity/events/{parity_event_id}` | Single parity event |
| GET | `/parity/summary` | Per-instrument parity summary |
| GET | `/symbols/{symbol}/lineage` | Symbol data provenance |
| GET | `/artifacts` | List artifacts |
| GET | `/artifacts/{artifact_id}/download` | Download artifact |
| GET | `/data/certification` | List certification records |
| GET | `/openapi.json` | OpenAPI schema (machine-readable) |
| GET | `/docs` | Swagger UI (interactive) |
| GET | `/redoc` | ReDoc (interactive) |
