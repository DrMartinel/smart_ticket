# ADR-0015: Jev, a hosted model, reranks the cross-encoder's shortlist, and thresholds read its score

**Status:** Implemented since 2026-10-03 (`f1ce5b3`, `0f4a4c1`), on `main`
in shadow mode. Written after the fact on 2026-10-04: the code, CLAUDE.md
and other ADRs cited it before it existed. Review it as a Proposed ADR; the
open items below are what acceptance still needs.
**Date:** 2026-10-04 (decided 2026-10-02/03)
**Builds on:** ADR-0005 (thresholds compare one reranker's score, never
RRF), ADR-0014 (candidate expansion through page links)
**Touches:** ADR-0009 and ADR-0012 (every model self-hosted behind
ai-engine), ADR-0001 (code decides)
**Superseded in part by:** nothing. ADR-0017 adds a second Jev question,
the category, on the same client.

## Context

On the 2026-10-01 baseline, retrieval recall@3 was 0.767, the failing CI
gate (≥ 0.90). The `bge-reranker-v2-m3` cross-encoder ordered the fused
candidates and its top-1 was compared with `retrieval.floor` (0.45). Most
misses were pages that *describe* a symptom outranking the page with the
*fix* (GuardDuty and SES tickets, TODO item 9).

Rerankers measured on the same 83 tickets (`evals/HISTORY.md`, 2026-10-01
(2) to 2026-10-02 (4)):

