# Smart Ticket Triage

An AI-assisted IT service desk. It masks, classifies, routes and answers support
tickets. It also runs the rest of the desk: ticket lifecycles, SLAs, teams,
incidents, security, KB governance, reporting, access control, and an agent
that works on the requester's behalf. Humans stay in the loop at every step
that matters.

> **The governing principle:** the LLM produces *proposals*; deterministic code makes *decisions*.
> Every LLM-authored field carries a `proposed_` prefix, a pure `Router` is the only place a
> branch is chosen, and ai-engine connects to Postgres as a role that can only read.

Implements [`requirement.md`](requirement.md) (Architecture Specification v2, in Vietnamese) and
the phase 2 pack in [`docs/requirements/phase-2/`](docs/requirements/phase-2/README.md)
(features F1–F17). Section references in the code and docs (`§5`, `§8`, `F15 §h.3`) point back to them.

---

## New here?

Go to **[`docs/`](docs/README.md)**. It gives a reading order that takes about an hour.

| Start with | For |
|---|---|
| [Onboarding](docs/onboarding.md) | Get it running and watch a ticket get triaged. Do this first. |
| [Glossary](docs/glossary.md) | The vocabulary. The spec is Vietnamese and its terms are everywhere. |
| [Architecture](docs/architecture.md) | How the pieces fit and the exact path a ticket takes. |
| [Development](docs/development.md) | Conventions, common tasks, and the setup gotchas. |
| [Testing](docs/testing.md) | Test layers and what the CI gate enforces. |
| [`CLAUDE.md`](CLAUDE.md) | The hard rules and the "where to make a change" table |

The rest of this README is reference material: what the system is, how to run it, and where the settings are.

---

## Current status

