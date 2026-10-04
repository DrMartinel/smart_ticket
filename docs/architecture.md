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
│  FastAPI + LangGraph │──►│  + pg_search (BM25)    │
│                      │ RO│  tickets, kb_chunks,   │
│  injection → retrieve│   │  ai_runs, audit_log…   │
│  → shortlist → rerank│   └────────────────────────┘
│  → category → infer  │   ┌────────────────────────┐
│  → validate          │──►│  vLLM (self-hosted)    │
│                      │   │  chat/NER · embed ·    │
│  NO business writes  │   │  cross-encoder         │
│  NO routing decisions│   └────────────────────────┘
│                      │   ┌────────────────────────┐
│                      │──►│  Jev (hosted, TypeSafe)│
│                      │   │  rerank · category     │
└──────────────────────┘   │  masked text + KB only │
                           └────────────────────────┘
```

### Why these boundaries

**core-api owns all writes and all decisions.** It is the only service that can change business state. If you are adding a feature that decides something, it belongs here.

**ai-engine has no authority.** It returns `TrustSignals` plus a proposal and nothing else. It was split out for four reasons, in ascending order of importance: dependency isolation (LangChain/LangGraph churn badly), differing scale profiles (RAM for models vs. I/O for API), independent deploys (change a prompt without restarting the gateway), and — the one that actually justifies the cost — **structural permission separation**.

**web is a thin client.** No business logic. Its TypeScript types are generated from core-api's schemas, so a schema change that breaks the frontend fails at build rather than in production.

---

## 3. Contracts

There is no shared schema package (ADR-0010). Each type is defined in the module that uses it, and the frontend's types are generated from core-api's. The ai-engine wire shapes exist once per service and must be changed in both.

| Types | core-api | ai-engine |
|---|---|---|
| `TicketIn` (`extra="forbid"`) | `apps/tickets/request_schema.py` | — |
| `TicketMasked` (`frozen=True`), the proposal union (auto-reply / route / runbook / clarification / insufficient-context), `RetrievalSignals`, `GenerationSignals`, `PolicySignals`, `ClassificationSignals`, `TrustSignals`, `AIRunRequest`, `AIRunResponse`, `TicketCategory`, the `/v1/embed` and `/v1/pii/detect` bodies | `infrastructure/dtos.py` | `schemas.py` |
| `PIILevel` | `apps/tickets/utils/patterns.py` | `schemas.py` |
| `Branch`, `ReasonCode`, `ReviewQueue`, `RiskTier`, `KBArticleMeta`, `RoutingDecision` | `apps/tickets/utils/router.py` | — |
| `Thresholds` | `config/settings/base.py` | — |
| `TrustScore` | `apps/tickets/utils/trust_scorer.py` | — |
| `ReviewAction`, `Verdict` · `UserRole` | `apps/review/models.py` · `apps/accounts/models.py` | — |

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
   ├─ Tier 2: LLM NER via ai-engine /v1/pii/detect (free-form PII regex can't catch)
   │    ├─ timeout or error?
   │    │    └─► pii_level = mask_failed  (never "assume clean")
   │    └─ spans cover more than masking.ner_max_share of the text?
   │         └─► pii_level = mask_failed  (still fully masked)
   │
   ├─ Merge overlapping hits, then replace them with numbered placeholders  [EMAIL_1], [PHONE_VN_1]
   ├─ Encrypt real values → pii_quarantine (AES-GCM, 72h TTL)
   └─ INSERT INTO tickets  ← the first DB write; only masked text
```

Masking is inline **on purpose**. Async masking would create a window where raw PII exists in the database or on the broker. Numbering is per-label so that "the same email appears twice" survives masking — that relationship is a real classification signal.

The two NER calls (subject, body) run concurrently: they are independent, and sequential calls would make the worst case two full timeouts deep inside a request a user is waiting on.

Tier 2 runs in ai-engine (ADR-0012), on the self-hosted chat model through its own `clients.ner` client, never the possibly-cloud `clients.chat`. This is the **one** place raw text enters ai-engine: `/v1/pii/detect` logs neither the text nor the model's reply, and a failure comes back as a 502 that core-api resolves to `mask_failed`. NER decodes greedily, so a ticket masks the same way every time.

