# ADR-0019: DeepSeek's hosted API replaces vllm-chat, for evaluation

**Status:** Accepted for the evaluation stage only. Not for production.
**Date:** 2026-10-08
**Relaxes:** ADR-0009 (self-hosted model backend), ADR-0012 (raw ticket text
stays on the self-hosted NER server)
**Touches:** ADR-0018 (the offline entity_graph build), spec §5 (masking)

## Context

`vllm-chat` (Qwen3-8B-AWQ on one RTX 3060) serves three jobs: triage's
propose call, tier-2 PII NER, and the offline entity_graph build. Its
4,096-token context and ~60-90 generated tokens per second made the build
the bottleneck: six attempts to fit the context, then an estimate of ~26 GPU
hours for the full KB (`evals/HISTORY.md` 2026-10-08). During evaluation the
GPU time and the context limits cost more than the data boundary protects:
the golden set is synthetic and the KB is public AWS documentation.

## Decision

`CHAT_CLIENT_PROVIDER=deepseek` moves all three jobs to DeepSeek's hosted,
OpenAI-compatible API (`deepseek-flash`, on the `CLOUD_*` settings):

1. **Triage** sends masked ticket text, as `openai` already does.
2. **PII NER sends raw, unmasked ticket text** off the machine. This is the
   boundary ADR-0012 exists to keep, relaxed here by explicit decision for
   evaluation on synthetic tickets. Under `openai`, NER still stays local.
3. **The entity_graph build** sends public KB text.

> **Amended 2026-10-12:** each job now has its own setting. The proposal
> follows `CHAT_CLIENT_PROVIDER`, the drafted answer `DRAFT_CLIENT_PROVIDER`
> (ADR-0021), and PII NER `NER_CLIENT_PROVIDER` (`vllm` or `deepseek`). Raw
> ticket text reaches DeepSeek only with `NER_CLIENT_PROVIDER=deepseek`;
> `CHAT_CLIENT_PROVIDER=deepseek` alone no longer moves NER.

Measured against the live API (2026-10-08) and enforced in code:

- thinking is on unless disabled per request, and billed as output, so every
  call disables it;
- `json_schema` replies are refused (400), so every JSON reply is
  `json_object` and validated by the caller. The build's bounded extraction
  schema (policy v2+) is not enforced on DeepSeek; its 1M-token context
  makes room for the longer replies;
- NER runs at temperature 0, and its errors never carry the text or reply.

A build's working directory is scoped to its provider and model, so a
DeepSeek build never reuses a Qwen build's cached replies.

## Consequences

- **Every eval number before this ADR was Qwen's.** The propose model
  changed, so every gate must be re-measured before comparing.
- No GPU is needed for chat or NER; `vllm-embed` and `vllm-rerank` stay.
- Cost per ticket and per build is now real money (DeepSeek's off-peak rates
  are half its peak rates); `DEEPSEEK_COST_PER_1K_TOKENS` feeds the daily
  cost ceiling at the peak output rate.
- **Before production**, either revert to a self-hosted chat model or write
  a new ADR that keeps raw ticket text on infrastructure the operator
  controls. This ADR does not authorise sending real tickets to DeepSeek.
