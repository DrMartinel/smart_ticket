# CI/CD pipeline — status and next steps

**Last updated:** 2026-09-14
**Branch:** `ci/pipeline` (not pushed) · **Base:** `main` @ `729521e`

Working notes for the CI/CD setup, paused mid-way. Everything below was
verified by running it, except where marked otherwise.

---

## The finding that started this

There is no `.github/` directory in this repo. `infra/ci/eval-gate.yml` is a
complete, well-designed GitHub Actions workflow sitting in a path GitHub
never reads — **CI has never run, once, in this project's history.**

That also explains a bug found earlier: the workflow referenced
`evals/suites/test_build.py`, which does not exist. pytest exits 4 on a
missing path, so that gate step would have failed on its first run. Nothing
ever noticed, because there was no first run.

---

## Decisions taken

| Question | Decision |
|---|---|
| What should "CD" do? | Build the three images and publish to **GHCR** on merge to main. No deploy step — there is no deployment target in the repo (no k8s, Terraform, Helm, or registry config). Rollout stays manual. |
| The known-failing F1 gate | **Leave it blocking.** Main goes red until the `other` category F1 is actually fixed. That is the honest signal — it is a real documented failure, and CLAUDE.md rule 9 forbids lowering a floor to make CI green. |
| Extra coverage | **Ruff lint + format check only.** Frontend build, contract-drift check, and Docker smoke tests were considered and deliberately deferred — see Not doing yet. |

---

## Done and committed on `ci/pipeline`

### `b1e3d52` — ruff config made explicit, 5 findings cleared

`select = ["E4","E7","E9","F"]` is now pinned in `pyproject.toml` rather than
relying on ruff's implicit default.

This matters more than it looks: ruff's default rule set is **not stable
across releases**. The repo is clean under the historical default, but ruff
0.16 widened its own and reports **104 findings on unchanged code**. Without
the pin, a ruff upgrade turns CI red overnight for reasons unrelated to any
commit.

Three of the five findings were mine, introduced during the node-class
refactor: the module-level node instances added to the eval suites were
inserted *mid-import-block*, splitting it and triggering E402. Moved below
the imports. The other two were pre-existing unused imports.

### `651ab71` — `ruff format` across the workspace

66 files, mechanical only, isolated in its own commit so it does not bury
the CI setup. `ruff format` does not rewrap comments, so the prose
explaining spec/ADR reasoning is untouched.

Verified after: ai-engine 94 passed, core-api 67 passed, offline evals 4
passed, `ruff check` clean, and `masking.py` still at its contractual 100%
branch coverage.

---

## Uncommitted in the working tree

Both are written and YAML-validated, but **not committed**.

- `infra/ci/eval-gate.yml` → `.github/workflows/eval-gate.yml`. The working
  tree shows this as a delete plus an untracked `.github/` — re-stage it as a
  rename with `git add -A` so history is preserved. Two edits on top of the move: a header
  note explaining why it moved, and a `push: branches: [main]` trigger
  alongside the existing `pull_request` one — this repo currently merges
  straight to main, so a PR-only trigger would mean the gate still never
  ran.
- `.github/workflows/lint.yml` — new. Runs `ruff check` and
  `ruff format --check`. No services, no DB, no model, so it returns in
  under a minute. Ruff binary pinned to `0.16.7` via `uvx ruff@<version>`;
  `pyproject.toml` pins the rules. **Bump both together, deliberately.**

---

## Next steps, in order

