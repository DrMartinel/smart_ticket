# Dev Keycloak realm

`smart-ticket-realm.json` is imported by the compose `keycloak` service
(profile `sso`) on first start: `docker compose --profile sso up -d keycloak`,
then http://localhost:8081 (admin console at `/admin`, credentials from `.env`).

It holds the two clients core-api uses (`smart-ticket`, `smart-ticket-sync`),
the client roles F13 maps (four primary roles, three capabilities), the
`/it/<team>[/lead]` groups, and test users from the phase 2 pack's mock data
(`docs/requirements/phase-2/06-00-conventions.md` §6.0.5) plus `no.role` and
`two.roles` for the refusal paths. Every test user's password is `change-me`.
Client secrets are `${…}` placeholders Keycloak fills from the container's
environment, i.e. from `.env`.

Dev only. Production realms are configured as `docs/runbooks/keycloak.md` says.
