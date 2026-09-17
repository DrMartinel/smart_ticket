# Architecture

How the pieces fit, who is permitted to do what, and the exact path a ticket takes. Assumes you have read [`glossary.md`](glossary.md).

---

## 1. The organizing principle

> The LLM produces **proposals**. Deterministic code makes **decisions**.

Nearly every structural choice follows from wanting that boundary to hold even as prompts, models, and retrieval all change underneath it. Three mechanisms enforce it, at three different levels:

| Level | Mechanism | What it prevents |
|---|---|---|
| Types | Every LLM field prefixed `proposed_` | Reading a suggestion as a conclusion at the point of use |
| Code | `router.py` is the only place a `Branch` is chosen, and it is a pure function | A prompt change silently altering routing |
| Database | `ai-engine` connects as a `SELECT`-only role | A compromised or buggy AI service writing business data |

The third is the strongest, and it is why splitting `ai-engine` into its own service is worth the operational cost ([ADR-0004](adr/0004-split-ai-engine.md)). The boundary is enforced by Postgres grants, not by code review.

---

## 2. Services

```
┌──────────────────────────────────────────────────┐
│  web (Next.js)                                   │
│  /submit  /queue  /review/[id]  /dashboard  /kb  │
└───────────────────────┬──────────────────────────┘
                        │ REST · JWT · RBAC
┌───────────────────────▼──────────────────────────┐
│  core-api (Django + Ninja)   ← source of truth   │
│                                                  │
│  Masking ──► Incident ──► [ ai-engine ] ──►      │
│  Trust Scorer ──► Switch Router ──► HITL / act   │
│                                                  │
│  Owns: every write, every routing decision       │
└──────┬──────────────────────────────┬────────────┘
       │ Celery (idempotent)          │ read/write
┌──────▼───────────────┐   ┌──────────▼────────────┐
│  ai-engine           │   │  PostgreSQL + pgvector │
│  FastAPI + LangGraph │──►│                        │
│                      │ RO│  tickets, kb_chunks,   │
│  injection → retrieve│   │  ai_runs, audit_log…   │
│  → rerank → infer    │   └────────────────────────┘
│  → validate          │
│                      │   ┌────────────────────────┐
│  NO business writes  │   │  vLLM (self-hosted)    │
│  NO routing decisions│──►│  infer · embed · rerank│
└──────────────────────┘   └────────────────────────┘
```

### Why these boundaries

**core-api owns all writes and all decisions.** It is the only service that can change business state. If you are adding a feature that decides something, it belongs here.

**ai-engine has no authority.** It returns `TrustSignals` plus a proposal and nothing else. It was split out for four reasons, in ascending order of importance: dependency isolation (LangChain/LangGraph churn badly), differing scale profiles (RAM for models vs. I/O for API), independent deploys (change a prompt without restarting the gateway), and — the one that actually justifies the cost — **structural permission separation**.

**web is a thin client.** No business logic. Its TypeScript types are generated from the shared contracts, so a schema change that breaks the frontend fails at build rather than in production.

---

## 3. Shared contracts

`packages/contracts` is the single source of schema truth. Both Python services import it; the frontend's types are generated from it. There is no second definition of these shapes anywhere.

| Module | Contains |
|---|---|
| `enums.py` | `TicketCategory`, `PIILevel`, `Branch`, `ReasonCode`, `ReviewQueue`, `UserRole` |
| `ticket.py` | `TicketIn` (`extra="forbid"`), `TicketMasked` (`frozen=True`) |
| `llm_draft.py` | The proposal union: auto-reply / route / runbook / insufficient-context |
| `trust.py` | `RetrievalSignals`, `GenerationSignals`, `PolicySignals`, `TrustScore` |
| `routing.py` | `RoutingDecision`, `KBArticleMeta`, `Thresholds` |
| `ai_request.py` | The core-api ↔ ai-engine wire contract |

