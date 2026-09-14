# Changelog

Notable changes to Smart Ticket Triage.

Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).
The project is pre-release and unversioned — no tags exist yet, and every
package declares `0.1.0`. Sections below are grouped by the change set that
landed, newest first.

Behaviour changes are called out explicitly, because this system's
correctness is mostly about what it does when things go wrong: a change
that moves a failure path is more significant here than a new feature.

## [Unreleased]

### Added

- **CI/CD actually runs now.** There was no `.github/` directory, so
  `infra/ci/eval-gate.yml` — a complete, well-designed workflow — had sat in
  a path GitHub never reads for the project's entire history. Moved to
  `.github/workflows/eval-gate.yml` and given a `push: branches: [main]`
  trigger alongside the existing `pull_request` one, since this repo
  currently merges straight to main.
- `.github/workflows/lint.yml` — `ruff check` and `ruff format --check`,
  with no services attached so it returns in under a minute.
- `.github/workflows/publish-images.yml` — builds the three container
  images and pushes them to GHCR on merge to main, tagged with the commit
  SHA and `latest`. Three images rather than five: `core-api`, `worker` and
  `beat` share one image and differ only by `command`. No deploy step —
  there is no deployment target in the repo, so this produces artifacts and
  leaves rollout manual. It runs its own unit-test job instead of chaining
  behind the eval gate, which is knowingly red on the `other` F1 and would
  otherwise block publishing forever.

### Changed

- Ruff's rule selection is now pinned explicitly in `pyproject.toml`
  (`select = ["E4","E7","E9","F"]`) and the binary pinned in the workflows.
  Ruff's implicit default is not stable across releases: this repo is clean
  under the historical one, but ruff 0.16 reports 104 findings on unchanged
  code. Without the pin a ruff upgrade turns CI red overnight. Bump the two
  pins together.
- `ruff format` applied across the workspace (66 files, mechanical only).
  Comments are not rewrapped, so the prose explaining spec/ADR reasoning is
  untouched.

- **Graph nodes are now classes.** All seven nodes in
  `services/ai-engine/src/ai_engine/graph/nodes/` take their collaborators
  and configuration through `__init__` instead of reaching for module
  globals and re-reading `settings.*` on every call. `graph/build.py` is
  now the only place nodes are constructed and wired, via a `GraphDeps`
  dataclass. `build_graph()` remains callable with no arguments, so
  `main.py` is unchanged.
- **Providers sit behind Protocols.** `providers/protocols.py` defines the
  four seams between a node and the outside world — `Embedder`,
  `Reranker`, `LLMClient`, `ConnectionSource` — with class implementations
  behind each. Nodes depend on the Protocol, never on a concrete provider
  module, which is what makes them testable with no database, no Ollama
  and no model download.
- **Provider selection happens once, at startup.** `providers/factory.py`
  is the single place `EMBEDDING_PROVIDER` and `RERANKER_PROVIDER` are
  read.
- The cross-encoder's first model load is serialized behind a lock.
  `analyze` is a sync `def`, so FastAPI serves concurrent requests from a
  threadpool against one shared instance; previously each racing cold
  request built its own multi-GB model. The lock is not held across
  `predict()`. Peak RAM under a cold-start stampede goes from N× to 1×;
  the failure signature changes from OOM to a slow first batch.

### Fixed

- **`settings.prompt_version` is now honored.** `infer.py` read
  `classify.v3.md` by a hardcoded filename at import time, so bumping the
  setting changed what logs and responses *claimed* had run without
  changing what actually ran. Prompts now resolve through
  `llm/prompt_store.load_system_prompt()`. Resolves to the same file
  today, so no output changes.
- **An unknown provider selector is now fatal at startup** instead of
  falling through silently. A typo'd `RERANKER_PROVIDER` used to degrade
  to the lexical reranker, whose scores are a different calibration from
  the cross-encoder distribution `retrieval.floor` is fitted against
  (ADR-0005) — the refuse-before-LLM rate would be wrong and nothing would
  look broken.
- **The offline eval gate had never run.** `infra/ci/eval-gate.yml`
  listed `evals/suites/test_build.py`, which does not exist; pytest exits
  4 on a missing path. Graph-structure tests live in
  `services/ai-engine/tests/test_build.py` and run in the ai-engine step.
- A missing prompt file now fails in `build_graph()` rather than at
  `import ai_engine.graph.nodes.infer`. Still at boot; test collection no
  longer touches the filesystem.
- `load_system_prompt` rejects path separators, so if per-request prompt
  selection ever lands it cannot become an arbitrary file read.

### Added

- Four values that were hardcoded became configuration:
  `fusion_candidate_limit` (was `candidates[:10]`),
  `quote_fuzzy_threshold` (was `FUZZY_THRESHOLD = 0.95`), and
  `reranker_model` in `Settings`; the injection pattern set and negation
  lexicon became constructor parameters with module-level defaults. The
  latter two stay in code rather than `Settings` — they are linguistic
  data, like `patterns.py` holds the PII regexes, not tunable numbers.
- ai-engine unit tests went from 38 to 94, covering failure paths that
  were previously unreachable without live infrastructure: a DB outage
  during the KB-policy lookup degrading to deny-by-default, an embedder
  outage propagating rather than looking like an empty KB, circuit-open
  and all-providers-down mapping to their exact reason codes, and every
  budget-exhausted path spending nothing. `tests/conftest.py` provides a
  fake per Protocol.
- A test pinning ADR-0005: rerank output order follows the cross-encoder
  score, not the RRF order the candidates arrived in. This invariant had
  no test and does not fail loudly when broken.

### Removed

- The `embed_text`, `rerank`, `get_connection` and `chat_complete`
  module-level functions in ai-engine, now that every caller receives its
  collaborator through a constructor. core-api's own `embed_text` is a
  separate module, duplicated deliberately per ADR-0004, and is untouched.
- `services/ai-engine/tests/__init__.py`. With it present, ai-engine's and
  core-api's `conftest.py` both resolved to the module name
  `tests.conftest` and a whole-workspace `pytest` run died at collection.
  See the note in `pyproject.toml` — do not add it back.

### Known issues

- `other` category F1 is 0.75 against a 0.85 floor (precision 1.00, recall
  0.60). Real and documented in `evals/baselines/baseline.json`; see
  `docs/TODO.md` §3.
- `AIRunRequest.prompt_version` is echoed back in `AIRunResponse` while the
  graph runs whatever `settings.prompt_version` resolves to, so the
  response asserts a version that did not run. Corrupts audit trail and
  eval attribution. `docs/TODO.md` §6a.
- Trust-score coefficients are a hand-set prior, not fitted. `t_auto` and
  `t_route` are placeholders pending ≥500 shadow pairs.

## Earlier

Reconstructed from commit history; this file did not exist at the time.

### Fixed

- The local-LLM path made reliable, and three signal bugs corrected
  (`a82c13a`). Includes diacritic folding in the lexical reranker, without
  which an unaccented Vietnamese ticket scored ~0.04 against an accented KB
  article instead of ~0.75 — far below `retrieval.floor`, sending every
  such ticket to a human as "nothing in the KB matches".

### Added

- Fallback mechanism for embedding outages (`16e9abd`).
- Project README, architecture overview, and an onboarding reading path
  (`065caa5`, `ada67a7`).
