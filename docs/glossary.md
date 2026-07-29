# Glossary

The original specification ([`requirement.md`](../requirement.md)) is in Vietnamese and the codebase carries its vocabulary directly. This maps the terms you will meet in code, comments, and column names.

---

## The core distinction

**Proposal** — what the LLM produces. Never authoritative. Every LLM-authored field is prefixed `proposed_` (`proposed_intent`, `proposed_category`) so that at the point of use, the type itself reminds you this is a suggestion.

**Decision** — what `router.py` produces. Deterministic, testable, and the only thing that causes anything to happen. Expressed as a `Branch`.

> *"LLM sinh đề xuất, code ra quyết định"* — the LLM generates proposals, code makes decisions. This is the sentence the whole architecture is derived from.

---

## Routing

**Branch** — the outcome of a routing decision. One of:

| Branch | Meaning |
|---|---|
| `auto_reply` | Send a KB-sourced answer to the reporter without a human |
| `auto_route` | Assign to a team without a human |
| `hitl` | Send to the human review queue |
| `block` | Refuse and alert security (injection, critical PII) |
| `escalate` | Mass incident — hand to incident management |

**HITL** — Human In The Loop. The review queue where anything uncertain goes. The system is deliberately biased toward sending work here.

**Hard gate** — a check that cannot be outweighed by a high trust score. Injection detection and critical-PII detection are hard gates: no confidence level makes them passable. They run first, and their order is load-bearing (mass-incident is checked before duplicate logic, because 40 identical tickets is an outage, not spam).

**Reason code** — a machine-readable enum explaining *why* a decision was made (`injection_detected`, `retrieval_below_floor`, `kb_not_authorized`, `negation_mismatch`, …). Deliberately an enum rather than free text, because "which reason sent the most tickets to review this week?" is unanswerable over prose.

**Shadow mode** — `SHADOW_MODE=true`, the current default. The router evaluates every ticket and records what it *would* have done, but every ticket still goes to a human. The same `route()` function runs in both modes, so calibration data describes exactly what will happen when it is switched live.

**Trust score** — a calibrated probability that a proposal is correct, computed by logistic regression in **core-api** (never in ai-engine, so the LLM has no influence over the score used to judge it). Built only from externally verifiable signals.

**`t_auto` / `t_route`** — trust thresholds for auto-reply and auto-route. `t_route` is lower on purpose: a wrong auto-route costs one technician click (and yields a free label), while a wrong auto-reply reaches the user on a ticket that is already closed.

---

## PII and masking

**Masking** — replacing PII with numbered placeholders (`[EMAIL_1]`, `[PHONE_VN_1]`) before anything is written to the database. Runs **inline and synchronously** — if it were async there would be a moment where raw PII sat in the DB or on the broker, and that moment is the vulnerability the design exists to remove.

**PII level** — how sensitive what was found is:

| Level | Meaning | Effect |
|---|---|---|
| `routine` | Names, internal emails, employee IDs | Continue |
| `sensitive` | National ID, bank account, health info | Continue, flagged |
| `critical` | Password, token, API key | **BLOCK** + alert security |
| `mask_failed` | The masker errored or timed out | **HITL** — never treated as clean |

**`mask_failed` is not an error state** — it is the correct answer to "I could not verify." Uncertainty must cost a human's time, never risk a leak. Any change that makes a masking failure resolve toward "no PII found" is a serious regression.

**Quarantine** — the encrypted store (AES-GCM, key outside the DB, 72h TTL) holding the real values behind the placeholders. Reading from it is meant to require a stated reason and write an access-log row. *The read path is not yet implemented — see [`status.md`](status.md) Gap 1.*

**Tier 1 / Tier 2** — masking's two passes. Tier 1 is regex (fast, high-confidence, structured patterns; critical hits short-circuit before any model is called). Tier 2 is a local LLM catching free-form mentions regex cannot, e.g. *"anh Tuấn phòng kế toán tầng 3"*.

---

## Retrieval

**Hybrid retrieval** — BM25 (keyword) and vector (semantic) search run in parallel, then fused. Each catches what the other misses: exact error codes vs. paraphrase.

**RRF** — Reciprocal Rank Fusion, `score(d) = Σ 1/(k + rank_i(d))` with k=60. Combines the two result lists. **Never threshold on an RRF score** — it is a rank-derived value, not a similarity, and its absolute magnitude means nothing ([ADR-0005](adr/0005-threshold-on-cross-encoder-not-fused-score.md)).

**Cross-encoder / reranker** — scores each (query, passage) pair jointly for a genuine relevance judgment. This score is the *only* one thresholds compare against. The default `lexical` provider is a dependency-free token-overlap stand-in for CI and offline dev; it is not a substitute for retrieval quality.

