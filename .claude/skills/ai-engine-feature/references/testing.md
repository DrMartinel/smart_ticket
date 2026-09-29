# ai-engine test mechanics

General test philosophy is in `.claude/skills/refactor/references/readability.md` §12:
failure paths first, docstrings that name the failure mode, pin the invariant,
mutation-check. This file covers how to do that **in `services/ai-engine/tests`**.

```bash
uv run pytest services/ai-engine/tests -q
uv run pytest services/ai-engine/tests/test_<module>.py -q -k <name>
```

## The toolkit (`tests/conftest.py`)

Read `conftest.py` before writing tests. It is short and its docstrings explain each
piece.

| Fixture | Gives you | Use it for |
|---|---|---|
| `make_state(**overrides)` | a valid `TriageState` | override only the fields the test is about |
| `make_ticket(subject, body)` | a `TicketMasked` | tests about what text reaches a provider |
| `make_candidate(chunk_id, content, slug)` | a `Candidate` | rerank input |
| `kb_row(chunk_id, content, score, slug)` | a row shaped like BM25/vector SELECTs | canned DB rows |
| `fake_db` | the `FakeSessionSource` class: `(rows=… or callable(sql, params), error=…)` | DB answers and DB outages |
| `fake_embedder` | the `FakeEmbedder` class: `(vector=…, error=…)` | embedder answers and outages |
| `fake_reranker` | the `FakeReranker` class: `(scores=…, error=…)` | reranker ordering and outages |
| `fake_llm` | the `FakeLLM` class: `(result=LLMResult, error=…)` | LLM answers, `AllLLMDownError` |
| `use_db`, `use_embedder`, `use_reranker`, `use_llm` | a function that installs a fake and returns it | swapping the provider singletons |
| `reload_models`, `reload_embeddings`, `reload_reranker` | a function that re-runs a module's import-time wiring | provider-selection tests |

Rules that follow from how the suite is set up:

- **Use these as fixtures, never `from conftest import …`.** The root `pyproject.toml`
  runs pytest with `--import-mode=importlib`, because core-api also has a `tests`
  package. Under that mode conftest can't be imported. For the same reason there is
  **no** `tests/__init__.py`. Don't add one.
- **Plain fakes, not `unittest.mock`.** Each fake records what it was asked
  (`embedder.calls`, `reranker.calls`, `llm.prompts`, `db.sessions[i].executed`,
  `db.events`). Assert on those records: `reranker.calls == []` proves the node made
  no round-trip.
- **A new provider seam gets a new fake**, a `fake_x` fixture, a `use_x` fixture
  listing every module that reads it, and a `reload_x` fixture if it has import-time
  selection.
- **Tunables:** `monkeypatch.setattr(settings, "rerank_top_n", 2)`. Never edit
  `Settings` defaults in a test.
- `_FakeSession.execute` compiles each statement with the Postgres dialect. A query
  SQLAlchemy can't compile therefore fails in the unit test, and a
  `rows=callable(sql, params)` can answer the BM25 query and the vector query
  differently.
- Tests are type-checked by mypy (`check_untyped_defs`). Annotate helpers and return types
  where it's cheap, but don't annotate every fixture parameter.

## Which file

- A node's behaviour goes in `tests/test_<node module>.py`, for example `test_rerank.py`.
- A node's `decide()` and the production topology go in `tests/test_build.py`. That
  file holds `decide()` tests, **literal** node-name and edge sets, and
  `test_safety_critical_routes`.
- Builder rules go in `tests/test_compiler.py`, which uses throwaway nodes and never
  the production graph.
- LangGraph and pydantic state behaviour goes in `tests/test_state.py`.
- Provider selection and startup behaviour goes in `tests/test_provider_selection.py`.
- Reply parsing for a provider goes in `tests/test_providers.py` or `tests/test_llm_client.py`.
- The read-only DB boundary goes in `tests/test_db_tables.py` and `tests/test_db_queries.py`.

## Template: a node test file

```python
"""
<Node>-node tests. <What this node owns, and what goes wrong downstream if it is
wrong. Name the reason code or safety property involved.>
"""

from __future__ import annotations

import pytest

from ai_engine.core.config import settings
from ai_engine.graph.nodes.<module> import <Name>Node


@pytest.fixture
def make_node(use_db, use_embedder):
    """Install the fakes this node reads, then build it."""

    def make(db, embedder):
        use_db(db)
        use_embedder(embedder)
        return <Name>Node()

    return make


# --- failure paths first ------------------------------------------------------


def test_<dependency>_failure_propagates_rather_than_<safe_looking_result>(
    fake_db, fake_embedder, make_state, make_node
):
    """<The infra failure must not become an ordinary-looking result, because
    <result> routes as <X> under reason <Y>, hiding an outage.>"""

    node = make_node(fake_db(), fake_embedder(error=RuntimeError("down")))

    with pytest.raises(RuntimeError, match="down"):
        node(make_state())


def test_<empty_input>_makes_no_provider_call(fake_db, fake_embedder, make_state, make_node):
    """<Why spending a round-trip here is wrong.>"""

    embedder = fake_embedder()
    node = make_node(fake_db(), embedder)

    node(make_state(<field>=[]))

    assert embedder.calls == []


# --- behaviour ------------------------------------------------------------------


def test_only_masked_text_reaches_the_provider(
    fake_db, fake_embedder, make_state, make_ticket, make_node
):
    """Only masked text may cross into ai-engine's providers."""

    embedder = fake_embedder()
    node = make_node(fake_db(), embedder)

    node(make_state(ticket=make_ticket("subj", "body")))

    assert embedder.calls == ["subj\nbody"]


def test_<limit>_uses_the_configured_setting(fake_db, fake_embedder, make_state, monkeypatch, make_node):
    monkeypatch.setattr(settings, "<setting>", 2)
    ...
```

And in `tests/test_build.py`, for a branching node:

```python
def test_<condition>_decides_<outcome>(make_state):
    state = make_state(<field>=<value>)
    assert <Name>Node().decide(state) is <Name>Outcome.<MEMBER>
```

Then add the node name to both literal sets in
`test_graph_has_exactly_the_expected_nodes`, and its edges to
`test_compiled_edges_are_exactly_the_triage_topology`. If a route carries a safety
guarantee, assert it in `test_safety_critical_routes`.

## Template: provider selection

```python
def test_unknown_<x>_provider_raises(monkeypatch, reload_<x>):
    """<What a silent fallback would do wrong, e.g. a different calibration.>"""

    monkeypatch.setattr(settings, "<x>_provider", "typo")
    with pytest.raises(ValueError, match="unknown <x>_provider"):
        reload_<x>()


def test_default_<x>_is_<impl>(monkeypatch, reload_<x>):
    """Reads the DECLARED default, not the env-loaded instance: CI may export
    a different value."""

    default = Settings.model_fields["<x>_provider"].default
    assert default == "<value>"
    monkeypatch.setattr(settings, "<x>_provider", default)
    m = reload_<x>()
    assert type(m.<x>) is m.<Impl>   # use the RELOADED module's classes
```

## Mutation check

Once the tests pass, break the invariant each important test claims to guard, and
confirm that test fails. Some examples: drop the sort, swap a reason-code string,
hoist `connect()` out of its `try`, return `[]` on error. Then revert. A test that
still passes with the invariant broken is guarding nothing.
