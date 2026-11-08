"""The technician's tools, on the console surface (spec F15 §h.1)."""

from __future__ import annotations

from typing import Any, Literal
from uuid import UUID

from pydantic import Field

from ai_engine.agent.tools.chat import nothing
from ai_engine.agent.tools.projection import WITHHELD, person, untrusted
from ai_engine.agent.tools.tool import Context, Tier, Tool, ToolInput

StaffView = Literal["review", "mine", "open", "resolved", "all"]
Category = Literal["hardware", "software", "network", "access", "security", "other"]
ReassignReason = Literal[
    "wrong_team", "workload", "skill", "leave", "escalation", "requester_request", "other"
]


def masked(text: str | None, pii_level: str | None) -> dict[str, str] | str | None:
    """A ticket's text, withheld when its masking failed."""
    return WITHHELD if pii_level == "mask_failed" else untrusted(text)


def ticket_row(row: Any, context: Context) -> dict[str, Any]:
    """A staff ticket list row."""
    return {
        "public_id": row.get("public_id"),
        "subject_masked": masked(row.get("subject_masked"), row.get("pii_level")),
        "status": (row.get("status") or {}).get("name"),
        "category": row.get("category"),
        "assigned_team": row.get("assigned_team"),
        "assignee": person(row.get("assignee"), context.actor_username),
        "source": row.get("source"),
        "pii_level": row.get("pii_level"),
        "created_at": row.get("created_at"),
        "sla_due_at": row.get("sla_due_at"),
        "priority": row.get("priority"),
        "version": row.get("version"),
        "review_queue": (row.get("review") or {}).get("queue"),
    }


def ticket_page(body: Any, context: Context) -> dict[str, Any]:
    """A page of staff tickets."""
    return {
        "items": [ticket_row(r, context) for r in body.get("items", [])],
        "total": body.get("total"),
    }


def ticket_detail(body: Any, context: Context) -> dict[str, Any]:
    """One staff ticket with its routing history."""
    return {
        **ticket_row(body, context),
        "body_masked": masked(body.get("body_masked"), body.get("pii_level")),
        "placeholders": [p.get("placeholder") for p in body.get("pii_placeholders", [])],
        "resolved_at": body.get("resolved_at"),
        "reopened_count": body.get("reopened_count"),
        "routing": [
            {
                "branch": r.get("branch"),
                "reason_code": r.get("reason_code"),
                "decided_at": r.get("decided_at"),
            }
            for r in body.get("routing", [])
        ],
        "clarifications": [untrusted(c.get("question")) for c in body.get("clarifications", [])],
    }


def comments(body: Any, context: Context) -> list[dict[str, Any]]:
    """A ticket's comments."""
    rows = []
    for comment in body:
        held = (
            comment.get("hidden_for_review")
            or comment.get("discarded")
            or comment.get("pii_level") == "mask_failed"
        )
        rows.append(
            {
                "id": comment.get("id"),
                "author_kind": comment.get("author_kind"),
                "mine": person(comment.get("author"), context.actor_username) == "you",
                "visibility": comment.get("visibility"),
                "body_masked": WITHHELD if held else untrusted(comment.get("body_masked")),
                "created_at": comment.get("created_at"),
            }
        )
    return rows


def sla(body: Any, context: Context) -> dict[str, Any]:
    """A ticket's SLA clocks."""
    return {
        "priority": body.get("priority"),
        "policy": body.get("policy"),
        "clocks": [
            {
                name: clock.get(name)
                for name in (
                    "kind",
                    "state",
                    "due_at",
                    "remaining_minutes",
                    "paused",
                    "breached_at",
                )
            }
            for clock in body.get("clocks", [])
        ],
    }


def proposal_line(draft: dict[str, Any] | None) -> str | None:
    """The model's proposal on a review item, as one line of text."""
    if not draft:
        return None
    intent = draft.get("proposed_intent", "unknown")
    if intent == "runbook":
        args = ", ".join(str(v) for v in (draft.get("draft_payload") or {}).values())
        return f"runbook: {draft.get('runbook_id', '?')}({args})"
    return str(intent)


def review_item(item: Any, context: Context) -> dict[str, Any]:
    """A review queue row."""
    decisions = item.get("routing_decisions") or []
    return {
        "id": item.get("id"),
        "ticket_public_id": item.get("ticket_public_id"),
        "subject_masked": masked(item.get("subject_masked"), item.get("pii_level")),
        "body_masked": masked(item.get("body_masked"), item.get("pii_level")),
        "queue": item.get("queue"),
        "priority": item.get("priority"),
        "state": item.get("state"),
        "claimed_by": person(item.get("claimed_by"), context.actor_id),
        "created_at": item.get("created_at"),
        "proposal": untrusted(proposal_line(item.get("proposed_draft"))),
        "reason_code": decisions[-1].get("reason_code") if decisions else None,
    }


def review_queue(body: Any, context: Context) -> list[dict[str, Any]]:
    """The review queue."""
    return [review_item(item, context) for item in body]


def review_item_detail(body: Any, context: Context) -> dict[str, Any]:
    """One review item with its routing decisions; the comment it holds is withheld."""
    return {
        **review_item(body, context),
        "routing_decisions": [
            {"branch": d.get("branch"), "reason_code": d.get("reason_code")}
            for d in body.get("routing_decisions", [])
        ],
        "comment": WITHHELD if body.get("comment") else None,
    }


class PublicIdIn(ToolInput):
    public_id: str = Field(min_length=1, max_length=40)


