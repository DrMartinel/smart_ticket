# Testing

Two distinct layers with different purposes. Confusing them is the usual source of misplaced confidence.

| Layer | Answers | Deterministic | Runs on |
|---|---|---|---|
| **Unit** (`services/*/tests/`) | Does the code do what it says? | Yes | Every commit |
| **Eval** (`evals/suites/`) | Does the *system* still behave acceptably? | No — model output varies | Every PR, gated |

Unit tests protect logic. Evals protect behavior. A green unit suite says nothing about whether the model got worse, and a green eval run says nothing about whether your refactor broke an edge case.

---

## Running

```bash
uv sync --all-packages    # once; a bare `uv sync` won't install pytest

uv run pytest                              # everything (111 unit + 8 eval)
uv run pytest services/core-api/tests -q   # 73
uv run pytest services/ai-engine/tests -q  # 38
uv run pytest evals/suites -q              # 8 suites
```

Eval suites needing a live pipeline **skip** automatically when `ai-engine` isn't reachable, so unit tests stay runnable offline. `test_injection` and `test_quote_validation` run fully in-process with no dependencies at all.

Coverage on the two modules where it is contractual:

```bash
uv run pytest services/core-api/tests -q \
  --cov=apps.tickets.services.masking --cov=apps.tickets.services.router \
  --cov-report=term-missing
```

---

## What the unit tests actually protect

Worth knowing, because these are the invariants a reviewer will check you haven't broken.

### `test_masking.py` — **100% branch coverage is a release gate**

Spec §14 makes it the P0 exit condition, and the reason is asymmetry: a masking bug leaks PII silently, while a masking false-positive merely creates work. The tests pin, among others:

- A `critical` regex hit short-circuits **before** Ollama is called at all.
- A tier-2 timeout or error becomes `MASK_FAILED`, never "no PII found".
- A bare `{}` from the model still fails closed — resolving ambiguity toward "clean" is the one thing this stage must never do.
- Numbered placeholders preserve co-reference (the same email twice stays `[EMAIL_1]` twice).
- The request pins a JSON *Schema*, not bare `format: "json"`. If someone reverts that, the shape drifts and every ticket becomes a spurious `MASK_FAILED`.

### `test_router.py` — every branch, no I/O

The whole file runs without a database, model, or network. That is the property [ADR-0001](adr/0001-code-level-routing.md) is defending, and the test file is its proof. It covers each hard gate, each threshold boundary, and the ordering that matters — notably that `mass_incident` is checked before duplicate logic, and that a refuse-before-LLM run reports `retrieval_below_floor` rather than blaming the model for output it never produced.

### `test_trust_scorer.py` — the ADR-0003 invariant

`llm_self_confidence` must never enter the feature set. There is a test whose only job is to fail if someone adds it back.

Also pinned: quote features are skipped when a proposal carries no quote, so `contributions` can show "not applicable" rather than an unexplained zero. That is explainability only — both are linear terms, so a 0.0 value contributes 0.0 either way, and a test asserts the score does **not** move. If someone later gives those features a non-zero baseline, that test fails and forces a deliberate decision.

### `test_reranker_diacritics.py`

Vietnamese tickets are typed without tone marks; the KB is written with them. Under exact token matching a near-verbatim restatement of a KB title scored 0.042 against a 0.45 floor, tripping refuse-before-LLM and sending it to a human as "nothing matches". These tests pin the folding, including that `đ`/`Đ` need special handling (distinct letters, not decomposable base + mark) and that folding doesn't make unrelated text start matching.

---

## The eval harness

### Golden set

150 cases in `evals/golden/tickets.jsonl` at the spec §12.1 distribution:

| Tag | Share | Purpose |
|---|---|---|
| `kb_covered` | 40% | Core capability |
| `ambiguous` | 20% | Where systems actually break |
| `out_of_kb` | 15% | Does refusal work? |
| `high_risk` | 10% | Does the KB authority gate hold? |
| `injection` | 10% | Does the guardrail hold? |
| `pii` | 5% | Masking at each level |

**These cases are synthetic.** Treat a pass as *"the pipeline's wiring didn't regress"*, never as *"the model is good"*. Per spec §12.4, real cases should be promoted in over time from `eval_candidates` — human overrides, technician reroutes, and reopens after auto-reply. Those three are all humans correcting the system, which is precisely the signal worth training on.

### The gates

| Suite | Metric | Gate |
|---|---|---|
| `test_retrieval` | Recall@5 | ≥ 0.90 |
| `test_classification` | F1 **per category** | ≥ 0.85 each |
| `test_quote_validation` | Hallucination-catch precision | ≥ 0.95 |
| `test_refusal` | Out-of-KB refusal rate | ≥ 0.90 |
| `test_injection` | Detection recall | ≥ 0.95 |
| `test_end_to_end` | Auto-reply precision | ≥ 0.95 **absolute** |

Two of these are deliberately not negotiable:

**Per-category F1, never averaged.** An average hides the case that matters most: `security` is rare and severe, and can sit at F1 0.4 while the mean looks healthy.

**Auto-reply precision is an absolute floor, not relative to baseline.** A relative gate ratchets downward one acceptable-looking regression at a time.

### Known failure

`other` scores **F1 0.75** against the 0.85 floor — precision 1.00, recall 0.60, so the model *under*-assigns rather than over-assigns. The category maps to a single KB article (KB-0010, long-term leave — an HR matter arriving through IT), and classification on it is inconsistent.

This is recorded in `evals/baselines/baseline.json` as a known issue rather than smoothed into the baseline. **Do not** lower the floor, average the F1, or drop the category to make CI green. Fix the KB content or the prompt — see [`TODO.md`](TODO.md) item 3.

### Baselines

`evals/baselines/baseline.json` is committed, and updating it requires review by someone other than the author of the change that motivated it. Without that rule, the path of least resistance for a failing PR is to lower the bar, and the gate quietly stops meaning anything.

---

## Writing tests here

**Test the failure paths.** This system's correctness is mostly about what it does when things go wrong — a test that a degraded run reaches HITL with the right `reason_code` is worth more than another happy-path assertion.

**Explain the failure mode in the docstring.** Several test classes in this repo document the bug they exist to prevent, with enough context that someone can judge whether a future change is a regression or an intentional shift. That is the useful form.

**Prefer pinning the invariant over pinning the implementation.** `test_llm_self_confidence_does_not_change_score` survives any rewrite of the scorer; a test asserting a specific weight would not.

**When a test surprises you, check the test.** During this project a test asserting route proposals were "penalized" for having no quote failed — correctly. Both features are linear terms, so a 0.0 value contributes 0.0 whether summed or skipped, and the scores were identical. The reasoning was wrong, not the code. The rewritten test now pins the real property (scores don't move) plus a guard that fires if anyone gives those features a non-zero baseline.

---

## CI

`infra/ci/eval-gate.yml` runs the eval suites on every PR, compares against the committed baseline, and posts a report. Prompt changes go through it exactly like code changes — that is the whole reason `evals/` lives in this repository rather than in a notebook somewhere.
