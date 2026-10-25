# Keycloak realm for Smart Ticket

What a Keycloak realm needs for phase 2 F13 sign-in (ADR-0032). The dev realm in
[`infra/keycloak/smart-ticket-realm.json`](../../infra/keycloak/smart-ticket-realm.json)
has all of it; a production realm needs the same, configured by IT.

## Clients

| Client | Type | Settings |
|---|---|---|
| `smart-ticket` (`OIDC_CLIENT_ID`) | Confidential, standard flow only | PKCE method S256; redirect URIs = `OIDC_REDIRECT_URIS` (each app's `/auth/callback`); front-channel logout off; back-channel logout URL `https://<core-api>/api/auth/oidc/backchannel-logout`, session not required |
| `smart-ticket-sync` (`KEYCLOAK_ADMIN_CLIENT_ID`) | Confidential, service account only | Service-account roles from `realm-management`: `view-users`, `query-users`, `view-clients`, `query-clients`, `query-groups` |

Both secrets go in the environment (`OIDC_CLIENT_SECRET`,
`KEYCLOAK_ADMIN_CLIENT_SECRET`); production refuses the dev values.

## Roles, groups and mappers

- **Client roles on `smart-ticket`:** exactly one primary role per person
  (`employee`, `technician`, `manager`, `security`) plus any capabilities
  (`workflow_admin`, `kb_editor`, `incident_manager`). No role is refused as
  `no_access`; two primary roles as `ambiguous_role`, with a security alert.
- **Groups:** `/it/<team>` makes a member and `/it/<team>/lead` a lead of the
  core-api team with that slug. Other groups are ignored and audited.
- **Mappers on `smart-ticket`, added to the ID token:** a client-role mapper with
  claim `resource_access.smart-ticket.roles`, and a group-membership mapper with
  full paths, claim `groups`.

## Realm settings

- Brute-force detection on (core-api has no lockout for Keycloak users).
- `KC_HOSTNAME` set to the address browsers use, so tokens' `iss` equals
  `OIDC_ISSUER_URL`; core-api reaches Keycloak at `OIDC_SERVER_URL`.

## When something is wrong

| Symptom | Check |
|---|---|
| Everyone gets `idp_unavailable` | Keycloak reachable from core-api at `OIDC_SERVER_URL`; the sign-in page notices an outage within `OIDC_MIN_REFETCH_SEC` |
| Everyone gets `oidc_token_invalid` | `iss` in the token vs `OIDC_ISSUER_URL` (the hostname setting), the client id, server clocks (`OIDC_CLOCK_SKEW_SEC`) |
| A person gets `no_access` | Their `smart-ticket` client role, and the client-role mapper's "add to ID token" |
| `identity_sync_failed` in the audit log | The sync client's secret and service-account roles; `accounts_identity_sync_runs.error` names the failure |
| Keycloak itself is down | A break-glass manager signs in at `/login?local=1`; every use alerts security |