Two details worth understanding rather than just accepting:

**`TicketMasked` is `frozen=True`.** Once masked, no downstream code can alter the content. It carries `placeholder_keys` (`["[EMAIL_1]"]`) but never the values — looking those up requires the quarantine path, which is access-controlled and logged.

**`LLMProposalEnvelope` is a discriminated union** on `proposed_intent`. Pydantic routes by lookup table rather than trying each variant, which is faster and produces errors pointing at the right variant. `InsufficientContext` is a legitimate member, not an error case: the model needs a sanctioned way to say "I don't know", because a model with no such exit will invent something instead.

---

## 4. The path of one ticket

### Stage 1 — Submission and masking (synchronous, in the request)

```
POST /api/tickets/submit
   │
   ├─ Tier 1: regex scan
   │    └─ password / token / API key found?
   │         └─► BLOCK, alert security. No model is called. Stop.
   │
   ├─ Tier 2: local LLM NER (free-form PII regex can't catch)
   │    └─ timeout or error?
   │         └─► pii_level = mask_failed  (never "assume clean")
   │
   ├─ Replace hits with numbered placeholders  [EMAIL_1], [PHONE_VN_1]
   ├─ Encrypt real values → pii_quarantine (AES-GCM, 72h TTL)
   └─ INSERT INTO tickets  ← the first DB write; only masked text
```

Masking is inline **on purpose**. Async masking would create a window where raw PII exists in the database or on the broker. Numbering is per-label so that "the same email appears twice" survives masking — that relationship is a real classification signal.

The two NER calls (subject, body) run concurrently: they are independent, and sequential calls would make the worst case two full timeouts deep inside a request a user is waiting on.

### Stage 2 — Embedding and incident detection (Celery)

```
process_ticket(ticket_id)        acks_late=True, idempotency = {ticket_id}:{attempt}
   │
   ├─ embed(subject + body)  ── unreachable? ─► HITL / embedding_unavailable
   ├─ find similar tickets in the last 15 min
   │
   ├─ count > baseline + 3σ AND ≥ min_count?
   │    └─► MASS INCIDENT: create parent, escalate, SKIP ai-engine entirely
   │
   └─ otherwise similar?
        └─► duplicate: link to original, inherit assignment, continue
```

The baseline is rolling and per-category, so "unusual" means unusual *for this organization and this category*, and `baseline_rate` is persisted on the incident so the decision stays explainable months later.

### Stage 3 — ai-engine (LangGraph)

```
injection ──► InjectionDetected ──► emit_signals   (zero tokens spent)
       │ InjectionClear
       ▼
   hybrid_retrieve   BM25 top-20 ∥ vector top-20 ──► RRF (k=60) ──► top-10
       ▼
   rerank            cross-encoder ──► top-3
       │
       ├─ EvidenceBelowFloor (top1 < retrieval_floor) ──► emit_signals   ← REFUSE BEFORE LLM
       │ EvidenceAboveFloor
       ▼
   select_fewshots   few-shot examples for this category
       ▼
   infer             LLM ──► JSON, schema-constrained
       ▼
   validate          quote → fuzzy ≥0.95 → in-top-k → negation
       │
       ├─ RetryInference (schema invalid AND iteration < 2) ──► infer   (exactly one retry)
       │ SchemaValid / RetriesExhausted
       ▼
   emit_signals ──► terminal ──► END
```

Three properties are structural, not conventional:

1. **No node writes business data.** The graph returns signals and a proposal. All authority stays in core-api.
2. **Refuse-before-LLM.** Weak retrieval means the model is never invoked — cheaper *and* safer.
3. **No unbounded loop.** Exactly one edge can cycle (`validate → infer`), hard-capped at `iteration < 2`. Non-termination is impossible by construction, not by convention.

