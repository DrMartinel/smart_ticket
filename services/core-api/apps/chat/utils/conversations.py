"""Chat conversations: which conversation a turn joins, when one ends, and the earlier masked turns
a new turn carries to ai-engine (F3, ADR-0034)."""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timedelta
from enum import StrEnum

from django.conf import settings
from django.db import IntegrityError, transaction
from django.utils import timezone

from apps.accounts.models import User
from apps.audit.models import AuditLog
from apps.chat.models import Conversation, ConversationState, EndReason
from apps.chat.response_schema import ChatState
from apps.chat.utils.turns import chat_turn
from apps.core.errors import CodedError
from apps.lifecycle.utils.vocabulary import PipelineStatus
from apps.tickets.models import Ticket
from apps.tickets.utils.patterns import PIILevel
from apps.tickets.utils.router import Branch
from infrastructure.dtos import PriorTurn

logger = logging.getLogger(__name__)


class ChatRefusal(StrEnum):
    CONVERSATION_ENDED = "conversation_ended"
    CONVERSATION_NOT_FOUND = "conversation_not_found"


class ChatError(CodedError):
    """A chat request core-api refuses."""


class Conversations:
    """Starts, continues and ends a requester's conversations (BR-F3-01, BR-F3-02)."""

    def for_turn(
        self, requester: User, conversation_id: uuid.UUID | None, now: datetime | None = None
    ) -> Conversation:
        """The conversation a new turn joins: the named one while it is open, else a new one when
        none is named. A named conversation that is over is `conversation_ended`."""
        now = now or timezone.now()
        idle = settings.THRESHOLDS.requester.conversation_idle_minutes
        with transaction.atomic():
            active = (
                Conversation.objects.select_for_update()
                .active()
                .filter(requester=requester)
                .first()
            )
            if active is not None and not active.is_open_at(now, idle):
                self.end(active, EndReason.IDLE, now=now)
                active = None
            if conversation_id is not None and (active is None or active.id != conversation_id):
                if not Conversation.objects.filter(
                    id=conversation_id, requester=requester
                ).exists():
                    raise ChatError(404, ChatRefusal.CONVERSATION_NOT_FOUND, "no such conversation")
                raise ChatError(
                    409,
                    ChatRefusal.CONVERSATION_ENDED,
                    "the conversation has ended; start a new one",
                )
            if active is None:
                try:
                    with transaction.atomic():
                        active = self.start(requester, now)
                except IntegrityError:
                    # Another turn started one at the same moment: join it.
                    active = Conversation.objects.active().get(requester=requester)
            else:
                active.last_activity_at = now
                active.save(update_fields=["last_activity_at"])
            return active

    def start(self, requester: User, now: datetime) -> Conversation:
        conversation = Conversation.objects.create(
            requester=requester, started_at=now, last_activity_at=now
        )
        AuditLog.objects.record(
            "conversation_started",
            actor_type="human",
            actor_id=requester.id,
            payload={"conversation": str(conversation.id)},
        )
        return conversation

    def end(
        self, conversation: Conversation, reason: EndReason, *, now: datetime | None = None
    ) -> bool:
        """Ends an active conversation; False when it had already ended."""
        updated = Conversation.objects.filter(
            pk=conversation.pk, state=ConversationState.ACTIVE.value
        ).update(
            state=ConversationState.ENDED.value,
            ended_at=now or timezone.now(),
            end_reason=reason.value,
        )
        if not updated:
            return False
        conversation.refresh_from_db(fields=["state", "ended_at", "end_reason"])
        AuditLog.objects.record(
            "conversation_ended",
            actor_type="human" if reason is EndReason.USER else "system",
            actor_id=conversation.requester_id if reason is EndReason.USER else None,
            payload={"conversation": str(conversation.id), "reason": reason.value},
        )
        return True

    def end_by_requester(self, requester: User, conversation_id: uuid.UUID) -> None:
        """The requester asked for a new conversation ("Cuộc trò chuyện mới")."""
        conversation = Conversation.objects.filter(id=conversation_id, requester=requester).first()
        if conversation is None:
            raise ChatError(404, ChatRefusal.CONVERSATION_NOT_FOUND, "no such conversation")
        self.end(conversation, EndReason.USER)

    def current(self, requester: User, now: datetime | None = None) -> Conversation | None:
        """The requester's conversation a turn would join now, if any."""
        now = now or timezone.now()
        active = Conversation.objects.active().filter(requester=requester).first()
        idle = settings.THRESHOLDS.requester.conversation_idle_minutes
        return active if active is not None and active.is_open_at(now, idle) else None

    # ── turns that end a conversation ──

    def after_submit(self, ticket: Ticket) -> None:
        """A turn whose masking failed ends its conversation (BR-F3-02)."""
        if ticket.conversation is not None and ticket.pii_level == PIILevel.MASK_FAILED.value:
            self.end(ticket.conversation, EndReason.MASK_FAILED)

    def after_decision(self, ticket: Ticket, branch: Branch) -> None:
        """A blocked turn ends its conversation (BR-F3-02)."""
        if branch is Branch.BLOCK and ticket.conversation is not None:
            self.end(ticket.conversation, EndReason.BLOCKED)

    def ending_reason(self, turn: Ticket) -> EndReason | None:
        """Why an earlier turn may never be context: it was blocked or its masking failed."""
        if turn.pii_level == PIILevel.MASK_FAILED.value:
            return EndReason.MASK_FAILED
        latest = turn.routing_decisions.order_by("-decided_at").first()
        if latest is not None and latest.branch == Branch.BLOCK.value:
            return EndReason.BLOCKED
        return None

    # ── context ──

    def context_for(self, ticket: Ticket) -> list[PriorTurn]:
        """The earlier turns for `ticket`'s ai-engine request; none, with the conversation ended,
        when assembling them fails (ADR-0034)."""
        try:
            return self.prior_turns(ticket)
        except Exception as e:  # noqa: BLE001 — without context the ticket is analysed alone
            logger.exception("prior turns for %s failed", ticket.public_id)
            if ticket.conversation is not None:
                self.end(ticket.conversation, EndReason.CONTEXT_FAILED)
            AuditLog.objects.record(
                "prior_turns_failed",
                actor_type="system",
                ticket_id=ticket.id,
                payload={"ticket_public_id": ticket.public_id, "error": type(e).__name__},
            )
            return []

    def prior_turns(self, ticket: Ticket) -> list[PriorTurn]:
        """Up to `max_prior_turns` decided turns before `ticket` in its conversation, by the same
        requester, masked text only (BR-F3-01). An earlier blocked or mask-failed turn ends the
        conversation and gives none."""
        conversation = ticket.conversation
        if conversation is None or conversation.requester_id != ticket.reporter_id:
            return []
        th = settings.THRESHOLDS.requester
        earlier = list(
            Ticket.objects.filter(
                conversation=conversation,
                reporter_id=ticket.reporter_id,
                created_at__lt=ticket.created_at,
            )
            .exclude(pk=ticket.pk)
            .select_related("workflow_status")
            .order_by("-created_at")
        )
        for turn in earlier:
            reason = self.ending_reason(turn)
            if reason is not None:
                self.end(conversation, reason)
                return []
        decided = [
            t
            for t in earlier
            if t.status != PipelineStatus.NEW.value and t.routing_decisions.exists()
        ]
        turns = []
        for turn in reversed(decided[: th.max_prior_turns]):
            shown = chat_turn(turn)
            if shown.state is ChatState.THINKING:
                continue
            turns.append(
                PriorTurn(
                    question_masked=shown.question_masked,
                    outcome=shown.state.value,  # type: ignore[arg-type]
                    answer_excerpt=shown.answer.text[: th.answer_excerpt_chars]
                    if shown.answer
                    else "",
                )
            )
        return turns

    # ── the sweep ──

    def end_idle(self, now: datetime | None = None) -> int:
        """Ends every conversation idle past `conversation_idle_minutes`."""
        now = now or timezone.now()
        cutoff = now - timedelta(minutes=settings.THRESHOLDS.requester.conversation_idle_minutes)
        return sum(
            self.end(c, EndReason.IDLE, now=now) for c in Conversation.objects.idle_since(cutoff)
        )


# --- the conversations service ---

conversations = Conversations()
