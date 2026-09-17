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
| Code | `router.py` is the only place a `Branch` is chosen, and it is a pure function |
| Database | `ai-engine` connects as a `SELECT`-only Postgres role |

Things that look needlessly indirect — the `proposed_` prefixes, auto-reply
authority living on KB rows instead of in model output, a pure function taking
thresholds as an argument — exist to stop the LLM from quietly acquiring
authority it was never granted. **Read the comment before simplifying.** They
usually cite the ADR or spec section that explains what breaks without it.

## Hard rules (violating these is a regression, not a style choice)

1. **`router.py` stays pure.** No I/O, no importing global config, thresholds
   passed in as a parameter. Need data for a decision? Fetch it *before* the call
   and pass it. This is what makes every branch testable with no DB, model, or
   network — and what lets decisions be replayed against
   `routing_decisions.thresholds_used`.
2. **No magic numbers.** Every tunable lives in
   [`thresholds.yaml`](services/core-api/config/thresholds.yaml) — not a
   constant, not a default argument. Timeouts and connect budgets go in
   settings/env.
3. **Degrade toward humans.** Every new failure path routes to HITL with a
   specific `ReasonCode` (add it to the enum — the dashboard is built on the
   enum, free text is invisible to it). Never toward "assume it's fine."
   `mask_failed` resolving toward "no PII found" is the single worst regression
   possible here.
4. **`packages/contracts` is the only schema definition.** Change a shape there,
   then regenerate TS types. Never hand-edit `services/web/lib/types/generated.ts`.
   New fields on persisted contracts need a **default** so old rows still
   deserialize.
5. **`proposed_` prefixes are load-bearing.** Don't strip them "for consistency."
   The asymmetry between `draft.proposed_category` and `ticket.category` is the point.
6. **`llm_self_confidence` never enters the trust score or routing** (ADR-0003).
   A test exists whose only job is to fail if someone adds it back.
7. **`RunbookProposal` always goes to HITL** (ADR-0006). No threshold, no
   config flag, no exception. Changing this requires a new ADR that explicitly
   supersedes 0006.
8. **Retrieval thresholds compare against the cross-encoder score, never the RRF
   fusion score** (ADR-0005). RRF is rank-derived; its magnitude means nothing.
   Any PR touching `retrieve.py` / `fusion.py` / `rerank.py` needs this check —
   the bug it prevents does not fail loudly.
9. **Never lower an eval floor to make CI green.** Not the per-category F1 floor,
   not the auto-reply precision floor, and don't average per-category F1 or drop
   a category. Baseline updates require review by someone other than the author.

## Commands

```bash
uv sync --all-packages            # NOT plain `uv sync` — see Gotchas
cd services/web && npm install
```

```bash
uv run pytest                              # everything (242 unit + 8 eval)
uv run pytest services/core-api/tests -q   # 74
uv run pytest services/ai-engine/tests -q  # 168
uv run pytest evals/suites -q              # 8 suites; live ones skip if ai-engine is down
```

Coverage on the two modules where it is contractual:

```bash
uv run pytest services/core-api/tests -q --cov=apps.tickets.services.masking --cov=apps.tickets.services.router --cov-report=term-missing
```

Full stack (7 containers + the `vllm` profile for models). Migrations run automatically on `core-api` start:

```bash
cp infra/.env.example infra/.env && cd infra && docker compose up -d --build
```

```bash
docker compose exec core-api python manage.py seed_demo
```

Individual services against the Dockerized Postgres/Redis:

```bash
export DATABASE_URL=postgresql://app_user:app_password@localhost:5434/smart_triage CELERY_BROKER_URL=redis://localhost:6380/0 DJANGO_SETTINGS_MODULE=config.settings.dev
```

```bash
uv run --project services/core-api python services/core-api/manage.py runserver
```

```bash
uv run --project services/ai-engine uvicorn ai_engine.main:app --app-dir services/ai-engine/src --port 8001 --reload
```

Regenerate frontend types after any contract change:

```bash
uv run --package contracts python packages/contracts/scripts/gen_typescript.py
```

Ports: web 3000, core-api 8000, ai-engine 8001, **Postgres 5434**, **Redis 6380**
(host-published to avoid collisions; internally still `db:5432` / `redis:6379`).

## Layout