1. **Write `.github/workflows/publish-images.yml`.** Not started. Design
   settled during the session:
   - Trigger: `push: branches: [main]`.
   - Three images — `core-api`, `ai-engine`, `web`. Note the core-api image
     also serves the `worker` and `beat` containers (same image, different
     `command`), so it is three images, not five.
   - Build context is the **repo root** with `dockerfile:
     services/<name>/Dockerfile` — matching `infra/docker-compose.yml`,
     which uses `context: ..`.
   - Tag with the commit SHA **and** `latest`. Push to
     `ghcr.io/drmartinel/smart_ticket/<service>`. GHCR requires a lowercase
     path, so lowercase `github.repository` in a step rather than
     interpolating it raw.
   - Needs `permissions: { contents: read, packages: write }`. The built-in
     `GITHUB_TOKEN` is sufficient — no new secrets.
   - **Open design point:** publishing should not depend on the eval gate,
     because that gate is knowingly red on main (F1). Plan was a lightweight
     `verify` job inside this workflow — ruff + unit tests with a postgres
     service, *not* the F1 eval — that `publish` then `needs`. This
     duplicates the unit-test run in `eval-gate.yml`; that was judged an
     acceptable cost for keeping the two independent. Revisit if it annoys.

2. **Update the stale `infra/ci/eval-gate.yml` references** now that the
   file moved. Already enumerated:
   - `CLAUDE.md:210` (testing conventions)
   - `docs/testing.md:150`
   - `requirement.md:1234` — this is the spec, which describes the *intended*
     path. Probably leave it and let the workflow's own header note explain
     the divergence; decide deliberately rather than by reflex.
   - `CHANGELOG.md:55` refers to it in the past tense, describing where the
     file used to be. Correct as written; leave alone.

3. **Commit, merge to main, push.** Note the push has to go over SSH:
   `origin` is an HTTPS URL with no credentials in this environment, and
   `gh` is not installed. Use
   `git push git@github.com:DrMartinel/smart_ticket.git main`, or fix it
   permanently with
   `git remote set-url origin git@github.com:DrMartinel/smart_ticket.git`.

4. **Expect main to go red on the first run.** That is the agreed outcome,
   not a surprise: `other` category F1 is 0.75 against a 0.85 floor. See
   `docs/TODO.md` §3.

---

## Not doing yet — considered and deferred

- **Frontend build/lint in CI.** `services/web` has `next build` and
  `next lint` and no CI at all. Worth adding; skipped to keep this change
  reviewable.
- **Contract-drift check.** Regenerate `services/web/lib/types/generated.ts`
  via `gen_typescript.py` and fail if it differs from what is committed.
  This would catch the hand-edited-types violation CLAUDE.md rule 4 warns
  about, which currently nothing enforces.
- **Docker build smoke test on PRs.** Largely subsumed by the publish
  workflow once it exists, though that only runs on main.
- **Widening the ruff rule set.** The 104 findings under ruff 0.16's default
  are mostly import ordering (36 × I001) and mutable class defaults
  (20 × RUF012). Fixing them touches core-api broadly, so it is its own
  piece of work, not a rider on CI setup.

---

## Environment notes for whoever picks this up

- **`uv` was not installed** on this machine at the start of the session;
  installed to `~/.local/bin` (v0.12.13). Needs to be on `PATH`. System
  Python is 3.12, below the repo's `>=3.13` — uv provisions its own 3.14, so
  this only matters if you bypass uv.
- **`github.com` was added to `~/.ssh/known_hosts`** to allow a
  non-interactive push. The SSH key authenticates as `DrMartinel`.
- **Two of your containers are stopped**: `sag-api-1` and `sag-web-1`, which
  held ports 8000 and 3000. The smart_ticket stack currently holds them. To
  hand them back:
  `cd infra && docker compose down && docker start sag-api-1 sag-web-1`
- **The live eval suites are not usable as a gate on this hardware.**
  `test_classification` returns near-zero F1 across most categories because
  Ollama inference times out: the eval sends `max_latency_sec: 60` → 30s per
  attempt, and qwen3.5:9b needs more. The circuit breaker then opens and
  poisons the rest of the run. Confirmed **identical on `main`**, by
  rebuilding the ai-engine container from `main` and re-running — this is
  environmental, not a regression. Restart `ai-engine` between long eval runs
  to reset the in-process breaker.
- **6 core-api tests error** when that suite is run standalone
  (`test_incident.py`, `test_process_ticket.py`) — they need DB env the
  whole-workspace run supplies. Pre-existing; same on `main`.
