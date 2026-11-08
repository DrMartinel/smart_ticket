"""The agent's tools, by name and by surface (spec F15 §h.1)."""

from __future__ import annotations

from ai_engine.agent.tools import chat, console
from ai_engine.agent.tools.tool import Tool

TOOLS: dict[str, Tool] = {tool.name: tool for tool in (*chat.TOOLS, *console.TOOLS)}


def for_surface(surface: str) -> dict[str, Tool]:
    """The tools a surface offers: the chat's to an employee, the console's to a technician."""
    return {name: tool for name, tool in TOOLS.items() if tool.surface == surface}
