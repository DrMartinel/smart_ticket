# Recipe: change a prompt

Prompts are versioned and eval-gated like code (spec §12.3). A prompt change can
move classification F1, refusal rate and auto-reply precision without any unit test
noticing. The eval gate is the test that catches it.

Open these before writing: the current prompt in `core/prompts/` (the file
`settings.prompt_version` points at), `core/prompts/__init__.py`, `core/config.py`,
and the wire schema in both services: `core/state.py` here and
`services/core-api/infrastructure/dtos.py`.

## Steps

1. **Don't edit a shipped version.** Copy `<name>.v<N>.md` to `<name>.v<N+1>.md` and
   edit the copy. Old versions stay, because `ai_runs.prompt_version` records which
   one produced each proposal.
2. **Bump both version pointers** so they stay equal:
   - `prompt_version` in `services/ai-engine/src/ai_engine/core/config.py`, which is
     the prompt that **runs**;
   - the `AIRunRequest.prompt_version` default, which is what core-api sends. It
     is defined in both services (`core/state.py` and core-api's
     `infrastructure/dtos.py`); change both.

   ⚠️ `main.py` reports `req.prompt_version` in the response, but `InferNode` loads
   `settings.prompt_version`. If the two differ, `ai_runs` records the wrong prompt.
   Keeping them equal is currently the only guard.
3. **Keep the prompt within its authority.** A prompt may ask for a proposal. It
   can't grant permission for anything: auto-reply authority lives on
   `kb_articles.auto_reply_allowed`, and thresholds live in `thresholds.yaml`
   (CLAUDE.md "Where to make a change"). Don't tell the model it "may auto-reply".
4. **Keep the output schema.** The reply must parse as `LLMProposalEnvelope`, with
   `proposed_*` fields. `AutoReplyProposal` has to echo a `kb_slug` it was actually
   shown and a `verbatim_quote` taken from the shown chunks. The validator checks
   both.
5. **Check the wiring:**
   `tests/test_build.py::test_main_wires_the_prompt_for_settings_prompt_version`
   proves the new file is the one that runs. Then run
   `uv run pytest services/ai-engine/tests -q`.
6. **Run the evals** against a live stack. The suites that need ai-engine skip
   themselves if it isn't running, and a skip is not a pass:
   ```bash
   uv run pytest evals/suites -q
   ```
   Explain every metric that moved, in both directions. Per-category F1 is never
   averaged. Never lower a floor. Updating `evals/baselines/baseline.json` needs a
   reviewer other than the author (CLAUDE.md rule 9).
7. **Commit** as `feat(prompts): <name>.v<N+1> — <what changed>`. In the body, say
   what changed and why, and include the eval deltas. See c7f4872 for the precedent.

## Done when

- [ ] A new version file exists and the old one is untouched.
- [ ] `settings.prompt_version` and the `AIRunRequest` default are equal and bumped.
- [ ] The output still parses into `LLMProposalEnvelope`, and no authority is granted in the prompt text.
- [ ] Evals were run on a live stack and the deltas are explained.
