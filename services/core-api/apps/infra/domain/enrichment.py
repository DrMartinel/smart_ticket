"""Which of a reporter's cloud resources a ticket is about: the names and IDs its masked text
holds, then the volumes attached to the servers it names, or every server when it names none
and there are few enough (F17 BR-F17-14, BR-F17-24)."""

from __future__ import annotations

import re
from dataclasses import dataclass

from apps.infra.domain.resources import Network, Server, Volume
from apps.infra.domain.vocabulary import ResourceKind, ResourceSource


@dataclass(frozen=True)
class Resource:
    kind: ResourceKind
    id: str
    name: str
    project_id: str


@dataclass(frozen=True)
class Found:
    """A resource a run links, how it came to, and the text that named it."""

    resource: Resource
    source: ResourceSource
    token: str | None = None


@dataclass(frozen=True)
class Holdings:
    """The servers, volumes and networks in the reporter's projects."""

    servers: list[Server]
    volumes: list[Volume]
    networks: list[Network]

    def resources(self) -> list[Resource]:
        """Every server, volume and network, in that order."""
        return [
            *(Resource(ResourceKind.SERVER, s.id, s.name, s.project_id) for s in self.servers),
            *(Resource(ResourceKind.VOLUME, v.id, v.name, v.project_id) for v in self.volumes),
            *(Resource(ResourceKind.NETWORK, n.id, n.name, n.project_id) for n in self.networks),
        ]

    def attached_to(self, server_id: str) -> list[Resource]:
        """The volumes attached to the server `server_id`, by name."""
        return [
            Resource(ResourceKind.VOLUME, v.id, v.name, v.project_id)
            for v in sorted(self.volumes, key=lambda v: v.name)
            if any(a.server_id == server_id for a in v.attachments)
        ]


def named_in(text: str, resources: list[Resource]) -> list[Found]:
    """The resources whose name or ID `text` holds as a whole word, in the order they first
    appear."""
    hits: list[tuple[int, int, Found]] = []
    for order, resource in enumerate(resources):
        matches = [
            m
            for needle in {resource.name, resource.id} - {""}
            if (m := re.search(rf"(?<![\w-]){re.escape(needle)}(?![\w-])", text, re.IGNORECASE))
        ]
        if matches:
            first = min(matches, key=lambda m: m.start())
            hits.append((first.start(), order, Found(resource, ResourceSource.NAMED, first[0])))
    return [found for _, _, found in sorted(hits, key=lambda h: (h[0], h[1]))]


def linked(holdings: Holdings, text: str | None, cap: int) -> list[Found]:
    """The resources a run links, at most `cap`: those `text` names, then the volumes attached
    to the servers among them; when it names none (or is None, for a ticket whose masking
    failed), every server and their attached volumes if there are no more than `cap` servers,
    else none."""
    taken = named_in(text, holdings.resources()) if text is not None else []
    if not taken:
        if len(holdings.servers) > cap:
            return []
        taken = [
            Found(
                Resource(ResourceKind.SERVER, s.id, s.name, s.project_id),
                ResourceSource.EVERY_SERVER,
            )
            for s in sorted(holdings.servers, key=lambda s: s.name)
        ]
    attached = [
        Found(volume, ResourceSource.ATTACHED)
        for found in taken
        if found.resource.kind is ResourceKind.SERVER
        for volume in holdings.attached_to(found.resource.id)
    ]
    kept: dict[str, Found] = {}
    for found in [*taken, *attached]:
        kept.setdefault(found.resource.id, found)
    return list(kept.values())[:cap]
