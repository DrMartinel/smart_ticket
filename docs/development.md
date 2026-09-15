# Development

Conventions, common tasks, and the gotchas that cost time. Read [`architecture.md`](architecture.md) first.

---

## Setup

```bash
uv sync --all-packages          # NOT plain `uv sync`
cd services/web && npm install
```

> **Always `--all-packages`.** The root project has no dependencies of its own, so a bare `uv sync` installs neither the workspace members nor Django, and `uv run pytest` then fails with `Failed to spawn: pytest`. This has bitten people; it looks like a broken checkout.

### Running services individually

Point at the Dockerized Postgres and Redis so you only run what you're editing:

```bash
export DATABASE_URL=postgresql://app_user:app_password@localhost:5434/smart_triage
export CELERY_BROKER_URL=redis://localhost:6380/0
export DJANGO_SETTINGS_MODULE=config.settings.dev

uv run --project services/core-api python services/core-api/manage.py runserver
uv run --project services/core-api celery -A config worker -l info
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

### 4. Contracts are the single source of schema truth

Change a shape in `packages/contracts`, then regenerate the frontend types:

```bash
uv run --package contracts python packages/contracts/scripts/gen_typescript.py
```

Never hand-edit `services/web/lib/types/generated.ts`. Never define the same shape twice.

Adding a field to a persisted contract? Give it a **default**, so rows written before the change still deserialize. `GenerationSignals.quote_applicable` is the worked example.

### 5. Degrade toward humans

Any new failure path routes to HITL with a specific `reason_code`. Never toward "assume it's fine". If you add a `ReasonCode`, add it to the enum — the HITL-reason dashboard is built on that enum and free text is invisible to it.

---

## Common tasks

### Add a database field

```bash
# 1. edit the model in services/core-api/apps/<app>/models.py
uv run --project services/core-api python services/core-api/manage.py makemigrations
uv run --project services/core-api python services/core-api/manage.py migrate
```

Table and column names mirror the spec's DDL via `db_table` — keep that alignment, because `infra/migrations/sql/` is written against those exact names.

For things the ORM can't express (partial indexes, HNSW, CHECK constraints tied to business rules, triggers, role grants), add SQL to `infra/migrations/sql/` and apply it via `RunSQL` in `apps/dbextras/migrations/`. That keeps `manage.py migrate` the single entry point. Note the core-api Dockerfile copies that directory — a new SQL file that isn't copied will fail at container start.

### Add an API endpoint

Routers live in `apps/<app>/api.py` (Django Ninja). Follow the RBAC decorator pattern already used for the manager-only KB governance endpoint in `apps/kb/api.py`. Roles: `employee`, `technician`, `manager`, `security`.

### Change a prompt

Prompts are versioned files in `services/ai-engine/src/ai_engine/core/llm/prompts/`. Bump the version in the filename and in `core/config.py`, and note what changed. **Prompt changes go through the eval gate exactly like code changes** — that is the entire reason `evals/` lives in this repo and runs in CI.

### Add a KB article

Via the API/UI, or extend `seed_demo.py`. Note that `auto_reply_allowed` cannot be set directly — it goes through the governance path (manager role, mandatory reason, `kb_authority_log` entry). The seed command follows that same path rather than bypassing it, which is why the DB `CHECK` constraint holds even for seeded data.

### Add a golden eval case

Append to `evals/golden/tickets.jsonl` following [`SCHEMA.md`](../evals/golden/SCHEMA.md), tagged with one of the six distribution buckets. Best sources are real `eval_candidates` rows — humans correcting the system is exactly the signal calibration needs.

---

## Testing

Short version — full detail in [`testing.md`](testing.md):

```bash
uv run pytest                              # everything (111 unit + 8 eval)
uv run pytest services/core-api/tests -q
uv run pytest services/ai-engine/tests -q
uv run pytest evals/suites -q              # skips live suites if ai-engine is down
```

Two invariants CI enforces that you should not work around:

- **Masking keeps 100% branch coverage.** It is the P0 release gate.
- **Per-category F1 ≥ 0.85, never averaged.** Averaging hides the rare-but-serious category.

`other` currently fails at F1 0.75. That is a documented model weakness, not a broken checkout — see [`TODO.md`](TODO.md) item 3.

---

## Gotchas

| Symptom | Cause |
|---|---|
| `Failed to spawn: pytest` | `uv sync` instead of `uv sync --all-packages` |
| `ModuleNotFoundError: tests.*` on a whole-workspace run | core-api and ai-engine both have a package named `tests`. Handled by `--import-mode=importlib` in root `pyproject.toml` — don't remove it |
| Every ticket `mask_failed` | Containers can't reach Ollama (see [`onboarding.md`](onboarding.md) step 2), or the NER model isn't pulled |
| Submit hangs for a long time | Connect and read timeouts collapsed into one. They're deliberately separate: 3s connect, 120s read |
| All four generation checks ✗ | No LLM ran. Read the reason code above the panel — usually a degraded run |
| Unaccented Vietnamese matches nothing | The lexical reranker folds diacritics (`_strip_diacritics`). If this regresses, tickets typed without tone marks stop matching an accented KB |
| Connecting to port 5432 / 6379 fails | Host ports are **5434** and **6380**; `db:5432` / `redis:6379` are internal only |
| `core-api` exits at boot | `thresholds.yaml` missing or malformed — it's parsed into a Pydantic model at startup on purpose, so bad config fails loudly rather than at routing time |
| Frontend types out of sync | Re-run `gen_typescript.py` |

---

## Before you open a PR

- [ ] `uv run pytest` passes
- [ ] New behavior has a test; new *failure* paths have one too
- [ ] No new magic numbers — did it go in `thresholds.yaml`?
- [ ] Contract change → types regenerated, new fields defaulted
- [ ] New failure path → routes to HITL with a specific `reason_code`
- [ ] Prompt change → evals run, and you can explain any metric movement
- [ ] Comments explain **why**, especially for anything that looks like indirection worth removing
- [ ] Changed a documented behavior → updated the relevant doc in `docs/`

If you're deliberately relaxing a guardrail, say so explicitly in the PR description and link the ADR you're arguing against. [ADR-0006](adr/0006-runbook-always-hitl.md) exists because that pressure is expected — the point is that it should be a visible decision, not a quiet one.
