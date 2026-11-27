"""Which resources a ticket is about: the reporter's picks, then the names its masked text holds,
then attached volumes (F17 BR-F17-14, BR-F17-24)."""

from __future__ import annotations

from apps.infra.domain.enrichment import Holdings, Resource, linked, named_in
from apps.infra.domain.resources import Attachment, Server, Volume
from apps.infra.domain.vocabulary import ResourceKind, ResourceSource


def server(name: str) -> Server:
    return Server(
        id=f"id-{name}",
        name=name,
        project_id="p1",
        status="ACTIVE",
        task_state=None,
        host="h1",
        flavor="m1",
        vcpus=1,
        ram_mb=1024,
        addresses=[],
        volume_ids=[],
        security_groups=[],
        description="",
        metadata={},
        created="",
        updated="",
    )


def volume(name: str, attached_to: str | None = None) -> Volume:
    return Volume(
        id=f"id-{name}",
        name=name,
        project_id="p1",
        status="in-use" if attached_to else "available",
        size_gb=10,
        volume_type="ssd",
        attachments=[Attachment(f"id-{name}", f"id-{attached_to}", "/dev/vdb")]
        if attached_to
        else [],
        description="",
        metadata={},
        created="",
    )


def names(found: list) -> list[tuple[str, ResourceSource, str | None]]:
    return [(f.resource.name, f.source, f.token) for f in found]


def test_a_name_inside_a_longer_name_is_not_matched():
    resources = [Resource(ResourceKind.SERVER, "id-db-01", "db-01", "p1")]

    assert named_in("app-db-01 và db-01x đều chậm", resources) == []
    assert names(named_in("DB-01, chậm", resources)) == [("db-01", ResourceSource.NAMED, "DB-01")]


def test_a_resource_named_by_its_id_is_matched_in_the_order_it_appears():
    resources = [
        Resource(ResourceKind.SERVER, "id-db-01", "db-01", "p1"),
        Resource(ResourceKind.VOLUME, "id-vol-app-01", "vol-app-01", "p1"),
    ]

    found = named_in("id-vol-app-01 đầy, rồi db-01 chậm", resources)

    assert names(found) == [
        ("vol-app-01", ResourceSource.NAMED, "id-vol-app-01"),
        ("db-01", ResourceSource.NAMED, "db-01"),
    ]


def test_more_servers_than_the_cap_and_no_name_links_nothing():
    holdings = Holdings([server("a"), server("b"), server("c"), server("d")], [], [])

    assert linked(holdings, [], "Hệ thống chạy chậm", 3) == []
    assert linked(holdings, [], None, 3) == []


def test_every_server_comes_before_the_volumes_attached_to_them():
    holdings = Holdings([server("b"), server("a")], [volume("vol-a", "a")], [])

    assert names(linked(holdings, [], "chậm", 3)) == [
        ("a", ResourceSource.EVERY_SERVER, None),
        ("b", ResourceSource.EVERY_SERVER, None),
        ("vol-a", ResourceSource.ATTACHED, None),
    ]


def test_picks_come_first_then_names_then_attached_volumes():
    holdings = Holdings(
        [server("db-01"), server("app-01"), server("app-02")], [volume("vol-db-01", "db-01")], []
    )

    found = linked(holdings, [(ResourceKind.SERVER, "id-app-02")], "db-01, app-01, app-02", 3)

    assert names(found) == [
        ("app-02", ResourceSource.PICKED, None),
        ("db-01", ResourceSource.NAMED, "db-01"),
        ("app-01", ResourceSource.NAMED, "app-01"),
    ]


def test_a_pick_the_reporters_projects_do_not_hold_is_dropped():
    holdings = Holdings([server("db-01")], [], [])

    picked = [(ResourceKind.SERVER, "id-web-03"), (ResourceKind.VOLUME, "id-db-01")]

    assert names(linked(holdings, picked, None, 3)) == [
        ("db-01", ResourceSource.EVERY_SERVER, None)
    ]
