"""F7 fixtures: the controllable clock, an incident manager, and tickets that run the pipeline
with the embedding a test chooses."""

from __future__ import annotations

import itertools
from dataclasses import dataclass, field

import pytest

from apps.accounts.models import Capability, User, UserRole

from apps.accounts.testing import grant_capability
from apps.lifecycle.tests.conftest import strict  # noqa: F401 — the fixture
from apps.sla.tests.conftest import clock, submitted  # noqa: F401 — the fixture
from apps.tickets.models import Ticket
from apps.tickets.utils.pipeline import _degraded_signals, ticket_process
from infrastructure.ai_engine import ai_engine
from infrastructure.dtos import AIRunResponse, EmbedResponse, EngineSignals, TicketMasked

_wobble = itertools.count(1)

VPN, PRINTER = 0, 1


def near(axis: int) -> list[float]:
    """A vector close to `axis` (cosine about 0.99 to any other `near(axis)`), orthogonal to the
    other axes."""
    vector = [0.0] * 1024
    vector[axis] = 1.0
    vector[100 + next(_wobble) % 900] = 0.1
    return vector


@pytest.fixture(autouse=True)
def ner_finds_nothing(monkeypatch):
    async def fake_ner(*a, **kw):
        return []

    monkeypatch.setattr("apps.tickets.utils.masking.llm_ner", fake_ner)


@dataclass
class Engine:
    """ai-engine: embeds a ticket as `vector`; analyses it with every check failed."""

    vector: list[float] = field(default_factory=lambda: near(VPN))
    analysed: list[str] = field(default_factory=list)


@pytest.fixture
def engine(monkeypatch) -> Engine:
    fake = Engine()
    monkeypatch.setattr(
        ai_engine, "embed", lambda text: EmbedResponse(vector=fake.vector, model="test")
    )

    def analyze(masked: TicketMasked, request_id: str) -> AIRunResponse:
        fake.analysed.append(masked.ticket_public_id)
        d = _degraded_signals()
        return AIRunResponse(
            request_id=request_id,
            graph_version="test",
            prompt_version="test",
            model="test",
            proposal=None,
            signals=EngineSignals(
                retrieval=d.retrieval,
                generation=d.generation,
                classification=d.classification,
                injection_detected=False,
            ),
        )

    monkeypatch.setattr(ai_engine, "analyze", analyze)
    return fake


def person(username: str, role: UserRole = UserRole.EMPLOYEE) -> User:
    return User.objects.create_user(
        username=username, password="x", role=role.value, email=f"{username}@example.test"
    )


@pytest.fixture
def desk(db) -> dict[str, User]:
    """duc.tm, on-call incident manager; huy.pq, a manager; khoa.lv, a technician; requesters."""
    people = {
        "duc": person("duc.tm", UserRole.TECHNICIAN),
        "huy": person("huy.pq", UserRole.MANAGER),
        "khoa": person("khoa.lv", UserRole.TECHNICIAN),
        "lan": person("lan.nt"),
        "binh": person("binh.tt"),
        "chi": person("chi.lt"),
    }
    grant_capability(people["duc"], Capability.INCIDENT_MANAGER.value)
    return people


def arrive(reporter: User, engine: Engine, axis: int) -> Ticket:
    """A new ticket about `axis`, through the pipeline."""
    engine.vector = near(axis)
    ticket = submitted(reporter)
    ticket_process(str(ticket.id))
    ticket.refresh_from_db()
    return ticket
