# CLAUDE.md

Guidance for Claude Code working in this repository.

## What this is

Smart Ticket Triage — AI-assisted IT support ticket classification, routing, and
(eventually) auto-reply, with human-in-the-loop guardrails at every step.
Implements [`requirement.md`](requirement.md) (Architecture Specification v2, in
Vietnamese). Section references in code and docs (`§5`, `§8`, `§10.3`) point back
to it; it is the source of truth for *intent*.

## The organizing principle — read this before changing anything

> **The LLM produces proposals. Deterministic code makes decisions.**

Nearly every structural choice in this repo follows from wanting that boundary to
hold while prompts, models, and retrieval all change underneath it. Three
mechanisms enforce it at three levels:

| Level | Mechanism |
|---|---|
| Types | Every LLM-authored field is prefixed `proposed_` |
| Code | `router.py` is the only place a `Branch` is chosen, by a pure `Router` built from the thresholds |
| Database | `ai-engine` connects as a role that can only `SELECT`, except that the offline entity-graph build replaces its own `kb_article_associations` rows (ADR-0025) |

Things that look needlessly indirect — the `proposed_` prefixes, auto-reply
authority living on KB rows instead of in model output, a pure router built
from thresholds passed in — exist to stop the LLM from quietly acquiring
authority it was never granted. **Check the ADRs and
[`load-bearing.md`](.claude/skills/refactor/references/load-bearing.md) before
simplifying:** they record what breaks without it. Code comments don't (see
*Comments and docstrings*).

## Hard rules (violating these is a regression, not a style choice)

1. **`router.py` stays pure.** `Router` is a frozen object built from the
   thresholds (no default); `Router(th).route(...)` does no I/O and imports no
   global config. Need data for a decision? Fetch it *before* the call
   and pass it. This is what makes every branch testable with no DB, model, or
   network — and what lets decisions be replayed against
   `routing_decisions.thresholds_used`.
2. **No magic numbers.** Every tunable lives in
   [`thresholds.yaml`](services/core-api/config/thresholds.yaml) — not a
   constant, not a default argument. Timeouts, connect budgets and other
   operational settings go in the root `.env.example` (below), never as a
   default in settings code or docker-compose.yml.
3. **Degrade toward humans.** Every new failure path routes to HITL with a
   specific `ReasonCode` (add it to the enum — the dashboard is built on the
   enum, free text is invisible to it). Never toward "assume it's fine."
   `mask_failed` resolving toward "no PII found" is the single worst regression
   possible here.
4. **No shared contracts package (ADR-0010).** Each schema is defined in the
   module that uses it (the ADR has the table). The ai-engine wire shapes exist
   in both services — core-api `infrastructure/dtos.py`; in ai-engine,
   `schemas.py` for the HTTP bodies and the graph's own `graph/ticket.py`,
   `graph/nodes/infer/proposals.py` and `graph/nodes/emit_signals/signals.py`
   for what they carry — so change **both in the same PR**; until the cross-service
   integration tests exist, nothing else catches drift. Never define routing or
   scoring types (`Branch`, `ReasonCode`, `TrustScore`, …) in ai-engine, and
   never put a type `router.py` needs in a Django `models.py`. After a core-api
   schema change, regenerate TS types; never hand-edit
   `lib/types/generated.ts` in `services/admin-console` or `services/chat`. New fields on persisted schemas need
   a **default** so old rows still deserialize.
5. **`proposed_` prefixes are load-bearing.** Don't strip them "for consistency."
   The asymmetry between `proposal.proposed_intent` and `decision.branch` is the point.
6. **`llm_self_confidence` never enters the trust score or routing** (ADR-0003).
   A test exists whose only job is to fail if someone adds it back.
7. **`RunbookProposal` always goes to HITL** (ADR-0006). No threshold, no
   config flag, no exception. Changing this requires a new ADR that explicitly
   supersedes 0006.
8. **Retrieval thresholds compare against the reranker's score (Jev's,
   ADR-0015), never the cross-encoder's or the RRF fusion score** (ADR-0005).
   RRF is rank-derived; its magnitude means nothing. The cross-encoder only
   orders the pool and picks Jev's shortlist.
   Any PR touching `graph/nodes/retrieve/` / `graph/nodes/candidate_pool/` / `graph/nodes/rerank/` needs this check —
   the bug it prevents does not fail loudly.
