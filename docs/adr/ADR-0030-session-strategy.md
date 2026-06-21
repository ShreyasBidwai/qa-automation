# ADR-0030: Authentication uses server-side opaque sessions (not JWT)

- Status: Accepted
- Date: 2026-06-21
- Deciders: Engineering

## Context

B2 adds email/password authentication: sign up / in / out, and a session the SPA
sends on protected requests. The choice is **stateless JWT** vs **server-side
opaque sessions** (a `sessions` table). Password hashing is settled separately
(argon2id via `argon2-cffi` — modern, memory-hard, no bcrypt 72-byte truncation).

## Decision

**Server-side opaque sessions.** Sign-in mints a random 256-bit token
(`secrets.token_urlsafe(32)`), persists a `sessions` row, and returns the token;
the client sends it as `Authorization: Bearer <token>`.

- **Hashed at rest.** Only `sha256(token)` is stored (`sessions.token_hash`,
  unique). A DB leak does not expose live sessions, and we never log the token.
- **Lookup.** Each protected request hashes the bearer token, loads the session by
  hash (one indexed query), checks `expires_at`, loads the user.
- **Sign-out really works.** It deletes the session row → the token is dead
  immediately. Password reset deletes *all* of a user's sessions.
- **Expiry** is `session_ttl_seconds` (default 14 days), enforced on read.

## Why not JWT

A JWT is valid until it expires; you cannot revoke one without a server-side
denylist — which is itself server state, so "stateless" JWT + working logout
collapses back into server state anyway. For a product where **sign-out and
session revocation must be real** (shared/demo boxes, password reset must kill old
sessions), an opaque session table is simpler and honest: revocation is a `DELETE`.
We already run Postgres; one indexed lookup per request is negligible, and there's
no signing-key management or token-bloat. JWT's only real win (no DB read) doesn't
pay for the revocation complexity here.

## Consequences

- Real logout + reset-time revocation; expiry tunable by config, not baked into a
  signed token.
- One indexed `sessions` lookup per authenticated request (cheap; add cleanup of
  expired rows later — expiry is already enforced on read, so stale rows are inert).
- Bearer-token-in-header (not a cookie) → no CSRF surface for this pure-API flow;
  the SPA stores the token and attaches it via the typed client.
- Token transport is opaque and swappable; if we ever need stateless edge auth,
  JWTs can be layered on without changing the session model.
