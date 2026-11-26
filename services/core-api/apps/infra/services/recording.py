"""The `infra_queries` record of a person's, their agent's or a ticket's cue reads (F17
BR-F17-10, ADR-0048 decision 10): one row per read of the cloud or its observability, however
it ended, the coded refusal a failed read answers with, and what a reply says of a source its
turn could not read (BR-F17-07)."""

from __future__ import annotations

import logging
import time
import uuid
from collections.abc import Iterable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from apps.accounts.models import Language, User
from apps.accounts.permissions import Caller
from apps.infra.clients.backends import (
    BackendNotFound,
    BackendRefused,
    BackendUnavailable,
    OpenStack,
)
from apps.infra.domain.untrusted import HasFreeText, MaskedTexts
from apps.infra.domain.vocabulary import (
    InfraError,
    InfraRefusal,
    QueryCheck,
    QueryRefused,
)
from apps.infra.models import InfraBackend, InfraOutcome, InfraQuery, InfraQueryKind, InfraVia
from apps.infra.services.scope import InfraScope

if TYPE_CHECKING:
    from apps.tickets.models import Ticket

logger = logging.getLogger(__name__)

# What a backend's answer that can't be parsed raises.
UNREADABLE = (KeyError, TypeError, ValueError, IndexError)


@dataclass
class Read:
    """One read as it runs: what it sent, its rows, the texts it withheld, whether its answer
    was cut to the result cap, and its row's id."""

    backend: InfraBackend
    kind: InfraQueryKind
    projects: list[str]
    calls: list[str] = field(default_factory=list)
    rows: int = 0
    withheld: int = 0
    truncated: bool = False
    link: str = ""
    query_id: uuid.UUID | None = None

    def shown[T: HasFreeText](self, items: list[T]) -> list[T]:
        """`items` with their free text masked or withheld, counted on the read."""
        masked = MaskedTexts.of([t for item in items for t in item.free_text()])
        self.rows, self.withheld = len(items), self.withheld + masked.withheld
        shown, at = [], 0
        for item in items:
            n = len(item.free_text())
            shown.append(item.with_free_text(masked.texts[at : at + n]))
            at += n
        return shown


