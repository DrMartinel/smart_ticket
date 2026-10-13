---
name: checklist-add
description: Add a rule to the refactor checklist (.claude/skills/refactor/references/checklist.md), the list /refactor checks every change against. Turns a rule the user states, or a correction they just made, into a numbered item with a severity, how to check it, a real violation and fix from this repo, and its source. Use this whenever the user says "add this to the checklist", "make this a rule", "from now on check that…", "remember this for refactors", or corrects how code was written and wants it enforced in future reviews, even if they don't name the checklist.
argument-hint: <the rule, in your words>
---

# Add a checklist item

The checklist is what `/refactor` holds every change to. An item that is vague,
duplicated or has no example gets applied inconsistently, so each one goes in
with the same five parts. The file is
`.claude/skills/refactor/references/checklist.md`.

## 1. Pin down the rule

Take the rule from the arguments, or from what the user just corrected in the
conversation. If it is ambiguous (what exactly counts as a violation?), ask one
question before writing. Rewrite it as one sentence that a reviewer could answer
pass or fail by reading a diff.

## 2. Check it against what exists

Read the whole checklist, `CLAUDE.md` and
`.claude/skills/refactor/references/readability.md`.

- **Already covered:** tell the user which item covers it, and offer to sharpen
  that item instead of adding a new one.
- **Conflicts** with CLAUDE.md, readability.md or an existing item: show both
  texts and ask which wins. CLAUDE.md's hard rules outrank the checklist, so a
  rule that contradicts one also needs CLAUDE.md changed, which is the user's call.
- **Conflicts with existing code:** grep for it. If current code breaks the new
  rule, say how much and where; the checklist only fails code a diff adds or
  changes, so older code is not blocked, but the user should know.

## 3. Write the item

Use the next free number (`C-NN`), under the section that fits, or a new `##`
section if none does:

```markdown
### C-NN [convention] <the rule as a short title>
- **Check:** <what to look for in the diff, specific enough to answer pass/fail>
- **Violation:** <a real snippet from this repo, or one from the conversation>
- **Fix:** <the same snippet, corrected>
- **Source:** <CLAUDE.md section, ADR, readability.md §, or "this checklist (date)">
```

- **Severity:** `[regression]` only for a hard rule or safety invariant (CLAUDE.md
  hard rules, ADRs, `load-bearing.md`); everything else is `[convention]`.
- **Examples** come from this repo (grep for a real case) or from the
  conversation. A made-up example invites a made-up reading of the rule.
- The item follows the repo's comment rule too: say what to check, not why.

## 4. Decide whether it is also a convention

The checklist enforces rules; CLAUDE.md and readability.md state them. If the
rule is new to both, ask whether to add it there as well (CLAUDE.md for
repo-wide rules, readability.md for code style), and set **Source** to wherever
it lands.

## 5. Show the result

Show the added item and any other file changed. Don't commit unless asked.
