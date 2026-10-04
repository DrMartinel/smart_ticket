# Development

Conventions, common tasks, and the gotchas that cost time. Read [`architecture.md`](architecture.md) first.

---

## Setup

```bash
uv sync --all-packages          # NOT plain `uv sync`
cd services/web && npm install
```

core-api's commands are targets in [`services/core-api/Makefile`](../services/core-api/Makefile); run `make` in that directory to list them.

> **Always `--all-packages`.** The root project has no dependencies of its own, so a bare `uv sync` installs neither the workspace members nor Django, and `uv run pytest` then fails with `Failed to spawn: pytest`. This has bitten people; it looks like a broken checkout.

### Running services individually

Point at the Dockerized Postgres and Redis so you only run what you're editing. A root `.env` copied from `.env.example` already does (host ports 5434 / 6380). Both services read only `.env` and environment variables, which win; nothing reads the template. Override in `.env` or on the command line, e.g. `DATABASE_URL=... make runserver`. After pulling, diff `.env` against `.env.example`: a changed value there doesn't reach your copy.

```bash
cd services/core-api
make runserver   # :8000
make worker      # celery worker (and `make beat`)

# from the repo root
uv run --project services/ai-engine uvicorn ai_engine.main:app \
    --app-dir services/ai-engine/src --port 8001 --reload
cd services/web && npm run dev
```

`--project` selects which member's environment to use. Whole-workspace commands (like `uv run pytest`) run from the root without it.

---

## The five conventions

These are the ones a reviewer will actually push back on.

### 1. `proposed_` prefixes are load-bearing

Anything the LLM authored carries the prefix. At the point of use, `draft.proposed_category` reads as *a suggestion*, while `ticket.category` reads as *a fact*. Don't strip the prefix "for consistency" — the asymmetry is the point.

### 2. No magic numbers

Every tunable lives in [`thresholds.yaml`](../services/core-api/config/thresholds.yaml). Not a constant, not a default argument. A number in code is a number nobody can calibrate, and thresholds are data pending calibration, not logic.

Threshold-adjacent values (timeouts, connect budgets) live in settings/env rather than being hardcoded, for the same reason.

### 3. `router.py` stays pure

No I/O, no imports of global config, thresholds passed in. This is what makes every branch testable without a database or a model, and it's why decisions can be replayed later against the exact thresholds recorded in `routing_decisions.thresholds_used`.

If you need data to make a routing decision, fetch it *before* the call and pass it in.

### 4. Schemas live where they are used

There is no shared contracts package (ADR-0010). A schema is defined in the module that uses it; `docs/architecture.md` §3 has the table. The ai-engine wire shapes (`AIRunRequest`, `AIRunResponse` and everything in them) exist in both services — core-api `infrastructure/dtos.py`, ai-engine `schemas.py` — so change **both** in the same PR. After a core-api schema change, regenerate the frontend types:

```bash
cd services/core-api && make types
```

Never hand-edit `services/web/lib/types/generated.ts`.

Adding a field to a persisted schema? Give it a **default**, so rows written before the change still deserialize. `GenerationSignals.quote_applicable` is the worked example. The one deliberate exception is `TrustSignals.classification` (ADR-0017): no signals existed before it, so every producer must state Jev's answer.

### 5. Degrade toward humans

Any new failure path routes to HITL with a specific `reason_code`. Never toward "assume it's fine". If you add a `ReasonCode`, add it to the enum — the HITL-reason dashboard is built on that enum and free text is invisible to it.

---

## Common tasks

### Add a database field

```bash
# 1. edit the model in services/core-api/apps/<app>/models.py
cd services/core-api
make makemigrations
make migrate
```

Table and column names mirror the spec's DDL via `db_table` — keep that alignment, because `infra/migrations/sql/` is written against those exact names.

For things the ORM can't express (partial indexes, HNSW, CHECK constraints tied to business rules, triggers, role grants), add SQL to `infra/migrations/sql/` and apply it via `RunSQL` in `apps/dbextras/migrations/`. That keeps `manage.py migrate` the single entry point. Note the core-api Dockerfile copies that directory — a new SQL file that isn't copied will fail at container start.

### Add an API endpoint

Routers live in `apps/<app>/views.py` (Django Ninja). Keep the handler thin: bind and validate the input, call a model method or manager method (writes and decisions belong on the model they change), or a function in the app's `utils` (logic no single model owns, including cross-model reads), and return the model. Reads that belong to one model are manager methods too. Request bodies go in the app's `request_schema.py`; declare the output with `response=` and an output Schema in `response_schema.py`, so the shape is validated and documented in OpenAPI. Gate a handler by role with `@require_role(...)` from `apps/accounts/permissions.py`. Roles: `employee`, `technician`, `manager`, `security`. No router applies it yet: KB governance is enforced inside `KbArticle.set_auto_reply_allowed` (`apps/kb/models.py`), not at the endpoint.

### Change a prompt or a Jev question

Prompts and Jev's questions are versioned files in `services/ai-engine/src/ai_engine/core/prompts/`, each selected by a setting:

