---
name: create-mr
description: Open a merge request (a GitHub pull request on DrMartinel/smart_ticket) for the current branch, with a description of exactly two filled sections that summarise the code - Summary (what the code now does, component by component, naming the routes, services, models, graph nodes and pages it changes) and Rationale (why the code is shaped this way - the spec or ADR behind it, the design choices a reviewer would question and the implementation not taken). Reads the branch's commits and diff, has the mr-reviewer subagent run /code-review plus the repo's own rules (best practice, readability, hard rules, tests, docs), runs the checks the change calls for and reports them to the user, drafts the title and body, validates that both sections are there and name the code, shows the draft and waits for approval, then pushes and opens the PR with gh. Use this whenever the user says "open an MR", "create a PR", "make a merge request", "ship this branch", "raise a PR for this", or asks for a PR/MR description, even if they don't name the skill.
argument-hint: [base branch, default main] [extra context for the description]
---

# Create a merge request

Arguments: **$ARGUMENTS**. A first word that names a branch is the base; anything
else is context for the description. The base defaults to `main`.

"MR" and "PR" mean the same thing here: the repo is on GitHub
(`DrMartinel/smart_ticket`), so the result is a pull request opened with `gh`.

Every description has exactly these two sections, in this order, each with
real content about the code:

| Section | Answers | Never |
|---|---|---|
| `## Summary` | What the code now does, one bullet per component (route, service, model, migration, graph node, prompt, page), each naming the code in backticks (`Class.method`, the route, the table, the node) and the behaviour it has now; mechanical files in one closing bullet | A file-by-file changelog or `git diff --stat` in prose; restating the title; check results or review findings |
| `## Rationale` | Why the code is shaped this way: the spec, ADR, bug or decision behind it, then each choice in the diff a reviewer would question (the layer it sits in, the data it stores, the failure path and its `ReasonCode`, a schema changed in both services) with its reason, and the implementation not taken | "To improve the code"; a why no reviewer could disagree with; a business case that never mentions the code |

The checks and the review gate the MR but stay out of the body: their results
go to the user at step 7 and in the step 8 report. The one exception is the
**Before merge** line (step 6).

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
- For **Summary**: where the behaviour starts (a route, a service method, a graph
  node, a page) and what it calls from there; each component the diff adds or
  changes and what it now does, including what a reader can't see from one
  hunk (new tables and columns, `ReasonCode` values, permissions and agent
  tiers, settings, thresholds, wire fields); and which files are mechanical
  (regenerated TS types, migrations Django wrote, renames, fixtures, docs).
- For **Rationale**: each choice in the code a reviewer could question: why it
  sits in this layer (`where-logic-goes.md`), why load-bearing code
  (`load-bearing.md`) was touched or left alone, why a failure ends at this
  `ReasonCode`, and what the code would have looked like the other way.

## 3. Start the review

Spawn the **`mr-reviewer`** subagent (`.claude/agents/mr-reviewer.md`) in the
background, so it reviews while you run the checks in step 4. Prompt it with the
base, the head branch and what you learnt in step 2 (series position, the spec
or ADR the change implements). It runs `/code-review high` on the diff, then
checks the repo's own rules: CLAUDE.md's hard rules, `where-logic-goes.md`, the
refactor checklist, readability, load-bearing code, comments, tests and docs,
and `/review` for each service the diff touches.

If `mr-reviewer` isn't listed as an agent type (agents load at session start, so
a session older than the file won't have it), spawn `general-purpose` with:
"Read `.claude/agents/mr-reviewer.md` and follow it for base `<base>`, head
`<branch>`. <context>".

## 4. Run the checks

Run what the changed paths call for, from CLAUDE.md's *Commands*, and keep the
real output (command, result, counts) to show the user in step 7:

| Changed | Run |
|---|---|
| `services/core-api/` | `cd services/core-api && make check` (and `make coverage` if `masking.py` or `router.py` changed) |
| `services/ai-engine/` | `uv run pytest services/ai-engine/tests -q`, `uv run mypy` |
| A core-api schema on the wire or in the API | `make types`, then check the regenerated TS files are committed |
| `services/admin-console/` or `services/chat/` | that app's `npm run lint` and `npm run build` (or what its `package.json` defines) |
| Only docs or skills | nothing to run; say so |

**Never start an eval run or a live probe unless the user asked for one.** If a
prompt, retrieval or routing change needs evals, tell the user they were not
run and are needed before merge; the **Before merge** line says so too.

