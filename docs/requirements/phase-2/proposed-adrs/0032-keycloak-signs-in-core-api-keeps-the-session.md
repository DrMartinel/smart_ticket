# ADR-0032: Keycloak signs people in; core-api keeps the session

**Status:** Proposed (phase 2 pack, stage 2). Moved to [`docs/adr/0032-keycloak-signs-in-core-api-keeps-the-session.md`](../../../adr/0032-keycloak-signs-in-core-api-keeps-the-session.md); its status there is the one that counts
**Date:** 2026-10-17
**Builds on:** ADR-0029 (rotating refresh tokens in httpOnly cookies)
**Feature:** F13 ([spec](../06-F13-identity.md))

## Context

Users are created by hand with local passwords. A real organization needs
directory sign-in, lockout, and fast deprovisioning. ADR-0029 gives
immediate revocation because every request checks a live token family in
core-api's own table.

## Decision

1. **OIDC authorization code with PKCE.** The browser carries only the
   one-time code. core-api exchanges it as a confidential client, verifies
   the ID token (JWKS signature, `iss`, `aud`, `exp`, `nonce`) and keeps no
   Keycloak token afterwards.
2. **core-api then starts an ADR-0029 session**, unchanged: access token in
   memory, rotating refresh token in an httpOnly cookie per app,
   `SessionAuth`'s live-family check.
3. **Rights come from claims** at each sign-in: one primary role (zero or
   several → refused), capabilities, team groups (ADR-0031).
4. **Deprovisioning:** Keycloak back-channel logout revokes all families at
   once; a sync task every 5 minutes deactivates disabled users and revokes
   sessions whose rights shrank. A failed Keycloak read deactivates nobody.
5. **Local passwords** only for at most two flagged break-glass `manager`
   accounts; each use alerts `security`.

## Consequences

- Keycloak outage blocks new sign-ins only; live sessions continue to their
  ADR-0029 limits.
- Brute-force protection moves to Keycloak (closes ADR-0029 "not done").
- Realm configuration is documented in a runbook; it is part of the system.
