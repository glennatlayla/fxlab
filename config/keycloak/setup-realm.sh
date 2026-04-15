#!/usr/bin/env bash
# ------------------------------------------------------------------------------
# Keycloak post-init setup script.
#
# Runs AFTER Keycloak has imported the fxlab realm to:
#   1. Set the fxlab-api client secret from KEYCLOAK_API_CLIENT_SECRET env var.
#   2. Create the initial admin user from FXLAB_ADMIN_EMAIL / FXLAB_ADMIN_PASSWORD.
#
# Usage:
#   KEYCLOAK_URL=http://localhost:8080 \
#   KEYCLOAK_ADMIN=admin \
#   KEYCLOAK_ADMIN_PASSWORD=<admin-console-password> \
#   KEYCLOAK_API_CLIENT_SECRET=<generated-secret> \
#   FXLAB_ADMIN_EMAIL=admin@fxlab.io \
#   FXLAB_ADMIN_PASSWORD=<strong-temp-password> \
#     bash config/keycloak/setup-realm.sh
#
# All secrets come from environment variables — nothing is hardcoded.
# This script is idempotent: re-running it updates rather than duplicates.
# ------------------------------------------------------------------------------

set -euo pipefail

: "${KEYCLOAK_URL:?KEYCLOAK_URL is required}"
: "${KEYCLOAK_ADMIN:?KEYCLOAK_ADMIN is required}"
: "${KEYCLOAK_ADMIN_PASSWORD:?KEYCLOAK_ADMIN_PASSWORD is required}"
: "${KEYCLOAK_API_CLIENT_SECRET:?KEYCLOAK_API_CLIENT_SECRET is required}"

REALM="fxlab"
CLIENT_ID="fxlab-api"

# -- Obtain admin token --------------------------------------------------------

echo "[setup] Obtaining admin token from ${KEYCLOAK_URL}..."
TOKEN_RESPONSE=$(curl -sf -X POST \
  "${KEYCLOAK_URL}/realms/master/protocol/openid-connect/token" \
  -d "grant_type=password" \
  -d "client_id=admin-cli" \
  -d "username=${KEYCLOAK_ADMIN}" \
  -d "password=${KEYCLOAK_ADMIN_PASSWORD}")

ADMIN_TOKEN=$(echo "${TOKEN_RESPONSE}" | python3 -c "import sys,json; print(json.load(sys.stdin)['access_token'])")

if [ -z "${ADMIN_TOKEN}" ]; then
  echo "[setup] ERROR: Failed to obtain admin token." >&2
  exit 1
fi
echo "[setup] Admin token obtained."

# -- Set fxlab-api client secret -----------------------------------------------

echo "[setup] Looking up client ID for '${CLIENT_ID}'..."
CLIENT_UUID=$(curl -sf -H "Authorization: Bearer ${ADMIN_TOKEN}" \
  "${KEYCLOAK_URL}/admin/realms/${REALM}/clients?clientId=${CLIENT_ID}" \
  | python3 -c "import sys,json; clients=json.load(sys.stdin); print(clients[0]['id'] if clients else '')")

if [ -z "${CLIENT_UUID}" ]; then
  echo "[setup] ERROR: Client '${CLIENT_ID}' not found in realm '${REALM}'." >&2
  exit 1
fi

echo "[setup] Setting client secret for ${CLIENT_ID} (uuid=${CLIENT_UUID})..."
curl -sf -X PUT \
  -H "Authorization: Bearer ${ADMIN_TOKEN}" \
  -H "Content-Type: application/json" \
  "${KEYCLOAK_URL}/admin/realms/${REALM}/clients/${CLIENT_UUID}/client-secret" \
  -d "{\"type\":\"secret\",\"value\":\"${KEYCLOAK_API_CLIENT_SECRET}\"}" \
  > /dev/null 2>&1 || {
    # Fallback: update the client entity directly with the secret
    curl -sf -X PUT \
      -H "Authorization: Bearer ${ADMIN_TOKEN}" \
      -H "Content-Type: application/json" \
      "${KEYCLOAK_URL}/admin/realms/${REALM}/clients/${CLIENT_UUID}" \
      -d "{\"secret\":\"${KEYCLOAK_API_CLIENT_SECRET}\"}" \
      > /dev/null
  }
echo "[setup] Client secret set."

# -- Create initial admin user (if configured) ---------------------------------

if [ -n "${FXLAB_ADMIN_EMAIL:-}" ] && [ -n "${FXLAB_ADMIN_PASSWORD:-}" ]; then
  echo "[setup] Creating FXLab admin user ${FXLAB_ADMIN_EMAIL}..."

  # Check if user already exists
  EXISTING=$(curl -sf -H "Authorization: Bearer ${ADMIN_TOKEN}" \
    "${KEYCLOAK_URL}/admin/realms/${REALM}/users?email=${FXLAB_ADMIN_EMAIL}" \
    | python3 -c "import sys,json; print(len(json.load(sys.stdin)))")

  if [ "${EXISTING}" = "0" ]; then
    curl -sf -X POST \
      -H "Authorization: Bearer ${ADMIN_TOKEN}" \
      -H "Content-Type: application/json" \
      "${KEYCLOAK_URL}/admin/realms/${REALM}/users" \
      -d "{
        \"username\": \"${FXLAB_ADMIN_EMAIL}\",
        \"email\": \"${FXLAB_ADMIN_EMAIL}\",
        \"emailVerified\": true,
        \"enabled\": true,
        \"firstName\": \"FXLab\",
        \"lastName\": \"Admin\",
        \"credentials\": [{
          \"type\": \"password\",
          \"value\": \"${FXLAB_ADMIN_PASSWORD}\",
          \"temporary\": true
        }]
      }" > /dev/null

    # Assign admin realm role
    USER_UUID=$(curl -sf -H "Authorization: Bearer ${ADMIN_TOKEN}" \
      "${KEYCLOAK_URL}/admin/realms/${REALM}/users?email=${FXLAB_ADMIN_EMAIL}" \
      | python3 -c "import sys,json; users=json.load(sys.stdin); print(users[0]['id'] if users else '')")

    ADMIN_ROLE=$(curl -sf -H "Authorization: Bearer ${ADMIN_TOKEN}" \
      "${KEYCLOAK_URL}/admin/realms/${REALM}/roles/admin")

    if [ -n "${USER_UUID}" ] && [ -n "${ADMIN_ROLE}" ]; then
      curl -sf -X POST \
        -H "Authorization: Bearer ${ADMIN_TOKEN}" \
        -H "Content-Type: application/json" \
        "${KEYCLOAK_URL}/admin/realms/${REALM}/users/${USER_UUID}/role-mappings/realm" \
        -d "[${ADMIN_ROLE}]" > /dev/null
      echo "[setup] Admin role assigned to ${FXLAB_ADMIN_EMAIL}."
    fi
    echo "[setup] Admin user created (temporary password — must change on first login)."
  else
    echo "[setup] Admin user ${FXLAB_ADMIN_EMAIL} already exists, skipping."
  fi
else
  echo "[setup] FXLAB_ADMIN_EMAIL/PASSWORD not set, skipping admin user creation."
fi

echo "[setup] Keycloak realm setup complete."
