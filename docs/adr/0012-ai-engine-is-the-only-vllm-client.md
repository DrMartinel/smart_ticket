# ADR-0012: ai-engine is the only vLLM client

**Status:** Accepted
**Date:** 2026-09-29
**Supersedes:** ADR-0009's core-api table (core-api calling vLLM directly)
**Relaxes:** "only masked text enters ai-engine" (ADR-0004, `TicketMasked`), for one endpoint

## Context

ADR-0009 had both services call the vLLM servers. core-api called
`vllm-chat` for Tier-2 PII NER during masking and `vllm-embed` for ticket, KB
and few-shot embeddings. ai-engine called all three servers.

That left two clients for each server, each with its own URL settings,
timeouts and reply parsing. It also left one silent coupling: ticket, KB and
query vectors are only comparable if both services embed with the same
model, and the only thing keeping them on one model was the same
`EMBED_MODEL` value being set in two places.

## Decision

Every model call in the system goes through ai-engine. core-api has no vLLM
URL or model setting and talks to one server, ai-engine, through
`infrastructure.ai_engine.AIEngineClient`.

| Capability | ai-engine endpoint | Code |
|---|---|---|
| Triage (unchanged) | `POST /v1/analyze` | `graph/triage.py` |
| Ticket / KB / few-shot embeddings | `POST /v1/embed` → `{vector, model}` | `embedder` (`core/providers/embeddings.py`) |
| Tier-2 PII NER (masking) | `POST /v1/pii/detect` → `{spans}` | `pii_detector` (`core/providers/pii.py`) |

- `/v1/embed` returns the model that produced the vector, and core-api stores
  that on `ticket_embeddings`. The "keep two `EMBED_MODEL`s equal" rule is
  gone because there is only one.
- core-api has no embedder of its own, not even a stub. `EMBEDDING_PROVIDER`
  is ai-engine's alone, and `stub` there is the offline and emergency option
  for the whole system. Every vector in pgvector comes from one embedder, so
  stub and real vectors can't be mixed. core-api's unit tests never call
  ai-engine: an autouse fixture answers `/v1/embed` deterministically and
  fails every other call as unreachable.
- The failure contracts are unchanged. Any failure on `/v1/embed`,
  ai-engine unreachable included, reaches HITL as `embedding_unavailable`.
  Any failure on `/v1/pii/detect` makes the ticket `mask_failed`, never "no
  PII found".

## The raw-text exception

NER exists to find the PII that masking then removes, so it has to see the
**unmasked** ticket. Routing it through ai-engine means raw PII now enters
ai-engine, which ADR-0004 and the `TicketMasked` contract said never
happens. This ADR deliberately relaxes that, for `/v1/pii/detect` only, on
these conditions:

1. **Self-hosted only.** NER uses its own `clients.ner` client on
   `chat_base_url`, never `clients.chat`, which can be a cloud provider
   (`chat_client_provider=openai`). Raw PII never leaves the deployment.
   *`test_pii.py::test_ner_never_uses_the_chat_client`.*
2. **Nothing retains it.** The endpoint does not log the text or the model's
   output. Provider errors reach core-api as a 502 whose detail is the error
   class only. 422 bodies drop pydantic's `input` echo.
   *`test_main.py`.*
3. **No state.** The text isn't stored, cached or passed into the graph.
   The triage graph still only ever sees `TicketMasked`.

Everything else in ai-engine still sees masked text only.

## Consequences

- **Masking now depends on ai-engine being up.** If ai-engine is down, every
  ticket is `mask_failed` and goes to a human. That was already true when
  vllm-chat was down, and it is the designed behaviour (spec §5.2).
- **One more hop on the submit path.** Masking runs inline in the submit
  request. core-api's connect budget (`MODEL_CONNECT_TIMEOUT_SEC`, 3s) keeps
  an unreachable ai-engine from hanging the request.
- **KB ingestion needs ai-engine**, stub or not. `seed_demo` must run after
  ai-engine has started.
- **The NER prompt is versioned in ai-engine** (`core/prompts/pii_ner.v1.md`)
  like every other prompt. What counts as PII is now split: regex in
  core-api `patterns.py`, the free-form prompt in ai-engine.
