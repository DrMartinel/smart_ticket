# Claude Code skills for this repo

These skills turn the repo's conventions into repeatable workflows, so that any
Claude Code session builds and refactors code the same way. They live in
`.claude/skills/` and are committed with the code they describe.

The hard rules are still in [`CLAUDE.md`](../CLAUDE.md). The skills build on them
and never override them.

## What's here

| Skill | Use it to… | Invoke | You get back |
|---|---|---|---|
| **`/ai-engine-feature`** | build or change anything in `services/ai-engine`: a node, provider, state field, signal, retrieval change, prompt bump, or setting | `/ai-engine-feature add a node that flags duplicate-ticket language before retrieval` | a plan for you to approve, then the implementation, tests, verification and docs |
| **`/ai-engine-review`** | check a branch before you open a PR | `/ai-engine-review` (base defaults to `main`) or `/ai-engine-review HEAD~3` | a report sorted into Regression / Convention / Nit, with `file:line` links and fixes. It doesn't edit anything |
| **`/refactor`** | clean up Python in any service (ai-engine, core-api, contracts, evals) without changing what it does | `/refactor services/core-api/apps/tickets/services/pipeline.py` | an audit table of proposed moves. You pick the ones you want, and they're applied one at a time |

## How to invoke

- **Explicitly:** type the slash command followed by what you want, as in the table.
- **Implicitly:** Claude loads a skill by itself when your request matches the
  skill's description, e.g. "add a reranker fallback node" or "this file is messy,
  clean it up". If it doesn't, name the skill ("use /refactor on …").

## Typical flows

**New ai-engine feature**
```
/ai-engine-feature <what>  →  review the plan, answer open questions, approve
                           →  Claude implements, tests (failure paths first), runs pytest/pyright/ruff
                           →  /ai-engine-review  →  commit (ask Claude, or do it yourself)  →  PR
```

**Cleanup**
```
/refactor <file | module | concern>  →  read the audit table  →  reply with the move numbers you want
                                     →  each move applied + verified separately  →  commit the ones you like
```

**Before a PR**, run `/ai-engine-review` even if you wrote the code by hand.

## Where the workflows stop

Every workflow **stops and waits for you** at one point:

| Skill | Stops after | What you're shown |
|---|---|---|
| `/ai-engine-feature` | planning | files to touch, state fields and their defaults, outcomes and routes, each failure path and the reason code it ends at, the tests, and which hard rules are in play |
| `/refactor` | the audit | ranked moves (gain, risk, guarding test, draft commit), behaviour changes it noticed, and load-bearing code it chose to leave alone |
| `/ai-engine-review` | the report | nothing gets edited unless you ask |

The skills **never commit on their own**. They propose commit messages in the repo's
style (`refactor(ai-engine): …`, with a body saying why) and commit only when you ask.

## Where the rules live

To understand a rule, or change it, edit the reference file, not the SKILL.md:

| Topic | File |
|---|---|
| General Python taste: module shape, comments, naming, typing, errors, tests, commits | [`skills/refactor/references/readability.md`](skills/refactor/references/readability.md) |
| Refactor moves the repo endorses, each with its precedent commit | [`skills/refactor/references/moves.md`](skills/refactor/references/moves.md) |
| Code that looks removable but isn't, and the test or ADR that guards it | [`skills/refactor/references/load-bearing.md`](skills/refactor/references/load-bearing.md) |
| ai-engine specifics: node contract, providers, failure semantics, state, DB | [`skills/ai-engine-feature/references/ai-engine-conventions.md`](skills/ai-engine-feature/references/ai-engine-conventions.md) |
| Step-by-step recipes (node, provider, signal, prompt, retrieval) | [`skills/ai-engine-feature/references/recipes/`](skills/ai-engine-feature/references/recipes/) |
| Test toolkit and templates for ai-engine | [`skills/ai-engine-feature/references/testing.md`](skills/ai-engine-feature/references/testing.md) |
| Review checklist (shared by the feature and review skills) | [`skills/ai-engine-feature/references/checklist.md`](skills/ai-engine-feature/references/checklist.md) |

## Maintaining the skills

- **When your taste changes, edit the reference file** that states the rule. Keep
  each SKILL.md as the workflow only.
- **Point to code; don't copy it.** Rules cite exemplar files (`graph/nodes/rerank.py`,
  `router.py`) so Claude reads the current version. Don't paste in lists that go
  stale, such as node names, test counts or route tables.
- **When a refactor sets a new precedent, add it to `moves.md`** with its commit SHA.
  When you add a new guardrail, add it to `load-bearing.md` along with the test that
  guards it.
- **When a file or symbol is renamed**, grep `.claude/skills/` for the old name.
  `/refactor`'s sweep step does this automatically.
- **After editing a skill, test it:** run it in plan mode on a throwaway request,
  e.g. `/ai-engine-feature add a node that flags duplicate-ticket language before retrieval`.
  Check that the plan touches the right files (state, node module, `build.py`,
  `conftest.py`, `test_build.py`), routes every outcome, lists failure paths first,
  and stops before writing code.

## Troubleshooting

| Symptom | Fix |
|---|---|
| A skill doesn't appear in `/` completion | It must be at `.claude/skills/<name>/SKILL.md` with `name:` and `description:` frontmatter. Restart the session after adding it. |
| Claude didn't use the skill by itself | Invoke it explicitly. If that keeps happening for a certain kind of request, add that phrasing to the skill's `description`. |
| The skill cites a file or symbol that no longer exists | The code moved. Update the reference to point at the new location. |
| The skill and a doc in `docs/` disagree | The code is the source of truth. Fix whichever of the two is wrong. |
