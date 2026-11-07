---
name: create-mr
description: Open a merge request (a GitHub pull request on DrMartinel/smart_ticket) for the current branch, with a description that always has three filled sections - Summary, Rationale and Test plan. Reads the branch's commits and diff, has the mr-reviewer subagent run /code-review plus the repo's own rules (best practice, readability, hard rules, tests, docs), runs the checks the change calls for, drafts the title and body, validates that no section is missing or empty, shows the draft and waits for approval, then pushes and opens the PR with gh. Use this whenever the user says "open an MR", "create a PR", "make a merge request", "ship this branch", "raise a PR for this", or asks for a PR/MR description, even if they don't name the skill.
argument-hint: [base branch, default main] [extra context for the description]
---

# Create a merge request

Arguments: **$ARGUMENTS**. A first word that names a branch is the base; anything
else is context for the description. The base defaults to `main`.

"MR" and "PR" mean the same thing here: the repo is on GitHub
(`DrMartinel/smart_ticket`), so the result is a pull request opened with `gh`.

Every description has exactly these three sections, in this order, each with
real content:

| Section | Answers | Never |
|---|---|---|
| `## Summary` | What changes, as bullets a reviewer can check against the diff | A file-by-file changelog, or restating the title |
| `## Rationale` | Why this change, why this way: the spec, ADR, bug or decision behind it, and the alternative not taken when there was one | "To improve the code"; a why that no reviewer could disagree with |
| `## Test plan` | What was run and what it showed, and what was not run and why | A check claimed but not run; "tests pass" without saying which |

## 1. Check the branch

```bash
git status --short
git branch --show-current
git fetch origin <base>
git log --oneline origin/<base>..HEAD
git diff --stat origin/<base>...HEAD
```

- **On `main`:** stop. Ask the user for a branch name (phase-2 features use
  `f<N>/<slug>`, e.g. `f15/pr2-agent-tiers`) and create it before going on.
- **No commits ahead of the base:** stop and say so.
- **Uncommitted changes:** list them and ask whether they belong in this MR. Never
  commit them without being asked.
- **An open PR for this branch already exists** (`gh pr list --head <branch>`): offer
  to update its description with `gh pr edit` instead of opening a second one.

## 2. Read the change

Read every commit message in full (`git log origin/<base>..HEAD`) and the diff.
Commit bodies carry the why in this repo, so they are the first source for
**Rationale**. Also note:

- ADRs, specs (`docs/requirements/`) and `requirement.md` sections the change
  implements or touches. Link them by repo-relative path.
- Whether the change touches a hard rule in `CLAUDE.md` (router purity,
  `thresholds.yaml`, degrade-to-HITL, the ai-engine wire schema, `proposed_`
  prefixes, ADR-0003/0005/0006, eval floors).
- Whether it **deliberately relaxes a guardrail**. If so, the Rationale says so in
  plain words and links the ADR it argues against (CLAUDE.md, *Before opening a PR*).
- For one PR of a series (F15 is nine), which number it is, what came before and
  what comes next.

## 3. Start the review

Spawn the **`mr-reviewer`** subagent (`.claude/agents/mr-reviewer.md`) in the
background, so it reviews while you run the checks in step 4. Prompt it with the
base, the head branch and what you learnt in step 2 (series position, the spec
or ADR the change implements). It runs `/code-review high` on the diff, then
checks the repo's own rules: CLAUDE.md's hard rules and *Where logic goes*, the
refactor checklist, readability, load-bearing code, comments, tests and docs,
and `/ai-engine-review` when ai-engine is touched.

If `mr-reviewer` isn't listed as an agent type (agents load at session start, so
a session older than the file won't have it), spawn `general-purpose` with:
"Read `.claude/agents/mr-reviewer.md` and follow it for base `<base>`, head
`<branch>`. <context>".

## 4. Run the checks

Run what the changed paths call for, from CLAUDE.md's *Commands*, and keep the
real output for the Test plan:

