/**
 * Authentication and authorization type definitions.
 *
 * Purpose:
 *   Define the shape of JWT claims, user identity, and auth context
 *   used throughout the frontend application.
 *
 * These types mirror the backend's AuthenticatedUser and JWT payload
 * from services/api/auth.py.
 */

/** JWT access token payload (decoded). */
export interface JwtPayload {
  /** Subject — user ULID. */
  sub: string;
  /** User role (operator, reviewer, admin, viewer). */
  role: string;
  /** User email address. */
  email: string;
  /** Space-separated scope list. */
  scope: string;
  /** JWT ID — unique token identifier. */
  jti: string;
  /** Issued at (Unix seconds). */
  iat: number;
  /** Expiration (Unix seconds). */
  exp: number;
  /** Not before (Unix seconds). */
  nbf: number;
  /** Issuer. */
  iss: string;
  /** Audience. */
  aud: string;
}

/** Authenticated user identity available to the UI. */
export interface AuthUser {
  userId: string;
  email: string;
  role: string;
  scopes: string[];
}

/** Token pair returned by the /auth/token endpoint. */
export interface TokenResponse {
  access_token: string;
  refresh_token: string;
  token_type: string;
  expires_in: number;
  scope: string;
}

/** OIDC discovery document (subset of fields used by the frontend). */
export interface OidcDiscovery {
  issuer: string;
  token_endpoint: string;
  revocation_endpoint: string;
  jwks_uri: string;
  userinfo_endpoint: string;
  grant_types_supported: string[];
  scopes_supported: string[];
}
