"""A caller's `infra_queries` record (F17 BR-F17-10): one row per read of the cloud or its
observability, however it ended, and the coded refusal a failed read answers with."""

from __future__ import annotations

import logging
import time
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field

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

logger = logging.getLogger(__name__)

# What a backend's answer that can't be parsed raises.
UNREADABLE = (KeyError, TypeError, ValueError, IndexError)


@dataclass
class Read:
    """One read as it runs: what it sent, its rows, the texts it withheld and its row's id."""

    backend: InfraBackend
    kind: InfraQueryKind
    projects: list[str]
    calls: list[str] = field(default_factory=list)
    rows: int = 0
    withheld: int = 0
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
    """The reads one caller makes, each recorded as it ends."""

    def __init__(self, caller: Caller) -> None:
        self.caller = caller

    def own_scope(self, cloud: OpenStack) -> InfraScope:
        """The caller's Keystone projects; refuses with `infra_scope_unavailable` when Keystone
        can't answer, never widening the scope."""
        started = time.monotonic()
        try:
            return InfraScope.own(self.caller, cloud)
        except BackendUnavailable as e:
            logger.warning("infra: scope lookup failed: %s", e)
            failed = Read(InfraBackend.CLOUD, InfraQueryKind.RESOURCE, [])
            failed.calls.append("GET identity /role_assignments")
            self.record(
                failed, InfraOutcome.SCOPE_UNAVAILABLE, InfraRefusal.SCOPE_UNAVAILABLE, started
            )
            raise InfraError(
                InfraRefusal.SCOPE_UNAVAILABLE, "the cloud can't say which projects are yours"
            ) from e

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
            self.record(read, InfraOutcome.REFUSED, InfraRefusal.QUERY_REFUSED, started)
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
        self, read: Read, outcome: InfraOutcome, refusal: InfraRefusal | None, started: float
    ) -> InfraQuery:
        agent = self.caller.agent
        row = InfraQuery.objects.create(
            actor=self.caller.user,
            via=(InfraVia.AGENT if agent else InfraVia.HUMAN).value,
            agent_turn_id=agent.turn if agent else None,
            backend=read.backend.value,
            kind=read.kind.value,
            compiled="\n".join(read.calls),
            projects=read.projects,
            outcome=outcome.value,
            refusal=refusal.value if refusal else None,
            duration_ms=int((time.monotonic() - started) * 1000),
            rows=read.rows if outcome is InfraOutcome.OK else 0,
            withheld=read.withheld,
            link=read.link,
        )
        read.query_id = row.id
        return row
