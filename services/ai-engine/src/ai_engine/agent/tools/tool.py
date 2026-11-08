"""
A tool: one core-api route the agent may call, the arguments the model
gives it, and the projection of its answer the model sees (spec F15 §h.1).
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from string import Formatter
from typing import Any, Literal
from urllib.parse import quote
from uuid import UUID

from pydantic import BaseModel, ConfigDict, SecretStr

from ai_engine.agent.tools.client import CoreApi, Reply


class Tier(StrEnum):
    """The route's agent tier in core-api (ADR-0046 §5)."""

    READ = "read"
    SELF = "self"
    CONFIRM = "confirm"
    HUMAN_ONLY = "human_only"


class ToolInput(BaseModel):
    """A tool's arguments. Unknown keys are refused."""

    model_config = ConfigDict(extra="forbid", frozen=True)


@dataclass(frozen=True)
class Context:
    """Who the turn acts for, as code needs it; none of it reaches the model."""

    token: SecretStr
    actor_id: UUID | None
    actor_username: str
    chat_conversation_id: UUID | None


@dataclass(frozen=True)
class Tool:
    """One route. Path fields come from the arguments of the same name; `query`
    names the arguments sent as query parameters; the rest is the JSON body,
    with `fixed` added."""

    name: str
    surface: Literal["chat", "console"]
    tier: Tier
    method: str
    path: str
    Input: type[ToolInput]
    description: str
    project: Callable[[Any, Context], Any]
    query: tuple[str, ...] = ()
    fixed: Mapping[str, Any] = field(default_factory=dict)

    @property
    def writes(self) -> bool:
        """Whether the route changes anything."""
        return self.tier is not Tier.READ

    def path_for(self, values: Mapping[str, Any]) -> str:
        """The route's path with `values` filled in."""
        names = [name for _, name, _, _ in Formatter().parse(self.path) if name]
        return self.path.format(**{name: quote(str(values[name]), safe="") for name in names})

    def run(self, api: CoreApi, args: ToolInput, context: Context) -> tuple[str, Reply]:
        """Calls the route once; the path sent and core-api's reply."""
        values = args.model_dump(mode="json", exclude_none=True)
        path = self.path_for(values)
        in_path = {name for _, name, _, _ in Formatter().parse(self.path) if name}
        params = {k: v for k, v in values.items() if k in self.query}
        body = {k: v for k, v in values.items() if k not in in_path and k not in self.query}
        json = None if self.method == "GET" else {**body, **self.fixed}
        return path, api.send(self.method, path, context.token, params=params or None, json=json)

    def describe(self) -> dict[str, Any]:
        """The tool as the prompt lists it."""
        return {
            "name": self.name,
            "description": self.description,
            "arguments": self.Input.model_json_schema(),
        }
