# ADR-0029: Rotating refresh tokens in httpOnly cookies

**Status:** Proposed
**Date:** 2026-10-15
**Touches:** `apps/accounts`, both frontends' `lib/session.ts`, every endpoint's auth

## Context

The frontends signed in through `/api/token/pair`, kept the access token in
`localStorage`, and threw the refresh token away. With ninja-jwt's default
five-minute access lifetime, staff were signed out every five minutes with
nothing to renew the token. Any script running on either app could read the
token from `localStorage`. Signing out only forgot the token in that browser:
the token itself worked until it expired, and nothing could end a sign-in on
another device.

## Decision

1. **Two tokens, two places.** `POST /api/auth/login` answers with a short-lived
   access token (`AUTH_ACCESS_TOKEN_LIFETIME_SEC`), which the frontend keeps in
   memory only. It also sets a refresh token as an httpOnly cookie scoped to
   `/api/auth/`, which no script can read and no other endpoint receives. A page
   load restores the session with `POST /api/auth/refresh`. The frontend
   refreshes 30 s before the access token expires, and once again on any 401
   before giving up.
2. **The refresh token is opaque and stored hashed.** It is a random 48-byte
   string; `accounts_refresh_sessions` stores its SHA-256 only.
3. **Every refresh rotates it, and a reuse ends the sign-in.** Each login starts
   a token *family*. A refresh marks the presented token used and issues a new
   one in the family. Presenting a used token is treated as theft: the whole
   family is revoked and a `security_alert` is audited. The one exception is a
   reuse within `AUTH_REFRESH_REUSE_GRACE_SEC` of the rotation: that is two tabs
   refreshing at once, and it gets an access token but no new cookie.
4. **A sign-in is idle-limited and age-limited.** A refresh token unused for
   `AUTH_REFRESH_IDLE_HOURS` expires. No sign-in outlives
   `AUTH_SESSION_MAX_HOURS`, however often it refreshes.
5. **Access tokens die with their sign-in.** Each access token carries its
   family (`sid`). `SessionAuth`, the auth class on every endpoint, refuses a
   token whose family has no live row. Signing out, signing out everywhere,
   ending a sign-in from `GET /api/auth/sessions`, or deactivating the user
   therefore stops that sign-in's access tokens at once, not when they expire.
   A token minted without a sign-in is refused, which is why `/api/token/*` is
   removed.
6. **One cookie per frontend.** `X-Auth-Client` (`admin` or `chat`) names the
   cookie (`st_refresh_admin`, `st_refresh_chat`), so both apps can be open in
   one browser on localhost. The custom header also forces a CORS preflight,
   so another origin cannot drive the cookie endpoints.
7. **CORS sends credentials** (`CORS_ALLOW_CREDENTIALS`) only to
   `CORS_ALLOWED_ORIGINS`. The cookie is `SameSite=Lax` and not `Secure` in
   local dev. `production.py` forces `Secure`.

## Consequences

- One indexed query per request (`SessionAuth`) buys immediate revocation.
- Scripts and curl sign in with `/api/auth/login` and send `X-Auth-Client`
  (README).
- Sign-ins, failures, sign-outs and reuse are in `audit_log`
  (`auth_login`, `auth_login_failed`, `auth_logout`, `security_alert`).
- Not done: a lockout after repeated failed passwords, and a UI listing the
  user's sign-ins (the API exists).
