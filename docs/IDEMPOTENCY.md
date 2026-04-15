# Idempotency Key Support — BE-06

## Overview

The FXLab API supports **idempotency keys** to prevent duplicate operations when clients retry failed requests. This is especially important for mobile clients on unreliable networks, which may submit the same request multiple times without knowing if the first one succeeded.

## Use Case

**Scenario**: A mobile user activates a kill switch, but the request times out before receiving a response. The user taps "retry" — should the system:
- ✗ Activate a second kill switch (wrong — now two simultaneous activations)
- ✓ Return the cached response from the first activation (correct)

The Idempotency-Key header lets clients tell the server "if you've already processed this exact request, replay the cached response instead of processing it again."

## Request Headers

### Idempotency-Key (recommended for mutations)

Include an `Idempotency-Key` header on all **POST, PUT, PATCH** requests:

```http
POST /kill-switch/global HTTP/1.1
Host: api.fxlab.example.com
Authorization: Bearer <token>
Idempotency-Key: 12e3456e-e89b-12d3-a456-426614174000

{
  "reason": "Manual activation",
  "activated_by": "operator-id"
}
```

**Format**: Any string (UUID, ULID, or custom identifier recommended for traceability).

**Key characteristics**:
- Must be unique per logical request (not per retry)
- Should persist across client retries
- Recommended: use UUID v4 or ULID for automatic generation

### Idempotency-Key is Optional (Backward Compatible)

Requests without an `Idempotency-Key` header are processed normally without idempotency tracking. This ensures older clients continue to work.

```http
POST /research/runs HTTP/1.1
# No Idempotency-Key header — processed normally, no caching
```

## Response Headers

### Idempotency-Key-Status

The server echoes back an `Idempotency-Key-Status` header on responses to requests with an `Idempotency-Key`:

| Value | Meaning |
|-------|---------|
| `stored` | This is a new request; response has been cached |
| `replayed` | This is a retry; response was retrieved from cache |
| (absent) | Request had no Idempotency-Key header or was excluded from idempotency |

**Example (first request)**:
```http
HTTP/1.1 200 OK
Idempotency-Key-Status: stored
Content-Type: application/json

{
  "event_id": "01HABCDEF00000000000000001",
  "scope": "global",
  "activated_at": "2024-04-13T17:45:30Z"
}
```

**Example (retry with same key)**:
```http
HTTP/1.1 200 OK
Idempotency-Key-Status: replayed
Content-Type: application/json

{
  "event_id": "01HABCDEF00000000000000001",  // Same as first response
  "scope": "global",
  "activated_at": "2024-04-13T17:45:30Z"
}
```

## Supported Operations

### Methods
- **POST** (creates a resource) — idempotent
- **PUT** (updates a resource) — idempotent
- **PATCH** (partial update) — idempotent
- **GET** (reads a resource) — skipped (inherently idempotent)
- **DELETE** (deletes a resource) — **not** idempotent

### Endpoints

| Endpoint | Method | Idempotent | Notes |
|----------|--------|-----------|-------|
| `/kill-switch/global` | POST | ✓ | Activate global kill switch |
| `/kill-switch/strategy/{id}` | POST | ✓ | Activate strategy-scoped kill switch |
| `/kill-switch/symbol/{symbol}` | POST | ✓ | Activate symbol-scoped kill switch |
| `/kill-switch/emergency-posture/{id}` | POST | ✓ | Execute emergency posture |
| `/kill-switch/{scope}/{target}` | DELETE | ✗ | Deactivate kill switch — **no idempotency** |
| `/kill-switch/status` | GET | ✗ | Query status — **no idempotency** |
| `/research/runs` | POST | ✓ | Submit a research run |

### Excluded Paths (always bypassed)

These paths **never** participate in idempotency caching, even if an `Idempotency-Key` is provided:
- `/health` — Health probe
- `/` — Root endpoint
- `/docs` — Swagger UI
- `/openapi.json` — OpenAPI spec
- `/redoc` — ReDoc UI
- `/auth/token` — Token generation (tokens must be unique per request)

