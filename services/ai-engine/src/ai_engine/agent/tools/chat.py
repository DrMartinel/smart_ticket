"""The employee's tools, on the chat surface (spec F15 §h.1)."""

from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from pydantic import Field

from ai_engine.agent.tools.client import CoreApi, Reply
from ai_engine.agent.tools.projection import WITHHELD, untrusted
from ai_engine.agent.tools.tool import Context, Tier, Tool, ToolInput
from ai_engine.core.config import settings

# What each chat state means for the employee, so the model need not guess.
_MEANING = {
    "thinking": "The helpdesk is still looking at this. Check again with get_chat_turn.",
    "answered": "The helpdesk answered from a knowledge-base page.",
    "clarify": "The helpdesk asks which of the options is meant; answer with answer_clarification.",
    "suggest_ticket": "The helpdesk could not answer this itself. A ticket can be opened with request_ticket.",
    "with_support": "A ticket is with the support team.",
}


def chat_turn(body: Any, context: Context) -> dict[str, Any]:
    """A chat turn: the state, the KB answer and the clarifying question."""
    answer = body.get("answer") or {}
    clarification = body.get("clarification") or {}
    incident = body.get("incident") or {}
    return {
        "public_id": body.get("public_id"),
        "state": body.get("state"),
        "meaning": _MEANING.get(body.get("state", ""), ""),
        "answer": {
            "text": untrusted(answer.get("text")),
            "kb_title": answer.get("kb_title"),
            "kb_url": answer.get("kb_url"),
        }
        if answer
        else None,
        "clarification": {
            "question": untrusted(clarification.get("question")),
            "options": [untrusted(o) for o in clarification.get("options", [])],
        }
        if clarification
        else None,
        "status_name": body.get("status_name"),
        "resolved": body.get("resolved", False),
        "incident": incident.get("title"),
    }


def ticket_request(body: Any, context: Context) -> dict[str, Any]:
    """A chat turn after asking for a ticket."""
    return {
        "public_id": body.get("public_id"),
        "state": body.get("state"),
        "status_name": body.get("status_name"),
    }


_ROW_FIELDS = (
    "public_id",
    "subject_masked",
    "source",
    "status_label",
    "team",
    "resolution_due_at",
    "sla_paused",
    "unread_comments",
    "created_at",
    "resolved_at",
    "can_reopen_until",
    "rating",
)


def my_ticket_row(row: Any) -> dict[str, Any]:
    """One of the employee's tickets, as a list row."""
    return {name: row.get(name) for name in _ROW_FIELDS}


def my_tickets(body: Any, context: Context) -> dict[str, Any]:
    """The employee's tickets, open and recent."""
    return {
        "open": [my_ticket_row(r) for r in body.get("open", [])],
        "recent": [my_ticket_row(r) for r in body.get("recent", [])],
        "more_before": body.get("more_before"),
    }


def my_ticket(body: Any, context: Context) -> dict[str, Any]:
    """One of the employee's tickets with its thread."""
    thread = []
    for comment in body.get("thread", []):
        text = comment.get("body_masked")
        if comment.get("state") != "shown":
            text = WITHHELD
        thread.append(
            {
                "author_kind": comment.get("author_kind"),
                "mine": comment.get("mine", False),
                "state": comment.get("state"),
                "body_masked": text if comment.get("mine") else untrusted(text),
                "created_at": comment.get("created_at"),
            }
        )
    return {
        **my_ticket_row(body),
        "body_masked": body.get("body_masked"),
        "thread": thread,
        "can_reply": body.get("can_reply"),
        "can_rate": body.get("can_rate"),
        "reopened_count": body.get("reopened_count"),
        "reopened_from": body.get("reopened_from"),
    }


def nothing(body: Any, context: Context) -> dict[str, Any]:
    """A write's answer: the UI shows what changed."""
    return {}


class AskIn(ToolInput):
    message: str = Field(min_length=10, max_length=10_000)


class PublicIdIn(ToolInput):
    public_id: str = Field(min_length=1, max_length=40)