Each node is a `BaseNode` subclass (`core/node.py`) taking its collaborators
through `__init__` and reading tunables from `core/config.py`. Its node name is derived from the class
name (`HybridRetrieveNode` → `hybrid_retrieve`), and a branching node reports
where it ended up as a domain `Outcome` from `decide()` — it never names its
successor. The whole topology is `wire_triage` in `graph/flow.py`, which
routes each outcome of a node instance to the next instance on a
`GraphBuilder` (`graph/build.py`). `GraphBuilder.compile` validates the routes
at startup (every outcome routed, nothing unreachable) and is the only place a
node becomes a LangGraph string. `main.py` constructs the instances, wires and
compiles them once, at import time. See
[graph-node-architecture.md](graph-node-architecture.md).
Where a dependency has more than one implementation chosen from config, nodes
depend on an abstract base class beside those implementations — `Embedder` and
`Reranker` in `core/providers/base.py`, `LLMClient` in
`core/providers/llm/client.py` —
never on a concrete provider module. Every implementation subclasses its base
class, so a provider missing its method fails at construction, which happens
at startup. The database client has one implementation and no base class:
nodes take `SqlAlchemySessionSource` from `core/db/client.py`.

`core/providers/factory.py` is the single place `EMBEDDING_PROVIDER` and
`RERANKER_PROVIDER` are read. ai-engine's self-hosted models run on vLLM —
chat always, embeddings and rerank by default —
over its OpenAI-compatible APIs (ADR-0009). core-api uses the same vLLM servers
for PII detection and embeddings. Selection happens once at startup and an
unrecognized value is fatal — a typo used to fall through to the lexical
reranker, whose scores are a different calibration from the cross-encoder
distribution `retrieval.floor` is fitted against (ADR-0005).

Two constraints on anything added here: `main.py` builds the graph at uvicorn
import time, so no constructor may open a socket or load a model — every model
is served by vLLM; and `analyze` is a sync `def`, so node instances
are shared across FastAPI's threadpool and must be read-only after
construction.

### Stage 4 — Scoring and routing (core-api)

```
TrustSignals ──► trust_scorer.score()      ← in core-api, NOT ai-engine
                        │                     (so the LLM can't score itself)
                        ▼
              router.route(signals, proposal, kb, thresholds)   ← pure function

   HARD GATES, in this order — the order is load-bearing
     injection            ──► BLOCK    + alert security
     pii_level = critical ──► BLOCK    + alert security
     mass_incident        ──► ESCALATE   (before any duplicate logic)
     pii_level = mask_fail──► HITL       (queue: mask_failed, priority 1)
     retrieval < floor    ──► HITL       (before the schema gate: no LLM ran,
                                          so "no proposal" is a consequence,
                                          not the cause)
     no/invalid proposal  ──► HITL

   TRUST-BASED
     AutoReplyProposal:
        kb.auto_reply_allowed?      no ──► HITL / kb_not_authorized
        quote_source_in_topk?       no ──► HITL / quote_source_mismatch
        quote_match ≥ threshold?    no ──► HITL / quote_invalid
        negation_consistent?        no ──► HITL / negation_mismatch
        trust ≥ t_auto?             no ──► HITL / trust_below_auto
                                    yes ──► AUTO_REPLY

     RunbookProposal:                   ──► HITL, always. No exceptions.

     RouteProposal:
        category_consistent?        no ──► HITL / category_inconsistent
        trust ≥ t_route?            no ──► HITL / trust_below_route
                                    yes ──► AUTO_ROUTE
```

`route()` takes thresholds as a **parameter** rather than importing them. That is what makes every branch testable without a database, a model, or a network — and it lets the exact thresholds in force be snapshotted into `routing_decisions.thresholds_used`, so a post-incident analysis months later can recover what the bar actually was at the time.

### Stage 5 — Execute or queue

```
persist RoutingDecision (with the threshold snapshot)

SHADOW_MODE=true  ──► enqueue HITL regardless; record what WOULD have happened
SHADOW_MODE=false ──► execute the decision
```