**Retrieval floor** — if the top reranked score is below `retrieval.floor` (0.45), the LLM is **never called**. This is both the largest cost saving and a safety property: a model with no source material has nothing to do but fabricate one.

**Refuse-before-LLM** — the above, as a graph edge. Worth knowing by name because it explains runs where `model = n/a` and every generation signal is false: nothing was generated, so nothing could be validated.

**`rerank_margin`** — top1 minus top2. A small margin means two KB articles overlap; that is both a signal to lower trust and a hint that the KB needs cleanup.

---

## Validation

**Verbatim quote** — for an auto-reply, the model must quote the KB text it relied on, exactly. This is what makes hallucination *mechanically* detectable rather than a matter of judgment.

**Quote match ratio** — how well that quote matches the retrieved chunk. Exact substring first; fuzzy only at ≥0.95, and only to absorb whitespace and punctuation drift.

**`quote_source_in_topk`** — mandatory: the quote must come from a chunk retrieval actually returned. A perfectly accurate quote pulled from a *different* KB article is a wrong answer in the right words.

**Negation check** — compares negation markers (`không`, `chưa`, `ngoại trừ`, `trừ khi`, `cấm`) between the quote and its source. Fuzzy matching cannot catch this: *"được cấp quyền"* and *"không được cấp quyền"* score ~0.96 similar and mean opposite things. In ITSM, an inverted condition is the most dangerous error class there is.

**`quote_applicable`** — whether quote checks apply at all. Route and runbook proposals carry no quote, so their quote signals are reported false; without this flag the UI shows red ✗ for checks that never ran.

---

## Incidents

**Duplicate** — a ticket similar to a recent one. Linked to the original, inherits its assignment, does not escalate.

**Mass incident** — many similar tickets in a short window, exceeding an **adaptive** baseline (`baseline + 3σ`, and at least `min_count`). Adaptive because 5 network tickets in 15 minutes is routine at a 5000-person company and alarming at a 100-person one. Detection creates a parent `Incident`, escalates, and **skips auto-reply entirely** — 40 people get one notification with an ETA instead of 40 individually-generated, possibly-wrong answers. This is a case where *not* using the AI is the right behavior.

---

## Evaluation

**Golden set** — 150 labeled cases at a fixed distribution (40% KB-covered, 20% ambiguous, 15% out-of-KB, 10% high-risk, 10% injection, 5% PII). Currently **synthetic** — a pass means "the wiring didn't regress," not "the model is good."

**Eval candidate** — a case auto-created whenever a human overrides the AI. The three free label sources are HITL overrides, technician reroutes, and reopens after auto-reply. All three are humans correcting the system, which is exactly the data calibration needs — provided the UI captures the *reason*, not just the outcome.

**Per-category F1** — measured per category, never averaged. An average hides the case that matters: a rare-but-serious category like `security` can sit at F1 0.4 while the mean looks healthy.

**Baseline** — committed metrics in `evals/baselines/baseline.json`. Updating it requires review, because otherwise the easiest way to make a failing PR pass is to lower the bar.

---

## Operations

**Circuit breaker** — trips at >20% LLM failures over 5 minutes, stays open 10 minutes, then admits 10% of traffic. When it opens, **alert the on-call team**: it means HITL volume is about to spike and more reviewers are needed. That is operational information, not a technical log line.

**Budget** — per-ticket caps on tokens, LLM calls, latency, and graph iterations, plus a daily cost ceiling. Exceeding any of them routes to HITL. This is both a cost control and a security control: an adversarial ticket engineered to induce a retry loop could otherwise burn the day's quota in minutes.

**Degraded** — any run where the pipeline could not complete normally (`embedding_unavailable`, `ai_engine_unavailable`, `circuit_open`, `budget_exceeded`). All of them degrade *toward a human*. A user waiting longer is acceptable; a user receiving a confident wrong answer is not.

**Runbook** — a scripted remediation the system can propose but **never** execute autonomously. Always through HITL, with no trust threshold high enough to skip it ([ADR-0006](adr/0006-runbook-always-hitl.md)). The spec flags this as the guardrail most likely to erode once `automation_rate` becomes a KPI.

---

## Metrics worth knowing by name

**`reopen_rate_after_autoreply`** — the single most important number. A wrong auto-reply that closed the ticket is an *invisible* failure: nobody is alerted, and the user simply gets bad information.

**`approve_rate_per_reviewer`** / **`median_time_spent_per_review`** — approval-fatigue detectors. A reviewer approving >95% at under 10 seconds median is rubber-stamping. That is *worse* than having no HITL, because it manufactures the appearance of oversight without the substance.

**`automation_rate`** — `(auto_reply + auto_route) / total`. Deliberately listed last. It is the metric most likely to be turned into a target, and the one whose pursuit does the most damage to the others.
