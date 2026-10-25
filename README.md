# Smart Ticket Triage

AI-assisted IT support ticket triage that classifies, routes, and (eventually) auto-replies to tickets — with **human-in-the-loop guardrails at every step**.

> **The governing principle:** the LLM produces *proposals*; deterministic code makes *decisions*. Every LLM-authored field carries a `proposed_` prefix so that distinction is visible at the type level.

Implements [`requirement.md`](requirement.md) (Architecture Specification v2). Section references throughout the code and docs (`§5`, `§8`, `§10.3`, …) point back to that document.

---

## New here?

Go to **[`docs/`](docs/README.md)** — it gives an ordered reading path that takes about an hour and ends with you able to make a change confidently.

| Start with | For |
|---|---|
| [Onboarding](docs/onboarding.md) | Get it running and watch a ticket get triaged. Do this first. |
| [Glossary](docs/glossary.md) | The vocabulary. The spec is Vietnamese and the domain terms are everywhere. |
| [Architecture](docs/architecture.md) | How the pieces fit and the exact path a ticket takes. |
| [Development](docs/development.md) | Conventions, common tasks, and the setup gotchas. |
| [Testing](docs/testing.md) | Test layers and what the CI gate really enforces. |

The rest of this README is the reference: what it is, how to run it, and where the knobs are.

---

## Current status

The system runs end to end. **`SHADOW_MODE=true` by default**: the router evaluates every ticket and records what it *would* have done, but every ticket still lands in the human queue. This is deliberate — it is spec §14's P1 phase, and it is how calibration data is collected at zero risk.