The same `route()` runs in both. That identity is the whole point: shadow data describes the real behavior, with no divergence introduced by a separate code path.

---

## 5. Data model

Tables mirror the spec's DDL exactly (same names, via `db_table`).

| Table | Holds | Notable |
|---|---|---|
| `tickets` | Masked text only | `category` written **only** by the router |
| `ticket_embeddings` | Vectors | Split out so re-embedding never locks the main table |
| `pii_quarantine` | Encrypted real values | AES-GCM, key outside the DB, hard 72h TTL |
| `pii_access_log` | Every raw-PII read | Mandatory reason. *Read path not yet built — [`status.md`](status.md) Gap 1* |
| `kb_articles` | KB + **auto-reply authority** | DB `CHECK`: the flag cannot be true without a named approver |
| `kb_chunks` | Chunks + embedding + tsvector | HNSW and GIN indexes |
| `kb_authority_log` | Every authority change | Append-only, reason required |
| `ai_runs` | One row per AI attempt | Signals, proposal, cost, `degraded_reason` |
| `routing_decisions` | One row per decision | Includes `thresholds_used` snapshot |
| `review_items` / `review_decisions` | HITL queue and outcomes | Captures *why*, not just what |
| `eval_candidates` | Auto-created on override | The free-label loop |
| `incidents` | Mass-incident parents | `baseline_rate` for explainability |
| `audit_log` | Everything | `REVOKE UPDATE, DELETE` — append-only enforced by Postgres |

Constraints that encode policy rather than data integrity:

```sql
-- Auto-reply cannot be enabled without an identifiable human approver
CHECK (auto_reply_allowed = false OR approved_by IS NOT NULL)

-- The audit log is append-only at the database level, not by convention
REVOKE UPDATE, DELETE ON audit_log FROM app_user;

-- ai-engine physically cannot write business tables
GRANT SELECT ON kb_articles, kb_chunks, fewshot_examples TO ai_engine_ro;
```

---

## 6. Failure behavior

Every degradation resolves toward a human. A user waiting longer is acceptable; a user receiving a confident wrong answer is not.

| Failure | Response |
|---|---|
| Cloud LLM timeout | Retry ×2 → self-hosted vLLM fallback → HITL |
| All LLMs down | HITL, `degraded_reason="all_llm_down"` |
| Embedding unavailable | HITL, `embedding_unavailable` |
| pgvector slow | BM25 only → always HITL (weak retrieval never earns automation) |
| ai-engine down | Tickets still accepted; all to HITL — **fail open toward people** |
| Worker dies mid-task | `acks_late` + idempotency key; redelivery cannot double-send |
| Budget exceeded | AI off for the day; everything to HITL |
| DB read-only | Submission returns 503 — an explicit refusal beats a silent loss |

Two timeout budgets exist per model call, and the distinction matters: **connect** is short (3s) because an unreachable provider is knowable immediately, while **read** is long (120s) because a cold model load legitimately takes 15–20s. Collapsing them means an unreachable provider burns the full read budget — which, since masking is inline, is a user watching a spinner.

---

## 7. Where to make a change

| To change… | Go to |
|---|---|
| When something is auto-replied | `thresholds.yaml`, or `kb_articles.auto_reply_allowed` — **not** the prompt |
| How a branch is chosen | `router.py` (and add branch tests) |
| What the model is asked | `ai-engine/core/prompts/*.md` — versioned, and eval-gated like code |
| What counts as PII | `tickets/services/patterns.py` (regex) or the NER prompt in `masking.py` |
| How relevance is judged | `ai-engine/core/providers/reranker.py`, `core/retrieval/` |
| What a reviewer sees | `TrustSignalsPanel.tsx`, `ReviewForm.tsx` |
| Any tunable number | `thresholds.yaml`, nowhere else |

See [`development.md`](development.md) for the mechanics.