class QueryLog:
    """The reads one person, their agent or a ticket's cues make, each recorded as it ends, and
    the rows recorded so far."""

    def __init__(
        self,
        actor: User | None,
        via: InfraVia,
        *,
        agent_turn: uuid.UUID | None = None,
        ticket: Ticket | None = None,
    ) -> None:
        self.actor = actor
        self.via = via
        self.agent_turn = agent_turn
        self.ticket = ticket
        self.recorded: list[InfraQuery] = []

    @classmethod
    def of(cls, caller: Caller, ticket: Ticket | None = None) -> QueryLog:
        """The reads `caller` makes, as their agent's when an agent acts for them."""
        agent = caller.agent
        return cls(
            caller.user,
            InfraVia.AGENT if agent else InfraVia.HUMAN,
            agent_turn=agent.turn if agent else None,
            ticket=ticket,
        )

    @classmethod
    def of_cues(cls, ticket: Ticket) -> QueryLog:
        """A ticket's cue reads: no actor, and the ticket (ADR-0048 decision 10)."""
        return cls(None, InfraVia.CUE, ticket=ticket)

    def own_scope(self, cloud: OpenStack) -> InfraScope:
        """The actor's Keystone projects; refuses with `infra_scope_unavailable` when Keystone
        can't answer, never widening the scope."""
        assert self.actor is not None
        started = time.monotonic()
        try:
            return InfraScope.own(self.actor, cloud)
        except BackendUnavailable as e:
            logger.warning("infra: scope lookup failed: %s", e)
            self.scope_unavailable(started)
            raise InfraError(
                InfraRefusal.SCOPE_UNAVAILABLE, "the cloud can't say which projects are yours"
            ) from e

    def scope_unavailable(self, started: float) -> InfraQuery:
        """Records a membership lookup Keystone didn't answer."""
        failed = Read(InfraBackend.CLOUD, InfraQueryKind.RESOURCE, [])
        failed.calls.append("GET identity /role_assignments")
        return self.record(
            failed, InfraOutcome.SCOPE_UNAVAILABLE, InfraRefusal.SCOPE_UNAVAILABLE, started
        )

    @contextmanager
    def read(
        self, backend: InfraBackend, kind: InfraQueryKind, projects: frozenset[str] | None
    ) -> Iterator[Read]:
        """Runs one read and records it, turning its failure into a coded refusal."""
        read = Read(backend, kind, InfraScope.listing(projects))
        started = time.monotonic()
        try:
            yield read
        except BackendNotFound as e:
            self.record(read, InfraOutcome.REFUSED, InfraRefusal.NOT_FOUND, started)
            raise InfraError(InfraRefusal.NOT_FOUND, "no such resource") from e
        except (QueryRefused, BackendRefused) as e:
            check = e.check if isinstance(e, QueryRefused) else QueryCheck.BACKEND_REFUSED
            self.record(read, InfraOutcome.REFUSED, InfraRefusal.QUERY_REFUSED, started, check)
            raise InfraError(InfraRefusal.QUERY_REFUSED, str(e), {"reason": check.value}) from e
        except (BackendUnavailable, *UNREADABLE) as e:
            failed = e.backend if isinstance(e, BackendUnavailable) else backend
            logger.warning("infra: %s read failed: %s", failed.value, e)
            self.record(
                read, InfraOutcome.BACKEND_UNAVAILABLE, InfraRefusal.BACKEND_UNAVAILABLE, started
            )
            raise InfraError(
                InfraRefusal.BACKEND_UNAVAILABLE,
                f"{failed.value} did not answer",
                {"backend": failed.value},
            ) from e
        else:
            self.record(read, InfraOutcome.OK, None, started)

    def record(
        self,
        read: Read,
        outcome: InfraOutcome,
        refusal: InfraRefusal | None,
        started: float,
        reason: QueryCheck | None = None,
    ) -> InfraQuery:
        row = InfraQuery.objects.create(
            actor=self.actor,
            via=self.via.value,
            agent_turn_id=self.agent_turn,
            ticket=self.ticket,
            backend=read.backend.value,
            kind=read.kind.value,
            compiled="\n".join(read.calls),
            projects=read.projects,
            outcome=outcome.value,
            refusal=refusal.value if refusal else None,
            refusal_reason=reason.value if reason else None,
            duration_ms=int((time.monotonic() - started) * 1000),
            rows=read.rows if outcome is InfraOutcome.OK else 0,
            withheld=read.withheld,
            truncated=read.truncated if outcome is InfraOutcome.OK else False,
            link=read.link,
        )
        read.query_id = row.id
        self.recorded.append(row)
        return row


_UNREACHABLE: dict[InfraBackend, dict[Language, str]] = {
    InfraBackend.PROMETHEUS: {
        Language.EN: "Prometheus was unreachable; this answer has no metrics.",
        Language.VI: "Không kết nối được Prometheus; câu trả lời này không có số liệu đo.",
    },
    InfraBackend.ELASTICSEARCH: {
        Language.EN: "Elasticsearch was unreachable; this answer has no logs or traces.",
        Language.VI: "Không kết nối được Elasticsearch; câu trả lời này không có log hay trace.",
    },
    InfraBackend.ALERTMANAGER: {
        Language.EN: "Alertmanager was unreachable; this answer has no alerts.",
        Language.VI: "Không kết nối được Alertmanager; câu trả lời này không có cảnh báo.",
    },
    InfraBackend.CLOUD: {
        Language.EN: "The cloud's API was unreachable; this answer has no resource state.",
        Language.VI: (
            "Không kết nối được API của hệ thống cloud; "
            "câu trả lời này không có trạng thái tài nguyên."
        ),
    },
}

_SCOPE_UNREAD = {
    Language.EN: (
        "Keystone did not answer, so your projects could not be read; "
        "this answer has none of your resources."
    ),
    Language.VI: (
        "Keystone không phản hồi nên không đọc được các dự án của bạn; "
        "câu trả lời này không có tài nguyên nào của bạn."
    ),
}


def missing_sources(queries: Iterable[InfraQuery], language: Language) -> list[str]:
    """What a reply says of each source its queries could not read, once per source, in the
    order the queries ran."""
    said: dict[str, None] = {}
    for query in queries:
        if query.outcome == InfraOutcome.SCOPE_UNAVAILABLE.value:
            said[_SCOPE_UNREAD[language]] = None
        elif query.outcome == InfraOutcome.BACKEND_UNAVAILABLE.value:
            said[_UNREACHABLE[InfraBackend(query.backend)][language]] = None
    return list(said)
