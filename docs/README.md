# Documentation

Start here. The documents below are ordered — reading them in sequence takes about an hour and gets you to the point where you can make a change confidently.

## If you are new, read in this order

| # | Document | Why | Time |
|---|---|---|---|
| 1 | [`onboarding.md`](onboarding.md) | Get it running, submit a ticket, watch it get triaged. Concrete before abstract. | 30 min |
| 2 | [`glossary.md`](glossary.md) | The vocabulary. The original spec is in Vietnamese and the codebase is dense with domain terms — skipping this makes everything else harder than it needs to be. | 10 min |
| 3 | [`architecture.md`](architecture.md) | How the pieces fit, who is allowed to do what, and the path a single ticket takes. | 20 min |
| 4 | [`adr/`](adr/) | Eight decisions that shaped the system, each written to survive being re-litigated. Read 0001 and 0003 at minimum. | 15 min |
| 5 | [`development.md`](development.md) | Conventions, how to make common changes, and the setup gotchas that will otherwise cost you an afternoon. | 15 min |

Then keep these nearby:

| Document | For |
|---|---|
| [`testing.md`](testing.md) | Test layers, the eval harness, and what the CI gate actually enforces |
| [`status.md`](status.md) | What is genuinely done vs. what merely has code, plus known gaps |
| [`TODO.md`](TODO.md) | Prioritized open work, each item self-contained enough to pick up |
| [`runbooks/on-call.md`](runbooks/on-call.md) | When it breaks in a running deployment |
| [`../requirement.md`](../requirement.md) | The original architecture specification (Vietnamese). The source of truth for *intent* — section numbers (§5, §8, §10.3) are cited throughout the code. |

## The one-sentence version

An LLM reads an IT support ticket and **proposes** what to do with it; deterministic, testable code **decides** whether to act on that proposal — and by default routes everything to a human anyway while the system's judgment is being calibrated.

If you remember nothing else, remember that split. Nearly every design decision in this repo follows from it, and the ones that look over-engineered usually exist to keep the LLM from quietly acquiring authority it was never granted.

## Where the important code lives

| Concern | Path | Note |
|---|---|---|
| The routing decision | [`router.py`](../services/core-api/apps/tickets/services/router.py) | Pure function. The only place a `Branch` is chosen. |
| PII masking | [`masking.py`](../services/core-api/apps/tickets/services/masking.py) | Runs inline before any DB write. 100% branch coverage is a release gate. |
| Shared schemas | [`packages/contracts/`](../packages/contracts/) | Single source of truth. Both Python services import it; the frontend's types are generated from it. |
| The AI pipeline | [`graph/flow.py`](../services/ai-engine/src/ai_engine/graph/flow.py) | LangGraph topology in one table. Refuses before calling the LLM when retrieval is weak. |
| Every tunable number | [`thresholds.yaml`](../services/core-api/config/thresholds.yaml) | No magic numbers anywhere else. |
| Why a ticket is in the queue | [`TrustSignalsPanel.tsx`](../services/web/components/TrustSignalsPanel.tsx) | The reviewer-facing explanation. |

## A note on reading the code

Comments in this codebase lean toward explaining **why**, often citing a spec section or an ADR. Where you see something that looks needlessly indirect — the `proposed_` field prefixes, authority living on KB rows instead of in the model's output, a pure function that takes thresholds as an argument — the comment usually explains what breaks without it. Those are worth reading before simplifying.
