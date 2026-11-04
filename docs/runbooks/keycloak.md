# Keycloak realm for Smart Ticket

What a Keycloak realm needs for phase 2 F13 sign-in (ADR-0032). The dev realm in
[`infra/keycloak/smart-ticket-realm.json`](../../infra/keycloak/smart-ticket-realm.json)
has all of it; a production realm needs the same, configured by IT.

## Clients

| Client | Type | Settings |
|---|---|---|
| `smart-ticket` (`OIDC_CLIENT_ID`) | Confidential, standard flow only | PKCE method S256; redirect URIs = `OIDC_REDIRECT_URIS` (each app's `/auth/callback`); front-channel logout off; back-channel logout URL `https://<core-api>/api/auth/oidc/backchannel-logout`, session not required |
| `smart-ticket-sync` (`KEYCLOAK_ADMIN_CLIENT_ID`) | Confidential, service account only | Service-account role `view-users` from `realm-management` |

Both secrets go in the environment (`OIDC_CLIENT_SECRET`,
`KEYCLOAK_ADMIN_CLIENT_SECRET`); production refuses the dev values.

## Roles and groups

Not read. Keycloak proves who a person is; their role and capabilities are
set in Admin → Settings → People (ADR-0042), and teams in Admin → Settings →
Teams (ADR-0041). A person's first company sign-in creates an employee
account. The client needs no role mapper.

## Realm settings

- Brute-force detection on (core-api has no lockout for Keycloak users).
- `KC_HOSTNAME` set to the address browsers use, so tokens' `iss` equals
  `OIDC_ISSUER_URL`; core-api reaches Keycloak at `OIDC_SERVER_URL`.
- Login theme `smart-ticket`: copy `infra/keycloak/themes/smart-ticket/` into
  the server's `themes/` directory (or the image), then select it under
  Realm settings → Themes. A production server caches themes, so restart it
  after a theme change.

## When something is wrong

| Symptom | Check |
|---|---|
| Everyone gets `idp_unavailable` | Keycloak reachable from core-api at `OIDC_SERVER_URL`; the sign-in page notices an outage within `OIDC_MIN_REFETCH_SEC` |
| Everyone gets `oidc_token_invalid` | `iss` in the token vs `OIDC_ISSUER_URL` (the hostname setting), the client id, server clocks (`OIDC_CLOCK_SKEW_SEC`) |
| A person gets `no_access` | The account is a break-glass or local one, which signs in at `/login?local=1` |
| A person signs in but sees only the employee pages | Their role in Admin → Settings → People |
| `identity_sync_failed` in the audit log | The sync client's secret and service-account roles; `accounts_identity_sync_runs.error` names the failure |
| Keycloak itself is down | A break-glass manager signs in at `/login?local=1`; every use alerts security |
