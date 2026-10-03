"""
Fakes for the provider seams, plus state and node builders.

Plain classes rather than unittest.mock, so a fake's behaviour reads in one
place. Swapped in for the provider singletons by the `use_*` fixtures, they
make the failure paths (DB outage, embedder down, LLM down) testable.
"""

from __future__ import annotations

from uuid import UUID

import copy
import importlib
import json
from collections.abc import Callable, Iterable
from contextlib import contextmanager
from typing import Any

import httpx
import pytest
from dotenv import dotenv_values
from sqlalchemy.dialects import postgresql

from ai_engine.core.config import ENV_FILE
from ai_engine.schemas import PIILevel, TicketMasked
from ai_engine.graph.state import TriageState

from ai_engine.core.providers import embeddings
from ai_engine.core.providers import clients
from ai_engine.core.providers.clients import ChatClient
from ai_engine.core.providers.embeddings import Embedder
from ai_engine.core.providers.pii import PiiDetector
from ai_engine.graph.state import Candidate
from ai_engine import main
from ai_engine.graph.nodes import emit_signals as emit_signals_node, fewshot as fewshot_node
from ai_engine.graph.nodes.candidate_pool import node as candidate_pool_node
from ai_engine.graph.nodes.candidate_pool import shortlister as shortlister_module
from ai_engine.graph.nodes.candidate_pool.shortlister import Shortlister
from ai_engine.graph.nodes.rerank import node as rerank_node
from ai_engine.graph.nodes.rerank.reranker import Passage
from ai_engine.graph.nodes.candidate_pool import links as links_module
from ai_engine.graph.nodes.retrieve import bm25 as bm25_module
from ai_engine.graph.nodes.retrieve import node as retrieve_node
from ai_engine.graph.nodes.retrieve import vector as vector_module


def _reloader(module):
    """Re-runs `module`'s import-time wiring against the current (usually
    monkeypatched) settings, and returns the module. Every module-level
    object is restored afterwards, so a test's config never leaks into
    another test. Reloading redefines the module's classes too, so assert
    against the returned module's classes (`m.ChatClient`), not ones imported
    at the top of a test file."""

    saved = dict(vars(module))
    yield lambda: importlib.reload(module)
    vars(module).update(saved)


@pytest.fixture
def env_template() -> dict[str, str | None]:
    """The repo root's `.env.example`: the template `.env` is copied from,
    never read by the service. For tests about what it ships."""
    return dotenv_values(ENV_FILE.with_name(".env.example"))


class ScriptedServer:
    """An httpx transport handler: answers every request with one canned JSON
    body (or raises it) and records (path, payload) for each."""

    def __init__(self, body):
        self._body = body
        self.sent: list[tuple[str, dict]] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.sent.append((request.url.path, json.loads(request.content)))
        if isinstance(self._body, Exception):
            raise self._body
        return httpx.Response(200, json=self._body)


@pytest.fixture
def serve(monkeypatch):
    """`serve("embed", body)`: swaps `clients.<name>` for a copy of the real
    client whose server is a ScriptedServer, so the client's own request
    building and reply validation run. Returns the server."""

    def install(name: str, body) -> ScriptedServer:
        client = copy.copy(getattr(clients, name))
        server = ScriptedServer(body)
        client.__dict__["_http"] = httpx.Client(
            base_url="http://test", transport=httpx.MockTransport(server)
        )
        monkeypatch.setattr(clients, name, client)
        return server

    return install


@pytest.fixture
def reload_clients():
    yield from _reloader(clients)


@pytest.fixture
def reload_embeddings():
    yield from _reloader(embeddings)


@pytest.fixture
def reload_shortlister():
    yield from _reloader(shortlister_module)


class FakeEmbedder(Embedder):
    """Records every string it was asked to embed, so a test can assert a
    node bought no round-trip at all."""

    def __init__(self, vector: list[float] | None = None, error: Exception | None = None):
        self.calls: list[str] = []
        self._vector = vector if vector is not None else [0.1] * 8
        self._error = error

    @property
    def model(self) -> str:
        return "fake-embed"

    def embed(self, text: str) -> list[float]:
        self.calls.append(text)
        if self._error is not None:
            raise self._error
        return self._vector


class FakePiiDetector(PiiDetector):
    """Records the raw texts it was handed. `error` makes detect() raise, which
    is how the fail-to-MASK_FAILED path gets exercised."""

    def __init__(self, spans: list[str] | None = None, error: Exception | None = None):
        self.calls: list[str] = []
        self._spans = spans if spans is not None else []
        self._error = error

    def detect(self, text: str) -> list[str]:
        self.calls.append(text)
        if self._error is not None:
            raise self._error
        return list(self._spans)


class FakeShortlister(Shortlister):
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


class FakeReranker:
    """Like FakeShortlister: `scores` are consumed positionally, so a test can
    invert the cross-encoder's order. Records (subject, body, passages)."""

    def __init__(self, scores: list[float] | None = None, error: Exception | None = None):
        self.calls: list[tuple[str, str, list[Passage]]] = []
        self._scores = scores if scores is not None else []
        self._error = error

    def score(self, subject: str, body: str, passages: list[Passage]) -> list[float]:
        self.calls.append((subject, body, list(passages)))
        if self._error is not None:
            raise self._error
        return list(self._scores[: len(passages)])


