---
name: ai-engine-review
description: Review a branch or diff that touches services/ai-engine (and any packages/contracts or core-api glue it drags in) against this repo's safety invariants and house conventions — node contract, degrade-to-HITL failure paths, read-only DB boundary, ADR-0003/0004/0005, test conventions, and style. Produces a categorised report (Regression / Convention / Nit) with file:line links and suggested fixes; does not edit code unless asked. Use this whenever the user asks to review, check, audit or sanity-check ai-engine changes, asks "is this ready for a PR?", "did I break any conventions?", or has just finished an ai-engine feature.
argument-hint: "[base-ref, default: main]"
---

# ai-engine review

Base: **$ARGUMENTS** (use `main` if empty).

The point of this review is to catch the regressions that don't fail loudly in this
codebase: an infrastructure failure that reads as an empty result, a threshold
compared against the wrong score, a provider that falls back without saying so, or
a node that gains a write path. Style comes second. Say plainly when something is
fine, and don't invent findings to fill the report.

## Steps

1. **Scope the diff.**
   ```bash
   git diff <base>...HEAD --stat
   git diff <base>...HEAD -- services/ai-engine packages/contracts services/core-api/apps/tickets
   ```
   If there are uncommitted changes, include `git diff` and `git diff --staged` too,
   and say that you did.
2. **Read in full**, not just the hunks. Read every changed source file, its test
   file, and any file it wires into (`graph/triage.py`, `tests/conftest.py`,
   `core/state.py`). Many findings only show up in the surrounding code, such as a
   new node missing from a `use_*` fixture or an outcome with no route.
3. **Walk the checklist:** `.claude/skills/ai-engine-feature/references/checklist.md`.
   For general style, use `.claude/skills/refactor/references/readability.md`. If a
   change removed or simplified something, check it against
   `.claude/skills/refactor/references/load-bearing.md`.
4. **Run the checks** and report what actually happened:
   ```bash
   uv run pytest services/ai-engine/tests -q
   uvx pyright@1.1.414
   uvx ruff@0.16.7 check . --exclude .venv
   uvx ruff@0.16.7 format --check . --exclude .venv
   ```
   If the diff touches contracts or core-api, run the whole workspace with
   `uv run pytest`. If it touches a prompt or retrieval, check whether eval results
   are mentioned. If they aren't, that is a finding.
5. **Spot-check the key tests.** For any new safety test, reason about whether it
   would fail if the invariant were broken. If it wouldn't, report it as a
   **[convention]**: "test doesn't guard what its docstring claims."

## Report format

```markdown
## ai-engine review: <base>...HEAD

**Checks:** pytest <pass/fail + counts> · pyright <clean/n> · ruff <clean/n> · evals <run/not run/n.a.>

### Regression (must fix before merge)
1. [file.py:42](services/ai-engine/...#L42) — <what is wrong>. **Rule:** <checklist item / ADR>. **Fix:** <concrete suggestion>.

### Convention
1. …

### Nit
1. …

### Looks good
- <things done well that are worth keeping, briefly>
```

Rank the findings within each section by impact. If a section is empty, write
"None." Leave the code alone unless the user asks for fixes. If they do, apply the
fixes, re-run step 4, and report what changed.
