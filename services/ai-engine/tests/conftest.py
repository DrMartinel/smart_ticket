"""
Fakes for the four provider seams, plus a TriageState builder.

ai-engine's tests deliberately used no fixtures and no mocks while every
node was a pure function. Nodes now take their collaborators through
__init__, which is what makes the failure paths reachable in a unit test at
all — DB outage, embedder down, circuit open, budget exhausted. These are
plain classes rather than unittest.mock objects on purpose: a fake whose
behaviour you can read in one place beats a Mock configured three lines
away from the assertion.
"""

from __future__ import annotations

import time
from contextlib import contextmanager

import pytest

from contracts.enums import PIILevel
from contracts.ticket import TicketMasked

from ai_engine.core.providers import factory as factory_mod
from ai_engine.core.providers.base import ConnectionSource, Embedder, LLMClient, Reranker
from ai_engine.core.retrieval.fusion import Candidate
from ai_engine.core.state import TriageState
from ai_engine.graph.nodes.emit_signals import EmitSignalsNode
from ai_engine.graph.nodes.fewshot import SelectFewshotsNode
from ai_engine.graph.nodes.infer import InferNode
from ai_engine.graph.nodes.injection import InjectionNode
from ai_engine.graph.nodes.rerank import RerankNode
from ai_engine.graph.nodes.retrieve import HybridRetrieveNode
from ai_engine.graph.nodes.validate import ValidateNode


class FakeEmbedder(Embedder):
    """Records every string it was asked to embed, so a test can assert a
    budget-exhausted node bought no round-trip at all."""

    def __init__(self, vector: list[float] | None = None, error: Exception | None = None):
        self.calls: list[str] = []
        self._vector = vector if vector is not None else [0.1] * 8
        self._error = error

    def embed(self, text: str) -> list[float]:
        self.calls.append(text)
        if self._error is not None:
            raise self._error
        return self._vector


class FakeReranker(Reranker):
    """`scores` is consumed positionally against `passages`, so a test can
    hand back an order that INVERTS the input and prove the node's output
    order follows the reranker rather than the RRF order it was given
    (ADR-0005)."""

    def __init__(self, scores: list[float] | None = None, error: Exception | None = None):
        self.calls: list[tuple[str, list[str]]] = []
        self._scores = scores if scores is not None else []
        self._error = error

    def score(self, query: str, passages: list[str]) -> list[float]:
        self.calls.append((query, list(passages)))
        if self._error is not None:
            raise self._error
        return list(self._scores[: len(passages)])


class FakeLLM(LLMClient):
    """Records the timeout it was handed, which is the only way to assert
    the infer node leaves headroom for the fallback attempt."""

    def __init__(self, result=None, error: Exception | None = None):
        self.timeouts: list[float | None] = []
        self.prompts: list[tuple[str, str]] = []
        self._result = result
        self._error = error

    def complete(self, system_prompt: str, user_prompt: str, *, timeout: float | None = None):
        self.timeouts.append(timeout)
        self.prompts.append((system_prompt, user_prompt))
        if self._error is not None:
            raise self._error
        return self._result


class _FakeCursor:
    def __init__(self, rows):
        self._rows = rows
        self._last: tuple | None = None
        self.executed: list[tuple] = []

    def execute(self, sql, params=None):
        self._last = (sql, params)
        self.executed.append((sql, params))

    def _resolve(self):
        # `rows` may be a callable so one connection can answer the BM25 and
        # vector queries differently — the only way to test, for example,
        # "lexical found nothing but vector did".
        if callable(self._rows):
            sql, params = self._last if self._last else ("", None)
            return list(self._rows(sql, params))
        return list(self._rows)

    def fetchall(self):
        return self._resolve()

    def fetchone(self):
        rows = self._resolve()
        return rows[0] if rows else None

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class _FakeConnection:
    def __init__(self, rows):
        self._rows = rows
        self.cursors: list[_FakeCursor] = []

    def cursor(self):
        cur = _FakeCursor(self._rows)
        self.cursors.append(cur)
        return cur


class FakeConnectionSource(ConnectionSource):
    """`error` makes connect() raise, which is how the DB-outage failure
    paths get exercised. `events` records open/close ordering so a test can
    prove a connection is not held across an HTTP round-trip."""

    def __init__(self, rows=(), error: Exception | None = None):
        self._rows = rows if callable(rows) else list(rows)
        self._error = error
        self.events: list[str] = []
        self.connections: list[_FakeConnection] = []

    @contextmanager
    def connect(self):
        if self._error is not None:
            raise self._error
        conn = _FakeConnection(self._rows)
        self.connections.append(conn)
        self.events.append("open")
        try:
            yield conn
        finally:
            self.events.append("close")


