# Recipe: add or change a core-api route

Exemplars: `apps/teams/views.py` (CRUD and queues), `apps/requester/views.py`
(a requester's own rows), `apps/accounts/permissions.py` (the gate).

1. **Schema.** Request shape in the app's `request_schema.py`, response shape in
   `response_schema.py`. Field checks only (`Field(min_length=…)`), no database access.
2. **Permission.** Pick an existing `Permission` URN from
   `apps/accounts/utils/catalog.py`. A new one needs its `PermissionSpec` there and
   a seed for the roles that hold it. Never check a role name (ADR-0045).
3. **Agent tier.** Declare `agent=AgentTier.…` (ADR-0046). `NONE` unless the F15
   tier table (`docs/requirements/phase-2/06-F15-agent.md` §h.3) names the route.
4. **Handler.** `@router.<verb>(…, auth=SessionAuth(), response=…)` then
   `@require(Permission.…)`. The body calls one service, model or queryset method
   and returns its result. Ticket-scoped work checks the ticket with
   `request.auth.require_covering(…)`.
5. **The work.** In the layer that owns it (`where-logic-goes.md`). A status,
   assignee, comment, incident link or security event changes only through its
   service (CLAUDE.md, *Where to make a change*). A refusal raises the app's error
   with a code from its `vocabulary.py`.
6. **Access snapshot.** Add the route to `ADDED_SINCE_SNAPSHOT` in
   `apps/accounts/tests/test_access_equivalence.py`.
7. **Tests**, failure paths first: refused without the permission (403 and the
   refusal code), refused for the wrong scope, each service refusal, then the
   happy path. Sign in with `api_as`.
8. **Types.** `make types`; commit both `lib/types/generated.ts`.
9. **Frontend.** If a console page calls it, gate the control with `can()` in
   `lib/permissions.ts` (see `../web/checklist.md`).
