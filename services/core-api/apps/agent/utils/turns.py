"""An agent conversation's turns: taking a message, running it through ai-engine, recording what
the agent did, and handing a stopped turn to a person (F15, ADR-0046)."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Literal, cast

from asgiref.sync import async_to_sync
from django.conf import settings
from django.db import transaction
from django.db.models import Max
from django.utils import timezone
from pydantic import SecretStr

from apps.accounts.models import Language, User
from apps.accounts.permissions import Caller
from apps.accounts.utils import SessionRefused, sessions
from apps.accounts.utils.catalog import Permission
from apps.agent.models import (
    PATH_MAX_LENGTH,
    AgentAction,
    AgentActionState,
    AgentConversation,
    AgentConversationEnd,
    AgentConversationState,
    AgentStep,
    AgentSurface,
    AgentTurn,
    AgentTurnState,
)
from apps.agent.utils.actions import AgentOrigin
from apps.agent.utils.vocabulary import (
    HANDOFF_TEXT,
    STOP_REASONS,
    AgentError,
    AgentRefusal,
)
from apps.audit.models import AuditLog
from apps.chat.utils.conversations import conversations
from apps.rollout.utils.rollout import rollout
from apps.rollout.utils.vocabulary import FlagBranch
from apps.tickets.models import PiiQuarantine, Ticket
from apps.tickets.utils.crypto import build_quarantine_entries
from apps.tickets.utils.masking import mask_reply
from apps.tickets.utils.patterns import PIILevel
from apps.tickets.utils.router import ReasonCode
from infrastructure.ai_engine import AIEngineUnavailable, ai_engine
from infrastructure.dtos import (
    AgentEarlierTurn,
    AgentHandoffReason,
    AgentLimits,
    AgentTurnRequest,
    AgentTurnResponse,
)

_FLAGS = {AgentSurface.CHAT: FlagBranch.AGENT_CHAT, AgentSurface.CONSOLE: FlagBranch.AGENT_CONSOLE}
# What a write step's outcome shows the person (BR-F15-12).
_RECEIPTS = {
    "ok": "done",
    "confirmation_required": "awaiting_confirmation",
    "drafted": "draft_waiting",
    "refused": "refused",
    "failed": "failed",
    "unknown": "failed",
}
# Reasons that end the conversation with the turn.
_ENDS_CONVERSATION = {
    ReasonCode.AGENT_INJECTION_DETECTED: AgentConversationEnd.INJECTION,
    ReasonCode.AGENT_MASK_FAILED: AgentConversationEnd.MASK_FAILED,
}


@dataclass(frozen=True)
class SweepResult:
    actions_expired: int
    conversations_ended: int
    turns_failed: int


class AgentTurns:
    """Takes a person's message to the agent, runs it, and records or hands off what came back."""

    # ── a new message (FR-F15-001) ──

    def start(
        self,
        caller: Caller,
        message: str,
        surface: AgentSurface,
        conversation_id: uuid.UUID | None,
    ) -> AgentTurn:
        """Masks `message`, stores it as the conversation's next turn and queues the turn; a
        message whose masking failed hands off at once (BR-F15-08)."""
        if not rollout.is_live(_FLAGS[surface]):
            raise AgentError(403, AgentRefusal.AGENT_OFF, "the assistant is off")
        if surface is AgentSurface.CONSOLE:
            caller.require(Permission.TICKETS_READ)
        user = caller.user
        if caller.session_family is None:
            raise AgentError(403, AgentRefusal.AGENT_OFF, "this sign-in cannot run the assistant")
        if conversation_id is not None:
            self._open_conversation(user, surface, conversation_id, lock=False)
        masked = async_to_sync(mask_reply)(
            message, settings.THRESHOLDS.masking.ner_max_share, taken=[]
        )
        entries = build_quarantine_entries(masked.placeholder_map)
        now = timezone.now()
        with transaction.atomic():
            if conversation_id is None:
                conversation = AgentConversation.objects.create(user=user, surface=surface.value)
            else:
                conversation = self._open_conversation(user, surface, conversation_id, lock=True)
            if conversation.turns.unfinished().exists():
                raise AgentError(
                    409, AgentRefusal.TURN_RUNNING, "the assistant is still working on a message"
                )
            last = conversation.turns.aggregate(last=Max("seq"))["last"] or 0
            turn = AgentTurn.objects.create(
                conversation=conversation,
                seq=last + 1,
                message_masked=masked.text_masked,
                pii_level=masked.pii_level.value,
                pii_map={ph: str(entry.ref) for ph, entry in entries.items()},
                session_family=caller.session_family,
            )
            PiiQuarantine.objects.store_for_turn(turn, entries)
            conversation.last_activity_at = now
            conversation.save(update_fields=["last_activity_at"])
            if masked.pii_level is not PIILevel.MASK_FAILED:
                # Imported here: tasks imports this module.
                from apps.agent import tasks

                transaction.on_commit(lambda: tasks.run_turn.delay(str(turn.id)))
                return turn
            AgentTurn.objects.filter(id=turn.id).update(
                state=AgentTurnState.RUNNING.value, started_at=now
            )
        self._hand_off(turn.id, ReasonCode.AGENT_MASK_FAILED)
        turn.refresh_from_db()
        return turn

    def _open_conversation(
        self, user: User, surface: AgentSurface, conversation_id: uuid.UUID, *, lock: bool
    ) -> AgentConversation:
        """The user's active conversation on `surface`; one idle too long is ended first."""
        rows = AgentConversation.objects.filter(
            id=conversation_id, user=user, surface=surface.value
        )
        conversation = (rows.select_for_update() if lock else rows).first()
        if conversation is None:
            raise AgentError(404, AgentRefusal.CONVERSATION_NOT_FOUND, "no such conversation")
        idle = timedelta(minutes=settings.THRESHOLDS.agent.conversation_idle_minutes)
        if conversation.is_active() and conversation.last_activity_at <= timezone.now() - idle:
            self.end(conversation, AgentConversationEnd.IDLE)
        if not conversation.is_active():
            raise AgentError(
                409, AgentRefusal.CONVERSATION_ENDED, "the conversation has ended; start a new one"
            )
        return conversation

    # ── running a turn (agent.run_turn) ──

    def run(self, turn_id: uuid.UUID) -> None:
        """Runs a queued turn once: mints its token, asks ai-engine, and records the result."""
        now = timezone.now()
        if not AgentTurn.objects.filter(id=turn_id, state=AgentTurnState.QUEUED.value).update(
            state=AgentTurnState.RUNNING.value, started_at=now
        ):
            return
        turn = AgentTurn.objects.select_related("conversation__user").get(id=turn_id)
        conversation = turn.conversation
        user = conversation.user
        if not conversation.is_active():
            self._hand_off(turn.id, ReasonCode.AGENT_TOKEN_REFUSED)
            return
        try:
            token = sessions.issue_for_agent(
                user, turn.session_family, conversation=conversation.id, turn=turn.id
            )
        except SessionRefused:
            self._hand_off(turn.id, ReasonCode.AGENT_TOKEN_REFUSED)
            return
        chat_conversation = None
        if conversation.surface == AgentSurface.CHAT.value:
            chat_conversation = conversations.current(user)
            if chat_conversation is not None:
                conversation.chat_conversation = chat_conversation
                conversation.save(update_fields=["chat_conversation"])
        th = settings.THRESHOLDS.agent
        request = AgentTurnRequest(
            turn_id=turn.id,
            surface=cast(Any, conversation.surface),
            language=_language(user),
            message_masked=turn.message_masked,
            earlier_turns=self.earlier_turns(turn),
            limits=AgentLimits(
                max_steps=th.max_steps,
                max_tool_calls=th.max_tool_calls_per_turn,
                max_model_tokens=th.max_model_tokens_per_turn,
            ),
            chat_conversation_id=chat_conversation.id if chat_conversation else None,
            actor_id=user.id,
            actor_username=user.username,
            token=SecretStr(token),
        )
        try:
            response = ai_engine.agent_turn(request)
        except AIEngineUnavailable:
            self._hand_off(turn.id, ReasonCode.AGENT_ENGINE_UNAVAILABLE)
            return
        self._record(turn, response)

    def earlier_turns(self, turn: AgentTurn) -> list[AgentEarlierTurn]:
        """The finished turns before `turn` that it carries, oldest first (BR-F15-17)."""
        earlier = (
            AgentTurn.objects.filter(conversation_id=turn.conversation_id, seq__lt=turn.seq)
            .exclude(state__in=(AgentTurnState.QUEUED.value, AgentTurnState.RUNNING.value))
            .exclude(pii_level=PIILevel.MASK_FAILED.value)
            .order_by("-seq")[: settings.THRESHOLDS.agent.max_earlier_turns]
        )
        return [
            AgentEarlierTurn(
                message_masked=t.message_masked,
                reply="\n".join(
                    [t.reply_text]
                    + [f"[{r['outcome']}] {r['method']} {r['path']}" for r in t.receipts]
                ),
            )
            for t in reversed(earlier)
        ]

    def _record(self, turn: AgentTurn, response: AgentTurnResponse) -> None:
        """Stores the turn's steps and outcome; a turn no longer running keeps what it has."""
        actions = set(
            AgentAction.objects.filter(
                turn=turn, id__in=[s.action_id for s in response.steps if s.action_id]
            ).values_list("id", flat=True)
        )
        with transaction.atomic():
            locked = AgentTurn.objects.select_for_update().get(id=turn.id)
            if locked.state != AgentTurnState.RUNNING.value:
                return
            AgentStep.objects.bulk_create(
                AgentStep(
                    turn=locked,
                    seq=step.seq,
                    tool=step.tool[:40],
                    arguments_masked=step.arguments,
                    method=step.method[:8],
                    path=step.path[:PATH_MAX_LENGTH],
                    status_code=step.status_code,
                    outcome=step.outcome,
                    injection_flagged=step.injection_flagged,
                    action_id=step.action_id if step.action_id in actions else None,
                )
                for step in response.steps
            )
            locked.receipts = [
                {
                    "tool": step.tool,
                    "outcome": _RECEIPTS[step.outcome],
                    "method": step.method,
                    "path": step.path,
                    "action_id": str(step.action_id) if step.action_id in actions else None,
                }
                for step in response.steps
                if step.method != "GET"
            ]
            locked.tool_calls = len(response.steps)
            locked.model = response.model[:100]
            locked.prompt_version = response.prompt_version[:50]
            locked.tokens_in = response.tokens_in
            locked.tokens_out = response.tokens_out
            locked.cost_usd = response.cost_usd
            if response.outcome != "handed_off":
                locked.state = response.outcome
                locked.reply_text = response.reply
                locked.finished_at = timezone.now()
            locked.save(
                update_fields=[
                    "receipts",
                    "tool_calls",
                    "model",
                    "prompt_version",
                    "tokens_in",
                    "tokens_out",
                    "cost_usd",
                    "state",
                    "reply_text",
                    "finished_at",
                ]
            )
        if response.outcome == "handed_off":
            reason = (
                STOP_REASONS[response.stop_reason]
                if response.stop_reason is not None
                else ReasonCode.AGENT_SCHEMA_INVALID
            )
            self._hand_off(turn.id, reason)

    # ── handing off (BR-F15-13, BR-F15-14, FR-F15-016) ──

    def _hand_off(self, turn_id: uuid.UUID, reason: ReasonCode) -> None:
        """Ends a running turn with `reason` and its message in the user's language; on the chat
        surface, an employee's turn becomes a ticket for a person."""
        with transaction.atomic():
            turn = (
                AgentTurn.objects.select_for_update()
                .select_related("conversation__user")
                .filter(id=turn_id, state=AgentTurnState.RUNNING.value)
                .first()
            )
            if turn is None:
                return
            conversation = turn.conversation
            user = conversation.user
            turn.state = AgentTurnState.HANDED_OFF.value
            turn.stop_reason = reason.value
            turn.reply_text = HANDOFF_TEXT[reason][Language(_language(user))]
            turn.finished_at = timezone.now()
            turn.save(update_fields=["state", "stop_reason", "reply_text", "finished_at"])
            if reason in _ENDS_CONVERSATION:
                self.end(conversation, _ENDS_CONVERSATION[reason])
        ticket = None
        if (
            conversation.surface == AgentSurface.CHAT.value
            and reason is not ReasonCode.AGENT_TOKEN_REFUSED
        ):
            ticket = Ticket.objects.submit_for_agent(
                turn,
                cast(AgentHandoffReason, reason.value),
                conversations.current(user),
                AgentOrigin(conversation.id, turn.id, "").audit_fields(),
            )
            AgentTurn.objects.filter(id=turn.id).update(handoff_ticket=ticket)
            conversations.after_submit(ticket)
        AuditLog.objects.record(
            "agent_turn_handed_off",
            actor_type="system",
            ticket_id=ticket.id if ticket else None,
            payload={
                "reason": reason.value,
                "ticket_public_id": ticket.public_id if ticket else None,
                **AgentOrigin(conversation.id, turn.id, "").audit_fields(),
            },
        )

    # ── ending ──

    def end(self, conversation: AgentConversation, reason: AgentConversationEnd) -> bool:
        """Ends an active conversation; False when it had already ended."""
        now = timezone.now()
        if not AgentConversation.objects.filter(
            id=conversation.id, state=AgentConversationState.ACTIVE.value
        ).update(state=AgentConversationState.ENDED.value, ended_at=now, end_reason=reason.value):
            return False
        conversation.refresh_from_db(fields=["state", "ended_at", "end_reason"])
        return True

    def end_by_user(self, user: User, conversation_id: uuid.UUID) -> None:
        conversation = AgentConversation.objects.filter(id=conversation_id, user=user).first()
        if conversation is None:
            raise AgentError(404, AgentRefusal.CONVERSATION_NOT_FOUND, "no such conversation")
        self.end(conversation, AgentConversationEnd.USER)

    def dismiss(self, user: User, action_id: uuid.UUID) -> None:
        """The user dismisses a pending action of theirs."""
        action = AgentAction.objects.filter(id=action_id, user=user).first()
        if action is None:
            raise AgentError(404, AgentRefusal.NOT_PENDING, "no such action")
        if not AgentAction.objects.filter(
            id=action.id, state=AgentActionState.PENDING.value
        ).update(
            state=AgentActionState.DISMISSED.value, resolved_at=timezone.now(), resolved_by=user
        ):
            raise AgentError(409, AgentRefusal.NOT_PENDING, "this action is no longer pending")

    # ── agent.sweep (FR-F15-019) ──

    def sweep(self, now: datetime | None = None) -> SweepResult:
        """Expires pending actions past their time, ends idle conversations, and hands off turns
        queued or running longer than their token lives."""
        now = now or timezone.now()
        th = settings.THRESHOLDS.agent
        expired = AgentAction.objects.filter(
            state=AgentActionState.PENDING.value, expires_at__lte=now
        ).update(state=AgentActionState.EXPIRED.value, resolved_at=now)
        ended = (
            AgentConversation.objects.active()
            .filter(last_activity_at__lte=now - timedelta(minutes=th.conversation_idle_minutes))
            .exclude(turns__state__in=(AgentTurnState.QUEUED.value, AgentTurnState.RUNNING.value))
        )
        ended_count = 0
        for conversation in ended:
            ended_count += self.end(conversation, AgentConversationEnd.IDLE)
        cutoff = now - timedelta(seconds=th.token_ttl_seconds)
        stuck = [
            turn_id
            for turn_id in AgentTurn.objects.filter(
                state=AgentTurnState.QUEUED.value, queued_at__lte=cutoff
            ).values_list("id", flat=True)
            if AgentTurn.objects.filter(id=turn_id, state=AgentTurnState.QUEUED.value).update(
                state=AgentTurnState.RUNNING.value, started_at=now
            )
        ]
        stuck += AgentTurn.objects.filter(
            state=AgentTurnState.RUNNING.value, started_at__lte=cutoff
        ).values_list("id", flat=True)
        for turn_id in stuck:
            self._hand_off(turn_id, ReasonCode.AGENT_ENGINE_UNAVAILABLE)
        return SweepResult(expired, ended_count, len(stuck))


def _language(user: User) -> Literal["vi", "en"]:
    return "en" if user.language == Language.EN.value else "vi"


agent_turns = AgentTurns()