Masking can also fail by removing too much. Everything after it, the injection detector included, sees only masked text, so an NER span over a whole sentence hides that sentence from all of them: it once hid an injection and, on another ticket, the request itself (`evals/HISTORY.md`, 2026-10-04 (2)). When NER's spans, beyond the regex hits, cover more than `masking.ner_max_share` of the ticket (`thresholds.yaml`), the ticket is `mask_failed` and goes to a human. Every span stays masked: dropping one could leak PII. `evals/suites/test_masking.py` measures how often NER over-masks.

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
                     (pg_search BM25, ADR-0013; records BM25's article order)
       ▼
   candidate_pool    cross-encoder scores the candidates, plus chunks of pages
                     linked from its top-3 seeds (ADR-0014/0015)
                     ──► pool, in cross-encoder order
       ▼
   rerank            Jev re-scores the pool's top-15 ──► Jev's top-3
                     each chunk keeps both: shortlist_score, rerank_score
       ▼
   classify_category Jev chooses the category (ADR-0017): masked ticket +
                     the top page's title if above the floor, else no page
       │
       ├─ EvidenceBelowFloor (Jev's top1 < retrieval.floor) ──► emit_signals   ← REFUSE BEFORE LLM
       │ EvidenceAboveFloor
       ▼
   select_fewshots   nearest few-shot examples by embedding, across categories
       ▼
   infer             LLM ──► JSON, schema-constrained
       ▼
   validate          quote → fuzzy ≥0.95 → in-top-k → negation;
                     a clarify proposal's options must be shown pages
       │
       ▼                 (schema invalid → no retry; emit_signals, then HITL)
   emit_signals ──► terminal ──► END
```

Three properties are structural, not conventional:

1. **No node writes business data.** The graph returns signals and a proposal. All authority stays in core-api.
2. **Refuse-before-LLM.** Weak retrieval means the model is never invoked — cheaper *and* safer.
3. **No loop.** The graph is acyclic — every node runs at most once per ticket, so non-termination is impossible by construction. A schema-invalid proposal goes to a human, not back to the model.

Each node is a `BaseNode` subclass (`graph/build/node.py`) that uses the provider
singletons (`db`, `embedder`, `shortlister`, `reranker`, `classifier`, `clients.chat`) directly and reads
tunables from `core/config.py`. Its node name is derived from the class
name (`HybridRetrieveNode` → `hybrid_retrieve`), and a branching node reports
where it ended up as a domain `Outcome` from `decide()` — it never names its
successor. The generic `Edge`, `Graph` and `GraphBuilder` live in
`graph/build/`. `graph/triage.py` holds the topology (a list of routes from
each outcome of a node instance to the next instance) and `triage_graph`,
compiled once at import time from the instances each node module builds. `GraphBuilder.compile`
validates the routes at startup (every outcome routed, nothing unreachable)
and is the only place a node becomes a LangGraph string. `main.py` only
invokes `triage_graph`. See
[graph-node-architecture.md](graph-node-architecture.md).
Models are reached through two layers. The clients in
`core/providers/clients.py` are the lower one and own each server's protocol:
`VLLMClient` has `embed()`, `rerank()` and `complete_json()`, `JevClient` has
`ask()` (yes/no) and `choose()` (one choice question), and each builds its request and validates the reply against a
Pydantic DTO from `core/providers/dtos.py`. `ChatClient` does triage chat through `complete()` (LangChain;
`vllm_chat` or `openai_chat` builds it). The providers
(`core/providers/embeddings.py` and `pii.py`, and the shortlister, the reranker
and the category classifier beside their nodes in `graph/nodes/candidate_pool/`,
`graph/nodes/rerank/` and `graph/nodes/classify_category/`)
are the upper one and
own their tasks: the vector width pgvector needs, PII-safe errors, which
answer is the score.
They call the client objects `core/providers/clients.py` builds from config at
import time (`embed`, `rerank`, `ner`, `chat`, and `jev` for the hosted Jev), one per server. `StubEmbedder` and `LexicalShortlister` are
offline alternatives for CI that talk to no server. Nodes depend on the `Embedder`
and `Shortlister` base classes and on `ChatClient`, never on a provider class. The database client
has one implementation and no base class:
nodes take `SqlAlchemySessionSource` from `core/db/client.py`.

The bottoms of `core/providers/embeddings.py` and
`graph/nodes/candidate_pool/shortlister.py` are the only
places `EMBEDDING_PROVIDER` and `SHORTLIST_PROVIDER` are read, and
`core/db/client.py` builds the single `db`. ai-engine's self-hosted models run
on vLLM — embeddings and rerank always, chat by default —
over its OpenAI-compatible APIs (ADR-0009). ai-engine is the only vLLM client
(ADR-0012): core-api gets its PII detection and embeddings from ai-engine's
`/v1/pii/detect` and `/v1/embed`, through `infrastructure.ai_engine.AIEngineClient`.
Selection happens once at startup and an
unrecognized value is fatal — a typo used to fall through to the lexical
shortlister, whose scores are a different calibration from the cross-encoder's
(ADR-0005). Whatever the shortlister, the score thresholds read is Jev's
(ADR-0015): `retrieval.floor` arrives per request in `AIRunRequest`, ai-engine
reports `RetrievalSignals.scorer = "jev"`, and core-api's router compares the
floor only for that scorer.

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
     scorer ≠ jev         ──► HITL       (retrieval_floor_unset: no floor for that scale)
     retrieval < floor    ──► HITL       (before the schema gate: no LLM ran,
                                          so "no proposal" is a consequence,
                                          not the cause)
     no/invalid proposal  ──► HITL       (schema_invalid)
     insufficient_context ──► HITL       (retrieval_below_floor)

   The ticket's category is Jev's choice (signals.classification, ADR-0017),
   never the LLM's proposed_category, which is log-only. Only clarify and
   auto-route use it; an auto-reply takes its KB page's category.

   CLARIFY (ADR-0016), before trust: a question grants nothing
     ClarificationProposal:
        Jev's category = security?      yes ──► HITL / clarify_security
        Jev's confidence ≥ min?         no  ──► HITL / category_low_confidence
        clarify_options_in_topk?        no  ──► HITL / clarify_options_not_shown
                                        yes ──► CLARIFY (queue: clarification;
                                                a person asks it, in shadow
                                                mode and out of it, until the
                                                requester side exists)

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
        Jev's confidence ≥ min?     no ──► HITL / category_low_confidence
        category_consistent?        no ──► HITL / category_inconsistent
        trust ≥ t_route?            no ──► HITL / trust_below_route
                                    yes ──► AUTO_ROUTE (to Jev's category)
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
| `kb_chunks` | Chunks + embedding | HNSW index; pg_search BM25 index on content + section title (ADR-0013) |
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
| LLM unreachable, timed out or erroring | No retry → HITL, `all_llm_down` |
| Embedding unavailable | HITL, `embedding_unavailable` |
| Retrieval query, cross-encoder or Jev fails (reranking or the category) | ai-engine raises, answers 500 → HITL, `ai_engine_unavailable`. No fallback to another score scale or to the LLM's category |
| ai-engine down | Tickets still accepted; all to HITL — **fail open toward people** |
| Worker dies mid-task | `acks_late` + idempotency key; redelivery cannot double-send |
| Daily cost ceiling exceeded (core-api) | AI off for the day; everything to HITL |

Two timeout budgets exist per model call, and the distinction matters: **connect** is short (3s) because an unreachable provider is knowable immediately, while **read** is long (120s) because a cold model load legitimately takes 15–20s. Collapsing them means an unreachable provider burns the full read budget — which, since masking is inline, is a user watching a spinner.

---

## 7. Where to make a change

| To change… | Go to |
|---|---|
| When something is auto-replied | `thresholds.yaml`, or `kb_articles.auto_reply_allowed` — **not** the prompt |
| How a branch is chosen | `router.py` (and add branch tests) |
| What the model is asked | `ai-engine/core/prompts/*.md` — versioned, and eval-gated like code |
| What Jev is asked | `ai-engine/core/prompts/*.json` (`rerank_resolves.v*`, `category.v*`) — versioned and eval-gated the same way |
| What counts as PII | `tickets/utils/patterns.py` (regex) or ai-engine's NER prompt `core/prompts/pii_ner.v*.md` |
| How relevance is judged | ai-engine `graph/nodes/retrieve/`, `graph/nodes/candidate_pool/` (shortlister), `graph/nodes/rerank/` (Jev) |
| How the category is chosen | ai-engine `graph/nodes/classify_category/` (Jev's question), `classification.min_confidence` in `thresholds.yaml` |
| What a reviewer sees | `TrustSignalsPanel.tsx`, `ReviewForm.tsx` |
| Any tunable number | `thresholds.yaml`, nowhere else |

See [`development.md`](development.md) for the mechanics.