| Phase | What it covers | State |
|---|---|---|
| **P0** | Contracts, DB schema, masking, audit log, golden set, CI gate | ✅ Complete — masking at 100% branch coverage |
| **P1** | Full AI graph, router in shadow mode, HITL queue, dashboard | ✅ Complete |
| **P2** | Trust-score calibration, choose `T_auto` / `T_route` from a PR curve | ⏳ Scripts ready, awaiting ≥500 shadow pairs |
| **P3–P5** | Enable auto-route, then auto-reply, then runbooks | ⏸ Config flips, not missing code — see [Rollout](#rollout-phases) |

See [`docs/status.md`](docs/status.md) for a component-by-component breakdown against the spec, and [`docs/TODO.md`](docs/TODO.md) for the prioritized open work.

---

## Architecture

```
┌──────────────────────────────┐
│  web (Next.js)               │
│  Submit · Queue · Review     │
│  Dashboard · KB Management   │
└──────────────┬───────────────┘
               │ REST (JWT, RBAC)
┌──────────────▼───────────────┐
│  core-api (Django + Ninja)   │  ← source of truth
│  Masking · Trust Scorer      │
│  Switch Router · HITL Queue  │
│  Incident Detector · Audit   │
└──────┬───────────────┬───────┘
       │ Celery        │
┌──────▼──────┐  ┌─────▼───────┐
│  ai-engine  │  │  PostgreSQL │
│  FastAPI +  │──│  + pgvector │
│  LangGraph  │  │  + pg_search│
│  READ-ONLY  │  └─────────────┘
└──┬───────┬──┘
   │       └──────────────┐
┌──▼──────────────┐  ┌────▼──────────────────┐
│ vLLM            │  │ Jev (hosted)          │
│ chat · NER ·    │  │ rerank · category     │
│ embed · cross-  │  │ masked text + KB only │
│ encoder         │  └───────────────────────┘
└─────────────────┘
```

Three services with **structurally enforced** permission boundaries:

| Service | Stack | Role |
|---|---|---|
| **core-api** | Django 6 · Django Ninja · Celery | Business logic, all routing decisions, HITL queue, audit log. The only service that writes business data. |
| **ai-engine** | FastAPI · LangGraph | Retrieval (vector search on the ticket → RRF, ADR-0020), a cross-encoder shortlist, reranking and category choice by Jev, LLM inference, validation. The only client of every model (ADR-0012). Connects as the `ai_engine_ro` Postgres role with `SELECT`-only grants — it *cannot* write business tables even if compromised (ADR-0004). |
| **web** | Next.js 15 · React 19 | Ticket submission, review queue, dashboards, KB governance. |

| Infrastructure | Purpose |
|---|---|
| PostgreSQL 17 + pgvector + pg_search | Relational data, 1024-dim HNSW vector indexes, BM25 full-text search (ParadeDB `pg_search`, ADR-0013) |
| Redis 7 | Celery broker & result backend |
| vLLM (`vllm` profile) | Self-hosted models: inference, PII NER, embeddings, the cross-encoder shortlister |
| Jev (hosted, TypeSafe) | The reranker and the category classifier (ADR-0015, ADR-0017). Needs `JEV_API_KEY`; receives only masked ticket text and KB text |

---

## Key design principles

- **LLM proposes, code decides.** [`router.py::route()`](services/core-api/apps/tickets/utils/router.py) is the *only* place a `Branch` is chosen. It is a pure function — no I/O, thresholds passed as a parameter — so every branch is exhaustively unit-testable without a model or a network (ADR-0001).
- **Trust score over self-confidence.** `llm_self_confidence` is logged but **never** routed on. Trust comes from externally verifiable signals: rerank scores, whether the quoted text actually exists in the retrieved chunk, whether a negation got flipped (ADR-0003).
- **Fail toward humans.** Every degradation — LLM timeout, embedding outage, masking failure, weak retrieval, daily cost ceiling — routes to HITL. Never to auto-reply. A user waiting longer is acceptable; a user receiving a confident wrong answer is not.
- **Authority lives on the KB, not in the model.** `kb_articles.auto_reply_allowed` defaults to `false`, is settable only by a manager with a logged reason, and is enforced by a DB `CHECK` constraint requiring a named approver (ADR-0002).
- **Refuse before spending.** If Jev's top reranked score falls below the floor, the LLM is never called — cheaper *and* safer, since a model with no source is a model that invents one.
- **Shadow mode first.** The same `route()` runs in both modes, so calibration data describes exactly what will happen when it's switched live.

---

## Repository structure

```
smart_ticket/
├── services/
│   ├── core-api/                # Django + Django Ninja + Celery
│   │   ├── Makefile             #   core-api dev commands: `make` lists them
│   │   ├── scripts/gen_typescript.py # generates web/lib/types/generated.ts
│   │   ├── apps/                #   each: views · request/response_schema · models (fat) · utils · tasks · tests/
│   │   │   ├── core/            #   shared foundation, imports no app: BaseModel · trace_id middleware · wait_for_db · test helpers
│   │   │   ├── accounts/        #   RBAC: employee · technician · manager · security
│   │   │   ├── tickets/         #   models, views, Celery entry points, utils/*
│   │   │   │   └── utils/       #     router · trust_scorer · masking · patterns · crypto · pipeline
│   │   │   ├── kb/              #   KB CRUD + auto_reply_allowed governance
│   │   │   ├── review/          #   HITL queue, decisions, eval candidates
│   │   │   ├── fewshot/         #   few-shot pool (TTL, retraction)
│   │   │   ├── audit/           #   append-only audit log
│   │   │   ├── itsm_mock/       #   mock ITSM runbook execution
│   │   │   ├── metrics/         #   dashboard aggregation
│   │   │   └── dbextras/        #   raw-SQL migrations (indexes, constraints, grants)
│   │   ├── infrastructure/      #   the ai-engine client (every model call) + wire schema (dtos.py)
│   │   └── config/              #   settings/{base,development,production,test} · celery · thresholds.yaml
│   ├── ai-engine/               # FastAPI + LangGraph
│   │   └── src/ai_engine/
│   │       ├── main.py          #   HTTP routes: /v1/analyze, /v1/embed, /v1/pii/detect
│   │       ├── schemas.py       #   the HTTP bodies (mirrors core-api's dtos.py), built from graph types
│   │       ├── graph/           #   state.py · ticket.py · triage.py (the route list) · build/ (node, edge, graph, builder)
│   │       │   └── nodes/       #   injection · fewshot · validate,
│   │       │       ├── infer/           # and a folder per stage with helpers or types: node · proposals
│   │       │       ├── emit_signals/    # node · signals
│   │       │       ├── retrieve/        # bm25 · vector · rrf fusion
│   │       │       ├── candidate_pool/  # shortlister (cross-encoder) · link expansion
│   │       │       ├── rerank/          # Jev reranker
│   │       │       └── classify_category/ # Jev's category choice · the floor gate
│   │       └── core/            #   infrastructure, never imports graph/:
│   │           ├── config.py    #     settings (types only; values from .env)
│   │           ├── db/          #     the read-only DB client and tables
│   │           ├── providers/   #     embedders · PII NER · model clients (vLLM, Jev, chat) and their DTOs
│   │           └── prompts/     #     versioned prompts (.md) and Jev questions (.json)
│   └── web/                     # Next.js App Router
│       ├── app/                 #   submit · queue · review/[id] · dashboard · kb · login
│       ├── components/          #   TrustSignalsPanel · ReviewForm · NavBar
│       └── lib/types/generated.ts
├── evals/                       # Eval harness — treated as code, gated in CI
│   ├── golden/tickets.jsonl     #   174 synthetic cases (see SCHEMA.md)
│   ├── suites/                  #   retrieval · classification · quote · refusal · injection · masking · e2e
│   ├── HISTORY.md · history/    #   every full run and probe: what it meant, and its numbers (+ dashboard.html)
│   ├── calibration/             #   fit trust score · choose thresholds from PR curve
│   └── baselines/baseline.json  #   committed; changes require review
├── docker-compose.yml           # the stack; reads .env (from .env.example)
├── .env.example                 # template for .env: every setting, its value and why
├── infra/
│   ├── db/                      #   Postgres image (pgvector + pg_search)
│   └── migrations/sql/          #   extensions, HNSW indexes, CHECK constraints, RO role
├── .github/workflows/           # lint · eval-gate · publish-images
└── docs/
    ├── README.md                # documentation index + reading order — start here
    ├── onboarding.md            # day one: run it, submit a ticket, orient
    ├── glossary.md              # domain vocabulary (the spec is Vietnamese)
    ├── architecture.md          # deep dive + end-to-end ticket flow
    ├── development.md           # conventions, common tasks, gotchas
    ├── testing.md               # test layers + eval harness
    ├── status.md                # implementation status vs spec + known gaps
    ├── TODO.md                  # prioritized open work
    ├── adr/                     # 17 Architecture Decision Records
    └── runbooks/on-call.md      # when it breaks in production
```

---

## Prerequisites

| Requirement | Version | Notes |
|---|---|---|
| Python | 3.13+ | |
| Node.js | 18.18+ | 24 recommended (Next 15) |
| Docker + Compose | — | Compose v2+ |
| [uv](https://docs.astral.sh/uv/) | 0.9+ | manages the Python workspace |
| NVIDIA GPU | — | for the `vllm` compose profile; on Windows, via WSL2 / Docker Desktop |

### Models

The `vllm` compose profile downloads its models from Hugging Face on first start
(`CHAT_MODEL`, `EMBED_MODEL`, and `RERANKER_MODEL` for `vllm-rerank`),
cached in `HF_CACHE_DIR`. Without it every ticket still flows — masking fails
closed to `MASK_FAILED` and everything goes to a human, by design.

Reranking and the category need **Jev**, TypeSafe's hosted model: set
`JEV_API_KEY` in `.env`. Without it every ticket that reaches retrieval fails
to `ai_engine_unavailable`, a human. Only masked ticket text and KB text are
sent.

---

## Getting started

### 1. Configure

```bash
cp .env.example .env
```

`.env.example` is the template: every setting for core-api, ai-engine and
compose, each with its value and the reason for it. Only `.env` is read. For anything beyond local dev, regenerate the two secrets:

```bash
python -c "import os,base64;print('PII_ENCRYPTION_KEY='+base64.b64encode(os.urandom(32)).decode())"
```

### 2. Start the stack

```bash
docker compose up -d --build
```

Self-hosted models run in the `vllm` profile (ADR-0009). The three servers
share one GPU, so start them one at a time and size their memory fractions to
your card first: [`docs/onboarding.md`](docs/onboarding.md) step 2 has the
numbers (on a 12 GiB card they only just fit).

```bash
docker compose --profile vllm up -d vllm-chat    # then vllm-embed, then vllm-rerank
```

| Service | Port | |
|---|---|---|
| `web` | [3000](http://localhost:3000) | Next.js frontend |
| `core-api` | [8000](http://localhost:8000/api/docs) | Django REST API (OpenAPI docs) |
| `ai-engine` | [8001](http://localhost:8001/docs) | FastAPI inference service |
| `db` | 5434 | PostgreSQL + pgvector |
| `redis` | 6380 | Celery broker |
| `worker` / `beat` | — | Celery worker & scheduler |

> Postgres and Redis use **5434** and **6380** on the host to avoid colliding with locally-running instances. Inside the compose network they remain `db:5432` and `redis:6379`.

Migrations run automatically on `core-api` startup.

### 3. Users and the demo knowledge base

The demo KB is a frozen snapshot of AWS documentation in [`demo_kb/`](demo_kb/): every page of 12 guides (IAM, IAM Identity Center, VPC, Client VPN, EC2, WorkSpaces, SES, Lambda, GuardDuty, Security Hub), 3,542 pages. The scenario is an internal cloud-platform help desk; demo tickets are in English.

```bash
python3 demo_kb/fetch.py     # first time: download the snapshot's pages (~30 min, resumable)

# People sign in through Keycloak (phase 2 F13, ADR-0032). The dev realm in
# infra/keycloak/ has test users (password change-me): lan.nt (employee),
# duc.tm, ha.vt, mai.bn, tu.dv (technicians), huy.pq, quang.nv, dung.ht
# (managers), anh.lh (security). core-api creates each on first sign-in.
docker compose --profile sso up -d keycloak

# The KB loader names an approving manager, and local password sign-in is for
# break-glass managers only (at most identity.max_break_glass_accounts).
docker compose exec core-api python manage.py shell -c "
from apps.accounts.models import User
User.objects.create_user('manager1', password='change-me', role='manager')"
docker compose exec core-api python manage.py set_break_glass manager1

docker compose exec core-api python manage.py load_demo_kb --approver manager1
```

`load_demo_kb` checks every page against `demo_kb/manifest.json`, so the database holds exactly the committed snapshot. It then applies the auto-reply approvals in `demo_kb/curation.json` through the same governance path a manager uses (`KbArticle.set_auto_reply_allowed`: manager actor, reason, `kb_authority_log` row). Each approval is pinned to the SHA-256 of the text that was reviewed; if AWS changes that page, the approval is not applied, and an existing one is revoked.

### 4. Local development (without Docker)

```bash
uv sync --all-packages                     # install every workspace member

cd services/core-api && make migrate runserver   # :8000; `make worker` for celery
uv run --project services/ai-engine uvicorn ai_engine.main:app \
    --app-dir services/ai-engine/src --port 8001 --reload
cd services/admin-console && npm install && npm run dev   # :3000
cd services/chat && npm install && npm run dev            # :3001
```

core-api's commands live in [`services/core-api/Makefile`](services/core-api/Makefile); `make` there lists them.

Point `DATABASE_URL` at `localhost:5434` and `CELERY_BROKER_URL` at `localhost:6380` to reuse the Dockerized Postgres and Redis.

---

## Configuration

### Thresholds

Every tunable number lives in one file — **no magic numbers in code**:

```
services/core-api/config/thresholds.yaml
```

| Parameter | Default | Purpose |
|---|---|---|
| `routing.t_auto` | 0.88 | Trust minimum for auto-reply (target precision ≥ 0.95) |
| `routing.t_route` | 0.72 | Trust minimum for auto-route (target precision ≥ 0.85) |
| `routing.quote_match` | 0.95 | Minimum verbatim-quote match ratio |
| `retrieval.floor` | 0.30 🔧 | **Jev's** top reranked score below which the LLM is never called (ADR-0005, ADR-0015) |
| `classification.min_confidence` | 0.65 🔧 | Jev's category confidence below which a route or clarify goes to a human (ADR-0017) |
| `clarification.max_rounds` | 1 | Questions a chat ticket may ask its requester before a person takes it (ADR-0023) |
| `clarification.wait_minutes` | 60 🔧 | How long a question stays open before the chat offers a ticket instead |
| `clarification.option_margin` · `max_options` | 0.1 🔧 · 5 | Pages a clarifying question offers: within this of Jev's best score, at most this many |
| `masking.ner_max_share` | 0.7 🔧 | Share of a ticket NER may mask beyond the regex hits before it is `mask_failed` |
| `incident.min_count` | 5 | Similar tickets needed before mass-incident escalation |
| `budget.max_latency_sec` | 300 | How long core-api waits on ai-engine; must exceed the per-call model ceiling |
| `budget.daily_cost_ceiling_usd` | 50 | Daily spend cap — exceeding it routes everything to HITL |

Values marked 🔧 are **assumptions awaiting calibration**, not tuned values. The full snapshot is written into `routing_decisions.thresholds_used` on every decision, so a post-hoc investigation can always recover what the thresholds were *at the time*.

### Environment variables

Full list in [`.env.example`](.env.example). The ones that change behavior most:

| Variable | Default | Effect |
|---|---|---|
| `SHADOW_MODE` | `true` | Router records decisions without acting; everything still goes to HITL |
| `EMBEDDING_PROVIDER` | `vllm` | ai-engine's embedder, which also embeds for core-api. `stub` = deterministic hash embeddings, no network (used by CI) |
| `SHORTLIST_PROVIDER` | `vllm` | bge-reranker-v2-m3 via vllm-rerank; `lexical` = token overlap, no model (CI) |
| `JEV_API_KEY` | empty | Jev's key; required for any run that reaches retrieval. Tests use fakes |
| `PROMPT_VERSION` · `PII_NER_PROMPT_VERSION` | `propose.v9` · `pii_ner.v2` | Which prompt files run |
| `RERANK_PROMPT_VERSION` · `CATEGORY_QUESTION_VERSION` | `rerank_choice.v1` · `category.v1` | Which Jev question files run |
| `PII_ENCRYPTION_KEY` | dev key | Base64 32-byte AES-GCM key for the quarantine store |
| `PII_QUARANTINE_TTL_HOURS` | `72` | Hard TTL on encrypted raw PII |
| `MODEL_TIMEOUT_SEC` | `120` | Ceiling for one model call (NER, embeddings, inference); core-api's read timeout on NER and embedding calls to ai-engine |

---

## Ticket processing pipeline

```
Ticket submitted  ──►  PII Masking (INLINE, before any DB write)
                         │  regex tier 1 → critical (password/token)  ──►  BLOCK + security alert
                         │  LLM NER tier 2 → timeout/error            ──►  HITL (mask_failed)
                         ▼
                       Embedding + Incident Detection
                         │  embedding unavailable                     ──►  HITL (embedding_unavailable)
                         │  mass incident (adaptive baseline + 3σ)    ──►  ESCALATE, skip AI entirely
                         │  duplicate                                 ──►  link to original, inherit assignment
                         ▼
                       ai-engine  (Celery, idempotent per ticket:attempt)
                         ├─ injection detection      ──► detected ──►  BLOCK (zero tokens spent)
                         ├─ drafted answer (HyDE): the passage that would answer the ticket,
                         │     steers retrieval only, never shown        ──► fails ──► HITL
                         ├─ retrieval: vector on the ticket + BM25 and vector on the draft
                         │     → RRF (k=60) → 10 pages, + each page's chunks nearest the draft
                         ├─ cross-encoder shortlist vs the ticket (+ chunks of entity-graph
                         │     linked pages) → top 15
                         ├─ Jev reranks the 15 → top 5, one page per slot
                         ├─ Jev chooses the category (ticket + the top page's title)
                         │     └─ Jev's top-1 below floor ──► refuse, LLM never called
                         ├─ few-shot selection
                         ├─ LLM inference (JSON-schema constrained, no retry)
                         └─ validation: exact quote → fuzzy ≥0.95 → in-top-k → negation check
                         ▼
                       Trust Scorer  (core-api — deliberately NOT in ai-engine)
                         ▼
                       Switch Router  (pure function, hard gates in order)
                         ├─ auto_reply   → KB-sourced answer     [requires kb.auto_reply_allowed]
                         ├─ auto_route   → assign to Jev's category's team
                         ├─ clarify      → ask which page they mean (in the chat; a review item for form tickets)
                         ├─ hitl         → human review queue
                         ├─ block        → security alert
                         └─ escalate     → incident management
```

Every outcome carries a machine-readable `ReasonCode`, which is what makes *"which reason pushed the most tickets to HITL this week?"* an answerable question.

---

## API

Interactive docs at [`/api/docs`](http://localhost:8000/api/docs). All routes except sign-in (`/api/auth/login`, `/refresh`, `/logout`) and the lifecycle callback require `Authorization: Bearer <access token>`, and core-api checks the caller's role on every one of them (PRE-1): a role outside the route's set gets 403 `{"code": "role_not_allowed", "message": …, "details": {"role": …}}` and writes an `access_denied` audit row (one per user, route and method per `access_denied.audit_window_seconds`). Sign-in (ADR-0029) returns a five-minute access token and sets the refresh token as an httpOnly cookie for `/api/auth/`; every request to `/api/auth/` names its frontend in `X-Auth-Client` (`admin` or `chat`).

| Method | Path | Role |
|---|---|---|
| `POST` | `/api/auth/login` · `/refresh` · `/logout` | — (`X-Auth-Client` header) |
| `GET`/`DELETE` | `/api/auth/sessions` · `/sessions/{family}` · `POST /api/auth/logout-everywhere` | any |
| `GET`/`POST`/`PATCH`/`DELETE` | `/api/lifecycle/...` (workflows, statuses, transitions, fields, ticket moves, approvals; ADR-0028) | technician+ / manager |
| `GET` | `/api/accounts/me` | any |
| `POST` | `/api/tickets/submit` | any |
| `GET` | `/api/tickets/{public_id}` | staff (technician, manager, security); an employee sees only their own (404 otherwise) |
| `GET` | `/api/tickets` · `/api/tickets/board` · `/api/tickets/{public_id}/detail` | technician, manager, security |
| `GET` | `/api/review/queue` | technician, manager, security |
| `GET`/`POST` | `/api/review/items/{id}` · `/claim` · `/decide` | technician, manager, security; a `runbook_approval` item is decided by a technician or manager only |
| `GET`/`POST` | `/api/kb` | any / manager |
| `POST` | `/api/kb/{slug}/auto-reply-allowed` · `/risk-tier` · `/reingest` | **manager** (route and model) |
| `GET` | `/api/metrics/dashboard` | technician, manager |
| `GET` | `/api/itsm/runbooks` · `POST /api/itsm/review-items/{id}/execute` | technician, manager |
| `GET` | `/api/fewshot/category/{category}` | technician, manager |

```bash
TOKEN=$(curl -s -X POST http://localhost:8000/api/auth/login \
  -H 'Content-Type: application/json' -H 'X-Auth-Client: chat' -c /tmp/st-cookies \
  -d '{"username":"employee1","password":"change-me"}' | python3 -c 'import json,sys;print(json.load(sys.stdin)["access"])')

curl -s -X POST http://localhost:8000/api/tickets/submit \
  -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d '{"subject":"Forgot my AWS access portal password","body":"I can'"'"'t remember my access portal password and I am locked out of all my accounts. How do I reset it?"}'
```

---

## Testing

```bash
uv sync --all-packages                     # once — installs every workspace member
uv run pytest                              # everything (unit + eval)
cd services/core-api && make test          # core-api only
uv run pytest services/ai-engine/tests -q
uv run pytest evals/suites -q              # the eval suites
```

> Use `uv sync --all-packages`, not a bare `uv sync`. The root project has no
> dependencies of its own, so a plain sync installs neither the workspace
> members nor Django — `pytest` then fails to start.

The eval suites that exercise the live pipeline **skip automatically** when `ai-engine` isn't reachable, so the unit suites stay runnable offline. `test_injection` and `test_quote_validation` run fully in-process with no dependencies.

Coverage on the two modules where it matters:

```bash
cd services/core-api && make coverage
```

Both sit at **100%**, and `make coverage` fails below that, as CI does. For masking, spec §14 makes it the P0 exit condition.

### Eval harness & CI gate

174 synthetic cases: 150 at the spec §12.1 distribution plus 24 edge cases (see [`evals/golden/SCHEMA.md`](evals/golden/SCHEMA.md)). The harness masks each ticket with core-api's own `mask()`, as production does. They are **synthetic on purpose and explicitly not a substitute** for a hand-labeled set — treat a pass as *"the wiring didn't regress"*, not *"the model is good."*

```bash
uv run pytest evals/suites -q
uv run python evals/report.py --compare evals/baselines/baseline.json
```

| Suite | Metric | Gate |
|---|---|---|
| Retrieval | Recall@3 | ≥ 0.90 |
| Classification | F1 **per category**, on Jev's choice | ≥ 0.85 each |
| Quote validation | Hallucination-catch precision | ≥ 0.95 |
| Refusal | Out-of-KB refusal rate | ≥ 0.90 |
| Injection | Detection recall | ≥ 0.95 |
| End-to-end | Auto-reply precision | ≥ 0.95 (absolute, not relative) |

Per-category F1 is deliberately not averaged — a rare-but-serious category like `security` can sit at 0.4 while the mean still looks healthy.

> **Gate state:** the last full run (2026-10-04 (8), `propose.v8`) passes every gate but auto-reply precision, 0.944 against 0.95: two underspecified tickets are auto-replied instead of clarified. Retrieval recall@3 0.917, per-category F1 ≥ 0.93 on Jev's category, branch accuracy 0.906. Every run, and what it meant, is in [`evals/HISTORY.md`](evals/HISTORY.md); earlier runs are in [`evals/HISTORY-archive.md`](evals/HISTORY-archive.md). Do not lower a floor to make CI green.

---

## Architecture Decision Records

| ADR | Decision |
|---|---|
| [0001](docs/adr/0001-code-level-routing.md) | Routing by code, never by prompt |
| [0002](docs/adr/0002-kb-level-autoreply-authority.md) | Auto-reply authority lives on KB metadata |
| [0003](docs/adr/0003-reject-llm-self-confidence.md) | `llm_self_confidence` excluded from routing and trust score |
| [0004](docs/adr/0004-split-ai-engine.md) | ai-engine split out with read-only DB credentials |
| [0005](docs/adr/0005-threshold-on-cross-encoder-not-fused-score.md) | Thresholds on cross-encoder scores, never on fused RRF ranks |
| [0006](docs/adr/0006-runbook-always-hitl.md) | Runbook execution always requires human approval |
| [0007](docs/adr/0007-langchain-owns-transport-only.md) | LangChain owns transport only |
| [0008](docs/adr/0008-sqlalchemy-query-layer.md) | ai-engine queries through SQLAlchemy |
| [0009](docs/adr/0009-self-hosted-vllm-backend.md) | Self-hosted vLLM as the model backend |
| [0010](docs/adr/0010-no-shared-contracts.md) | No shared contracts package; wire schemas in both services |
| [0011](docs/adr/0011-uuid-primary-keys.md) | UUID primary keys |
| [0012](docs/adr/0012-ai-engine-is-the-only-vllm-client.md) | ai-engine is the only vLLM client |
| [0013](docs/adr/0013-pg-search-bm25-and-keyword-agreement.md) | pg_search BM25 and keyword agreement (BM25 on the ticket superseded by 0020) |
| [0014](docs/adr/0014-candidate-expansion-and-llm-reorder.md) | Candidate expansion through page links (Proposed) |
| [0015](docs/adr/0015-jev-reranks-the-shortlist.md) | Jev reranks the cross-encoder's shortlist; thresholds read its score |
| [0016](docs/adr/0016-clarify-branch.md) | A `clarify` branch (Proposed) |
| [0017](docs/adr/0017-jev-classifies-the-category.md) | Jev chooses the category; the LLM's is log-only (Proposed) |
| [0018](docs/adr/0018-association-sources.md) | Association sources for link expansion: authored links or an entity graph (entity graph shipped) |
| [0019](docs/adr/0019-deepseek-for-evaluation.md) | DeepSeek's hosted API, for evaluation (draft superseded by 0022) |
| [0020](docs/adr/0020-no-bm25-on-the-ticket.md) | No BM25 on the ticket; the keyword-agreement trust feature removed |
| [0021](docs/adr/0021-hyde-drafted-answer-steers-retrieval.md) | A drafted answer steers retrieval (HyDE) |
| [0022](docs/adr/0022-deepseek-drafts-in-production.md) | The drafted answer runs on DeepSeek in production |
| [0023](docs/adr/0023-requester-answers-the-clarifying-question.md) | The requester answers the clarifying question (Proposed) |
| [0024](docs/adr/0024-drafted-answer-grounded-in-kb-pages.md) | The drafted answer is grounded in the KB's pages (Rejected for now: no measured gain on this KB) |

ADR-0006 is flagged in the spec as the one most likely to erode once `automation_rate` becomes a KPI. Read it before proposing a bypass.

---

## Rollout phases

| Phase | Enable | Gate to advance |
|---|---|---|
| **P2** | Calibrate trust score; set `T_auto`/`T_route` from PR curve | Auto-reply precision ≥ 0.95 on holdout |
| **P3** | Auto-route (`SHADOW_MODE=false`) | Reroute rate < 15% for 2 weeks |
| **P4** | Auto-reply on 3–5 `risk_tier=low` KB articles | Reopen rate < 5% for 1 month |
| **P5** | Runbooks (still via HITL), few-shot pool, widen KB whitelist | Per-batch reopen threshold |

P3 precedes P4 deliberately: a wrong auto-route costs one technician click (and yields a free training label), while a wrong auto-reply reaches the user on a closed ticket where nobody notices.

---

## Operations

[`docs/runbooks/on-call.md`](docs/runbooks/on-call.md) covers LLM provider outages, the daily cost ceiling, embedding outages, degraded retrieval, and the MASK_FAILED flood.

The two metrics most worth watching are counterintuitive: **`reopen_rate_after_autoreply`** (a wrong auto-reply that closed the ticket is an *invisible* failure) and **`approve_rate_per_reviewer`** — a reviewer approving >95% at <10 s median is rubber-stamping, which is worse than having no HITL at all because it manufactures false assurance.

---

## Tech stack

| Layer | Technology |
|---|---|
| API | Django 6.0 · Django Ninja · ninja-jwt |
| AI pipeline | FastAPI 0.140 · LangGraph |
| Task queue | Celery 5.6 · Redis 7 |
| Database | PostgreSQL 17 · pgvector (HNSW) · ParadeDB pg_search (BM25) |
| Embeddings | BGE-M3, 1024-dim (via vLLM) |
| Shortlister | BGE-Reranker-v2-M3 cross-encoder (via vLLM, default) · lexical (CI) |
| Reranker · category | Jev `jev-1.13.0` (TypeSafe System One, hosted) |
| LLM | Qwen3 8B AWQ for inference and PII NER (via vLLM) |
| Frontend | Next.js 15 · React 19 · Tailwind |
| Tooling | uv workspace · pytest · Ruff |

---

## License

Proprietary. All rights reserved.