| Changed | Run |
|---|---|
| `services/core-api/` | `cd services/core-api && make check` (and `make coverage` if `masking.py` or `router.py` changed) |
| `services/ai-engine/` | `uv run pytest services/ai-engine/tests -q`, `uv run mypy` |
| A core-api schema on the wire or in the API | `make types`, then check the regenerated TS files are committed |
| `services/admin-console/` or `services/chat/` | that app's `npm run lint` and `npm run build` (or what its `package.json` defines) |
| Only docs or skills | nothing to run; say so |

**Never start an eval run or a live probe unless the user asked for one.** If a
prompt, retrieval or routing change needs evals, the Test plan says that evals
were not run and that they are needed before merge.

If a check fails, stop and show the output. Don't open the MR on a red run unless
the user says to, and then the Test plan states the failure.

Also walk CLAUDE.md's *Before opening a PR* checklist and note any item that
doesn't hold.

## 5. Act on the review

Wait for the reviewer's report (you're notified when it finishes; don't poll),
then show the user its findings, ranked as it gave them.

- **Blocking:** stop. Ask whether to fix each one now or open the MR anyway.
  Only a clear "open it anyway" lets a blocking finding through, and then the
  Test plan names it.
- **Should fix and Nit:** list them and ask which to fix. Don't fix any
  unasked.
- Make the fixes the user picks as **new commits** on the branch (never amend
  pushed commits), then re-run the step 4 checks for the paths you touched. If
  a fix was more than trivial, re-run the reviewer on the new diff.

The reviewer's closing `Review: …` line, updated for what was fixed, goes in
the Test plan.

## 6. Draft the title and body

**Title:** the repo's commit style, under 72 characters:
`feat(f15): an agent tier on every route`, `fix(incidents): …`, `docs(…): …`.
For one PR of a series: `F15 PR 2: an agent tier on every route`.

Write the body to the scratchpad as `mr-body.md`:

```markdown
<optional one-line lead: series position, spec and ADR links>

## Summary
- <what changes, one bullet per reviewable unit>

## Rationale
<why this change and why this way; links to the ADR/spec/issue; the alternative
not taken; any guardrail deliberately relaxed, named as such>

## Test plan
- <command> → <result, with counts: "1,470 passed", "clean">
- <new tests: file, what failure each one prevents>
- Review: /code-review high + repo rules — <n> blocking, <n> should fix, <n> nits; <what was fixed, what was accepted and why>
- <what was not run, and why> (e.g. "No eval run; triage is untouched.")
- [ ] <anything the reviewer must still do by hand>

🤖 Generated with [Claude Code](https://claude.com/claude-code)
```

Write it the way the docs here are written: plain sentences, concrete names,
numbers from the actual run. Keep it short; a reviewer reads the diff too.

Then validate it. All three headings must exist, in order, each followed by
non-empty text before the next heading:

```bash
python3 - "<scratchpad>/mr-body.md" <<'EOF'
import re, sys
body = open(sys.argv[1]).read()
want = ["Summary", "Rationale", "Test plan"]
found = re.findall(r"^## (.+?)\s*$", body, re.M)
assert [h for h in found if h in want] == want, f"sections out of order or missing: {found}"
for name in want:
    text = re.search(rf"^## {name}\s*$(.*?)(?=^## |\Z)", body, re.M | re.S).group(1)
    text = text.replace("🤖 Generated with [Claude Code](https://claude.com/claude-code)", "")
    assert re.sub(r"<[^>]*>|\s|-|\[ \]", "", text), f"{name} is empty or still a placeholder"
print("ok")
EOF
```

Fix and re-run until it prints `ok`.

## 7. Show it and wait

Show the user the title, the base and head branches, the commits going in, any
review findings left open, and the full body. Pushing and opening a PR are outward-facing: **wait for a clear yes**.
Apply any edits they ask for and re-validate.

## 8. Push and open

```bash
git push -u origin <branch>
gh pr create --base <base> --head <branch> --title "<title>" --body-file "<scratchpad>/mr-body.md"
```

Add `--draft` only if the user asked for a draft. Then call the ccd_pr
`get_status` tool and, if it doesn't report this PR, `bind_pr` it. Never enable
auto-merge unless asked.

Report the PR link (`https://github.com/DrMartinel/smart_ticket/pull/<n>`) and
anything left open: failed or skipped checks, review findings accepted unfixed, evals still needed, unchecked items
in the Test plan.
