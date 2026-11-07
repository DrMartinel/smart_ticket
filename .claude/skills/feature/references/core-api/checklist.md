# core-api change checklist

Used by `/feature` (self-review) and `/review` (reviewing a diff) when
`services/core-api/` is touched. Answer each item that applies to the change.
**[regression]** means a hard rule or safety invariant: it must be fixed before
merge. **[convention]** means the house style: fix it unless there is a stated
reason not to.

Rules live in `CLAUDE.md` (hard rules, *Where to make a change*),
`.claude/skills/refactor/references/where-logic-goes.md` (layers),
`.claude/skills/refactor/references/readability.md` (general) and
`.claude/skills/refactor/references/checklist.md` (numbered items). Items that look
removable but aren't are listed in `.claude/skills/refactor/references/load-bearing.md`.

## Authority & safety

- [regression] A `Branch` is chosen only in `router.py`. `Router` stays pure: no I/O, no global config, data fetched before the call (hard rule 1).
- [regression] Nothing the LLM wrote is treated as a decision. `proposed_` fields stay prefixed and are never copied into a decision field unchecked (hard rule 5).
- [regression] `llm_self_confidence` enters no score and no route (ADR-0003).
- [regression] A `RunbookProposal` still always reaches a person (ADR-0006). Nothing goes around `runbooks.execute` / `runbooks.run`.
- [regression] Auto-reply authority comes only from a page's grant (`KbArticle.is_authorized()`), never from model output or a prompt.
- [regression] Going live still needs both `SHADOW_MODE` off and the branch's rollout flag (`Rollout.is_live`, ADR-0035).
- [regression] Raw PII is read only through `PiiReveal.reveal()`; no new `crypto.decrypt()` caller. Text a person writes is masked on the way in (`comments.add`, the masking path), never stored raw.
- [regression] Nothing from `load-bearing.md` was simplified away.

## Failure paths

- [regression] Every new failure path ends at HITL with a specific `ReasonCode` (added to the enum in `router.py` if new), never free text and never "assume it's fine" (hard rule 3).
- [regression] A mask or NER failure never resolves to "no PII found".
- [regression] A refusal raises the app's error type with its refusal code (a `StrEnum` in that app's `vocabulary.py`), so the client and the audit log can count it.

## Routes and access

- [regression] Every route has `auth=SessionAuth()` and `@require(Permission.…)`; access is never checked on a role name (ADR-0045).
- [regression] Every route declares its agent tier (`agent=AgentTier.…`, ADR-0046): `NONE` unless the F15 tier table names it.
- [regression] A new permission is a `Permission` URN with its `PermissionSpec` in `apps/accounts/utils/catalog.py`. A new route goes in `ADDED_SINCE_SNAPSHOT` in `apps/accounts/tests/test_access_equivalence.py`.
- [convention] The handler is thin: it takes the request schema, makes one call to a service, model or queryset method, and returns with `response=`. No handler builds a response dict (`where-logic-goes.md` rule 1).

## Where the change lives

- [regression] A status changes only through `lifecycle.move` / `system_move` / `automatic_move`; an assignee through `assignment`; a comment through `comments.add`; an incident link through `incidents`; a security event through `security_alerts.raise_`; a KB page's text through a draft (CLAUDE.md, *Where to make a change*).
- [regression] A notification goes through `notifier.emit` from the service that owns the event, with the event in the catalog and its seed migration.
- [convention] One-row rules on the model, which-rows on the queryset, cross-model work and side effects in a service class (`where-logic-goes.md` rules 1, 3–5).
- [convention] No helper with a single caller unless it is a named business rule; no more than 3 arguments passed through (rule 2).

## Config

- [regression] A tunable number is in `config/thresholds.yaml` with a field on `Thresholds` in `config/settings/base.py`, and the file's `version` is bumped (ADR-0044). Never a constant or a default argument (hard rule 2).
- [regression] An operational setting is in all three: the settings code (type only, no default), the root `.env.example` (value and why), and the service's `environment:` in `docker-compose.yml`. `apps/core/tests/test_settings_env.py` fails if they disagree.

## Data and schema

- [regression] A new model inherits `apps.core.models.BaseModel` (UUID primary key, ADR-0011) and sets `db_table` to the spec DDL's name.
- [regression] A migration exists for every model change (`make makemigrations`, then `manage.py makemigrations --check` is clean). What the ORM can't express is SQL in `infra/migrations/sql/` applied by `RunSQL` in `apps/dbextras/migrations/`.
- [regression] A new field on a persisted schema (JSON column, wire DTO) has a default so old rows still deserialize.
- [regression] An ai-engine wire change is in `infrastructure/dtos.py` **and** ai-engine's schema in the same PR (hard rule 4, ADR-0010).
- [regression] After a response or request schema change, `make types` was run and both `lib/types/generated.ts` files are committed, not hand-edited.
- [regression] A new grant to the ai-engine role keeps it read-only, apart from the two entity-graph exceptions (ADR-0004, ADR-0025, ADR-0037).

## Tests

- [regression] Each new failure path has a test that reaches HITL with the right `reason_code`, or the refusal with the right code.
- [regression] `masking.py` and `router.py` stay at 100% branch coverage (`make coverage`).
- [convention] Tests are named for the failure mode they prevent and pin the invariant, not the implementation; they sign in with `api_as`.
- [convention] Live-only behaviour uses `apps.rollout.testing.all_live(settings)`.

## Docs

- [convention] Changed documented behaviour updates the relevant `docs/` file; `docs/status.md` and `docs/TODO.md` change together.
- [convention] Comments and docstrings say **what** only; a removed why-comment's reason is in an ADR or `load-bearing.md`.
