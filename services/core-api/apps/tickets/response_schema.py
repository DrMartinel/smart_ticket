"""
Response shapes for the ticket endpoints.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from ninja import Field, Schema

from apps.kb.models import KbArticle
from apps.tickets.models import PiiAccessLog, RoutingDecision, Ticket
from apps.tickets.utils.patterns import placeholder_level


class TicketSubmitOut(Schema):
    ticket_public_id: str = Field(alias="public_id")
    status: str
    pii_level: str


class TicketOut(Schema):
    public_id: str
    subject_masked: str
    body_masked: str
    pii_level: str
    status: str
    category: str | None
    created_at: datetime


class PersonOut(Schema):
    username: str
    email: str


class StatusOut(Schema):
    key: str
    name: str
    color: str
    stage: str
    is_completed: bool


class OpenReviewOut(Schema):
    id: uuid.UUID
    queue: str
    priority: int
    state: str


def status_of(ticket: Ticket) -> StatusOut:
    """The ticket's lifecycle status, or its bare key for a ticket that predates workflows."""
    status = ticket.workflow_status
    if status is None:
        return StatusOut(
            key=ticket.status,
            name=ticket.status.replace("_", " "),
            color="",
            stage="",
            is_completed=False,
        )
    return StatusOut(
        key=status.key,
        name=status.name,
        color=status.color,
        stage=status.base.name,
        is_completed=status.base.is_completed,
    )


def open_review_of(ticket: Ticket) -> OpenReviewOut | None:
    """The review item still waiting for a person, most urgent first."""
    waiting = [r for r in ticket.review_items.all() if r.state in ("pending", "claimed")]
    if not waiting:
        return None
    first = min(waiting, key=lambda r: (r.priority, r.created_at))
    return OpenReviewOut(id=first.id, queue=first.queue, priority=first.priority, state=first.state)


class StaffTicketRow(Schema):
    public_id: str
    subject_masked: str
    status: StatusOut
    category: str | None
    assigned_team: str | None
    assignee: str | None
    reporter: str
    source: str
    pii_level: str
    created_at: datetime
    sla_due_at: datetime | None
    review: OpenReviewOut | None

    @staticmethod
    def resolve_status(ticket: Ticket) -> StatusOut:
        return status_of(ticket)

    @staticmethod
    def resolve_assignee(ticket: Ticket) -> str | None:
        return ticket.assigned_to.username if ticket.assigned_to else None

    @staticmethod
    def resolve_reporter(ticket: Ticket) -> str:
        return ticket.reporter.username

    @staticmethod
    def resolve_review(ticket: Ticket) -> OpenReviewOut | None:
        return open_review_of(ticket)


class StaffTicketPage(Schema):
    items: list[StaffTicketRow]
    total: int
    counts: dict[str, int]


class StaffTicketBoard(Schema):
    items: list[StaffTicketRow]
    counts: dict[str, int]


class RoutingOut(Schema):
    branch: str
    reason_code: str
    reason_detail: str
    shadow_mode: bool
    decided_at: datetime


class AiSummaryOut(Schema):
    """What the triage pipeline concluded, read off its latest run."""

    intent: str | None
    category: str | None
    category_confidence: float | None
    kb_slug: str | None
    kb_title: str | None
    answer_draft: str | None
    verbatim_quote: str | None
    trust_score: float | None
    degraded_reason: str | None
    injection_detected: bool


class ClarificationOut(Schema):
    question: str
    options: list[str]
    answer_masked: str | None
    asked_at: datetime
    answered_at: datetime | None


class PlaceholderOut(Schema):
    placeholder: str
    level: str


class StaffTicketDetail(StaffTicketRow):
    body_masked: str
    pii_placeholders: list[PlaceholderOut] = []
    reporter_person: PersonOut
    resolved_at: datetime | None
    reopened_count: int
    routing: list[RoutingOut]
    ai: AiSummaryOut | None
    reviews: list[OpenReviewOut]
    clarifications: list[ClarificationOut]

    @staticmethod
    def resolve_reporter_person(ticket: Ticket) -> PersonOut:
        return PersonOut(username=ticket.reporter.username, email=ticket.reporter.email)

    @staticmethod
    def resolve_routing(ticket: Ticket) -> list[RoutingDecision]:
        return list(ticket.routing_decisions.order_by("-decided_at"))

    @staticmethod
    def resolve_pii_placeholders(ticket: Ticket) -> list[PlaceholderOut]:
        return [
            PlaceholderOut(placeholder=ph, level=placeholder_level(ph).value)
            for ph in sorted(ticket.pii_map)
        ]

    @staticmethod
    def resolve_reviews(ticket: Ticket) -> list[OpenReviewOut]:
        return [
            OpenReviewOut(id=r.id, queue=r.queue, priority=r.priority, state=r.state)
            for r in ticket.review_items.order_by("-created_at")
        ]

    @staticmethod
    def resolve_clarifications(ticket: Ticket) -> list[ClarificationOut]:
        return [
            ClarificationOut(
                question=c.question,
                options=[o.get("title", o.get("slug", "")) for o in c.options],
                answer_masked=c.answer_masked,
                asked_at=c.asked_at,
                answered_at=c.answered_at,
            )
            for c in ticket.clarifications.order_by("asked_at")
        ]

    @staticmethod
    def resolve_ai(ticket: Ticket) -> AiSummaryOut | None:
        run = ticket.ai_runs.order_by("-created_at").first()
        if run is None:
            return None
        proposal = run.proposed_draft or {}
        signals = run.trust_signals or {}
        classification = signals.get("classification") or {}
        slug = proposal.get("kb_slug")
        kb = KbArticle.objects.filter(slug=slug).only("title").first() if slug else None
        return AiSummaryOut(
            intent=proposal.get("proposed_intent"),
            category=classification.get("category_choice"),
            category_confidence=classification.get("category_confidence")
            if classification
            else None,
            kb_slug=slug,
            kb_title=kb.title if kb else None,
            answer_draft=proposal.get("answer_draft"),
            verbatim_quote=proposal.get("verbatim_quote"),
            trust_score=float(run.trust_score) if run.trust_score is not None else None,
            degraded_reason=run.degraded_reason,
            injection_detected=bool((signals.get("policy") or {}).get("injection_detected")),
        )


class RevealOut(Schema):
    placeholder: str
    value: str
    shown_until: datetime


class AccessLogRowOut(Schema):
    id: uuid.UUID
    accessed_at: datetime
    actor: str
    ticket: str
    placeholder: str
    level: str
    reason_code: str
    reason: str
    review_item: uuid.UUID | None
    outcome: str

    @staticmethod
    def resolve_actor(row: PiiAccessLog) -> str:
        return row.actor.username

    @staticmethod
    def resolve_ticket(row: PiiAccessLog) -> str:
        return row.ticket.public_id

    @staticmethod
    def resolve_level(row: PiiAccessLog) -> str:
        return placeholder_level(row.placeholder).value

    @staticmethod
    def resolve_review_item(row: PiiAccessLog) -> uuid.UUID | None:
        return row.review_item_id
