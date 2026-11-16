"""
The F15 agent graph (spec F15 §h.6): its route list and `agent_graph`,
compiled once at import. `tests/test_agent_graph.py` pins its edges.

1. The person's message is screened before any model call; a hit hands off.
2. The only loop is choose_action → call_tool → choose_action. choose_action
   stops at its caps (steps, tool calls, tokens) without calling the model,
   and its limit outcome leaves the loop, so the graph is `Cycles.BOUNDED`.
3. A confirm route's 202 ends the turn: the person confirms the card.
4. A failure, an unknown write outcome, a refused token or a write after an
   injection hit in a result hands off. Nothing is retried.
"""

from __future__ import annotations

from ai_engine.graph.agent_state import AgentState
from ai_engine.graph.build.builder import GraphBuilder
from ai_engine.graph.build.graph import Cycles
from ai_engine.graph.build.node import SingleExit
from ai_engine.graph.nodes.agent.call_tool import CallOutcome, call_tool
from ai_engine.graph.nodes.agent.choose import ChooseOutcome, choose_action
from ai_engine.graph.nodes.agent.end import finish, hand_off
from ai_engine.graph.nodes.agent.screen import ScreenOutcome, screen_message

_agent = GraphBuilder(entry=screen_message, cycles=Cycles.BOUNDED)

# An injected message reaches no model.
_agent.route(screen_message, ScreenOutcome.INJECTION_DETECTED, hand_off)
_agent.route(screen_message, ScreenOutcome.CLEAR, choose_action)

_agent.route(choose_action, ChooseOutcome.CALL_TOOL, call_tool)
_agent.route(choose_action, ChooseOutcome.REPLY, finish)
# Steps, tool calls or tokens used up: no made-up answer.
_agent.route(choose_action, ChooseOutcome.LIMIT_REACHED, hand_off)
_agent.route(choose_action, ChooseOutcome.MODEL_FAILED, hand_off)
_agent.route(choose_action, ChooseOutcome.SCHEMA_INVALID, hand_off)

_agent.route(call_tool, CallOutcome.RESULT, choose_action)
_agent.route(call_tool, CallOutcome.DRAFTED, choose_action)
_agent.route(call_tool, CallOutcome.AWAITING_CONFIRMATION, finish)
_agent.route(call_tool, CallOutcome.FAILED, hand_off)
# A write whose answer was lost is never sent again.
_agent.route(call_tool, CallOutcome.OUTCOME_UNKNOWN, hand_off)

_agent.route(finish, SingleExit.DONE, _agent.end)
_agent.route(hand_off, SingleExit.DONE, _agent.end)
agent_graph = _agent.compile(AgentState)


def recursion_limit(max_steps: int) -> int:
    """LangGraph's step cap for a turn: a backstop above the graph's own limits."""
    return 2 * max_steps + 5