## Cache Behavior

### TTL (Time-To-Live)

Cached responses are stored for **1 hour** (configurable via `IDEMPOTENCY_WINDOW` environment variable).

After the TTL expires, the key is eligible for garbage collection. A new request with the same key will be treated as a fresh request and processed again.

```bash
# Default: 1 hour = 3600 seconds
IDEMPOTENCY_WINDOW=3600

# Custom: 30 minutes
IDEMPOTENCY_WINDOW=1800

# Custom: 24 hours
IDEMPOTENCY_WINDOW=86400
```

### What Gets Cached

- **Status code** (e.g., 200, 201, 409, 422)
- **Response body** (JSON payload)
- **Response headers** (except hop-by-hop headers like `Set-Cookie`)

### What Doesn't Get Cached

- **5xx server errors** (500, 502, 503, etc.) — not cached; a retry should get a fresh attempt
- **Hop-by-hop headers** (Connection, Transfer-Encoding, Set-Cookie, etc.)
- **Concurrent requests with the same key** — return 409 Conflict while the first is processing

## Concurrent Request Handling

### Scenario: Request In-Flight

If a request with key `K` is still being processed and a second request arrives with the same key:

```http
# Request 1 (slow processing)
POST /kill-switch/global
Idempotency-Key: my-key

# (server is processing... 100ms later)

# Request 2 (same key, while request 1 is still in-flight)
POST /kill-switch/global
Idempotency-Key: my-key

# Response from request 2:
HTTP/1.1 409 Conflict
{
  "detail": "Duplicate request currently being processed. Please wait and retry."
}
```

**Rationale**: Prevents cascading failures. If request 1 is slow or hanging, request 2 should not also hang or overload the service. The client should back off and retry after a delay.

**Retry strategy** (recommended for clients):
```
delay = 500ms
for attempt in range(max_retries):
    try:
        response = await POST(..., headers={'Idempotency-Key': key})
        if response.status_code == 409:
            await sleep(delay)
            delay *= 2  # exponential backoff
            continue
        return response
    except timeout:
        await sleep(delay)
        delay *= 2
        continue
```

## CORS Support

The `Idempotency-Key` header is explicitly allowed in CORS preflight requests:

```http
OPTIONS /kill-switch/global HTTP/1.1
Origin: https://app.fxlab.example.com
Access-Control-Request-Method: POST
Access-Control-Request-Headers: Idempotency-Key, Content-Type

HTTP/1.1 200 OK
Access-Control-Allow-Headers: Authorization, Content-Type, X-Correlation-ID, X-Client-Source, Idempotency-Key
Access-Control-Allow-Methods: GET, POST, PUT, PATCH, DELETE, OPTIONS
```

## Architecture

### Middleware Stack

The IdempotencyMiddleware runs in the request/response pipeline:

```
DrainMiddleware (shutdown signal)
  ↓
CorrelationIDMiddleware (tracing)
  ↓
ClientSourceMiddleware (audit)
  ↓
BodySizeLimitMiddleware (size check)
  ↓
RateLimitMiddleware (rate limiting)
  ↓
IdempotencyMiddleware ← YOU ARE HERE
  ↓
CORSMiddleware
  ↓
[Route handlers]
```

**Key property**: Idempotency runs **after** rate limiting. This means:
- Rate limits are enforced per-request (not per-key)
- Cached responses don't consume rate-limit quota (they're returned before rate-limit check)

### Storage Backends

#### In-Memory (Default)

Responses are cached in an in-memory `IdempotencyStore` with TTL cleanup:

```python
_store = IdempotencyStore(window_seconds=3600)
```