| Reranker | Best recall@3 | Notes |
|---|---|---|
| Cross-encoder (baseline) | 0.767 · 0.800 with link expansion | AUROC gold vs rest 0.62 / 0.72 |
| Laya, zero-shot System One, CPU | worse than baseline | at chance (AUROC 0.53), lost up to 10 cases |
| Qwen3-8B re-ordering above the floor | 0.850 | both presentation orders must agree |
| Qwen3-Reranker-4B, self-hosted | 0.900 (cross-encoder's top 20) | 3.1 s per ticket on an idle GPU shared with chat |
| **Jev "resolves" noul, cross-encoder's top 15 of the links pool** | **0.917**, nothing lost | AUROC 0.84; gold page first 51/56; < 0.5 s per ticket |

Jev is TypeSafe's hosted System One model (`POST
api.typesafe.ai/v1/systemone`). It answers structured questions about a
JSON state: a `noul` (probability a statement is true), a `score` (a
weighted mean over ordered levels) or a `choice`.

## Decision

1. **Two stages.** The cross-encoder is the *shortlister*: it orders the
   pool (the fused candidates plus link-expanded chunks, ADR-0014) and its
   top `RERANK_POOL` (15) chunks are Jev's shortlist. Jev is the
   *reranker*: it scores each shortlisted chunk, its order is final, and its
   top `rerank_top_n` (3) go on (`CandidatePoolNode`, `RerankNode`,
   `JevReranker`).
2. **One noul question per chunk**, `core/prompts/rerank_resolves.v1.json`:
   "Does `passage` tell the user how to fix or resolve the problem described
   in `ticket`?". The state is `{ticket: {subject, body}, passage: {title,
   text}}`. One request per chunk, all of a ticket's in parallel. The
   question is a versioned file (`RERANK_PROMPT_VERSION`), eval-gated like a
   prompt.
3. **Thresholds read Jev's score only** (ADR-0005 applied to the new
   reranker). Each chunk keeps both scores, `shortlist_score` and
   `rerank_score`; anything compared with a threshold goes through
   `RankedChunk.final_score()`, which raises when Jev hasn't scored the
   chunk. `retrieval.floor` is on Jev's scale (0.30 🔧, the middle of the
   probe's 0.12-0.48 gap between the highest out-of-KB and lowest
   KB-covered top-1). (A `RetrievalSignals.scorer` field once named the
   scale and sent anything not `jev` to a human as `retrieval_floor_unset`;
   removed on 2026-10-04: no stored signals predate Jev, and it could not
   see the change most likely to move the scale, a new question to the same
   model. Changing the question or the model means choosing the floor again.)
4. **A Jev failure fails the run.** No retry, a 429 included, and no
   fallback to the cross-encoder's order: its scores would be compared
   with a floor set on Jev's. ai-engine answers 500, and core-api sends the
   ticket to a human as `ai_engine_unavailable`. (The probe's follow-up
   suggested degrading to the cross-encoder order; that was rejected for
   this reason.)
5. **What leaves the host.** Only masked ticket text (core-api's `mask()`)
   and KB text. The model is pinned (`JEV_MODEL=jev-1.13.0`), never the
   `jev-latest` alias, which would move the scale the floor is set on. The
   key (`JEV_API_KEY`) lives only in ai-engine's environment.
6. **An exception to ADR-0009/0012, not a reversal.** Every other model
   stays self-hosted on vLLM. Jev is still reached only through ai-engine
   (`JevClient`), so ADR-0012's "one route to every model" holds.

### Why a noul, not a `score` or `choice`

The first probe asked nouls because TypeSafe's RAG-passage example does,
and "resolves" passed the gate. On 2026-10-04 (`evals/HISTORY.md`
2026-10-04 (7)) a five-level `score` version of the same question was asked
on every pair of production's shortlist, in the same session: the same
recall@3 (0.917) and the same five misses, slightly worse ordering (MRR
0.868 against 0.879), and a top level that saturates (27 chunks at the
maximum). Both separate out-of-KB tickets perfectly. With nothing gained,
switching would only move the floor's scale. A `choice` among chunks would
need every chunk in one request and has no per-chunk score to threshold.

## Consequences

- **Recall.** The 2026-10-02 (5) full run reached recall@3 0.917, passing
  its gate for the first time. Still missed: g011, g012, g048, g055, g056.
- **Availability.** A hosted API in the request path of every ticket that
  passes the injection guard: up to 15 requests per ticket. Jev failed four
  times on 2026-10-04 (a TLS error twice, two 520s); each failure is a
  ticket for a human, never a guess. Since ADR-0017 a failure also costs
  the category.
- **Calibration.** `t_auto`, `t_route` and the trust coefficients were
  hand-set for the cross-encoder's `rerank_top1`; Jev's top-1 runs much
  higher (median 0.93 on KB-covered tickets). The trust score runs on
  inputs it was never set for (TODO items 2 and 4); it lifted g148 to an
  auto-reply in the 2026-10-02 (5) run. P3 waits on this.
- **Cost and latency.** About $0.042 per million input tokens, ~700 tokens
  per request; ~0.23 s per request at p50, all of a ticket's in parallel.
- **Refusal moved scale.** `retrieval.floor` 0.30 refuses no KB-covered
  ticket and admits no out-of-KB one on the golden set, but it was chosen
  from that set. It must be re-chosen on shadow pairs.

## Open before acceptance

- **Prompt injection through Jev.** The injection suite's tickets stop at
  the injection guard before retrieval, so Jev has never been measured on
  adversarial ticket or KB text; TypeSafe's notes on Jev 1.13 say
  adversarial state can move answers.
- **Data handling.** Zero retention is an enterprise-tier term at
  TypeSafe; the current key's terms are not recorded here.
- **Repeatability** over all 60 KB-covered tickets (only the 14 baseline
  misses were re-scored; noul scores moved by 0.008 on average between
  2026-10-02 and 2026-10-04).
- A `GRAPH_VERSION` bump for the topology change.

## Alternatives

- **Keep the cross-encoder as the only reranker.** Self-hosted and free,
  but recall 0.767-0.800, below the gate.
- **Qwen3-Reranker-4B, self-hosted.** 0.900, inside ADR-0009, but 3.1 s per
  ticket on a GPU already shared with chat, embed and the cross-encoder.
- **An LLM re-ordering the chunks above the floor** (ADR-0014).
  0.850, and a second chat call per ticket.
- **Jev's "relevant" noul** ("Does `passage` address the subject of
  `ticket`?"). 0.900: it does not lift the page with the fix over the page
  that describes the symptom, which is the failure this decision is for.
- **Jev ranking the whole pool.** The same 0.917 as the top 15, at about
  four times the requests.
- **A `score` question** (above).
- **Fall back to the cross-encoder's order when Jev fails.** Rejected in
  decision 4.