The system runs end to end, and **every automated branch is live by default**
(ADR-0051, the owner's choice for the R&D stage). A branch acts exactly when its
rollout flag is on, and every flag starts on, the agent's included. A manager or
security officer turns one off in **Admin → Rollout**, or all of them at once
(`POST /api/rollout/off`, `manage.py rollout_off`). A held-back decision is still
recorded while a person handles the ticket. `SHADOW_MODE` is gone.

> ⚠️ This relaxes a guardrail. The trust-score coefficients and `t_auto` / `t_route` are
> still a **hand-set prior**, not fitted: calibration needs ≥ 500 decision pairs (TODO 28).

| Area | State |
|---|---|
| Spec v2 core: masking, AI graph, trust score, router, HITL, audit, evals | ✅ Built. Masking and router at 100% branch coverage |
| Phase 2 F1–F14: SLA, teams, chat, notifications, PII reveal, KB governance, incidents, security, rollout, reports, entity graph, runbooks, SSO, access | ✅ Unit-tested and browser-checked |
| F15 agent (ADR-0046) | ⚠️ Built (nine PRs). The trace suite and the `agent` eval have not run yet |
| F17 infrastructure reach (ADR-0048) | 🚧 PRs 1–3a merged (cloud-sim, scoped reads, structured queries, customers). 3b–9 in review |
| F16 agent wave 2 (ADR-0047) · ADR-0050 · ADR-0049 parts 2–4 | 📝 Proposed |
| Trust-score calibration | ⏳ Scripts ready; waits for ≥ 500 pairs |

[`docs/status.md`](docs/status.md) has the component-by-component breakdown, where ✅ means
*verified working*, not *code exists*. [`docs/TODO.md`](docs/TODO.md) has the prioritized open work.

---

## Architecture

```
   ┌──────────────────────┐        ┌──────────────────────┐
   │ admin-console :3000  │        │ chat :3001           │
   │ Workspace · Admin    │        │ ask · My tickets     │
   │ (staff)              │        │ (requesters, agent)  │
   └──────────┬───────────┘        └──────────┬───────────┘
              │   REST · session tokens · URN permissions
              └──────────────┬────────────────┘
                             │            ┌──────────────────┐
                             │            │ Keycloak (SSO)   │
┌────────────────────────────▼───────┐    │ OIDC + PKCE      │
│ core-api (Django + Ninja)          │◄───┤                  │
│ the source of truth                │    └──────────────────┘
│ masking · trust score · Router     │
│ HITL · lifecycle · SLA · teams     │    ┌──────────────────┐
│ incidents · security · KB · audit  │───►│ cloud-sim (dev)  │
│ rollout · reports · access · agent │    │ OpenStack APIs,  │
└───┬────────────────────┬───────────┘    │ Prometheus, ES,  │
    │ Celery: worker,    │ read/write     │ APM, Alertmgr    │
    │ worker-agent, beat │                └──────────────────┘
┌───▼───────────────┐  ┌─▼───────────────────┐
│ ai-engine         │  │ PostgreSQL 17       │
│ FastAPI+LangGraph │─►│ pgvector · pg_search│
│ triage graph      │RO│                     │
│ agent graph       │  └──────────▲──────────┘
│ NO authority      │             │ entity-graph rows only
└──┬─────────────┬──┘  ┌──────────┴──────────┐
   │             │     │ graph-builder       │
   │             │     └─────────────────────┘
┌──▼─────────┐ ┌─▼──────────────┐
│ vLLM       │ │ hosted models  │
│ embed ·    │ │ Jev: rerank ·  │
│ cross-enc. │ │ category       │
│ (chat opt.)│ │ DeepSeek: chat │
└────────────┘ └────────────────┘
```

| Service | Stack | Role |
|---|---|---|
| **core-api** | Django 6 · Django Ninja · Celery | Every decision and every write but one. Business logic, the `Router`, HITL, the ticket lifecycle, and the permission check on every route |
| **ai-engine** | FastAPI · LangGraph | Has **no authority**. The triage graph returns signals and a proposal and writes nothing. The agent graph acts only by calling core-api routes as the signed-in person. It is the only client of every model (ADR-0012). It connects as `ai_engine_ro` with `SELECT`-only grants (ADR-0004). The one exception is the offline entity-graph build (ADR-0025, ADR-0037) |
| **admin-console** | Next.js 15 · React 19 | Staff console: a **Workspace** for daily work and an **Admin** area under `/admin/*` (ADR-0039). Thin client |
| **chat** | Next.js 15 · React 19 | The requester's app: chat questions, clarifying answers, My tickets, the agent. Thin client |
| **cloud-sim** | FastAPI | A simulated OpenStack with metrics, logs, traces and faults for F17 (dev and test only, ADR-0048) |

| Compose service / profile | Purpose |
|---|---|
| `db` · `redis` | Postgres 17 + pgvector + ParadeDB `pg_search` (ADR-0013) · Celery broker |
| `worker` · `worker-agent` · `beat` | Celery: the pipeline and actions · agent turns on their own queue · sweeps and nightly jobs |
| `graph-builder` | Rebuilds stale entity-graph edges every `GRAPH_BUILD_INTERVAL_MIN` |
| `vllm` profile | `vllm-embed` (bge-m3), `vllm-rerank` (bge-reranker-v2-m3 shortlister), and `vllm-chat` (Qwen3-8B-AWQ, only for a job set to `vllm`) |
| `sso` profile | Keycloak with the dev realm in `infra/keycloak/` (ADR-0032) |
| `infra` profile | cloud-sim, Prometheus, prom-label-proxy, Alertmanager, Elasticsearch, Kibana, APM Server |

| Hosted model | Job | Receives |
|---|---|---|
| **Jev** (`jev-1.13.0`, needs `JEV_API_KEY`) | Reranks the shortlist and chooses the category, each as one choice question (ADR-0015, ADR-0017, ADR-0026) | Masked ticket text and KB text |
| **DeepSeek** (needs `CLOUD_API_KEY`) | The template's default for all four chat jobs: proposal, HyDE draft, PII NER, agent (ADR-0019, ADR-0022) | Masked text. NER sees raw text, and only when `NER_CLIENT_PROVIDER=deepseek` |

---

## Key design principles

- **LLM proposes, code decides.** [`router.py`](services/core-api/apps/tickets/domain/router.py) is the only place a `Branch` is chosen. `Router(thresholds).route(...)` is pure: no I/O and no global config. That makes every branch testable without a model or a network, and lets a decision be replayed against `routing_decisions.thresholds_used` (ADR-0001).
- **The flag decides whether, never which.** The same `route()` runs whether a branch is live or held back, so a held-back decision describes exactly what would have happened live (ADR-0051).
- **Trust score over self-confidence.** `llm_self_confidence` is logged but never scored or routed on (ADR-0003). Trust comes from signals that can be checked from outside the model: Jev's score, whether a quote exists in the cited chunk, and whether a negation was flipped.
- **Degrade toward humans.** Every failure goes to HITL with a specific `ReasonCode`: masking, embedding, a model or Jev outage, weak retrieval, an agent hand-off, or the cost ceiling. The dashboard is built on that enum.
- **Authority lives on the KB, not in the model.** A page may be auto-replied from only if a manager granted it, with a reason, and the grant is pinned to the SHA-256 of the reviewed text (ADR-0002, ADR-0036). Editing the text revokes it.
- **Refuse before spending.** If Jev's passages fall below `retrieval.floor`, the proposal LLM is never called.
- **Runbooks always go to a human** (ADR-0006). No threshold or flag bypasses that, and the real Keycloak and n8n executors stay behind it (ADR-0038).
- **The agent acts as the user.** It holds the person's own permissions, and every route declares an agent tier: read, self, confirm, human_only or none. Changes go through confirmation cards, never around them (ADR-0046).
- **One tunable, one place.** Every number is in [`thresholds.yaml`](services/core-api/config/thresholds.yaml), which changes by pull request (ADR-0044). Every operational setting is in [`.env.example`](.env.example). Neither has a default in code.

---

## What it does

Each phase 2 feature has its own spec in [`docs/requirements/phase-2/`](docs/requirements/phase-2/README.md).

| | Feature | What it adds | ADR |
|---|---|---|---|
| — | **Triage** | Inline two-tier PII masking, incident check, LangGraph pipeline, trust score, the `Router`'s six branches, HITL queue with eval-candidate feedback | 0001–0027 |
| — | **Lifecycle** | Configurable workflows, statuses with a kind, transitions with field rules, custom fields, and actions (assignment, SLA, email, webhook, n8n) | 0028, 0040 |
| F1 | SLA | Business-time response and resolution clocks per calendar and policy. Priority comes from incidents, security and the customer's tier floor | 0030 |
| F2 | Teams | Category ownership, `least_loaded` / `round_robin` assignment at handoff, take and reassign | 0031, 0041 |
| F3 | Requester chat | Conversations with up to 6 earlier masked turns as context, My tickets, replies, reopen, ratings | 0034 |
| F4 | Notifications | Outbox written in the event's transaction. Email and signed webhooks after commit, per-user preferences and language | 0033 |
| F5 | PII reveal | The one `decrypt()` caller, with a reason, an append-only access log and rate limits | — |
| F6 | KB governance | Drafts outside `kb_articles`, approved by a second person. Authority queue and gap report | 0036 |
| F7 | Mass incidents | Centroid matching, an adaptive-baseline detector, confirm, broadcasts, close-all | — |
| F8 | Security inbox | Every security event raised through one service, grouped, acknowledged and triaged | — |
| F9 | Rollout | A flag per branch (`auto_route`, `auto_reply`, `requester_questions`, agent), recorded on every decision | 0035, 0051 |
| F10 | Reports | Nightly facts table, SLA / automation / team reports, CSV, weekly email | — |
| F11 | Entity graph | Link expansion over an LLM-built entity graph. Edits mark edges stale, `graph-builder` rebuilds them, editors can override | 0018, 0025, 0037 |
| F12 | Runbooks | Catalog as data. Keycloak and n8n executors with target rules, always approved by a person | 0006, 0038 |
| F13 | Identity | Keycloak OIDC + PKCE sign-in. core-api keeps rotating-refresh sessions in httpOnly cookies | 0029, 0032 |
| F14 | Org & access | URN permissions, roles as permission sets, grants scoped to global / team / department, access reviews | 0042, 0045 |
| F15 | Agent | A bounded agent graph (screen → choose action ⇄ call tool → reply / confirm card / hand-off) that acts as the user | 0046 |
| F17 | Infrastructure | Scoped, masked reads of the customer's cloud (OpenStack, Prometheus, logs, traces, alerts). Customers and tiers. Infra actions through core-api | 0048 |
| — | Categories | Categories are rows in `ticket_categories`. Jev's options are their descriptions | 0049 |

---

## Ticket processing pipeline

```
Ticket submitted ──► PII masking (inline, before any DB write)
                       │ regex tier 1: critical (password/token)      ──► block + security alert
                       │ NER tier 2 (ai-engine): error or over-masking ──► HITL mask_failed
                       ▼
                     Customer lookup (Keystone domain → customer, F17)
                     Embedding + mass-incident check
                       │ embedding unavailable                        ──► HITL embedding_unavailable
                       │ joins / triggers a mass incident             ──► escalate, skip AI
                       ▼
                     ai-engine triage graph (Celery, idempotent per ticket:attempt)
                       ├─ injection detection                ──► detected ──► block, zero tokens
                       ├─ draft_answer (HyDE): the passage that would answer it ──► fails ──► HITL
                       ├─ retrieve: vector on the ticket + BM25 and vector on the draft → RRF
                       ├─ candidate_pool: cross-encoder vs the ticket, + entity-graph links → 15
                       ├─ rerank: Jev's choice question → top 5, one page per slot
                       │     └─ below retrieval.floor ──► refuse, LLM never called
                       ├─ classify_category: Jev chooses among the active categories
                       ├─ few-shot selection → infer (JSON-schema constrained, no retry)
                       └─ validate: exact quote → fuzzy ≥ 0.95 → in top-k → negation
                       ▼
                     Trust scorer (core-api, so the LLM can't score itself)
                       ▼
                     Router (pure, hard gates in order)
                       ├─ auto_reply → KB-sourced answer   [authorized page, Jev's choice ≥ 0.9]
                       ├─ auto_route → the category's team, assigned by its strategy
                       ├─ clarify    → ask which shown page they mean (one round)
                       ├─ hitl       → review queue, with a ReasonCode
                       ├─ block      → security alert
                       └─ escalate   → incident management
                       ▼
                     Rollout flag on? act : hold back (recorded, a person handles it)
                       ▼
                     Lifecycle: status via lifecycle.system_move → SLA clocks → notifications
```

**Agent turns** follow their own path ([`apps/agent/services/turns.py`](services/core-api/apps/agent/services/turns.py)).
core-api masks the message inline: a mask failure or critical PII hands off before any model runs.
It queues the turn on `worker-agent`, and ai-engine's agent graph calls core-api routes as the person.
Every step, receipt and token is recorded. A change becomes a confirmation card, and a hand-off reaches the `Router` with its own reason.

Every outcome carries a machine-readable `ReasonCode`, so *"which reason sent the most tickets to a person this week?"* is a query, not an investigation.

---

## Repository structure

```
smart_ticket/
├── services/
│   ├── core-api/                 # Django + Ninja + Celery
│   │   ├── Makefile              #   every dev command; `make` lists them
│   │   ├── apps/                 #   each: models · domain/ · services/ · views · *_schema · tasks · tests/
│   │   │   ├── core/             #     shared foundation, imports no app
│   │   │   ├── tickets/          #     intake, masking, trust scorer, router, pipeline, comments, PII reveal
│   │   │   ├── review/ fewshot/  #     HITL queue and decisions · the few-shot pool
│   │   │   ├── lifecycle/        #     workflows, transitions, rules, actions (ADR-0028)
│   │   │   ├── categories/ sla/ teams/                # ADR-0049 · F1 · F2
│   │   │   ├── chat/ requester/ notifications/        # F3 · F3 · F4
│   │   │   ├── kb/ incidents/ security/ rollout/      # F6, F11 · F7 · F8 · F9
│   │   │   ├── reports/ metrics/                      # F10 · the dashboard
│   │   │   ├── itsm_mock/ accounts/ agent/ infra/     # F12 · F13, F14 · F15 · F17
│   │   │   ├── audit/            #     append-only audit log
│   │   │   └── dbextras/         #     RunSQL migrations for infra/migrations/sql/
│   │   ├── infrastructure/       #   AIEngineClient and the wire schema (dtos.py)
│   │   ├── scripts/gen_typescript.py  # generates both frontends' lib/types/generated.ts
│   │   └── config/               #   settings/{base,development,production,test} · celery · thresholds.yaml
│   ├── ai-engine/src/ai_engine/  # FastAPI + LangGraph
│   │   ├── main.py · schemas.py  #   /v1/analyze, /v1/agent/turn, /v1/embed, /v1/pii/detect
│   │   ├── graph/                #   triage.py · agent.py · ticket.py · agent_state.py · build/
│   │   │   └── nodes/            #   injection · draft_answer · retrieve · candidate_pool · rerank ·
│   │   │                         #   classify_category · score_options · infer · validate · emit_signals · agent/
│   │   ├── agent/tools/          #   the agent's tools: core-api routes, as the person
│   │   └── core/                 #   config · db (read-only) · providers · prompts · associations (entity graph)
│   ├── admin-console/            # Next.js staff console (Workspace + /admin/*)
│   ├── chat/                     # Next.js requester app
│   └── cloud-sim/                # simulated OpenStack (F17, dev and test only)
├── evals/                        # eval harness, gated in CI
│   ├── golden/                   #   tickets.jsonl (652) · kb_covered_drafted.jsonl (440) · multi_turn.jsonl (24)
│   ├── suites/                   #   11 suites, see Testing
│   ├── HISTORY.md · history/     #   every full run and what it meant
│   ├── calibration/              #   fit the trust score, choose thresholds from the PR curve
│   └── baselines/baseline.json   #   committed; a change needs a reviewer other than the author
├── demo_kb/                      # frozen AWS-docs snapshot: sources, manifest, curation
├── infra/
│   ├── db/                       #   Postgres image (pgvector + pg_search)
│   ├── keycloak/                 #   dev realm and test users
│   ├── observability/            #   Prometheus rules, Alertmanager, APM config
│   └── migrations/sql/           #   grants, CHECKs, HNSW indexes, triggers
├── docker-compose.yml · .env.example
├── .github/workflows/            # lint · eval-gate · publish-images
└── docs/                         # reading path, architecture, status, TODO, 51 ADRs, runbooks,
                                  # requirements/phase-2/ (F1–F17 specs)
```

---

## Prerequisites

| Requirement | Version | Notes |
|---|---|---|
| Python | 3.13+ | |
| Node.js | 18.18+ | 24 recommended (Next 15) |
| Docker + Compose | v2+ | |
| [uv](https://docs.astral.sh/uv/) | 0.9+ | manages the Python workspace |
| NVIDIA GPU | — | for the `vllm` profile (embeddings, shortlister); on Windows via WSL2 |
| API keys | — | `JEV_API_KEY` (rerank, category) and `CLOUD_API_KEY` (DeepSeek, the template's chat provider) |

Without the models, tickets still flow. Masking fails closed to `mask_failed`,
and a run that reaches retrieval without Jev fails to `ai_engine_unavailable`.
Both send the ticket to a person, by design.

---

## Getting started

```bash
cp .env.example .env                       # every setting, its value and why; only .env is read
docker compose up -d --build               # core stack; migrations run on core-api start
docker compose --profile vllm up -d vllm-embed    # then vllm-rerank; vllm-chat only if a job uses it
docker compose --profile sso up -d keycloak       # sign-in (test users: password change-me)
docker compose --profile infra up -d              # optional: cloud-sim and observability (F17)
```

The vLLM servers share one GPU. Start them one at a time and size their memory
fractions to your card first: [`docs/onboarding.md`](docs/onboarding.md) step 2 has the numbers.
For anything beyond local dev, regenerate the secrets in `.env`, for example:

```bash
python -c "import os,base64;print('PII_ENCRYPTION_KEY='+base64.b64encode(os.urandom(32)).decode())"
```

| Service | Host port | |
|---|---|---|
| `admin-console` | [3000](http://localhost:3000) | staff console |
| `chat` | [3001](http://localhost:3001) | requester app |
| `core-api` | [8000](http://localhost:8000/api/docs) | REST API and OpenAPI docs |
| `ai-engine` | [8001](http://localhost:8001/docs) | AI service |
| `keycloak` | [8081](http://localhost:8081) | SSO (`sso` profile) |
| `vllm-chat` / `-embed` / `-rerank` | 8100–8102 | `vllm` profile |
| `db` · `redis` | **5434** · **6380** | inside compose still `db:5432` / `redis:6379` |
| `cloud-sim` · Prometheus · Alertmanager · ES · Kibana · APM | 8090 · 9091 · 9094 · 9201 · 5602 · 8201 | `infra` profile, [README](services/cloud-sim/README.md) |

### Users and the demo knowledge base

The demo KB is a frozen snapshot of AWS documentation in [`demo_kb/`](demo_kb/): every page of 12 guides, 3,542 pages, for an internal cloud-platform help desk. Demo tickets are in English.

```bash
python3 demo_kb/fetch.py     # first time: download the snapshot (~30 min, resumable)

# People sign in through Keycloak. The dev realm has lan.nt (employee); duc.tm, ha.vt,
# mai.bn, tu.dv (technicians); huy.pq, quang.nv, dung.ht (managers); anh.lh (security).
# core-api creates each on first sign-in; access is granted in Admin → People & access.

# The KB loader names an approving manager. Local password sign-in is for
# break-glass managers only (at most identity.max_break_glass_accounts).
docker compose exec core-api python manage.py shell -c "
from apps.accounts.models import User
User.objects.create_user('manager1', password='change-me', role='manager')"
docker compose exec core-api python manage.py set_break_glass manager1

cd services/core-api && make load-demo-kb ARGS="--approver manager1"
# then ai-engine's build --rescore-only writes the entity-graph edges (demo_kb/README.md)
```

`load_demo_kb` checks every page against `demo_kb/manifest.json`. It then applies the auto-reply
approvals in `demo_kb/curation.json` through the same governance path a manager uses. Each approval
is pinned to the SHA-256 of the reviewed text, so a page whose text changed is not authorized.

### Local development (without Docker)

```bash
uv sync --all-packages                     # NOT a bare `uv sync`: the root project has no deps

cd services/core-api && make migrate runserver           # :8000; also make worker, beat
uv run --project services/ai-engine uvicorn ai_engine.main:app \
    --app-dir services/ai-engine/src --port 8001 --reload
cd services/admin-console && npm install && npm run dev  # :3000
cd services/chat && npm install && npm run dev           # :3001
```

The root `.env` already points at the Dockerized Postgres and Redis on their host ports.

---

## Configuration

### Thresholds

Every tunable number is in [`services/core-api/config/thresholds.yaml`](services/core-api/config/thresholds.yaml).
It is parsed into a Pydantic model at boot, so core-api refuses to start if it is malformed.
It changes only by pull request, with a new `version` (ADR-0044). Some of the values:

| Parameter | Value | Purpose |
|---|---|---|
| `routing.t_auto` · `t_route` | 0.88 · 0.72 🔧 | Trust minimum for auto-reply · auto-route |
| `routing.quote_match` | 0.95 | Minimum verbatim-quote match ratio |
| `retrieval.floor` | 0.6 🔧 | Jev's passages' total below which the proposal LLM is never called (ADR-0005, ADR-0015) |
| `retrieval.min_rerank_confidence` | 0.9 🔧 | Jev's confidence an auto-reply's cited page needs |
| `classification.min_confidence` | 0.65 🔧 | Jev's category confidence below which a route or clarify goes to a person |
| `clarification.max_rounds` · `wait_minutes` | 1 · 60 🔧 | Questions a chat ticket may ask · how long one stays open |
| `masking.ner_max_share` | 0.7 🔧 | Share of a ticket NER may mask before it is `mask_failed` |
| `incident.similarity` · `min_count` | 0.85 · 5 | Joining an open incident · proposing a new one |
| `sla.*` · `sla.tier_floor` | — | Warning percentages · the priority each customer tier raises to |
| `agent.max_steps` · `max_tool_calls_per_turn` | 8 · 6 | Bounds on one agent turn |
| `budget.daily_cost_ceiling_usd` | 50 🔧 | Above it, AI is off and everything goes to a person |

🔧 marks an assumption awaiting calibration. The full snapshot is written to
`routing_decisions.thresholds_used` on every decision, together with the rollout
flags it ran under (`rollout_snapshot`).

### Environment

Every setting is in [`.env.example`](.env.example), with its value and the reason for it. Some of them:

| Variable | Template value | Effect |
|---|---|---|
| `CHAT_CLIENT_PROVIDER` · `DRAFT_…` · `NER_…` · `AGENT_…` | `deepseek` | Which model runs each chat job; `vllm` for self-hosted (CI pins `vllm`) |
| `EMBEDDING_PROVIDER` · `SHORTLIST_PROVIDER` | `vllm` | `stub` / `lexical` run with no model (CI) |
| `PROMPT_VERSION` · `DRAFT_PROMPT_VERSION` · `PII_NER_PROMPT_VERSION` · `AGENT_PROMPT_VERSION` | `propose.v10` · `hyde_draft.v3` · `pii_ner.v2` · `agent.v2` | Which prompt files run |
| `RERANK_PROMPT_VERSION` · `CATEGORY_QUESTION_VERSION` | `rerank_choice.v1` · `category.v2` | Which Jev question files run |
| `RERANK_POOL` · `RERANK_TOP_N` | 15 · 5 | Jev's shortlist · pages the proposal is shown |
| `MODEL_TIMEOUT_SEC` | 120 | Ceiling for one model call; connect timeouts are separate (3 s) |
| `PII_QUARANTINE_TTL_HOURS` | 72 | Hard TTL on encrypted raw PII |

A new setting goes in the settings code (type only), `.env.example` and the service's `environment:` in
`docker-compose.yml`. Tests fail if the three disagree. After pulling, diff your `.env` against `.env.example`.

---

## API

Interactive docs are at [`/api/docs`](http://localhost:8000/api/docs). Every route except sign-in,
refresh, sign-out and the lifecycle callback needs `Authorization: Bearer <access token>` from
`/api/auth/login` (ADR-0029). Each route checks a permission (`require(Permission.…)`, a URN; ADR-0045)
and declares the tier the agent may call it at (ADR-0046). A refusal is a 403 `permission_missing`
with an `access_denied` audit row, and `test_every_route_is_gated` fails on a new route without a gate.

---

## Testing

```bash
uv sync --all-packages
uv run pytest                              # everything (unit + eval)
cd services/core-api && make check         # lint + typecheck + test
make coverage                              # masking + router at 100%, the release gate
uv run pytest services/ai-engine/tests -q
uv run pytest evals/suites -q              # live suites skip if ai-engine is down
uv run mypy                                # all four packages
```

### Eval harness and CI gate

The golden set is **synthetic**: a pass means *"the wiring didn't regress,"* never *"the model is good."*
The harness masks each ticket with core-api's own `mask()`, as production does.

| Suite | Metric | Gate |
|---|---|---|
| Retrieval | Recall@5 | ≥ 0.90 |
| Classification | F1 **per category**, on Jev's choice | each above its floor; never averaged |
| Quote validation | Hallucination-catch precision | ≥ 0.95 |
| Refusal · Injection | Out-of-KB refusal · detection recall | ≥ 0.90 · ≥ 0.95 |
| End-to-end | Auto-reply **page** precision (branch and cited page both right) | ≥ 0.95, absolute |
| Masking · multi-turn · agent traces | Masking end to end · chat memory · agent behaviour | multi-turn and trace cases await review |

> **Gate state:** the last full run (2026-10-14 (2), `rerank_choice.v1`, `category.v2`) passed every gate it
> measured: recall@5 0.924, auto-reply precision 0.992 (branch only), per-category F1 ≥ 0.90,
> refusal and injection 1.00. Since 2026-11-06 the gate is page precision, which the full-set sweep measured
> at **0.946, below the floor**. `propose.v10`, `hyde_draft.v3` and `agent.v2` have not been evaluated yet.
> Every run is in [`evals/HISTORY.md`](evals/HISTORY.md). **Never lower a floor to make CI green.**

---

## Architecture Decision Records

Fifty-one decisions in [`docs/adr/`](docs/adr/), each written to survive being re-litigated. Read 0001 and 0003 at minimum.

| ADR | Decision |
|---|---|
| [0001](docs/adr/0001-code-level-routing.md) | Routing by code, never by prompt |
| [0002](docs/adr/0002-kb-level-autoreply-authority.md) | Auto-reply authority lives on KB metadata |
| [0003](docs/adr/0003-reject-llm-self-confidence.md) | `llm_self_confidence` excluded from routing and trust score |
| [0004](docs/adr/0004-split-ai-engine.md) | ai-engine split out with read-only DB credentials |
| [0005](docs/adr/0005-threshold-on-cross-encoder-not-fused-score.md) | Thresholds on a reranker's score, never on fused RRF ranks |
| [0006](docs/adr/0006-runbook-always-hitl.md) | Runbook execution always requires human approval |
| [0007](docs/adr/0007-langchain-owns-transport-only.md) | LangChain owns transport only |
| [0008](docs/adr/0008-sqlalchemy-query-layer.md) | ai-engine queries through SQLAlchemy |
| [0009](docs/adr/0009-self-hosted-vllm-backend.md) | Self-hosted vLLM as the model backend |
| [0010](docs/adr/0010-no-shared-contracts.md) | No shared contracts package; wire schemas in both services |
| [0011](docs/adr/0011-uuid-primary-keys.md) | UUID primary keys |
| [0012](docs/adr/0012-ai-engine-is-the-only-vllm-client.md) | ai-engine is the only model client |
| [0013](docs/adr/0013-pg-search-bm25-and-keyword-agreement.md) | pg_search BM25 (BM25 on the ticket superseded by 0020) |
| [0014](docs/adr/0014-candidate-expansion-and-llm-reorder.md) | Candidate expansion through page links (partly superseded by 0015, 0026) |
| [0015](docs/adr/0015-jev-reranks-the-shortlist.md) | Jev reranks the cross-encoder's shortlist; thresholds read its score |
| [0016](docs/adr/0016-clarify-branch.md) | A `clarify` branch |
| [0017](docs/adr/0017-jev-classifies-the-category.md) | Jev chooses the category |
| [0018](docs/adr/0018-association-sources.md) | Association sources for link expansion: the entity graph |
| [0019](docs/adr/0019-deepseek-for-evaluation.md) | DeepSeek's hosted API, for evaluation |
| [0020](docs/adr/0020-no-bm25-on-the-ticket.md) | No BM25 on the ticket |
| [0021](docs/adr/0021-hyde-drafted-answer-steers-retrieval.md) | A drafted answer steers retrieval (HyDE) |
| [0022](docs/adr/0022-deepseek-drafts-in-production.md) | The drafted answer runs on DeepSeek |
| [0023](docs/adr/0023-requester-answers-the-clarifying-question.md) | The requester answers the clarifying question |
| [0024](docs/adr/0024-drafted-answer-grounded-in-kb-pages.md) | Drafts grounded in KB pages (Rejected for now) |
| [0025](docs/adr/0025-ai-engine-writes-the-entity-graph.md) | ai-engine writes the entity graph's rows |
| [0026](docs/adr/0026-jev-reranks-with-one-choice-question.md) | Jev reranks with one choice question; an auto-reply cites Jev's choice |
| [0027](docs/adr/0027-owner-approves-low-and-medium-risk-pages.md) | Every low- and medium-risk demo page approved for auto-reply |
| [0028](docs/adr/0028-configurable-ticket-lifecycle.md) | Configurable ticket lifecycle |
| [0029](docs/adr/0029-rotating-refresh-tokens-in-httponly-cookies.md) | Rotating refresh tokens in httpOnly cookies |
| [0030](docs/adr/0030-sla-clocks-on-lifecycle-events.md) | SLA clocks count business time, driven by lifecycle events |
| [0031](docs/adr/0031-capabilities-and-team-scope.md) | Capabilities and team scope alongside the role |
| [0032](docs/adr/0032-keycloak-signs-in-core-api-keeps-the-session.md) | Keycloak signs people in; core-api keeps the session |
| [0033](docs/adr/0033-notifications-through-an-outbox.md) | Notifications through an outbox, sent after commit |
| [0034](docs/adr/0034-conversation-context-for-the-model.md) | A chat conversation gives the model its earlier masked turns |
| [0035](docs/adr/0035-reviewed-thresholds-and-per-branch-rollout.md) | Per-branch rollout switches |
| [0036](docs/adr/0036-kb-drafts-outside-kb-articles.md) | KB drafts outside `kb_articles`; a text change revokes authority |
| [0037](docs/adr/0037-entity-graph-as-a-kb-feature.md) | The entity graph survives edits, rebuilds, takes overrides |
| [0038](docs/adr/0038-runbook-executors-behind-adr-0006.md) | Real runbook executors stay behind ADR-0006 |
| [0039](docs/adr/0039-console-workspace-and-admin-areas.md) | The console has a Workspace and an Admin area |
| [0040](docs/adr/0040-workflow-statuses-carry-their-kind.md) | Workflow statuses carry their own kind |
| [0041](docs/adr/0041-teams-live-only-in-core-api.md) | Teams live only in core-api |
| [0042](docs/adr/0042-roles-are-set-in-the-console.md) | Roles and capabilities are set in the console |
| [0043](docs/adr/0043-one-person-applies-a-change.md) | One person applies a change (relaxes a guardrail) |
| [0044](docs/adr/0044-thresholds-change-by-pull-request.md) | `thresholds.yaml` changes by pull request (relaxes a guardrail) |
| [0045](docs/adr/0045-roles-are-permission-sets-with-scope.md) | Roles are permission sets, granted with a scope |
| [0046](docs/adr/0046-agent-acts-as-the-user.md) | The agent acts as the signed-in user, through tiered routes |
| [0047](docs/adr/0047-agent-arguments-and-grouped-actions.md) | Agent arguments checked; grouped actions (Proposed) |
| [0048](docs/adr/0048-agent-reaches-infrastructure.md) | The agent reads infrastructure and proposes changes through core-api |
| [0049](docs/adr/0049-ticket-categories-are-rows.md) | Ticket categories are rows (part 1 built) |
| [0050](docs/adr/0050-agent-asks-branch-picks-the-path.md) | The agent asks; the branch picks the workflow path (Proposed) |
| [0051](docs/adr/0051-a-flag-alone-makes-a-branch-live.md) | A branch's flag alone makes it live; shadow mode goes (relaxes guardrails) |

ADR-0006 is the one the spec flags as most likely to erode once `automation_rate` becomes a KPI.
Read it before proposing a bypass.

---

## Rollout

Since ADR-0051 there are no spec §14 phases to switch through. Each branch is live while its
flag is on in **Admin → Rollout**, and one manager can turn it on or off (ADR-0043). The spec's ordering still
explains which flag to turn off first if something goes wrong. Auto-route is the safest: a wrong
route costs one technician click and gives a free training label. A wrong auto-reply reaches the
user on a closed ticket, where nobody notices.

---

## Operations

[`docs/runbooks/on-call.md`](docs/runbooks/on-call.md) covers model and Jev outages, the daily cost ceiling,
embedding outages, degraded retrieval, and a `mask_failed` flood. To stop all automation at once:
`manage.py rollout_off`.

Two metrics deserve the most attention, and neither is obvious:

- **`reopen_rate_after_autoreply`**: a wrong auto-reply that closed the ticket is an *invisible* failure.
- **`approve_rate_per_reviewer`**: a reviewer approving > 95% in < 10 s is rubber-stamping. That is worse than no HITL, because it creates assurance that isn't real.

---

## Tech stack

| Layer | Technology |
|---|---|
| API | Django 6.0 · Django Ninja · Celery 5.6 · Redis 7 |
| AI pipeline and agent | FastAPI 0.140 · LangGraph |
| Database | PostgreSQL 17 · pgvector (HNSW) · ParadeDB pg_search |
| Embeddings · shortlister | BGE-M3 1024-dim · BGE-Reranker-v2-M3, via vLLM (`stub` / `lexical` in CI) |
| Reranker · category | Jev `jev-1.13.0` (TypeSafe, hosted) |
| Chat models | DeepSeek (hosted, the template default) · Qwen3-8B-AWQ via vLLM |
| Identity | Keycloak (OIDC + PKCE) · core-api sessions |
| Observability (F17 sim) | Prometheus · Alertmanager · Elasticsearch · Kibana · Elastic APM |
| Frontends | Next.js 15 · React 19 · Tailwind · shadcn/ui |
| Tooling | uv workspace · pytest · mypy + django-stubs · Ruff |

---

## License

Proprietary. All rights reserved.