def _make_ticket(
    subject: str = "không đăng nhập được", body: str = "máy tính báo lỗi"
) -> TicketMasked:
    return TicketMasked(
        ticket_public_id="TKT-1",
        subject_masked=subject,
        body_masked=body,
        pii_level=PIILevel.ROUTINE,
        placeholder_keys=[],
    )


def _make_candidate(chunk_id: int = 1, content: str = "nội dung", slug: str = "kb-a") -> Candidate:
    return Candidate(
        chunk_id=chunk_id,
        article_id=chunk_id * 10,
        article_slug=slug,
        content=content,
        rrf_score=1.0 / chunk_id,
    )


def _make_state(**overrides) -> dict:
    """A valid TriageState with generous budgets. Tests that care about one
    budget override exactly that key, which makes the intent obvious —
    previously every test rewrote the whole literal dict."""

    state = {
        "ticket": _make_ticket(),
        "request_id": "req-1",
        "retrieval_floor": 0.5,
        "max_tokens": 100_000,
        "max_llm_calls": 5,
        "max_latency_sec": 600,
        "max_graph_iterations": 5,
        "tokens_used": 0,
        "llm_calls": 0,
        "started_at": time.time(),
        "iteration": 0,
    }
    state.update(overrides)
    return TriageState(**state)


def _exhausted_budget_state(**overrides) -> dict:
    """A state that BudgetedNode rejects — the shared precondition for
    every "degrade before spending anything" test."""

    return _make_state(llm_calls=99, max_llm_calls=1, **overrides)


def _triage_nodes(*, db=None, embedder=None, reranker=None, llm=None) -> dict:
    """The seven production nodes wired to fakes, keyed by `wire_triage`'s
    parameters — the test-side counterpart of the instances main.py builds.
    Pass it as `wire_triage(**nodes)`; replace one entry with a subclass of
    the real node to swap in a fake. It cannot silently drift: every
    `wire_triage` parameter is a required keyword."""

    db = db if db is not None else FakeConnectionSource()
    embedder = embedder if embedder is not None else FakeEmbedder()
    return {
        "injection": InjectionNode(),
        "retrieve": HybridRetrieveNode(db=db, embedder=embedder),
        "rerank": RerankNode(reranker=reranker if reranker is not None else FakeReranker()),
        "fewshots": SelectFewshotsNode(db=db, embedder=embedder),
        "infer": InferNode(llm=llm if llm is not None else FakeLLM()),
        "validate": ValidateNode(),
        "emit": EmitSignalsNode(db=db),
    }


class _StubCrossEncoderModel:
    """Stands in for a loaded `sentence_transformers.CrossEncoder`."""

    def predict(self, pairs):
        return [0.0] * len(pairs)


@pytest.fixture(autouse=True)
def never_load_real_reranker_weights(monkeypatch):
    """Keep the unit suite free of a 2.3GB model load.

    `build_providers()` loads the real model when `cross_encoder` is selected, and
        it takes no arguments — so patching this name is the only way a test can
        select that provider without pulling 2.3GB of weights that no CI runner
        has. The default is `lexical`, so this does not fire on a plain
        build_providers(); it catches the tests that switch. Autouse because the
        trap is invisible from the test body: selecting a provider and loading a
        multi-GB model do not look like the same action.

        Tests that assert something ABOUT loading re-patch this themselves;
        monkeypatch applies their stub over this one and unwinds both.
    """

    monkeypatch.setattr(factory_mod, "_load_cross_encoder", _StubCrossEncoderModel)


# --- fixtures -------------------------------------------------------------
# The fakes and builders are exposed as fixtures rather than imported
# directly: the root pyproject runs pytest with --import-mode=importlib
# (core-api and ai-engine both ship a package named `tests`), under which a
# test module cannot `from conftest import ...`.


@pytest.fixture
def fake_embedder():
    """The FakeEmbedder class — call it with (vector=..., error=...)."""
    return FakeEmbedder


@pytest.fixture
def fake_reranker():
    return FakeReranker


@pytest.fixture
def fake_llm():
    return FakeLLM


@pytest.fixture
def fake_db():
    return FakeConnectionSource


@pytest.fixture
def triage_nodes():
    """_triage_nodes — call it with (db=..., embedder=..., reranker=..., llm=...)
    to replace any fake."""
    return _triage_nodes


@pytest.fixture
def make_state():
    return _make_state


@pytest.fixture
def exhausted_budget_state():
    return _exhausted_budget_state


@pytest.fixture
def make_ticket():
    return _make_ticket


@pytest.fixture
def make_candidate():
    return _make_candidate


def _kb_row(chunk_id: int, content: str, score: float, slug: str = "kb-a") -> tuple:
    """A row shaped like the SELECT in bm25_search / vector_search:
    (chunk_id, article_id, slug, content, score)."""

    return (chunk_id, chunk_id * 10, slug, content, score)


@pytest.fixture
def kb_row():
    return _kb_row