- **Pros**: Fast, zero infrastructure
- **Cons**: Lost on service restart; single-process only (doesn't work with multiple replicas)

#### Redis (Production)

When `IDEMPOTENCY_BACKEND=redis` and Redis is available, the middleware switches to `RedisIdempotencyStore`:

```bash
export IDEMPOTENCY_BACKEND=redis
export REDIS_URL=redis://localhost:6379/0
```

- **Pros**: Persistent across restarts; works with multiple replicas
- **Cons**: Requires Redis; adds network latency

**Failover**: If Redis is unavailable, the middleware falls back to in-memory storage and logs a warning.

## Client Implementation

### TypeScript / JavaScript (Axios Example)

```typescript
import axios from 'axios';
import { v4 as uuidv4 } from 'uuid';

const apiClient = axios.create({
  baseURL: 'https://api.fxlab.example.com',
});

// Request interceptor: auto-generate Idempotency-Key for mutations
apiClient.interceptors.request.use((config) => {
  if (config.method && ['post', 'put', 'patch'].includes(config.method.toLowerCase())) {
    // Generate a unique key if not already present
    if (!config.headers['Idempotency-Key']) {
      config.headers['Idempotency-Key'] = uuidv4();
    }
  }
  return config;
});

// Response interceptor: log idempotency status
apiClient.interceptors.response.use((response) => {
  const status = response.headers['Idempotency-Key-Status'];
  if (status === 'replayed') {
    console.log('Response was replayed from cache (retry of previous request)');
  } else if (status === 'stored') {
    console.log('Response was fresh (first time processing this request)');
  }
  return response;
});

// Usage: idempotency happens automatically
const response = await apiClient.post('/kill-switch/global', {
  reason: 'Manual activation',
  activated_by: 'operator-123',
});
```

### Python (Requests Example)

```python
import requests
import uuid

class IdempotentSession(requests.Session):
    """Session that auto-generates Idempotency-Key for mutations."""

    def request(self, method, url, **kwargs):
        if method.upper() in ('POST', 'PUT', 'PATCH'):
            headers = kwargs.get('headers', {})
            if 'Idempotency-Key' not in headers:
                headers['Idempotency-Key'] = str(uuid.uuid4())
            kwargs['headers'] = headers
        return super().request(method, url, **kwargs)


session = IdempotentSession()
response = session.post(
    'https://api.fxlab.example.com/kill-switch/global',
    json={
        'reason': 'Manual activation',
        'activated_by': 'operator-123',
    },
    headers={'Authorization': f'Bearer {token}'},
)
```

### Handling Responses

```python
if response.status_code == 409:
    # Concurrent duplicate — back off and retry
    print("Request in-flight; retrying after delay...")
    await asyncio.sleep(1)  # Retry after 1 second
elif response.headers.get('Idempotency-Key-Status') == 'replayed':
    print("This response was retrieved from cache (previous request)")
elif response.headers.get('Idempotency-Key-Status') == 'stored':
    print("This is a fresh response (first time this key was processed)")
```

## Error Scenarios

### Case 1: Invalid Kill Switch State

**Request 1** (succeeds):
```http
POST /kill-switch/global
Idempotency-Key: key-1

HTTP/1.1 200 OK
Idempotency-Key-Status: stored
{...}
```

**Request 2** (retry with same key):
```http
POST /kill-switch/global
Idempotency-Key: key-1

HTTP/1.1 200 OK
Idempotency-Key-Status: replayed  ← Cached from request 1
{...}
```

The business logic never sees request 2 — the cached response is replayed.

### Case 2: Validation Error

**Request 1** (invalid payload):
```http
POST /research/runs
Idempotency-Key: key-2
Content-Type: application/json

{ "invalid": "payload" }

HTTP/1.1 422 Unprocessable Entity
Idempotency-Key-Status: stored  ← Error is cached!
{ "detail": "Field validation error..." }
```

**Request 2** (retry with same key, corrected payload):
```http
POST /research/runs
Idempotency-Key: key-2
Content-Type: application/json

{ "config": { "run_type": "backtest", ... } }

HTTP/1.1 422 Unprocessable Entity
Idempotency-Key-Status: replayed  ← Cached error from request 1
{ "detail": "Field validation error..." }  ← OLD ERROR!
```

**Lesson**: Clients should use a **new** Idempotency-Key when retrying with a corrected payload. The old key is "poisoned" with the error response.

## Testing

### Unit Tests

```bash
pytest tests/unit/test_idempotency_middleware.py -v
```

Covers:
- Basic request/response caching
- Duplicate key detection
- Expired key cleanup
- Concurrent request detection (409)
- Excluded paths
- Thread safety

### Integration Tests

```bash
pytest tests/integration/test_idempotency_integration.py -v
```

Covers:
- CORS header propagation
- GET/OPTIONS request bypass
- Middleware integration with real HTTP stack

### Manual Testing

```bash
# Test 1: Basic idempotency
KEY="test-$(date +%s%N | md5sum | cut -c1-8)"
curl -X POST http://localhost:8000/kill-switch/global \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Idempotency-Key: $KEY" \
  -d '{"reason":"Test","activated_by":"test"}'

# Test 2: Replay with same key (should return cached response)
curl -X POST http://localhost:8000/kill-switch/global \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Idempotency-Key: $KEY" \
  -d '{"reason":"Different reason","activated_by":"test"}'
# ^ Should return same event_id with "Idempotency-Key-Status: replayed"
```

## Configuration

### Environment Variables

| Variable | Default | Notes |
|----------|---------|-------|
| `IDEMPOTENCY_BACKEND` | `memory` | `memory` or `redis` |
| `IDEMPOTENCY_WINDOW` | `3600` | Cache TTL in seconds |
| `REDIS_URL` | `redis://localhost:6379/0` | Only used when `IDEMPOTENCY_BACKEND=redis` |

### Example: Redis in Production

```dockerfile
# Dockerfile
ENV IDEMPOTENCY_BACKEND=redis
ENV IDEMPOTENCY_WINDOW=86400  # 24 hours
ENV REDIS_URL=redis://redis:6379/0
```

## FAQ

### Q: What if the client doesn't send an Idempotency-Key?
**A**: The request is processed normally without caching. Idempotency-Key is optional for backward compatibility.

### Q: What if the same key is used for different endpoints?
**A**: Each endpoint maintains its own cache namespace. The same key used at two different endpoints will produce two independent cached responses.

### Q: Can I use the same key for retries after hours/days?
**A**: Not recommended. If the key has expired from cache (> IDEMPOTENCY_WINDOW), a new request will be processed as fresh, potentially creating a duplicate operation. Use a new key for operations after a significant delay.

### Q: What if my process crashes mid-request?
**A**: If a request is marked "in-flight" and the process crashes, the key remains in-flight indefinitely (in-memory) or until Redis TTL expires. On restart, the crashed request is forgotten. A retry with the same key will be treated as a fresh request. This is acceptable because:
1. The operation likely didn't complete (process crashed)
2. Retrying is the correct action
3. The old "in-flight" lock will eventually expire

### Q: Can I disable idempotency for a specific endpoint?
**A**: Yes, add the path to `_EXCLUDED_PATHS` in `/services/api/middleware/idempotency.py`. But this is not recommended for mutation endpoints.

### Q: Is idempotency the same as preventing duplicate database writes?
**A**: No. Idempotency at the HTTP level prevents duplicate **responses**; the business logic still needs to enforce database-level uniqueness constraints (UNIQUE indexes, foreign key constraints, etc.) for critical data integrity.

## References

- [RFC 9110: Idempotent Request Methods](https://www.rfc-editor.org/rfc/rfc9110#name-idempotent-methods)
- [Stripe API: Idempotent Requests](https://stripe.com/docs/api/idempotent_requests)
- [AWS API Best Practices: Idempotency](https://docs.aws.amazon.com/whitepapers/latest/modern-application-development-in-aws/idempotency.html)
