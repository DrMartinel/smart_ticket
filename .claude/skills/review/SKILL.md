---
name: review
description: Review a branch or diff anywhere in this repo (core-api, ai-engine, the web apps) against its safety invariants and house conventions - router purity, degrade-to-HITL failure paths with a ReasonCode, the read-only ai-engine DB boundary, ADR-0003/0004/0005/0006, the wire schema in both services, route permissions and agent tiers, thresholds and settings, the layer rules in where-logic-goes.md, test conventions and style. It walks the checklist of each service the diff touches and produces a categorised report (Regression / Convention / Nit) with file:line links and suggested fixes; it does not edit code unless asked. Use this whenever the user asks to review, check, audit or sanity-check changes, asks "is this ready for a PR?", "did I break any conventions?", or has just finished a feature.
argument-hint: "[base-ref, default: main]"
---

# Review

Base: **$ARGUMENTS** (use `main` if empty).

The point of this review is to catch the regressions that don't fail loudly in this
codebase: an infrastructure failure that reads as an empty result, a threshold
compared against the wrong score, a provider that falls back without saying so, a
node that gains a write path, a route with no permission or agent tier, a decision
made outside `router.py`, or a status written around its service. Style comes second.
Say plainly when something is fine, and don't invent findings to fill the report.

## Steps

1. **Scope the diff.**
   ```bash
   git diff <base>...HEAD --stat
   git diff <base>...HEAD
   ```
   If there are uncommitted changes, include `git diff` and `git diff --staged` too,
   and say that you did. Note which services the diff touches:

   | Paths | Service | Checklist |
   |---|---|---|
   | `services/ai-engine/` | ai-engine | `.claude/skills/feature/references/ai-engine/checklist.md` |
   | `services/core-api/`, `infra/` | core-api | `.claude/skills/feature/references/core-api/checklist.md` |
   | `services/admin-console/`, `services/chat/` | web | `.claude/skills/feature/references/web/checklist.md` |

   A change to `services/core-api/infrastructure/dtos.py` or to ai-engine's wire
   schema touches **both** services (hard rule 4): check the other side changed too.
2. **Read in full**, not just the hunks. Read every changed source file, its test
   file, and any file it wires into: for ai-engine `graph/triage.py`,
   `tests/conftest.py`, `graph/state.py`, `schemas.py`; for core-api the app's
   `views.py`, `models.py`, its service in `utils/` and the migration. Many findings
   only show up in the surrounding code, such as a new node missing from a `use_*`
   fixture, an outcome with no route, or a route missing from the access snapshot.
3. **Walk each touched service's checklist.** For core-api also apply
   `.claude/skills/refactor/references/where-logic-goes.md`. For general style, use
   `.claude/skills/refactor/references/readability.md`. If a change removed or
   simplified something, check it against
   `.claude/skills/refactor/references/load-bearing.md`.
4. **Run the checks** for each touched service and report what actually happened:

   | Touched | Run |
   |---|---|
   | ai-engine | `uv run pytest services/ai-engine/tests -q` · `uv run mypy` |
   | core-api | `cd services/core-api && make check` · `make coverage` if `masking.py` or `router.py` changed · `manage.py makemigrations --check` if a model changed |
   | web | that app's `npm run lint` and `npm run build` |
   | always | `uvx ruff@0.16.7 check . --exclude .venv` · `uvx ruff@0.16.7 format --check . --exclude .venv` |

   If the diff touches the wire schema or both services, run the whole workspace with
   `uv run pytest`. If a schema changed, check the regenerated `generated.ts` files are
   in the diff. If it touches a prompt or retrieval, check whether eval results are
   mentioned. If they aren't, that is a finding. Never start an eval run yourself.
5. **Spot-check the key tests.** For any new safety test, reason about whether it
   would fail if the invariant were broken. If it wouldn't, report it as a
   **[convention]**: "test doesn't guard what its docstring claims."

## Report format

```markdown
## Review: <base>...HEAD (<services touched>)

**Checks:** <per service: pytest pass/fail + counts · mypy clean/n · ruff clean/n · lint/build> · evals <run/not run/n.a.>

### Regression (must fix before merge)
1. [file.py:42](services/...#L42) — <what is wrong>. **Rule:** <checklist item / ADR>. **Fix:** <concrete suggestion>.

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