class ListTicketsIn(ToolInput):
    view: StaffView = "all"
    q: str = Field("", max_length=200)
    page: int = Field(1, ge=1)
    limit: int = Field(20, ge=1, le=50)


class TakeIn(PublicIdIn):
    expected_version: int


class CommentIn(PublicIdIn):
    body: str = Field(min_length=1, max_length=10_000)
    visibility: Literal["public", "internal"]
    move_to_waiting: bool = False
    expected_version: int | None = None


class QueueIn(ToolInput):
    queue: str | None = Field(None, max_length=30)
    state: str = "pending"


class ItemIn(ToolInput):
    item_id: UUID


class DecisionIn(ItemIn):
    action_taken: str = Field(min_length=1, max_length=40)
    kb_verdict: str | None = None
    category_verdict: str | None = None
    corrected_category: Category | None = None
    corrected_kb_id: UUID | None = None
    override_reason: str | None = Field(None, max_length=2_000)


class CommentDecisionIn(ItemIn):
    choice: Literal["show", "discard"]


class ReassignIn(PublicIdIn):
    to_user: str | None = Field(None, max_length=150)
    to_team: str | None = Field(None, max_length=50)
    to_category: Category | None = None
    reason_code: ReassignReason
    note: str = Field("", max_length=1_000)
    expected_version: int


class PriorityIn(PublicIdIn):
    priority: Literal["P1", "P2", "P3", "P4"]
    reason: str = Field("", max_length=500)
    expected_version: int


def drafted(body: Any, context: Context) -> dict[str, Any]:
    """A human_only route's answer: the draft waits for the person."""
    return {}


TOOLS = (
    Tool(
        name="list_tickets",
        surface="console",
        tier=Tier.READ,
        method="GET",
        path="/api/tickets",
        Input=ListTicketsIn,
        description="List tickets in a saved view (review, mine, open, resolved, all), optionally searched with q.",
        project=ticket_page,
        query=("view", "q", "page", "limit"),
    ),
    Tool(
        name="get_ticket_detail",
        surface="console",
        tier=Tier.READ,
        method="GET",
        path="/api/tickets/{public_id}/detail",
        Input=PublicIdIn,
        description="Read one ticket: its text, status, team, assignee and routing history.",
        project=ticket_detail,
    ),
    Tool(
        name="list_comments",
        surface="console",
        tier=Tier.READ,
        method="GET",
        path="/api/tickets/{public_id}/comments",
        Input=PublicIdIn,
        description="Read a ticket's comments.",
        project=comments,
    ),
    Tool(
        name="get_sla",
        surface="console",
        tier=Tier.READ,
        method="GET",
        path="/api/tickets/{public_id}/sla",
        Input=PublicIdIn,
        description="Read a ticket's SLA clocks and due times.",
        project=sla,
    ),
    Tool(
        name="take_ticket",
        surface="console",
        tier=Tier.CONFIRM,
        method="POST",
        path="/api/tickets/{public_id}/take",
        Input=TakeIn,
        description="Prepare taking a ticket for the technician (needs its current version). They confirm it first.",
        project=nothing,
    ),
    Tool(
        name="add_comment",
        surface="console",
        tier=Tier.CONFIRM,
        method="POST",
        path="/api/tickets/{public_id}/comments",
        Input=CommentIn,
        description="Prepare a public or internal comment on a ticket. The technician confirms it first.",
        project=nothing,
    ),
    Tool(
        name="list_review_queue",
        surface="console",
        tier=Tier.READ,
        method="GET",
        path="/api/review/queue",
        Input=QueueIn,
        description="List review items, optionally in one queue.",
        project=review_queue,
        query=("queue", "state"),
    ),
    Tool(
        name="get_review_item",
        surface="console",
        tier=Tier.READ,
        method="GET",
        path="/api/review/items/{item_id}",
        Input=ItemIn,
        description="Read one review item with its routing decisions.",
        project=review_item_detail,
    ),
    Tool(
        name="claim_review_item",
        surface="console",
        tier=Tier.CONFIRM,
        method="POST",
        path="/api/review/items/{item_id}/claim",
        Input=ItemIn,
        description="Prepare claiming a review item for the technician. They confirm it first.",
        project=nothing,
    ),
    Tool(
        name="draft_review_decision",
        surface="console",
        tier=Tier.HUMAN_ONLY,
        method="POST",
        path="/api/review/items/{item_id}/decide",
        Input=DecisionIn,
        description="Draft a decision on a review item. Only the technician can apply it, on the item's page.",
        project=drafted,
        fixed={"time_spent_sec": 0},
    ),
    Tool(
        name="draft_comment_decision",
        surface="console",
        tier=Tier.HUMAN_ONLY,
        method="POST",
        path="/api/review/items/{item_id}/comment-decision",
        Input=CommentDecisionIn,
        description="Draft whether a held comment is shown or discarded. Only the technician can apply it.",
        project=drafted,
    ),
    Tool(
        name="draft_reassign",
        surface="console",
        tier=Tier.HUMAN_ONLY,
        method="POST",
        path="/api/tickets/{public_id}/reassign",
        Input=ReassignIn,
        description="Draft a reassignment. Only the technician can apply it, on the ticket's page.",
        project=drafted,
    ),
    Tool(
        name="draft_priority",
        surface="console",
        tier=Tier.HUMAN_ONLY,
        method="PATCH",
        path="/api/tickets/{public_id}/priority",
        Input=PriorityIn,
        description="Draft a priority change. Only the technician can apply it, on the ticket's page.",
        project=drafted,
    ),
)
