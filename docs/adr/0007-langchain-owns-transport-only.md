# ADR-0007: LangChain owns LLM transport only — retry, fallback and the breaker stay ours

**Status:** Accepted
**Date:** 2026-09-16

## Context

`ai-engine` already ran LangGraph, but the one place that actually spoke to a
model — `core/llm/client.py` — was hand-written httpx: two `httpx.post` calls,
two bespoke pydantic response models, and hand-maintained token extraction per
provider. Adding a provider meant adding another `_call_*` function and another
response schema, and each one was a fresh chance to get the failure mapping
wrong.

We wanted `ChatOllama` / `ChatOpenAI` / `ChatAnthropic` /
`ChatGoogleGenerativeAI` to do that work. The risk is that LangChain also
offers `.with_retry()` and `.with_fallbacks()`, which look like drop-in
replacements for the policy in `complete()` and are not.

## Decision

LangChain builds and calls the model. Everything that decides *what a failure
means* stays in this repo:

| Concern | Owner |
|---|---|
| HTTP, auth, wire format, token accounting | langchain-\* |
| Retry count and backoff | `client.py` |
| Cloud→Ollama fallback and its `degraded_reason` | `client.py` |
| Circuit breaker (spec §10.1) | `circuit_breaker.py` |
| Which provider is primary | `providers/factory.py`, at startup |
| Cost rate per provider | the `ChatModelFactory` subclass |

`DefaultLLMClient` keeps its `complete()` signature and its two exception
types. Nodes never see a LangChain type; the `LLMClient` seam in `base.py` is
unchanged.

## Rationale

### Why not `.with_fallbacks()`

It raises the *last* underlying exception and gives no supported signal for
which link answered. We need both: `infer.py` maps `CircuitOpenError` and
`AllLLMDownError` to different `degraded_reason` codes, and a successful
fallback must be tagged `cloud_fallback_to_ollama` so the trust score and the
reviewer panel can see the degradation. Composed as Runnables, a silent
fallback looks exactly like a clean cloud answer.

### Why not `.with_retry()`

The retry budget is per-attempt and computed at call time from the ticket's
remaining latency (`infer.py`). `.with_retry()` is configured at construction.
The breaker also has to record one outcome per primary *chain*, not per
attempt.

### Why the `except` clause is deliberately broad

The providers raise from genuinely disjoint hierarchies. `langchain-ollama`
surfaces raw `httpx` errors; `langchain-openai` and `langchain-anthropic` raise
`openai.APIError` / `anthropic` errors over **vendored `httpx2`** — and
`httpx.HTTPError is not httpx2.HTTPError`. `langchain-google-genai` adds
google-genai's own. An enumerated tuple would rot into an uncaught 500 the
first time a dependency adds a type, and a 500 here is a ticket that should
have degraded to HITL showing the reviewer a blank panel instead. So
`complete()` catches broadly and `CircuitOpenError` is raised before the loop
it could be swallowed by.

## Consequences

### Accepted: absent vs. null token counts are no longer distinguishable

The old `_OllamaGenerateResponse` treated a **missing** `prompt_eval_count` as
0 (Ollama omits it for a cached prompt) but rejected an explicit **null** as
malformed, because silently undercounting loosens the per-ticket token budget.
langchain-core normalises both into an absent `usage_metadata`. The exposure is
undercounting rather than a loud failure, and it is the price of not
maintaining four response schemas.

### Accepted: two of four providers cannot honour the connect/read split

Ollama and the OpenAI-compatible link take a real `httpx.Timeout`, so an
unreachable provider is knowable in ~3s while a slow one keeps the full read
budget. `ChatAnthropic.default_request_timeout` and
`ChatGoogleGenerativeAI.timeout` are pydantic `float` fields — a `Timeout`
object fails validation — and neither exposes an injectable HTTP client.
Reaching past that into the library's `cached_property` client would work today
and break silently on upgrade, which is the failure shape this service is built
to avoid.

Those two therefore get a flat timeout. This is tolerable because the split was
calibrated for the failure the gotchas table documents — "containers can't
reach Ollama", a blackholed connection on the local network. A hosted API that
is down usually refuses the connection or fails DNS, both of which return
immediately whatever the connect budget is. **Ollama, the case that motivated
the split, keeps it.**

### Accepted: Anthropic has no JSON mode

Ollama has `format="json"`, OpenAI has `response_format`, Gemini has
`response_mime_type`. Anthropic has no equivalent, so with
`CLOUD_PROVIDER=anthropic` the only thing keeping the reply parseable is the
instruction in the system prompt. `infer.py` already routes unparseable output
to HITL rather than a 500, so this is a HITL-rate risk rather than a
correctness hole — but a prompt change is likelier to hurt on this provider,
and the eval gate should be watched when switching to it.

### Gained: misconfiguration is fatal at boot

Provider selection moved out of `DefaultLLMClient` (which re-read `settings` on
every call) into `build_providers()`. A half-configured cloud link used to be
invisible — the old `_has_cloud()` returned False and the service ran
Ollama-only while the operator believed otherwise. Now `CLOUD_BASE_URL` without
a key, `openai` without a base URL, `gemini` *with* one (the Google client has
no endpoint override, so it would be silently dropped), and any unknown
`CLOUD_PROVIDER` all fail the boot.

### Gained: internal SDK retries are disabled explicitly

Anthropic defaults to 2 internal retries and Gemini to 6. Left on, one
`complete()` could issue a dozen requests, overrun the latency budget, and
still record a single failure against the breaker. Every factory passes
`max_retries=0`.

## Alternatives considered

**`init_chat_model("provider:model")`.** Requires the `langchain` umbrella
package, which is not otherwise a dependency, and hides exactly the selection
step `providers/factory.py` exists to make explicit and fatal.

**Migrating the reranker and the DB seam too.** Rejected, and this is not a
"later" — see `Reranker` in `base.py`: langchain-core's nearest abstraction,
`BaseDocumentCompressor.compress_documents()`, reorders and filters and hides
the score in `doc.metadata["relevance_score"]`, while ADR-0005 makes that
returned float the only number a threshold may see. A LangChain vectorstore
would likewise hide the raw SQL that the `ai_engine_ro` SELECT-only grant model
(ADR-0004) is written against.

**Migrating the embedder.** Done, but on the same terms: `OllamaEmbedder` wraps
`OllamaEmbeddings` while keeping the `EMBED_DIM` width check on our side of the
seam, because langchain-ollama has no opinion about the width our pgvector
column was migrated to, and a short vector fails far from its cause — or, at
length zero, reads as an ordinary "the KB has nothing relevant".
