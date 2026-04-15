# M14-T8b — Keycloak Integration + SecretProvider + Admin Panel API

**Created:** 2026-04-03
**Status:** IN_PROGRESS
**Prerequisite:** M14-T8 (OIDC-compatible endpoints — DONE)
**Blocks:** M22 Frontend Foundation (AuthProvider must target Keycloak)

---

## Objective

Replace self-rolled JWT token issuance with Keycloak as the canonical
identity provider. Centralise all secret access behind a SecretProvider
interface. Expose admin API endpoints for secret rotation and user
management that the frontend admin panel will consume.

---

## Architecture

```
┌─────────────────┐     ┌──────────────────┐
│  Frontend        │────▶│  Keycloak        │  ← Token issuance (RS256)
│  (oidc-client-ts)│     │  :8080           │  ← User management
└────────┬────────┘     └──────────────────┘
         │ Bearer token (RS256)                    ▲
         ▼                                         │ Admin API
┌─────────────────┐     ┌──────────────────┐      │
│  FXLab API       │────▶│  PostgreSQL      │      │
│  :8000           │     │  :5432           │      │
│  (validates JWT) │     └──────────────────┘      │
│  (/admin/* →  ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ┘
│   proxies to KC)│
└─────────────────┘
```

### Key changes from current architecture

1. **Keycloak** becomes the token issuer (RS256 signed JWTs).
2. **auth.py** stops issuing tokens. It validates Keycloak-signed tokens
   by fetching the JWKS from Keycloak's discovery endpoint.
3. **Self-rolled /auth/token** endpoint is archived. The frontend's
   oidc-client-ts library calls Keycloak's token endpoint directly.
4. **SecretProvider** interface abstracts secret access. Production uses
   env vars (or Vault later); tests use in-memory provider.
5. **Admin API** routes proxy to Keycloak Admin REST API for user CRUD
   and expose secret rotation endpoints.

---

## Deliverables

### D1 — Keycloak Docker Service

1. Add `keycloak` service to `docker-compose.yml`:
   - Image: `quay.io/keycloak/keycloak:24.0`
   - Port: 8080 (HTTP), 8443 (HTTPS)
   - Admin credentials from env vars (KEYCLOAK_ADMIN, KEYCLOAK_ADMIN_PASSWORD)
   - Persistent storage for H2/PostgreSQL
   - Health check: `/health/ready`

2. Create `config/keycloak/fxlab-realm.json` realm export:
   - Realm: `fxlab`
   - Client: `fxlab-api` (confidential, service-account enabled)
   - Client: `fxlab-web` (public, PKCE, redirect to localhost:3000)
   - Roles: admin, operator, reviewer, viewer
   - Client scopes matching ROLE_SCOPES: strategies:write, runs:write,
     promotions:request, approvals:write, overrides:request,
     overrides:approve, exports:read, feeds:read, operator:read, audit:read
   - Default role-scope mappings matching current ROLE_SCOPES dict
   - Bootstrap admin user: admin@fxlab.io / role=admin

### D2 — SecretProvider Interface + Implementations

1. `libs/contracts/interfaces/secret_provider.py`:
   ```python
   class SecretProviderInterface(ABC):
       def get_secret(self, key: str) -> str: ...
       def get_secret_or_default(self, key: str, default: str) -> str: ...
       def rotate_secret(self, key: str, new_value: str) -> None: ...
       def list_secrets(self) -> list[SecretMetadata]: ...
   ```

2. `services/api/infrastructure/env_secret_provider.py`:
   - Reads from os.environ
   - rotate_secret() raises NotImplementedError (env vars can't be rotated at runtime)
   - list_secrets() returns metadata for known secret keys

3. `libs/contracts/mocks/mock_secret_provider.py`:
   - In-memory dict, supports rotate_secret()

### D3 — auth.py Refactor (RS256 Keycloak Validation)

1. New `KeycloakTokenValidator` class:
   - Fetches JWKS from Keycloak's `/.well-known/openid-configuration` → `jwks_uri`
   - Caches public keys with TTL (5 minutes)
   - Validates RS256 tokens: signature, exp, nbf, iss, aud
   - Extracts sub, realm_access.roles, scope, email
   - Maps Keycloak roles to FXLab ROLE_SCOPES

2. Update `get_current_user()`:
   - Delegates to KeycloakTokenValidator when KEYCLOAK_URL is set
   - Falls back to self-rolled HS256 when KEYCLOAK_URL is not set (backward compat)
   - TEST_TOKEN bypass unchanged

3. Archive self-rolled `/auth/token` endpoint:
   - Move to `routes/auth_legacy.py` with deprecation notice
   - Keep discoverable but log DEPRECATION warning on every call

### D4 — Admin API Routes

1. `services/api/routes/admin.py`:
   - `GET /admin/secrets` — list secret metadata (key, last_rotated, source)
   - `POST /admin/secrets/{key}/rotate` — rotate a secret (requires admin role)
   - `GET /admin/users` — list Keycloak users (proxy to KC Admin API)
   - `POST /admin/users` — create user in Keycloak
   - `PUT /admin/users/{id}/roles` — assign roles in Keycloak
   - `POST /admin/users/{id}/reset-password` — trigger password reset
   - All routes require `Depends(require_scope("admin:manage"))`

2. `services/api/services/keycloak_admin_service.py`:
   - Wraps Keycloak Admin REST API (token-based auth)
   - Methods: list_users, create_user, update_roles, reset_password
   - Uses SecretProvider to get KEYCLOAK_ADMIN_CLIENT_SECRET

### D5 — Secret Access Migration

Migrate all raw `os.environ.get()` calls for secrets to use SecretProvider:
- `auth.py`: JWT_SECRET_KEY → secret_provider.get_secret("JWT_SECRET_KEY")
- `db.py`: DATABASE_URL → secret_provider.get_secret("DATABASE_URL")
- `routes/auth.py`: KEYCLOAK_ADMIN_CLIENT_SECRET → secret_provider

---

## Acceptance Criteria

- [ ] `docker-compose up` starts Keycloak alongside API, PostgreSQL, Redis
- [ ] Keycloak admin console accessible at http://localhost:8080
- [ ] `fxlab` realm auto-imported with correct clients, roles, scopes
- [ ] `POST http://localhost:8080/realms/fxlab/protocol/openid-connect/token`
      with valid credentials returns RS256 access token
- [ ] FXLab API validates Keycloak-issued RS256 tokens on protected endpoints
- [ ] Self-rolled HS256 still works when KEYCLOAK_URL is not set (backward compat)
- [ ] `GET /admin/secrets` returns metadata for all known secrets (admin only)
- [ ] `POST /admin/secrets/JWT_SECRET_KEY/rotate` rotates the key (admin only)
- [ ] `GET /admin/users` returns Keycloak user list (admin only)
- [ ] SecretProvider interface has env + mock implementations with tests
- [ ] All `os.environ.get()` for secrets replaced with SecretProvider calls
- [ ] 403 returned when non-admin calls /admin/* endpoints
- [ ] All existing 913 tests still pass (backward compatibility)
- [ ] New tests cover: Keycloak token validation, SecretProvider, admin routes