If a check fails, stop and show the output. Don't open the MR on a red run unless
the user says to, and then the **Before merge** line names the failure.

Also walk CLAUDE.md's *Before opening a PR* checklist and note any item that
doesn't hold.

## 5. Act on the review

Wait for the reviewer's report (you're notified when it finishes; don't poll),
then show the user its findings, ranked as it gave them.

- **Blocking:** stop. Ask whether to fix each one now or open the MR anyway.
  Only a clear "open it anyway" lets a blocking finding through, and then the
  **Before merge** line names it.
- **Should fix and Nit:** list them and ask which to fix. Don't fix any
  unasked.
- Make the fixes the user picks as **new commits** on the branch (never amend
  pushed commits), then re-run the step 4 checks for the paths you touched. If
  a fix was more than trivial, re-run the reviewer on the new diff. A fix that
  changes what the code does changes the Summary too.

Keep the reviewer's closing `Review: …` line, updated for what was fixed, for
step 7.

## 6. Draft the title and body

**Title:** the repo's commit style, under 72 characters:
`feat(f15): an agent tier on every route`, `fix(incidents): …`, `docs(…): …`.
For one PR of a series: `F15 PR 2: an agent tier on every route`.

Write the body to the scratchpad as `mr-body.md`:

```markdown
<optional one-line lead: series position, spec and ADR links>

**Before merge:** <only when one holds: a check that fails, a blocking finding accepted unfixed, evals not yet run>

## Summary
- **<component>** (<the route, `Class.method`, table or node, in backticks>): <what the code now does>
- **Mechanical:** <regenerated `generated.ts`, migrations Django wrote, renames>

## Rationale
<why the code is shaped this way, linking the ADR/spec/issue in a sentence;
then each choice in the diff a reviewer would question, with its reason; the
implementation not taken; any guardrail deliberately relaxed, named as such>

🤖 Generated with [Claude Code](https://claude.com/claude-code)
```

Write it the way the docs here are written: plain sentences, concrete names.
Keep it short; a reviewer reads the diff too.

**Summary** reads as a map of the code: start where the behaviour starts and
follow what it calls, so a reviewer can hold each bullet against the diff. One
bullet per component, not per file. A one-file change gets one or two bullets;
leave out the Mechanical bullet when nothing is mechanical.

**Rationale** explains the code, not the feature's business case: the spec or
ADR gets a link and a sentence, and the rest goes to the choices in this diff.
Take the reasons from the commit bodies, ADRs and specs; when the why of a
choice is in none of them, ask the user rather than invent one.

Leave out the **Before merge** line when none of its cases holds.

Then validate it. The body has exactly the two headings, in order, no
placeholder left, neither section empty, and the Summary names code:

```bash
python3 - "<scratchpad>/mr-body.md" <<'EOF'
import re, sys
body = open(sys.argv[1]).read()
body = body.replace("🤖 Generated with [Claude Code](https://claude.com/claude-code)", "")
prose = re.sub(r"```.*?```", "", body, flags=re.S)
want = ["Summary", "Rationale"]
found = re.findall(r"^## (.+?)\s*$", prose, re.M)
assert found == want, f"want exactly the sections {want}, found {found}"
left = re.findall(r"<[^>\n]+>", re.sub(r"`[^`\n]*`", "", prose))
assert not left, f"placeholders left: {left}"
part = dict(re.findall(r"^## (\w+)\s*$(.*?)(?=^## |\Z)", prose, re.M | re.S))
for name in want:
    assert re.sub(r"[\W_]", "", part[name]), f"{name} is empty"
assert "`" in part["Summary"], "Summary names no code: put each route, class, table or file in backticks"
print("ok")
EOF
```

Fix and re-run until it prints `ok`.

## 7. Show it and wait

Show the user the title, the base and head branches, the commits going in, the
check results from step 4, the `Review: …` line and any findings left open, and
the full body. Pushing and opening a PR are outward-facing: **wait for a clear
yes**. Apply any edits they ask for and re-validate.

## 8. Push and open

```bash
git push -u origin <branch>
gh pr create --base <base> --head <branch> --title "<title>" --body-file "<scratchpad>/mr-body.md"
```

Add `--draft` only if the user asked for a draft. Then call the ccd_pr
`get_status` tool and, if it doesn't report this PR, `bind_pr` it. Never enable
auto-merge unless asked.

Report the PR link (`https://github.com/DrMartinel/smart_ticket/pull/<n>`) and
anything left open: failed or skipped checks, review findings accepted unfixed,
and evals still needed.
