# Recipe: add or change a provider

A provider is anything outside the process that a node relies on: a model server,
an embeddings endpoint, a reranker. The pattern exists so that a bad configuration
fails at boot, a provider outage looks like an outage rather than an empty result,
and tests can swap the provider without mocks.

Open these before writing: `graph/nodes/candidate_pool/shortlister.py` (the full pattern: ABC, real
implementation, offline implementation, import-time selection),
`core/providers/embeddings.py`, `core/providers/clients.py`, `core/config.py`,
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

## 2. The client owns the protocol, and the provider owns the task

- **The client** (`core/providers/clients.py`) knows its server's endpoints: it
  builds each request and **validates** each reply against a Pydantic DTO in `dtos.py`,
  plus the checks the protocol implies (rerank index coverage, Jev's pinned model).
  Anything wrong raises `ValueError` with the reply included, except where the
  reply is PII (`complete_json`, which raises with no reply and no chained cause).
  A new vLLM endpoint is a method on `VLLMClient`; a new server is a new instance
  at the bottom of the module, plus `<x>_base_url` and `<x>_model` in `Settings`.
  A hosted API gets its own `HttpClient` subclass, like `JevClient` (`api_key=`
  goes as a bearer token).
- **The provider** calls one client method and applies the task's rules: the
  vector width (`LexicalEmbedder.embed`), PII-safe errors and the fallback unwrap
  (`VllmPiiDetector.detect`), which answer to read (`JevReranker`).
- No retries anywhere, SDK ones included (`max_retries=0`). Use the separate
  connect and read timeouts from `_split_timeout`.
- Mark it stateless in the docstring (`Stateless.`). Instances are shared across
  threads.

## 3. An offline implementation for CI

It is deterministic, talks to no server, and says in its docstring what it is
**not**: not a measure of quality, and not the same calibration. See
`LexicalShortlister` and `StubEmbedder`.

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

Construction **opens no socket**, so importing `graph/triage.py` must work with no
server running. Put any lazy HTTP client behind `cached_property`, the way
`HttpClient._http` does.

## 5. Config and infra

- In `Settings`, add `<thing>_provider` and any URL or model fields, typed and with
  no default.
- In the root `.env.example`'s ai-engine section (the template `.env` is copied
  from), add each in UPPER_CASE with its value and a comment listing the values
  and what each is for. Add it to your own `.env` too.
- In `docker-compose.yml`, add it to ai-engine's `environment:` allowlist as
  `${NAME:?see .env.example}` (`${NAME:-}` if optional), or set the
  container-side value if it differs from the host's.
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
Give the class its own `scorer` (a new `RerankScorer` value in both services'
wire schema), so only a floor set for it ever applies, and state that in the
class docstring. Don't let the offline variant be selected by
default (ADR-0005).

## Done when

- [ ] The ABC contract is documented, including the failure contract.
- [ ] The real implementation validates the reply, and the offline one is deterministic.
- [ ] An unknown value raises at import, and construction opens no socket.
- [ ] Settings, `.env.example` and compose are updated.
- [ ] The fake and the `fake_*`, `use_*` and `reload_*` fixtures are added, and the selection and parsing tests pass.
