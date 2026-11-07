# Claude Code skills for this repo

These skills turn the repo's conventions into repeatable workflows, so that any
Claude Code session builds and refactors code the same way. They live in
`.claude/skills/` and are committed with the code they describe.

The hard rules are still in [`CLAUDE.md`](../CLAUDE.md). The skills build on them
and never override them.

## What's here

| Skill | Use it to… | Invoke | You get back |
|---|---|---|---|
| **`/feature`** | build or change a feature in any service: a core-api route, model, service or setting; an ai-engine node, provider, state field, signal, retrieval change or prompt bump; a console or chat page | `/feature add a node that flags duplicate-ticket language before retrieval`, or `/feature let a team lead pause a member's assignments` | a plan for you to approve, then the implementation, tests, verification and docs |
| **`/review`** | check a branch before you open a PR, against the checklist of each service it touches | `/review` (base defaults to `main`) or `/review HEAD~3` | a report sorted into Regression / Convention / Nit, with `file:line` links and fixes. It doesn't edit anything |
| **`/refactor`** | clean up Python in any service (ai-engine, core-api, evals) without changing what it does, or check changes against the checklist | `/refactor services/core-api/apps/tickets/utils/pipeline.py`, or `/refactor check my changes against the checklist` | an audit table of proposed moves (applied one at a time once you pick them), or a pass/fail table per checklist item |
| **`/checklist-add`** | add a rule to the checklist `/refactor` enforces | `/checklist-add docstrings never name the return value` | the new numbered item, with how to check it, a real example from the repo, and where it came from |
| **`/create-mr`** | open a merge request (GitHub PR) for the current branch | `/create-mr`, or `/create-mr main this is F15 PR 3` | a review by the `mr-reviewer` subagent (`/code-review` plus the repo's rules), then a drafted title and a body with **Summary**, **Rationale** and **Test plan** (checked, none empty) for you to approve; then the push and the PR link |

## How to invoke

- **Explicitly:** type the slash command followed by what you want, as in the table.
- **Implicitly:** Claude loads a skill by itself when your request matches the
  skill's description, e.g. "add a reranker fallback node" or "this file is messy,
  clean it up". If it doesn't, name the skill ("use /refactor on …").

## Typical flows

**New feature**
```
/feature <what>  →  review the plan, answer open questions, approve
                 →  Claude implements, tests (failure paths first), runs each service's checks
                 →  /review  →  commit (ask Claude, or do it yourself)  →  /create-mr
```

**Cleanup**
```
/refactor <file | module | concern>  →  read the audit table  →  reply with the move numbers you want
                                     →  each move applied + verified separately  →  commit the ones you like
```

**Before a PR**, run `/review` even if you wrote the code by hand.

## Where the workflows stop

Every workflow **stops and waits for you** at one point:

| Skill | Stops after | What you're shown |
|---|---|---|
| `/feature` | planning | files to touch, ai-engine state fields and outcomes, core-api routes (permission and agent tier) and data, each failure path and the reason code it ends at, the tests, and which hard rules are in play |
| `/refactor` | the audit | ranked moves (gain, risk, guarding test, draft commit), behaviour changes it noticed, and load-bearing code it chose to leave alone |
| `/review` | the report | nothing gets edited unless you ask |
| `/create-mr` | the review, then the draft | blocking findings first (fix or accept each), then the title, base and head, the commits going in, the full description and the check results; nothing is pushed until you say yes |

The skills **never commit on their own**. They propose commit messages in the repo's
style (`refactor(ai-engine): …`, with a body saying why) and commit only when you ask.

## Where the rules live

To understand a rule, or change it, edit the reference file, not the SKILL.md:

| Topic | File |
|---|---|
| Which core-api layer a piece of logic goes in; when to extract a function or a class | [`skills/refactor/references/where-logic-goes.md`](skills/refactor/references/where-logic-goes.md) |
| General Python taste: module shape, comments, naming, typing, errors, tests, commits | [`skills/refactor/references/readability.md`](skills/refactor/references/readability.md) |
| Refactor moves the repo endorses, each with its precedent commit | [`skills/refactor/references/moves.md`](skills/refactor/references/moves.md) |
| Code that looks removable but isn't, and the test or ADR that guards it | [`skills/refactor/references/load-bearing.md`](skills/refactor/references/load-bearing.md) |
| ai-engine specifics: node contract, providers, failure semantics, state, DB | [`skills/feature/references/ai-engine/conventions.md`](skills/feature/references/ai-engine/conventions.md) |
| ai-engine recipes (node, provider, signal, prompt, retrieval) | [`skills/feature/references/ai-engine/recipes/`](skills/feature/references/ai-engine/recipes/) |
| Test toolkit and templates for ai-engine | [`skills/feature/references/ai-engine/testing.md`](skills/feature/references/ai-engine/testing.md) |
| core-api recipes (route, model, tunable or setting) | [`skills/feature/references/core-api/recipes/`](skills/feature/references/core-api/recipes/) |
| Review checklists, one per service (shared by `/feature` and `/review`) | [`ai-engine`](skills/feature/references/ai-engine/checklist.md) · [`core-api`](skills/feature/references/core-api/checklist.md) · [`web`](skills/feature/references/web/checklist.md) |

## Maintaining the skills

- **When your taste changes, edit the reference file** that states the rule. Keep
  each SKILL.md as the workflow only.
- **Point to code; don't copy it.** Rules cite exemplar files (`graph/nodes/classify_category/node.py`,
  `router.py`) so Claude reads the current version. Don't paste in lists that go
  stale, such as node names, test counts or route tables.
- **When a refactor sets a new precedent, add it to `moves.md`** with its commit SHA.
  When you add a new guardrail, add it to `load-bearing.md` along with the test that
  guards it.
- **When a file or symbol is renamed**, grep `.claude/skills/` for the old name.
  `/refactor`'s sweep step does this automatically.
- **After editing a skill, test it:** run it in plan mode on a throwaway request,
  e.g. `/feature add a node that flags duplicate-ticket language before retrieval`.
  Check that the plan touches the right files (state, node module, `graph/triage.py`,
  `conftest.py`, `test_build.py`), routes every outcome, lists failure paths first,
  and stops before writing code.

## Troubleshooting

| Symptom | Fix |
|---|---|
| A skill doesn't appear in `/` completion | It must be at `.claude/skills/<name>/SKILL.md` with `name:` and `description:` frontmatter. Restart the session after adding it. |
| Claude didn't use the skill by itself | Invoke it explicitly. If that keeps happening for a certain kind of request, add that phrasing to the skill's `description`. |
| The skill cites a file or symbol that no longer exists | The code moved. Update the reference to point at the new location. |
| The skill and a doc in `docs/` disagree | The code is the source of truth. Fix whichever of the two is wrong. |
