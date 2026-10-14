# Golden set schema

`tickets.jsonl` — one JSON object per line.

```json
{
  "id": "g001",
  "subject": "...",
  "body": "...",
  "truth": {
    "category": "access",
    "kb_slug": "ec2.TroubleshootingInstancesConnecting",
    "expected_branch": "auto_reply",
    "reason_code": "all_checks_passed"
  },
  "tags": ["kb_covered"]
}
```

- `truth.category` — one of `TicketCategory` (core-api `infrastructure/dtos.py`), or omitted if not determinable (e.g. pure injection cases). For `kb_covered` it is the target article's category from `demo_kb/manifest.json`. Every `out_of_kb` case is `other`.
- `truth.kb_slug` — the KB article slug that should answer this ticket, if any.
- `truth.acceptable_kb_slugs` — optional, drafted tickets only: other pages that resolve the ticket as well as `kb_slug`. The retrieval suite counts a hit on any of them (gated `retrieval_recall_at_3`) and reports `retrieval_recall_at_3_strict` (gold page only) beside it. `expected_branch` still follows `kb_slug` alone.
- `truth.clarify_slugs` — optional, `underspecified` tickets from g615 on: the pages that fix the ticket's different readings, the ones a clarifying question should offer. At least two.
- `truth.expected_branch` — one of `Branch` (core-api `apps/tickets/utils/router.py`): `auto_reply | auto_route | hitl | block | escalate | clarify`.
- `truth.reason_code` — one of `ReasonCode` (core-api `apps/tickets/utils/router.py`), when the specific gate/reason matters to the test (e.g. `injection_detected`, `kb_not_authorized`, `retrieval_below_floor`). Omitted when any HITL reason is acceptable.
- `tags` — free-form, used to filter by suite. At minimum one of the six distribution buckets below, or `edge`.

## Distribution (spec §12.1, 150 cases, plus 24 edge cases)

| Tag | Target | Actual | Why |
|---|---|---|---|
| `kb_covered` | 40% | 60 | Core capability |
| `ambiguous` | 20% | 30 | Where the system actually breaks. Each also carries its kind: `multi_issue` (18, two or more separate problems), `uncertain_cause` (6, one problem, cause unknown) or `vague` (6, too little to act on) |
| `out_of_kb` | 15% | 23 | Tests whether refusal works |
| `high_risk` | 10% | 15 | Tests KB authority gate. Each also carries `sensitive_access` (8, a routine request needing approval) or `security_incident` (7, something may already be wrong) |
| `injection` | 10% | 15 | Tests the injection guardrail |
| `pii` | 5% | 7 | Tests masking at each PII level (13 with the `pii_answerable` edge cases) |

The 24 `edge` cases come after these, as g151-g174, so the IDs above never
move. They are beyond §12.1's distribution, and each also carries one of:

| Tag | Count | Expected | Why |
|---|---|---|---|
| `underspecified` | 6 | `clarify` | Several pages fit and the ticket doesn't say which: the system should ask, not guess (ADR-0016) |
| `pii_answerable` | 6 | the page's own branch | Routine PII next to a request a page answers: masking and auto-reply on one ticket (also tagged `pii`) |
| `split_chunk` | 6 | `auto_reply` | The answer is in a continuation chunk without the page title or section heading |
| `near_miss` | 6 | the answering page's own branch | Same topic as an approved page that doesn't resolve them; an auto-reply citing that page is false by construction. They expected `hitl` until ADR-0027 approved the answering pages |

### More clarify tickets (g615 on)

Six clarify tickets were too few to compare who should decide to ask (the
LLM's clarify proposal or Jev, 2026-10-13). After the drafted tickets come
38 more `edge` cases, written from KB page titles, never from pipeline
output:

| Tag | Count | Expected | Why |
|---|---|---|---|
| `underspecified` | 22 (g615-g636) | `clarify` | As g151-g156; `truth.clarify_slugs` names the pages that fix each reading |
| `specific` | 16 (g637-g652) | the page's own branch | The same topics, specific enough that one page answers them: a clarify is a needless question |

Reviewer subagents read every page named, not people: they dropped
readings a page doesn't fix, swapped overview pages for the ones with the
steps, reworded 19 drafts and rejected 8 of the 30 underspecified ones (the
same fix for every reading, no page that fixes it, or one reading that
clearly wins). With g151-g156, 28 tickets expect `clarify`.

### Drafted `kb_covered` tickets (g175 on)

To make retrieval recall less sensitive to one ticket (1.7 points at 60
tickets), 440 more `kb_covered` tickets follow the edge cases, tagged
`kb_covered` and `drafted`, one per page, from `kb_covered_drafted.jsonl`.
`draft_kb_covered.py` drafted each with DeepSeek (ADR-0019: KB text only)
from a page sampled stratified by guide (duplicate-text copies and existing
targets excluded); reviewer subagents read the page and checked that the
ticket is not a paraphrase of it, that the page resolves it, and that it
reads like a real ticket. A rejected ticket was redrafted once with the
reviewer's reason, then dropped and its page replaced. Category and expected
branch follow the same rule as the authored ones (`answered_by`). Of the
440, 75 are redrafts and 134 name at least one acceptable page. When they
were drafted none targeted an approved page; since ADR-0027 (2026-10-14)
359 of them target one and expect `auto_reply`.

The drafted tickets carry the `kb_covered` tag, so the classification and
end-to-end suites score them too, not only retrieval.

**Acceptable pages were chosen by the reviewer subagents, not by people**
(the user's decision, 2026-10-11): where another page resolves a ticket as
well, the reviewer named it and it went into `acceptable_kb_slugs`. This
departs from the 2026-09-29 rule for the authored tickets (two blind human
reviewers decide alternatives), so strict recall is reported beside the
gated number.

Retrieval, classification and refusal select their cases by tag, so `edge`
cases count only in the end-to-end suite (branch accuracy, auto-reply
precision).

## Provenance

**This golden set is synthetic**, generated by `generate_golden.py` from
authored English help-desk tickets against the demo KB (`demo_kb/`, a frozen
snapshot of AWS documentation). Each `kb_covered` case targets a real page
in `demo_kb/manifest.json`; its category comes from the manifest and its
expected branch from `demo_kb/curation.json` (approved articles expect
`auto_reply`, the rest `kb_not_authorized`). Since ADR-0027 every low- and
medium-risk page is approved, so most KB-covered tickets expect
`auto_reply`; 402 labels changed on 2026-10-14, IDs and texts did not. Generation fails if a target
slug is missing from the manifest.
It is meant to exercise every branch and reason code end-to-end from day
one — it is explicitly **not** a substitute for the real, hand-labeled
golden set spec §12.1 calls for. Per spec §12.4, real cases should be
promoted into this set over time from human overrides, reroutes, and
reopens; until then, treat pass/fail against this set as "the pipeline's
wiring didn't regress," not as "the model is good."
