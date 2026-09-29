---
name: refactor
description: Behaviour-preserving refactor workflow for this repo's Python code (services/ai-engine, services/core-api, evals) — audit a file, module or concern, propose ranked refactor moves, wait for approval, then apply one move at a time with tests green before and after. Holds the repo's readability and maintainability conventions and the list of load-bearing code that must not be "simplified". Use this whenever the user asks to refactor, clean up, simplify, tidy, restructure, dedupe, rename, improve readability or maintainability, reduce complexity, or bring code "up to the ai-engine style" — even if they just say "this file is messy" or "can you make this nicer".
argument-hint: <path | module | concern>
---

# Refactor

Target: **$ARGUMENTS**. If that is empty, ask the user what to refactor before doing
anything else.

A refactor here does two things. It makes the code easier to read and change, and it
leaves every behaviour and every guardrail exactly as it was. The subtle risk in this
repo is simplifying something that looks like needless indirection but actually keeps
the LLM from gaining authority or keeps a failure from passing as success. That kind
of regression stays green. So this workflow is built around **reading before
cutting** and **one small, verified move at a time**.

## Reference files

- `references/readability.md` holds the conventions: the target style, with an
  exemplar file for each rule. Read it once per session before auditing.
- `references/moves.md` is the catalogue of refactor moves the repo has already made,
  each with its smell, its guard, and the commit that set the precedent.
- `references/load-bearing.md` lists code that must not be simplified. Read all of it
  before proposing anything.
- `CLAUDE.md` holds the hard rules. They override everything in this skill.

---

## Phase 0: Ground rules

- **Behaviour is preserved.** If a move changes what the code does, whether that is
  outputs, reason codes, persisted values, env var names, timing or failure mode, it
  is a behaviour change. Either split it out of the refactor or flag it explicitly.
  If the user approves it, the commit says `Deliberately relaxes …` or names the
  behaviour change.
- **Load-bearing items are off-limits** unless the user names that specific item.
- **Scope stays on the target.** If you notice problems elsewhere, list them at the
  end and don't fix them.

## Phase 1: Baseline

Establish what "green" means before anything moves:

```bash
uv run pytest <the target's test dir or file> -q
uv run mypy
```

- Record any failures that exist before you start. The evals have a known failure
  (the `other` category's F1). A failure you didn't cause is not yours to fix here,
  but you need to know about it so you don't blame your change later.
- If the code you intend to move has little or no test coverage, propose
  **characterisation tests first**, as their own step. They pin what the code does
  today, so the refactor can prove it didn't change anything.

## Phase 2: Audit

1. Read the target in full, then its tests, then its callers (`grep -rn` for each
   public name).
2. Read **every comment and docstring** in the target. Many of them name what would
   break if the code were simplified.
3. Run `git log --follow --oneline -- <file>` and look at the relevant commits
   (`git show <sha>`). Code that looks odd is often a deliberate fix. Don't revert it.
4. Check each candidate against `load-bearing.md` first, then match it to a move in
   `moves.md` and a rule in `readability.md`.
5. Look for these smells: single-use wrappers, unreachable branches, speculative
   machinery, DI plumbing, scattered wiring, decisions mixed into I/O, string literals
   where a contract enum exists, restating comments, missing contract docstrings,
   nested conditionals, positional arguments that are easy to swap, and type-checker noise.

## Phase 3: Propose, then STOP

Present the audit in exactly this shape, ranked by value/risk:

```markdown
## Refactor audit: <target>

Baseline: <tests passed/failed, mypy clean/n issues, known pre-existing failures>

| # | Move (moves.md #) | Where | Gain | Risk | Guarded by | Draft commit |
|---|---|---|---|---|---|---|
| 1 | Inline `_x` into `y` (#1) | [file.py:42](path#L42) | one less hop | low | test_foo.py | refactor(scope): … |

### Behaviour changes spotted (need your call)
- <anything that is NOT behaviour-preserving, e.g. a literal that matches no enum member>

### Considered, left alone
- <thing>: load-bearing, <one-line reason> (<ADR / test>)

### Outside the target (not touching)
- <observations elsewhere>
```

**Wait for the user to choose moves.** Don't start editing until they do. Being
shown a move is not the same as approving it.

## Phase 4: Apply, one move at a time

For each approved move, in order:

1. Make the change, and keep it to that one move.
2. Verify:
   ```bash
   uv run pytest <target tests> -q
   uv run mypy
   uvx ruff@0.16.7 check . --exclude .venv
   uvx ruff@0.16.7 format --check . --exclude .venv
   ```
3. If a guarding test exists for an invariant near the move, do a quick **mutation
   check**. Break the invariant, confirm the test fails, then revert. This shows the
   test still guards something after the move.
4. Show the diff and propose the commit message in the repo's style (see
   `readability.md` §13). The body says why, and for a removal it says what still
   holds afterwards.
5. **Commit only if the user asks.** Then go on to the next move.

If a move turns out bigger or riskier than proposed, stop and re-propose it rather
than pushing through.

## Phase 5: Sweep

After the last move:

- `grep -rn` the old names across `docs/`, `CLAUDE.md`, `.claude/skills/`, and
  `infra/` for any env var. Update what describes the code you changed. A doc update
  belongs in the same commit as the change it describes.
- If a core-api schema the web uses changed, run
  `uv run --package core-api python services/core-api/scripts/gen_typescript.py`.
  If an ai-engine wire shape changed, make the same change in the other service.
- If a move set a new precedent, offer to add it to `references/moves.md`.
- Run the full check: `uv run pytest` plus mypy plus ruff. Report the result
  honestly, including anything still failing.