9. **Never lower an eval floor to make CI green.** Not the per-category F1 floor,
   not the auto-reply precision floor, and don't average per-category F1 or drop
   a category. Baseline updates require review by someone other than the author.

## Commands

```bash
uv sync --all-packages            # NOT plain `uv sync` — see Gotchas
cd services/admin-console && npm install
cd services/chat && npm install
```

core-api's commands are targets in [`services/core-api/Makefile`](services/core-api/Makefile);
run `make` there to list them. Its recipes are the canonical spelling. It does
not export `DJANGO_SETTINGS_MODULE` (that would override `pytest.ini`'s test settings).

**Settings come only from the root `.env`** (git-ignored) and real
environment variables, which win; an empty value counts as unset. Neither the
settings code nor `docker-compose.yml` holds a default, and nothing reads the
root `.env.example`: it is the template (`cp .env.example .env`, needed for
pytest too), documenting every setting, its shipped value and why. Its values
point at the Dockerized Postgres/Redis on host ports; compose passes each
container an **allowlist** of its own settings from `.env` and sets the
container wiring itself. A new setting goes in the settings code (type only),
`.env.example` (value and why), **and** that service's `environment:` in
`docker-compose.yml`; tests fail if any of the three disagree. A value
changed in `.env.example` doesn't reach an existing `.env`: diff after
pulling. ai-engine's DSN is `AI_ENGINE_DATABASE_URL`, never `DATABASE_URL`
(core-api's read-write role, ADR-0004), and its container never receives the
latter. `thresholds.yaml` is separate and stays where it is.
Extra arguments go in `ARGS=`, e.g. `make test ARGS="-k router -x"`.

```bash
cd services/core-api
make test           # unit tests (DB tests use the Dockerized Postgres)
make coverage       # masking + router at 100%, the contractual gate
make typecheck      # mypy + django-stubs; config in root pyproject.toml, version pinned by uv.lock
make lint           # ruff check + format --check, pinned to match lint.yml
make check          # lint + typecheck + test
make runserver      # :8000; also: worker, beat, shell
make makemigrations / make migrate
make load-demo-kb ARGS="--approver manager1"   # demo KB, see demo_kb/README.md;
                    # then ai-engine's build --rescore-only writes the entity-graph edges
make types          # regenerate web TS types after any contract change
```

Whole workspace, from the repo root:

```bash
uv run pytest                              # everything (unit + eval)
uv run pytest services/ai-engine/tests -q
uv run pytest evals/suites -q              # 9 files; live ones skip if ai-engine is down
uv run mypy                                # all three packages
```

Full stack (7 containers + the `vllm` profile for models). Migrations run automatically on `core-api` start:

```bash
cp .env.example .env && docker compose up -d --build
```

ai-engine against the Dockerized stack:

```bash
uv run --project services/ai-engine uvicorn ai_engine.main:app --app-dir services/ai-engine/src --port 8001 --reload
```

CI (`.github/workflows/`) spells its commands out instead of calling the
Makefile, so keep the two in step when you change one.

Ports: web 3000, core-api 8000, ai-engine 8001, **Postgres 5434**, **Redis 6380**
(host-published to avoid collisions; internally still `db:5432` / `redis:6379`).

## Layout

| Concern | Path |
|---|---|
| The routing decision (a pure `Router`, the only place a `Branch` is chosen) | [router.py](services/core-api/apps/tickets/utils/router.py) |
| PII masking (inline, two-tier; 100% branch coverage is a release gate) | [masking.py](services/core-api/apps/tickets/utils/masking.py) |
| Trust score (in core-api, so the LLM can't score itself) | [trust_scorer.py](services/core-api/apps/tickets/utils/trust_scorer.py) |
| What happens to a ticket after submit (embed → incident check → ai-engine → score → route → act) | [pipeline.py](services/core-api/apps/tickets/utils/pipeline.py) |
| `AIEngineClient`, core-api's only route to ai-engine and, through it, to every model (ADR-0012; transport only, never judgement) | [infrastructure/](services/core-api/infrastructure/) |
| PII regex patterns | [patterns.py](services/core-api/apps/tickets/utils/patterns.py) |
| Every tunable number | [thresholds.yaml](services/core-api/config/thresholds.yaml) |
| Operational settings and their defaults (URLs, models, timeouts, top-k), for both services and compose | [.env.example](.env.example) |
| The Docker stack | [docker-compose.yml](docker-compose.yml) (repo root; DB image and raw SQL in [infra/](infra/)) |
| ai-engine wire schema (`AIRunRequest`/`AIRunResponse`, proposals, signals, embed/NER bodies) | core-api [dtos.py](services/core-api/infrastructure/dtos.py) · ai-engine [schemas.py](services/ai-engine/src/ai_engine/schemas.py) (HTTP bodies), [ticket.py](services/ai-engine/src/ai_engine/graph/ticket.py), [proposals.py](services/ai-engine/src/ai_engine/graph/nodes/infer/proposals.py), [signals.py](services/ai-engine/src/ai_engine/graph/nodes/emit_signals/signals.py) |
| The AI pipeline (LangGraph) | [graph/triage.py](services/ai-engine/src/ai_engine/graph/triage.py) |
| Prompts and Jev's questions (versioned `.md` / `.json`, eval-gated like code) | [core/prompts/](services/ai-engine/src/ai_engine/core/prompts/) |
| Reviewer-facing explanation | [TrustSignalsPanel.tsx](services/admin-console/components/TrustSignalsPanel.tsx) |
| Raw SQL (grants, CHECKs, HNSW, triggers) | [infra/migrations/sql/](infra/migrations/sql/) |
| Golden set + baselines + calibration scripts | [evals/](evals/) |
| KB source snapshot (AWS docs; fetcher, sources, manifest) | [demo_kb/](demo_kb/) |
| Ticket lifecycle after triage: workflows, transitions, rules, actions (ADR-0028) | [apps/lifecycle/](services/core-api/apps/lifecycle/), the engine in [engine.py](services/core-api/apps/lifecycle/utils/engine.py) |

Services: `core-api` (Django + Ninja) owns **every decision and every write
but one** (the `entity_graph` association rows, written by ai-engine's
offline build, ADR-0025) · `ai-engine` (FastAPI + LangGraph) has **no
authority**, returns signals and a proposal only, writes nothing while
triaging, and is the **only vLLM client** (ADR-0012: core-api's embeddings
and PII NER go through its `/v1/embed` and `/v1/pii/detect`) · `web` (Next.js) is a thin client with no business logic.

**If you are adding a feature that decides something, it belongs in core-api.**

### Where logic goes

Logic lives with the data it describes: rules about one row go on the model,
which rows count goes on the queryset, and work across several models goes
in a service class. Endpoints and schemas stay thin.

**1. Each piece goes in the layer that owns it.** Inside core-api, each app has:

| Layer | Module | Owns | Example |
|---|---|---|---|
| Endpoint | `views.py` | HTTP only: take the request schema, call a service class, model or queryset method, return the result with `response=` | a handler that validates the body and makes one call |
| Schema | `request_schema.py` / `response_schema.py` | Shape and field checks; no database access. No handler builds a response dict | `subject: str = Field(min_length=3, max_length=200)` |
| Model method | `models.py` | Rules about **one row**, from its own fields plus arguments | `article.chunks_are_current()` |
| QuerySet method | `models.py` | **Which rows** count | `ReviewItem.objects.for_queue(...)`, `FewshotExample.objects.active_for_category(...)` |
| Service class | `utils.py` or `utils/` (this repo's `services.py`) | Work across several models, transactions, and side effects (ai-engine calls, Celery, email) | the per-ticket run in `pipeline.py` (module functions today, see below) |
| Pure decision | `utils/` | A decision with no I/O | `router.py` (rule 1), `trust_scorer.py`, `masking.py` |
| Task | `tasks.py` | Celery entry points only; the work lives in services | `process_ticket` |

**2. Extract by meaning, not by how often code is used.** Extract a block
when it is a named business rule, has its own edge cases, or deserves its
own test. Inline it when the body is 1–3 obvious lines and the name would
restate them. If an extracted function needs more than 3 arguments passed
through, the cut is wrong: move the boundary or inline it.

**3. A private `_helper` is the last resort.** Before writing one, ask in
order: is it about one row (model method)? About which rows (queryset
method)? Otherwise, a method on the class that owns the data or the work (in
core-api, a service class in `utils`), named as a domain action. A module-level
function only for generic work tied to no use case or model, such as building a
regex or finding a pattern in a string (`normalize_ws` in `validate.py`).

**4. A class has to earn it.** Use one when it holds state or groups several
behaviours around one thing. A class with a single public method
(`OrderService.create()`) hasn't earned one: its method goes on the class that
owns that data or work (rule 3).

**5. Model methods stay pure-ish.** They don't touch `request`, write to
other models, call external systems (ai-engine, HTTP, Celery, email), or run
queries inside a `@property` (one extra query per row in a loop). Those go in
service classes.

Code that predates these rules:
- Model methods that break rule 5: `KbArticle.set_auto_reply_allowed` and
  `set_risk_tier` (write `KbAuthorityLog`), `ReviewItem.decide` (writes
  `ReviewDecision`, `EvalCandidate`).
- Manager methods that write, which rule 1 puts in service classes:
  `Ticket.objects.submit` (writes `AuditLog`, queues a task),
  `KbArticle.objects.create_and_ingest` / `upsert_from_source`,
  `Incident.objects.get_or_create_for_mass_incident`,
  `AuditLog.objects.record`.

- `utils/pipeline.py` and the other `utils` modules: use-case module-level
  functions, which rule 3 puts on a service class.

Move each to a service class when you next change it, keeping every
write in its current transaction (the authority log row is ADR-0002).

`apps/core` is the shared foundation: abstract `BaseModel`, middleware,
ops commands (`wait_for_db`), generic test helpers. Every app may import
from it; it imports from no app (`apps/core/tests/test_boundary.py`).
The role gate (`require_role`, `AuthedRequest`) lives in
`apps/accounts/permissions.py`, beside the `User` and `UserRole` it checks;
it can't live in `core`, which may not import `accounts`. Beside `apps/` sit
`infrastructure/` (the ai-engine client, with its wire schema in `dtos.py`) and
`config/settings/{base,development,production,test}.py`. Tests live in a
`tests/` package next to the code they test.

## Where to make a change

| To change… | Go to |
|---|---|
| When something is auto-replied | `thresholds.yaml`, or `kb_articles.auto_reply_allowed` — **not** the prompt |
| How a branch is chosen | `router.py` (and add branch tests) |
| What a degraded ticket run records, or a new `degraded_reason` from ai-engine | `apps/tickets/utils/pipeline.py` — not `tasks.py`, which is only the entry point |
| What the model is asked | `ai-engine/core/prompts/*.md` — bump the version in filename and `PROMPT_VERSION` in `.env.example` (and your `.env`) |
| What Jev is asked | `ai-engine/core/prompts/*.json` — bump the version in filename and `RERANK_PROMPT_VERSION` or `CATEGORY_QUESTION_VERSION` the same way |
| What counts as PII | `patterns.py` (regex) or the NER prompt `ai-engine/core/prompts/pii_ner.v*.md` |
| What is in the demo KB | `demo_kb/sources.json` (then `fetch.py`), approvals and risk tiers in `demo_kb/curation.json` — never by editing fetched pages |
| The entity-graph edges link expansion follows | ai-engine `core/associations/build.py`, which writes them; after `load-demo-kb`, its `--rescore-only` (`demo_kb/README.md`) |
| How relevance is judged | ai-engine `graph/nodes/retrieve/`, `graph/nodes/candidate_pool/` (shortlister), `graph/nodes/rerank/` (Jev) |
| How the category is chosen | ai-engine `graph/nodes/classify_category/` and its question `core/prompts/category.v*.json`; the confidence bar in `thresholds.yaml` |
| Any tunable number | `thresholds.yaml`, nowhere else |
| Sign-in, token lifetimes, who may call what | `apps/accounts/utils.py` (sessions), `SessionAuth` in `apps/accounts/permissions.py`, `AUTH_*` in `.env.example` (ADR-0029); the frontends' `lib/session.ts`, never `localStorage` |
| A ticket's status | `lifecycle.system_move` from pipeline code, `lifecycle.move` for a person: never `ticket.status = …` (ADR-0028) |
| What a workflow action can do | `apps/lifecycle/utils/actions.py` (a handler and an `ActionCode`); rules and events in `utils/rules.py` |

**Workflows** (`.claude/skills/`, usage in [`.claude/README.md`](.claude/README.md)):
`/ai-engine-feature` for any ai-engine change · `/ai-engine-review` before a PR ·
`/refactor` for behaviour-preserving cleanup in any Python service. The
repo-wide style guide is `.claude/skills/refactor/references/readability.md`.

DB fields: edit the model, then `makemigrations` / `migrate` via
`services/core-api/manage.py`. Table and column names mirror the spec DDL via
`db_table` — keep that alignment, `infra/migrations/sql/` is written against
those exact names. Things the ORM can't express go in `infra/migrations/sql/`
applied via `RunSQL` in `apps/dbextras/migrations/` (the core-api Dockerfile
copies that directory — a new SQL file that isn't copied fails at container start).

## Current state

- `SHADOW_MODE=true` is the default: the router decides and records, humans still
  handle every ticket. This is spec §14's P1 phase, by design.
- **Demo KB is English AWS documentation** (`demo_kb/`: every page of 12 AWS
  guides, 3,542 pages), loaded by `manage.py load_demo_kb`.
  Demo tickets and the golden set are English. The snapshot is frozen: pages
  are checked against `manifest.json`, and each auto-reply approval in
  `curation.json` is pinned to the SHA-256 of the reviewed text. Every low-
  and medium-risk page is approved (2,892 of 3,542, ADR-0027, a departure
  from spec §14 P4); high-risk pages are not.
- **Eval gates** ([`evals/HISTORY.md`](evals/HISTORY.md)): the last full run
  (2026-10-14 (2), `rerank_choice.v1`, `category.v2`) passes every gate it
  measured: retrieval recall@5 **0.924**, auto-reply precision **0.992**
  (119/120), per-category F1 ≥ 0.90 on Jev's choice, refusal and injection
  1.00. Its end-to-end suite ran in two parts (DeepSeek's balance ran out
  at g519; rerun after the top-up): 154 of 157 auto-replies right, the
  wrong three labelled `clarify` (g156, g626, g630); branch accuracy about
  0.52, mostly auto-replies Jev's confidence bar sends to a person. `category.v2` was
  written against the golden set, so it still needs a held-out check. 40
  drafted tickets carry a reviewed category (`evals/golden/SCHEMA.md`). Record
  every full run in `evals/HISTORY.md`; runs before the 2026-10-01 baseline
  are in `evals/HISTORY-archive.md`, read-only.
- Trust score coefficients are a **hand-set prior**, not fitted. `t_auto = 0.88`
  and `t_route = 0.72` are placeholders (marked 🔧 in `thresholds.yaml`).
  Calibration needs ≥500 shadow pairs. Do not enable P3/P4 before that.
  The `bm25_keyword_hit` feature is gone with BM25 on the ticket (ADR-0020,
  Proposed), and the remaining hand-set features score every ticket.
- **Retrieval drafts first** (HyDE, ADR-0021, Proposed): `draft_answer` has
  the chat model write the passage it expects would answer the ticket;
  retrieval fuses vector search on the ticket with BM25 and vector search on
  the draft, and each page's chunks nearest the draft join the pool. The
  cross-encoder and Jev still score against the ticket. A failed draft is a
  500 → HITL. Each model job has its own setting: the proposal
  `CHAT_CLIENT_PROVIDER`, the draft `DRAFT_CLIENT_PROVIDER`, PII NER
  `NER_CLIENT_PROVIDER` (raw text leaves only with `deepseek` there,
  ADR-0019). Production drafts on DeepSeek (ADR-0022; the template ships
  `vllm` so a copy boots without a key): recall@3 0.866 vs 0.816 on Qwen.
- **The retrieval gate is recall@5** since 2026-10-12, as spec §12.2 names
  it: the proposal is shown Jev's top 5 (`RERANK_TOP_N=5`). Latest, entity
  graph and DeepSeek drafting: recall@5 0.900, recall@3 0.866 (reported,
  ungated). `report.py`'s baseline comparison still reads recall@3:
  changing `baseline.json` needs a reviewer other than the author.
- Every run shortlists, then reranks: the shortlister, a cross-encoder (`vllm`,
  bge-reranker-v2-m3; `lexical` for CI/offline), orders the fused candidates plus
  link-expanded chunks, and **Jev**, the reranker (hosted, needs `JEV_API_KEY`),
  answers one choice question over its top 15 (`RERANK_POOL`, ADR-0026,
  Proposed): each chunk's probability is its score, and `none` is below the
  floor. An auto-reply must cite Jev's chosen page with confidence ≥
  `retrieval.min_rerank_confidence` (0.9 🔧), else HITL `rerank_disagrees` /
  `rerank_low_confidence`. The floor reads Jev's passages' total
  (`retrieval.floor` 0.6 🔧, chosen 2026-10-14 from golden-set data); a
  clarify's buttons come from Jev's yes/no score per page, asked only for a
  validated clarify. `retrieval.margin` and the trust weights are still on
  the old noul scale. Trust coefficients and `t_auto`/`t_route` were hand-set for
  the cross-encoder's `rerank_top1`: another reason P3 waits. Every ticket's
  *masked* text goes to Jev's API.
- **Jev also chooses the category** (ADR-0017, Proposed): `classify_category`
  asks it one choice question after reranking; the router routes auto-route
  and clarify on that choice and sends it to a human below
  `classification.min_confidence` (0.65 🔧) as `category_low_confidence`.
  The LLM no longer proposes a category (`propose.v8`). A Jev failure, reranking or
  category, is a 500 → HITL `ai_engine_unavailable`, never a fallback.
- **`clarify`** (ADR-0016, ADR-0023, Proposed): the router can choose to
  ask the requester which shown page they mean. A live chat ticket shows
  the question; the answer is masked like a ticket and the pipeline runs
  again, and a second `clarify` goes to a person (`clarify_round_cap`).
  Unanswered after `clarification.wait_minutes`, the chat offers a ticket.
  Form tickets and shadow mode: a review item in the `clarification` queue.
- PII quarantine **read** path is done (phase 2 F5): `PiiReveal.reveal()` in
  `apps/tickets/utils/pii_reveal.py` is the only `decrypt()` caller
  (`test_decrypt_has_one_caller`). **Never add another `decrypt()` call; anything
  that needs a raw value goes through `PiiReveal`, which writes the `PiiAccessLog`
  row in the same transaction, with a reason.**
- Golden set is **synthetic**. A passing eval means "the wiring didn't regress,"
  never "the model is good."

## Gotchas

| Symptom | Cause |
|---|---|
| `Failed to spawn: pytest` | `uv sync` instead of `uv sync --all-packages` — the root project has no deps of its own |
| `ModuleNotFoundError: tests.*` on a whole-workspace run | core-api and ai-engine both have a package named `tests`. Handled by `--import-mode=importlib` in root `pyproject.toml` — don't remove it |
| Every ticket `mask_failed` | ai-engine is down, or vllm-chat isn't reachable from it, or ai-engine's `CHAT_MODEL` doesn't match what it serves. **Never "fix" this by treating NER failure as no-PII-found** |
| Submit hangs ~120s | Connect and read timeouts collapsed into one. Deliberately separate: 3s connect, 120s read (a cold model load legitimately takes 15–20s) |
| Every generation check ✗ | No LLM ran — refuse-before-LLM. Read the reason code |
| Unaccented Vietnamese matches nothing | Diacritic folding (`LexicalShortlister._tokenize`) regressed; `đ`/`Đ` need special handling |
| Port 5432/6379 fails | Host ports are **5434** / **6380** |
| Every API call 401s with a token that looks valid | The token was not issued by `/api/auth/login` (no `sid`) or its sign-in ended: `SessionAuth` refuses both (ADR-0029). Tests sign in with `api_as`, scripts with `/api/auth/login` |
| `pg_search must be loaded via shared_preload_libraries`, or migrate fails at `dbextras.0003` | Postgres is the stock pgvector image, or started without the preload flag. Use compose's `db` (built from `infra/db/Dockerfile`, ADR-0013). Retrieval no longer runs BM25 on the ticket (ADR-0020), but the index and its migration stay |
| `core-api` exits at boot | `thresholds.yaml` missing or malformed — parsed into a Pydantic model at startup on purpose |
| `ImproperlyConfigured: X is not set` (core-api), `Field required` on `Settings` (ai-engine), or compose's `required variable X is missing a value` | No root `.env` (`cp .env.example .env`), or yours predates X: copy its line from `.env.example`. A new setting goes in `.env.example` too; never a default in code |
| Behaviour differs from a teammate's on the same commit (prompt, model, top-k) | Your `.env` holds an old value that `.env.example` has since changed: diff the two |
| Frontend types out of sync | Re-run `gen_typescript.py` |
| `ModuleNotFoundError: config.settings.dev` (or `.prod`) | Renamed to `config.settings.development` / `.production`; update `DJANGO_SETTINGS_MODULE` |
| mypy: `ImproperlyConfigured` / plugin can't load settings | The django-stubs plugin imports `config.settings.test` (set in `[tool.django-stubs]`). Run `uv run mypy` from the repo root (or `make typecheck` in core-api) after `uv sync --all-packages`, not `uvx mypy`, which has no Django |
| Tempted to annotate `objects`, `<fk>_id` or a reverse manager on a model | Don't: the django-stubs plugin infers managers, `_id` fields and related managers. Those declarations were pyright-era workarounds |
| `column "id" is of type bigint but expression is of type uuid` on a dev DB | The `db_data` volume was migrated before a `0001_initial` was rewritten in place (the UUID change). Django tracks migrations by name and won't re-run it. Reset the volume (`docs/onboarding.md` step 7); don't write a migration to patch a dev DB |
| A `vllm-*` container dies with `Engine core initialization failed` | CUDA out of memory: the three servers share one GPU. Fractions and start order: `docs/onboarding.md` step 2 |
| New model has a bigint `id`; `test_every_model_has_a_uuid_primary_key` fails | Inherit `apps.core.models.BaseModel`, which declares `id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)` (ADR-0011). `DEFAULT_AUTO_FIELD` is still `BigAutoField`, for Django's own tables |

## Comments and docstrings

Comments and docstrings say **what** a file, class or function does, in a
plain sentence: `"""Replaces the entity_graph rows with rows."""`. Not its
inputs and outputs (the signature has them), never **why** it is that way,
never **how** it does it. The why goes in the ADR (`docs/adr/`), the commit message, or
[`load-bearing.md`](.claude/skills/refactor/references/load-bearing.md); a
test guards it.

Older code still carries why-comments. Trim them when you touch that code, but
first make sure a comment's reason (especially a silent failure it names) is
recorded in an ADR or `load-bearing.md`; add the entry if it isn't.

## Testing conventions

Unit tests (core-api: a `tests/` package beside the code; ai-engine: `tests/`) protect logic; evals (`evals/suites/`) protect
behavior. A green unit suite says nothing about whether the model got worse.

- **Test the failure paths.** This system's correctness is mostly about what it
  does when things go wrong. A test that a degraded run reaches HITL with the
  right `reason_code` beats another happy-path assertion.
- **Name the test for the failure mode it prevents**
  (`test_a_failed_write_exits_1`). A docstring, if any, says what the test
  checks, like every other docstring; the why goes in the commit message or ADR.
- **Pin the invariant, not the implementation.**
  `test_llm_self_confidence_does_not_change_score` survives any rewrite of the
  scorer; asserting a specific weight would not.
- **When a test surprises you, check the test.** It has been the wrong side of
  the argument here before.
- Prompt changes go through the eval gate exactly like code changes
  (`.github/workflows/eval-gate.yml`). That is why `evals/` lives in this repo.

## Before opening a PR

- [ ] `uv run pytest` passes
- [ ] `uv run mypy` is clean
- [ ] New behavior has a test; new *failure* paths do too
- [ ] No new magic numbers — did it go in `thresholds.yaml`?
- [ ] Schema change → both services if it's on the ai-engine wire, types regenerated, new fields defaulted
- [ ] New failure path → HITL with a specific `reason_code`
- [ ] Prompt change → evals run, and you can explain any metric movement
- [ ] Comments and docstrings say only **what**, no why or how; a reason they used to carry is in an ADR or `load-bearing.md`
- [ ] Changed documented behavior → updated the relevant `docs/` file (and `status.md` / `TODO.md` together)

Deliberately relaxing a guardrail? Say so explicitly in the PR description and
link the ADR you're arguing against. That pressure is expected — the point is
that it is a visible decision, not a quiet one.

## Docs

[`docs/README.md`](docs/README.md) is the ordered reading path. Key ones:
[architecture.md](docs/architecture.md) (the path of one ticket, stage by stage) ·
[glossary.md](docs/glossary.md) (the Vietnamese-derived domain vocabulary — read
this early, the codebase is dense with it) · [development.md](docs/development.md) ·
[testing.md](docs/testing.md) · [status.md](docs/status.md) (what is *verified
working* vs. merely has code) · [TODO.md](docs/TODO.md) ·
[runbooks/on-call.md](docs/runbooks/on-call.md) · [adr/](docs/adr/) (thirty-eight
decisions, each written to survive being re-litigated — 0001 and 0003 at minimum;
0030–0038 come from the phase 2 pack; 0031–0033 are accepted, the rest proposed).
