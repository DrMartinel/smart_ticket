# ADR-0009: Self-hosted vLLM as a model backend

**Status:** Accepted — code only; not yet run against a real vLLM server

## Context

ai-engine has three model-backed capabilities: the chat LLM (infer), the
embedder, and the reranker. Before this decision the self-hosted side was
Ollama for chat and embeddings, and the reranker (`bge-reranker-v2-m3`) ran
**in-process** through FlagEmbedding, with ~2.3GB of weights baked into the
ai-engine image.

The goal is one self-hosted place that every model operation can be directed
to. Ollama cannot be that place: it exposes chat, generate and embeddings, but
no rerank or scoring endpoint (checked against Ollama 0.34.1 — `/api/rerank`
and `/v1/rerank` return 404), so a cross-encoder cannot be served by it.

vLLM serves all three through OpenAI-compatible APIs: `/v1/chat/completions`,
`/v1/embeddings`, and a Cohere-style `/v1/rerank` for cross-encoders.

## Decision

vLLM replaces Ollama as the system's self-hosted backend, and the in-process
FlagEmbedding reranker (`CrossEncoderReranker`, with torch and the weights
baked into the ai-engine image) is removed. Neither service talks to Ollama
any more, and ai-engine loads no model itself.

ai-engine (`OllamaLLM`, `OllamaEmbedder` and `langchain-ollama` are removed):

| Capability | Setting | vLLM class |
|---|---|---|
| Chat LLM | always vLLM — the only link without a cloud provider, the fallback behind one | `VLLMLLM` |
| Embeddings | `EMBEDDING_PROVIDER=vllm` (default) \| `stub` | `VLLMEmbedder` |
| Reranking | `RERANKER_PROVIDER=vllm` (default) \| `lexical` | `VLLMReranker` |

core-api:

| Capability | vLLM endpoint | Code |
|---|---|---|
| Tier-2 PII NER (masking) | `/v1/chat/completions` on `VLLM_CHAT_MODEL`, JSON-Schema-constrained | `masking.llm_ner` |
| Ticket / KB / few-shot embeddings | `/v1/embeddings` on `VLLM_EMBED_MODEL` (`EMBEDDING_PROVIDER=vllm` default \| `stub`) | `embeddings.embed_text` |

With `RERANKER_PROVIDER=vllm`, every model operation in the system goes to the
self-hosted servers. vLLM serves one model per process, so the three
capabilities are three servers (`vllm-chat`, `vllm-embed`, `vllm-rerank` in the
`vllm` compose profile), each with its own base URL.

Each class keeps the contract of the provider it replaces: no socket at
construction, separate connect and read timeouts, SDK retries off (retry and
fallback stay in `LLMClient.complete()`, ADR-0007), and RAISE rather than
degrade. `VLLMReranker` never falls back to lexical.

## Consequences

- **The reranker score scale is unverified.** `retrieval.floor` was written
  against FlagEmbedding's sigmoid-normalized `compute_score(normalize=True)`
  (ADR-0005). vLLM serves the same checkpoint, but whether it returns that
  scale has to be confirmed before calibrating. Until then, treat refusal
  behaviour as uncalibrated — docs/TODO.md item 4.
- **Stored vectors must be re-embedded through vLLM.** KB chunks, ticket
  embeddings and few-shot examples in pgvector came from Ollama's `bge-m3`; a
  different runtime can produce slightly different vectors for the same text.
  Query and KB embeddings must come from the same model on the same runtime,
  or retrieval quality degrades silently.
- **Masking now runs on a different model.** Tier-2 NER moved from Ollama's
  `qwen3:8b` to `VLLM_CHAT_MODEL` (default `Qwen/Qwen3-8B-AWQ`), sharing the
  chat server with inference because vLLM serves one model per server. The
  fail-closed contract is unchanged — any error, timeout or unusable reply is
  `MASK_FAILED` — but detection quality on real tickets must be re-checked
  before trusting it, since masking is the most sensitive path in the system.
- **Hardware.** Three vLLM servers reserve GPU memory up front, side by side;
  vLLM does not swap models the way Ollama does. The chat model needs a
  quantized checkpoint to fit consumer cards. On Windows vLLM runs only
  through WSL2 / Docker Desktop with an NVIDIA GPU.
- **The fallback reason is renamed** to `cloud_fallback_to_self_host`. Rows
  written before this ADR keep `cloud_fallback_to_ollama`; anything grouping
  on `ai_runs.degraded_reason` must treat the two as the same reason.