class FakeLLM(ChatClient):
    """Records the prompts it was handed."""

    def __init__(self, result=None, error: Exception | None = None):
        self.prompts: list[tuple[str, str]] = []
        self._result = result
        self._error = error

    def complete(self, system_prompt: str, user_prompt: str) -> Any:
        self.prompts.append((system_prompt, user_prompt))
        if self._error is not None:
            raise self._error
        return self._result


class _FakeResult:
    def __init__(self, rows):
        self._rows = rows

    def all(self):
        return list(self._rows)

    def first(self):
        return self._rows[0] if self._rows else None


type Rows = Iterable[Any] | Callable[[str, dict[str, Any]], Iterable[Any]]


class _FakeSession:
    """Answers `execute(statement)` with canned rows. The statement is compiled
    with the Postgres dialect first, so a `rows(sql, params)` callable can
    tell queries apart by their SQL — and so a statement SQLAlchemy cannot
    compile fails here rather than only against a real database."""

    def __init__(self, rows: Rows) -> None:
        self._rows = rows
        self.executed: list[tuple[str, dict]] = []

    def execute(self, statement):
        compiled = statement.compile(dialect=postgresql.dialect())
        sql, params = str(compiled), dict(compiled.params)
        self.executed.append((sql, params))
        # `rows` may be a callable so one session can answer the BM25 and
        # vector queries differently — the only way to test, for example,
        # "lexical found nothing but vector did".
        if callable(self._rows):
            return _FakeResult(list(self._rows(sql, params)))
        return _FakeResult(list(self._rows))


class FakeSessionSource:
    """Stands in for `db`: each `all`/`first` runs on its own fake session,
    as each real read borrows its own connection. `error` makes every read
    raise, which is how the DB-outage failure paths get exercised. `events`
    records open/close ordering so a test can prove no connection is held
    across an HTTP round-trip."""

    def __init__(self, rows: Rows = (), error: Exception | None = None):
        self._rows = rows if callable(rows) else list(rows)
        self._error = error
        self.events: list[str] = []
        self.sessions: list[_FakeSession] = []

    def all(self, statement):
        with self._session() as session:
            return session.execute(statement).all()

    def first(self, statement):
        with self._session() as session:
            return session.execute(statement).first()

    @contextmanager
    def _session(self):
        if self._error is not None:
            raise self._error
        session = _FakeSession(self._rows)
        self.sessions.append(session)
        self.events.append("open")
        try:
            yield session
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
        chunk_id=UUID(int=chunk_id),
        article_id=UUID(int=chunk_id * 10),
        article_slug=slug,
        content=content,
    )


def _make_state(**overrides) -> TriageState:
    """A valid TriageState; tests override only the key they care about."""

    state = {
        "ticket": _make_ticket(),
        "request_id": "req-1",
        "retrieval_floor": 0.5,
    }
    state.update(overrides)
    return TriageState(**state)


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
def fake_pii_detector():
    return FakePiiDetector


@pytest.fixture
def fake_shortlister():
    return FakeShortlister


@pytest.fixture
def fake_reranker():
    return FakeReranker


@pytest.fixture
def fake_llm():
    return FakeLLM


@pytest.fixture
def fake_db():
    return FakeSessionSource


# Nodes and endpoints use the provider singletons directly (`db`, `embedder`,
# `shortlister`, `reranker`, `pii_detector`, `clients.chat`). These fixtures swap one in for a fake in every node module
# that reads it, and return the fake. The modules are listed here once, so a
# test cannot miss one; monkeypatch raises on a misspelled attribute and
# restores everything after the test.


@pytest.fixture
def use_db(monkeypatch):
    def use(fake):
        for module in (bm25_module, vector_module, links_module, fewshot_node, emit_signals_node):
            monkeypatch.setattr(module, "db", fake)
        return fake

    return use


@pytest.fixture
def use_embedder(monkeypatch):
    def use(fake):
        for module in (retrieve_node, fewshot_node, main):
            monkeypatch.setattr(module, "embedder", fake)
        return fake

    return use


@pytest.fixture
def use_pii_detector(monkeypatch):
    def use(fake):
        monkeypatch.setattr(main, "pii_detector", fake)
        return fake

    return use


@pytest.fixture
def use_shortlister(monkeypatch):
    def use(fake):
        monkeypatch.setattr(candidate_pool_node, "shortlister", fake)
        return fake

    return use


@pytest.fixture
def use_reranker(monkeypatch):
    """Install a fake Jev, the reranker on every run."""

    def use(fake):
        monkeypatch.setattr(rerank_node, "reranker", fake)
        return fake

    return use


@pytest.fixture
def use_llm(monkeypatch):
    def use(fake):
        monkeypatch.setattr(clients, "chat", fake)
        return fake

    return use


@pytest.fixture
def make_state():
    return _make_state


@pytest.fixture
def make_ticket():
    return _make_ticket


@pytest.fixture
def make_candidate():
    return _make_candidate


def _kb_row(chunk_id: int, content: str, score: float, slug: str = "kb-a") -> tuple:
    """A row shaped like the SELECT in bm25_search / vector_search:
    (chunk_id, article_id, slug, content, score)."""

    return (UUID(int=chunk_id), UUID(int=chunk_id * 10), slug, content, score)


@pytest.fixture
def kb_row():
    return _kb_row
