"""Celery entry points for the agent (F15 §h.5); the work is in `utils/turns.py`."""

from __future__ import annotations

import dataclasses
import uuid

from celery import shared_task

from apps.agent.utils.turns import agent_turns


@shared_task(name="agent.run_turn", max_retries=0)
def run_turn(turn_id: str) -> None:
    agent_turns.run(uuid.UUID(turn_id))


@shared_task(name="agent.sweep")
def sweep() -> dict[str, int]:
    return dataclasses.asdict(agent_turns.sweep())
