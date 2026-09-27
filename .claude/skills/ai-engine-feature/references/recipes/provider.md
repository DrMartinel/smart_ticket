# Recipe: add or change a provider

A provider is anything outside the process that a node relies on: a model server,
an embeddings endpoint, a reranker. The pattern exists so that a bad configuration
fails at boot, a provider outage looks like an outage rather than an empty result,
and tests can swap the provider without mocks.

Open these before writing: `core/providers/reranker.py` (the full pattern: ABC, real
implementation, offline implementation, import-time selection),
`core/providers/embeddings.py`, `core/providers/llm/models.py`, `core/config.py`,
`tests/conftest.py` and `tests/test_provider_selection.py`.

## 1. The seam: an ABC in the provider module

```python
class <Thing>(ABC):
    """What the <consumer> node depends on."""

    @abstractmethod
    def <verb>(self, …) -> <T>:
        """<Contract, including shape and order.> Raises on provider failure —
        never <an empty/zero result>, which would read as <legitimate outcome>
        instead of <outage>."""
```

Only add an ABC if you will have **two implementations**: a real one and an offline
or fake one.

## 2. The real implementation owns the task, and the client owns transport

- The implementation builds the request, parses the reply, and **validates** it:
  shape, count, dimensions, index coverage. Anything wrong raises `ValueError` with
  the reply included (`_scores_in_input_order`, `LexicalEmbedder.embed`).
- Transport goes through a `VLLMLLM(...).request(path, payload)` client, built once
  at the bottom of `core/providers/llm/models.py` next to `embed` and `rerank`.
  A new server gets its own client instance plus `<x>_base_url` and `<x>_model`
  fields in `Settings`.
- No retries anywhere, SDK ones included (`max_retries=0`). Use the separate
  connect and read timeouts from `_split_timeout`.
- Mark it stateless in the docstring (`Stateless.`). Instances are shared across
  threads.

## 3. An offline implementation for CI

It is deterministic, talks to no server, and says in its docstring what it is
**not**: not a measure of quality, and not the same calibration. See
`LexicalReranker` and `StubEmbedder`.

## 4. Selection at import time: fatal on an unknown value

```python
# --- The <thing>, selected once when this module is imported ----------------
# An unknown value is fatal here, at boot: <what a silent fallback would get wrong>.

match settings.<thing>_provider:
    case "<offline>":
        <thing> = <Offline>()
    case "vllm":
        <thing> = <Real>()
    case other:
        raise ValueError(f"unknown <thing>_provider: {other!r} (expected 'vllm' or '<offline>')")
```

Construction **opens no socket**, so importing `graph/build.py` must work with no
server running. Put any lazy HTTP client behind `cached_property`, the way
`VLLMLLM._http` does.

## 5. Config and infra

- In `Settings`, add `<thing>_provider` with a comment listing its values and what
  each is for, plus any URL or model fields.
- In `infra/.env.example` and `infra/docker-compose.yml`, add the env vars with the
  same names in UPPER_CASE.
- If core-api embeds or scores the same way (core-api embeds tickets itself), the two
  services have to be kept on the same model **by config**, because they never share
  code (ADR-0004). Say so in a comment.

## 6. Tests

In `tests/conftest.py`:
- `class Fake<Thing>(<Thing>)` records `calls`, and takes `error=` to raise.
- The `fake_<thing>` fixture returns the class.
- The `use_<thing>` fixture patches **every** node module that imports the singleton.
- The `reload_<thing>` fixture calls `_reloader(<module>)`.

In `tests/test_provider_selection.py`:
- An unknown provider value raises.
- The declared default is pinned through `Settings.model_fields["…"].default`, not the
  instance, because CI env vars can override the instance.
- Each value selects the right class. Compare against the **reloaded** module's
  classes.
- Building the provider opens no connections.

For reply parsing, in `tests/test_providers.py`:
- A malformed, short, reordered or duplicated reply raises.
- A good reply parses into the contracted shape and order.

## 7. Calibration warning

If the provider's output is compared against any threshold, for example a reranker
score against `retrieval_floor`, then swapping providers changes the calibration.
State that in the class docstring. Don't let the offline variant be selected by
default (ADR-0005).

## Done when

- [ ] The ABC contract is documented, including the failure contract.
- [ ] The real implementation validates the reply, and the offline one is deterministic.
- [ ] An unknown value raises at import, and construction opens no socket.
- [ ] Settings, `.env.example` and compose are updated.
- [ ] The fake and the `fake_*`, `use_*` and `reload_*` fixtures are added, and the selection and parsing tests pass.