| File | Setting | Used by |
|---|---|---|
| `classify.v*.md` | `PROMPT_VERSION` | `InferNode`, the classify LLM |
| `pii_ner.v*.md` | `PII_NER_PROMPT_VERSION` | Tier-2 PII NER (`/v1/pii/detect`) |
| `rerank_resolves.v*.json` | `RERANK_PROMPT_VERSION` | Jev, once per shortlisted chunk (ADR-0015) |
| `category.v*.json` | `CATEGORY_QUESTION_VERSION` | Jev, the ticket's category (ADR-0017) |

Bump the version in the filename and the setting in the root `.env.example` (and your `.env`). A prompt's changelog goes in a leading `<!-- … -->` comment, which the loader strips so it is never sent. **Prompt and question changes go through the eval gate exactly like code changes** — that is the entire reason `evals/` lives in this repo and runs in CI. A Jev question changes the scale its answers are on: a new rerank question means re-choosing `retrieval.floor`, a new category question `classification.min_confidence`.

### Add a KB article

Via the API/UI, or for the demo KB: add a guide to `demo_kb/sources.json`, run `python3 demo_kb/fetch.py`, commit the updated `manifest.json`, and run `make load-demo-kb`. Articles are split into chunks at Markdown headings (`apps/kb/utils.py`), and each chunk records its section title. Note that `auto_reply_allowed` cannot be set directly — it goes through the governance path (manager role, mandatory reason, `kb_authority_log` entry). `load_demo_kb` follows that same path for the approvals in `demo_kb/curation.json`, each pinned to the SHA-256 of the reviewed text, which is why the DB `CHECK` constraint holds for every row.

### Add a golden eval case

Append to `evals/golden/tickets.jsonl` following [`SCHEMA.md`](../evals/golden/SCHEMA.md), tagged with one of the six distribution buckets (or `edge`, with a specific kind tag). Best sources are real `eval_candidates` rows — humans correcting the system is exactly the signal calibration needs.

---

## Testing

Short version — full detail in [`testing.md`](testing.md):

```bash
uv run pytest                              # everything (unit + eval)
cd services/core-api && make test          # core-api; `make check` adds ruff + mypy
uv run pytest services/ai-engine/tests -q
uv run pytest evals/suites -q              # skips live suites if ai-engine is down
```

Two invariants CI enforces that you should not work around:

- **Masking and the router keep 100% branch coverage** (`make coverage`). For masking it is the P0 release gate.
- **Per-category F1 ≥ 0.85, never averaged.** Averaging hides the rare-but-serious category.

The last full run failed per-category F1 (`security`, on the LLM's category), which Jev now chooses; `main` has no full run since. That is a documented finding, not a broken checkout — see [`../evals/HISTORY.md`](../evals/HISTORY.md) and [`TODO.md`](TODO.md) item 11.

---

## Gotchas

| Symptom | Cause |
|---|---|
| `Failed to spawn: pytest` | `uv sync` instead of `uv sync --all-packages` |
| `ModuleNotFoundError: tests.*` on a whole-workspace run | core-api and ai-engine both have a package named `tests`. Handled by `--import-mode=importlib` in root `pyproject.toml` — don't remove it |
| Every ticket `mask_failed` | ai-engine is down, or vllm-chat isn't running or reachable from it (see [`onboarding.md`](onboarding.md) step 2), or ai-engine's `CHAT_MODEL` doesn't match what it serves |
| Every ticket past the injection guard `ai_engine_unavailable` | Jev unreachable: `JEV_API_KEY` unset, or its API failing. By design there is no fallback |
| Classify fails as `all_llm_down` on long tickets | The prompt plus chunks overflow `VLLM_CHAT_MAX_MODEL_LEN` (4096 in recorded runs); vLLM answers 400 |
| Submit hangs for a long time | Connect and read timeouts collapsed into one. They're deliberately separate: 3s connect, 120s read |
| All four generation checks ✗ | No LLM ran. Read the reason code above the panel — usually a degraded run |
| Unaccented Vietnamese matches nothing | `LexicalShortlister` folds diacritics (`_tokenize`). If this regresses, tickets typed without tone marks stop matching an accented KB |
| Connecting to port 5432 / 6379 fails | Host ports are **5434** and **6380**; `db:5432` / `redis:6379` are internal only |
| `column "id" is of type bigint but expression is of type uuid` | Your dev DB volume predates a `0001_initial` migration that was rewritten in place. Reset it: [`onboarding.md`](onboarding.md) step 7 |
| `core-api` exits at boot | `thresholds.yaml` missing or malformed — it's parsed into a Pydantic model at startup on purpose, so bad config fails loudly rather than at routing time |
| Frontend types out of sync | Re-run `gen_typescript.py` |

---

## Before you open a PR

- [ ] `uv run pytest` passes
- [ ] New behavior has a test; new *failure* paths have one too
- [ ] No new magic numbers — did it go in `thresholds.yaml`?
- [ ] Contract change → both services' schemas, types regenerated, new fields defaulted
- [ ] New failure path → routes to HITL with a specific `reason_code`
- [ ] Prompt change → evals run, and you can explain any metric movement
- [ ] Comments explain **why**, especially for anything that looks like indirection worth removing
- [ ] Changed a documented behavior → updated the relevant doc in `docs/`

If you're deliberately relaxing a guardrail, say so explicitly in the PR description and link the ADR you're arguing against. [ADR-0006](adr/0006-runbook-always-hitl.md) exists because that pressure is expected — the point is that it should be a visible decision, not a quiet one.