| Concern | Path |
|---|---|
| The routing decision (pure function, only place a `Branch` is chosen) | [router.py](services/core-api/apps/tickets/services/router.py) |
| PII masking (inline, two-tier; 100% branch coverage is a release gate) | [masking.py](services/core-api/apps/tickets/services/masking.py) |
| Trust score (in core-api, so the LLM can't score itself) | [trust_scorer.py](services/core-api/apps/tickets/services/trust_scorer.py) |
| PII regex patterns | [patterns.py](services/core-api/apps/tickets/services/patterns.py) |
| Every tunable number | [thresholds.yaml](services/core-api/config/thresholds.yaml) |
| Shared schemas (single source of truth) | [packages/contracts/](packages/contracts/src/contracts/) |
| The AI pipeline (LangGraph) | [graph/build.py](services/ai-engine/src/ai_engine/graph/build.py) |
| Prompts (versioned, eval-gated like code) | [core/prompts/](services/ai-engine/src/ai_engine/core/prompts/) |
| Reviewer-facing explanation | [TrustSignalsPanel.tsx](services/web/components/TrustSignalsPanel.tsx) |
| Raw SQL (grants, CHECKs, HNSW, triggers) | [infra/migrations/sql/](infra/migrations/sql/) |
| Golden set + baselines + calibration scripts | [evals/](evals/) |

Services: `core-api` (Django + Ninja) owns **every write and every decision** ·
`ai-engine` (FastAPI + LangGraph) has **no authority**, returns signals and a
proposal only · `web` (Next.js) is a thin client with no business logic.

**If you are adding a feature that decides something, it belongs in core-api.**

## Where to make a change

| To change… | Go to |
|---|---|
| When something is auto-replied | `thresholds.yaml`, or `kb_articles.auto_reply_allowed` — **not** the prompt |
| How a branch is chosen | `router.py` (and add branch tests) |
| What the model is asked | `ai-engine/core/prompts/*.md` — bump the version in filename and `core/config.py` |
| What counts as PII | `patterns.py` (regex) or the NER prompt in `masking.py` |
| How relevance is judged | `ai-engine/core/providers/reranker.py`, `core/retrieval/` |
| Any tunable number | `thresholds.yaml`, nowhere else |

DB fields: edit the model, then `makemigrations` / `migrate` via
`services/core-api/manage.py`. Table and column names mirror the spec DDL via
`db_table` — keep that alignment, `infra/migrations/sql/` is written against
those exact names. Things the ORM can't express go in `infra/migrations/sql/`
applied via `RunSQL` in `apps/dbextras/migrations/` (the core-api Dockerfile
copies that directory — a new SQL file that isn't copied fails at container start).

## Current state

- `SHADOW_MODE=true` is the default: the router decides and records, humans still
  handle every ticket. This is spec §14's P1 phase, by design.
- **Known CI failure:** `other` category F1 is **0.75** against a 0.85 floor
  (precision 1.00, recall 0.60). Real, documented in
  `evals/baselines/baseline.json`, not a broken checkout. See TODO item 3.
- Trust score coefficients are a **hand-set prior**, not fitted. `t_auto = 0.88`
  and `t_route = 0.72` are placeholders (marked 🔧 in `thresholds.yaml`).
  Calibration needs ≥500 shadow pairs. Do not enable P3/P4 before that.
- Reranker defaults to `vllm` (the bge-reranker-v2-m3 cross-encoder on vllm-rerank);
  `lexical` is dependency-free, for CI/offline. `retrieval.floor` is specified as a
  *cross-encoder* score — the two distributions are separate calibrations, never
  interchangeable.
- PII quarantine **write** path is done; the **read** path is not. Currently fails
  safe (nobody can read raw PII). **Do not add a `decrypt()` call without writing
  the `PiiAccessLog` row in the same transaction, with a mandatory non-empty reason.**
- Golden set is **synthetic**. A passing eval means "the wiring didn't regress,"
  never "the model is good."

## Gotchas

| Symptom | Cause |
|---|---|
| `Failed to spawn: pytest` | `uv sync` instead of `uv sync --all-packages` — the root project has no deps of its own |
| `ModuleNotFoundError: tests.*` on a whole-workspace run | core-api and ai-engine both have a package named `tests`. Handled by `--import-mode=importlib` in root `pyproject.toml` — don't remove it |
| Every ticket `mask_failed` | vllm-chat isn't running or reachable, or `VLLM_CHAT_MODEL` doesn't match what it serves. **Never "fix" this by treating NER failure as no-PII-found** |
| Submit hangs ~120s | Connect and read timeouts collapsed into one. Deliberately separate: 3s connect, 120s read (a cold model load legitimately takes 15–20s) |
| All four generation checks ✗ | No LLM ran — refuse-before-LLM. Read the reason code |
| Unaccented Vietnamese matches nothing | Diacritic folding (`_strip_diacritics`) in the lexical reranker regressed; `đ`/`Đ` need special handling |
| Port 5432/6379 fails | Host ports are **5434** / **6380** |
| `core-api` exits at boot | `thresholds.yaml` missing or malformed — parsed into a Pydantic model at startup on purpose |
| Frontend types out of sync | Re-run `gen_typescript.py` |

## Testing conventions

Unit tests (`services/*/tests/`) protect logic; evals (`evals/suites/`) protect
behavior. A green unit suite says nothing about whether the model got worse.

- **Test the failure paths.** This system's correctness is mostly about what it
  does when things go wrong. A test that a degraded run reaches HITL with the
  right `reason_code` beats another happy-path assertion.
- **Explain the failure mode in the docstring** — enough context that someone can
  judge whether a future change is a regression or an intentional shift.
- **Pin the invariant, not the implementation.**
  `test_llm_self_confidence_does_not_change_score` survives any rewrite of the
  scorer; asserting a specific weight would not.
- **When a test surprises you, check the test.** It has been the wrong side of
  the argument here before.
- Prompt changes go through the eval gate exactly like code changes
  (`.github/workflows/eval-gate.yml`). That is why `evals/` lives in this repo.

## Before opening a PR

- [ ] `uv run pytest` passes
- [ ] New behavior has a test; new *failure* paths do too
- [ ] No new magic numbers — did it go in `thresholds.yaml`?
- [ ] Contract change → types regenerated, new fields defaulted
- [ ] New failure path → HITL with a specific `reason_code`
- [ ] Prompt change → evals run, and you can explain any metric movement
- [ ] Comments explain **why**, especially for anything that looks like removable indirection
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
[runbooks/on-call.md](docs/runbooks/on-call.md) · [adr/](docs/adr/) (nine
decisions, each written to survive being re-litigated — 0001 and 0003 at minimum).
