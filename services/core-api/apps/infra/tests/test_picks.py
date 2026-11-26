"""The resources a person picks on a choice card in the chat: checked against their own projects
when pressed, recorded once per turn the press sent, and never by the agent (F17 BR-F17-26,
FR-F17-025, UC-F17-14 4x, AC-F17-21)."""

from __future__ import annotations

import uuid
from typing import Any

import pytest
from cloud_sim.faults import FaultKind

from apps.accounts.models import User
from apps.agent.models import AgentConversation, AgentConversationEnd, AgentSurface, AgentTurn
from apps.agent.services.turns import agent_turns
from apps.agent.testing import as_agent
from apps.infra.models import InfraQuery, InfraVia, ResourcePick
from apps.infra.tests.conftest import CloudSim
from apps.tickets.domain.patterns import PIILevel

pytestmark = pytest.mark.django_db

PICKS = "/api/requester/infra/picks"


def turn_in(conversation: AgentConversation) -> AgentTurn:
    """The conversation's next turn."""
    return AgentTurn.objects.create(
        conversation=conversation,
        seq=conversation.turns.count() + 1,
        message_masked="db-01",
        pii_level=PIILevel.ROUTINE.value,
        session_family=uuid.uuid4(),
    )


def chat_of(person: User, surface: AgentSurface = AgentSurface.CHAT) -> AgentTurn:
    """The first turn of a new conversation of `person`'s."""
    return turn_in(AgentConversation.objects.create(user=person, surface=surface.value))


def pick(turn: AgentTurn, kind: str, resource_id: str) -> dict[str, Any]:
    return {
        "conversation_id": str(turn.conversation_id),
        "turn_id": str(turn.id),
        "kind": kind,
        "resource_id": resource_id,
    }


# ── refusals ──


def test_a_pick_of_another_companys_resource_is_refused_and_records_nothing(
    api_as, lan, cloud_sim: CloudSim
):
    web03 = cloud_sim.id_of("servers", "web-03")

    reply = api_as(lan).post(PICKS, pick(chat_of(lan), "server", web03), "application/json")

    assert reply.status_code == 404
    assert reply.json()["code"] == "infra_not_found"
    assert not ResourcePick.objects.exists()


def test_a_pick_naming_the_wrong_kind_is_refused(api_as, lan, cloud_sim: CloudSim):
    db01 = cloud_sim.id_of("servers", "db-01")

    reply = api_as(lan).post(PICKS, pick(chat_of(lan), "volume", db01), "application/json")

    assert reply.status_code == 404
    assert not ResourcePick.objects.exists()


def test_a_pick_in_someone_elses_conversation_is_refused_before_the_cloud_is_asked(
    api_as, lan, technician_user, cloud_sim: CloudSim
):
    db01 = cloud_sim.id_of("servers", "db-01")
    console = chat_of(lan, AgentSurface.CONSOLE)

    for turn in (chat_of(technician_user), console):
        reply = api_as(lan).post(PICKS, pick(turn, "server", db01), "application/json")

        assert reply.status_code == 404
        assert reply.json()["code"] == "conversation_not_found"
    assert not ResourcePick.objects.exists()
    assert cloud_sim.calls == []


def test_a_pick_on_an_ended_conversation_is_refused(api_as, lan, cloud_sim: CloudSim):
    db01 = cloud_sim.id_of("servers", "db-01")
    ended = chat_of(lan)
    agent_turns.end(ended.conversation, AgentConversationEnd.USER)

    reply = api_as(lan).post(PICKS, pick(ended, "server", db01), "application/json")

    assert reply.status_code == 409
    assert reply.json()["code"] == "conversation_ended"
    assert not ResourcePick.objects.exists()
    assert cloud_sim.calls == []


def test_a_pick_naming_a_turn_of_another_conversation_is_refused(api_as, lan, cloud_sim: CloudSim):
    db01 = cloud_sim.id_of("servers", "db-01")
    other = chat_of(lan)

    body = pick(chat_of(lan), "server", db01) | {"turn_id": str(other.id)}
    reply = api_as(lan).post(PICKS, body, "application/json")

    assert reply.status_code == 404
    assert reply.json()["code"] == "conversation_not_found"
    assert not ResourcePick.objects.exists()
    assert cloud_sim.calls == []


def test_keystone_down_refuses_a_pick_and_never_widens(api_as, lan, cloud_sim: CloudSim):
    db01 = cloud_sim.id_of("servers", "db-01")
    cloud_sim.cloud.add_fault(FaultKind.API_UNAVAILABLE, None, {})

    reply = api_as(lan).post(PICKS, pick(chat_of(lan), "server", db01), "application/json")

    assert reply.status_code == 424
    assert reply.json()["code"] == "infra_scope_unavailable"
    assert not ResourcePick.objects.exists()


def test_no_agent_tool_can_record_a_pick(lan, cloud_sim: CloudSim):
    db01 = cloud_sim.id_of("servers", "db-01")

    reply = as_agent(lan, "list_my_servers").post(
        PICKS, pick(chat_of(lan), "server", db01), "application/json"
    )

    assert reply.status_code == 403
    assert reply.json()["code"] == "agent_not_allowed"
    assert not ResourcePick.objects.exists()
    assert cloud_sim.calls == []


# ── recording ──


def test_a_pressed_resource_is_recorded_once_with_the_clouds_name_and_project(
    api_as, lan, cloud_sim: CloudSim
):
    turn = chat_of(lan)
    vol = cloud_sim.id_of("volumes", "vol-db-01")
    prod = cloud_sim.id_of("projects", "saomai-prod")

    first = api_as(lan).post(PICKS, pick(turn, "volume", vol), "application/json")
    again = api_as(lan).post(PICKS, pick(turn, "volume", vol), "application/json")

    assert first.status_code == again.status_code == 200
    assert first.json() == again.json()
    assert first.json() | {"picked_at": None} == {
        "conversation_id": str(turn.conversation_id),
        "turn_id": str(turn.id),
        "kind": "volume",
        "resource_id": vol,
        "name": "vol-db-01",
        "project_id": prod,
        "picked_at": None,
    }
    [row] = ResourcePick.objects.all()
    assert (row.person, row.conversation, row.turn) == (lan, turn.conversation, turn)


def test_pressing_a_resource_again_on_a_later_turn_records_it_for_that_turn(
    api_as, lan, cloud_sim: CloudSim
):
    db01 = cloud_sim.id_of("servers", "db-01")
    first = chat_of(lan)
    later = turn_in(first.conversation)

    for turn in (first, later):
        reply = api_as(lan).post(PICKS, pick(turn, "server", db01), "application/json")
        assert reply.json()["turn_id"] == str(turn.id)

    assert set(ResourcePick.objects.values_list("turn_id", flat=True)) == {first.id, later.id}


def test_a_pick_is_checked_as_the_persons_own_read(api_as, lan, cloud_sim: CloudSim):
    db01 = cloud_sim.id_of("servers", "db-01")

    api_as(lan).post(PICKS, pick(chat_of(lan), "server", db01), "application/json")

    assert {(q.via, q.actor_id, q.agent_turn_id) for q in InfraQuery.objects.all()} == {
        (InfraVia.HUMAN, lan.id, None)
    }