class ClarifyIn(PublicIdIn):
    answer: str = Field(min_length=1, max_length=2_000)


class MyTicketsIn(ToolInput):
    before: datetime | None = None


class ReplyIn(PublicIdIn):
    body: str = Field(min_length=1, max_length=10_000)


class ReopenIn(PublicIdIn):
    reason: str = Field(max_length=2_000)


@dataclass(frozen=True)
class AskHelpdesk(Tool):
    """`POST /api/chat/ask`, then the turn is polled until it leaves `thinking`."""

    def run(self, api: CoreApi, args: ToolInput, context: Context) -> tuple[str, Reply]:
        assert isinstance(args, AskIn)
        conversation = context.chat_conversation_id
        body = {
            "message": args.message,
            "conversation_id": str(conversation) if conversation else None,
        }
        reply = api.send("POST", self.path, context.token, json=body)
        if reply.status != 200 or not isinstance(reply.body, dict):
            return self.path, reply
        deadline = time.monotonic() + settings.agent_ask_wait_sec
        turn = f"/api/chat/tickets/{reply.body['public_id']}"
        while reply.body.get("state") == "thinking" and time.monotonic() < deadline:
            api.wait(settings.agent_ask_poll_interval_sec)
            polled = api.send("GET", turn, context.token)
            if polled.status != 200 or not isinstance(polled.body, dict):
                return self.path, polled
            reply = polled
        return self.path, reply


TOOLS = (
    AskHelpdesk(
        name="ask_helpdesk",
        surface="chat",
        tier=Tier.SELF,
        method="POST",
        path="/api/chat/ask",
        Input=AskIn,
        description="Ask the helpdesk a question for the employee. The helpdesk may answer, ask which option is meant, or suggest a ticket.",
        project=chat_turn,
    ),
    Tool(
        name="get_chat_turn",
        surface="chat",
        tier=Tier.READ,
        method="GET",
        path="/api/chat/tickets/{public_id}",
        Input=PublicIdIn,
        description="Look at a question asked earlier: is it still being looked at, answered, or with support?",
        project=chat_turn,
    ),
    Tool(
        name="answer_clarification",
        surface="chat",
        tier=Tier.SELF,
        method="POST",
        path="/api/chat/tickets/{public_id}/clarify",
        Input=ClarifyIn,
        description="Answer the helpdesk's clarifying question with the employee's own choice.",
        project=chat_turn,
    ),
    Tool(
        name="request_ticket",
        surface="chat",
        tier=Tier.SELF,
        method="POST",
        path="/api/chat/tickets/{public_id}/create-ticket",
        Input=PublicIdIn,
        description="Open a support ticket for a question the helpdesk could not answer (state suggest_ticket).",
        project=ticket_request,
    ),
    Tool(
        name="list_my_tickets",
        surface="chat",
        tier=Tier.READ,
        method="GET",
        path="/api/requester/tickets",
        Input=MyTicketsIn,
        description="List the employee's own tickets, open and recent.",
        project=my_tickets,
        query=("before",),
    ),
    Tool(
        name="get_my_ticket",
        surface="chat",
        tier=Tier.READ,
        method="GET",
        path="/api/requester/tickets/{public_id}",
        Input=PublicIdIn,
        description="Read one of the employee's tickets: its status, team, due time and thread.",
        project=my_ticket,
    ),
    Tool(
        name="reply_to_my_ticket",
        surface="chat",
        tier=Tier.CONFIRM,
        method="POST",
        path="/api/requester/tickets/{public_id}/replies",
        Input=ReplyIn,
        description="Prepare a reply on the employee's ticket. The employee confirms it before it is sent.",
        project=nothing,
    ),
    Tool(
        name="reopen_my_ticket",
        surface="chat",
        tier=Tier.CONFIRM,
        method="POST",
        path="/api/requester/tickets/{public_id}/reopen",
        Input=ReopenIn,
        description="Prepare reopening the employee's resolved ticket. The employee confirms it first.",
        project=nothing,
    ),
)
