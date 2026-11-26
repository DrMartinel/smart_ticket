"""Nova and Cinder: servers, their actions and states, and volume attachments."""

from __future__ import annotations

from cloud_sim.testing import TRANSITION_SEC, Sim

from cloud_sim.faults import FaultKind


def _action(sim: Sim, server: str, body: dict[str, object]) -> int:
    path = f"/compute/v2.1/servers/{sim.id_of('server', server)}/action"
    return sim.client.post(path, json=body, headers=sim.headers).status_code


def _status(sim: Sim, server: str) -> str:
    reply = sim.client.get(
        f"/compute/v2.1/servers/{sim.id_of('server', server)}", headers=sim.headers
    )
    status: str = reply.json()["server"]["status"]
    return status


def test_servers_filter_by_project(sim: Sim) -> None:
    project = sim.id_of("project", "hbr-web")

    reply = sim.client.get(
        "/compute/v2.1/servers/detail",
        params={"all_tenants": 1, "project_id": project},
        headers=sim.headers,
    )

    assert {s["name"] for s in reply.json()["servers"]} == {"web-03", "web-04", "cache-01"}


def test_an_unknown_server_is_404(sim: Sim) -> None:
    reply = sim.client.get("/compute/v2.1/servers/nope", headers=sim.headers)

    assert reply.status_code == 404
    assert "itemNotFound" in reply.json()


def test_a_soft_reboot_finishes_after_the_transition(sim: Sim) -> None:
    assert _action(sim, "db-01", {"reboot": {"type": "SOFT"}}) == 202
    assert _status(sim, "db-01") == "REBOOT"

    sim.clock.advance(TRANSITION_SEC)

    assert _status(sim, "db-01") == "ACTIVE"


def test_a_stopped_server_cannot_be_soft_rebooted(sim: Sim) -> None:
    _action(sim, "db-01", {"os-stop": None})
    sim.clock.advance(TRANSITION_SEC)

    assert _action(sim, "db-01", {"reboot": {"type": "SOFT"}}) == 409


def test_a_running_server_cannot_be_started(sim: Sim) -> None:
    assert _action(sim, "db-01", {"os-start": None}) == 409


def test_an_unknown_reboot_type_is_400(sim: Sim) -> None:
    assert _action(sim, "db-01", {"reboot": {"type": "GENTLE"}}) == 400


def test_a_soft_reboot_does_not_wake_a_hung_server(sim: Sim) -> None:
    server = sim.id_of("server", "db-01")
    sim.cloud.add_fault(FaultKind.SERVER_HUNG, server, {})

    _action(sim, "db-01", {"reboot": {"type": "SOFT"}})
    sim.clock.advance(TRANSITION_SEC)

    with sim.cloud.reading():
        assert not sim.cloud.is_up(sim.cloud.servers[server])


def test_a_hard_reboot_wakes_a_hung_server(sim: Sim) -> None:
    server = sim.id_of("server", "db-01")
    sim.cloud.add_fault(FaultKind.SERVER_HUNG, server, {})

    _action(sim, "db-01", {"reboot": {"type": "HARD"}})
    sim.clock.advance(TRANSITION_SEC)

    with sim.cloud.reading():
        assert sim.cloud.is_up(sim.cloud.servers[server])


def test_a_crash_looping_server_shows_error_and_can_be_hard_rebooted(sim: Sim) -> None:
    sim.cloud.add_fault(FaultKind.CRASH_LOOP, sim.id_of("server", "app-01"), {})

    assert _status(sim, "app-01") == "ERROR"
    assert _action(sim, "app-01", {"reboot": {"type": "SOFT"}}) == 409
    assert _action(sim, "app-01", {"reboot": {"type": "HARD"}}) == 202


def test_a_free_volume_attaches_and_detaches(sim: Sim) -> None:
    server, volume = sim.id_of("server", "db-01"), sim.id_of("volume", "vol-backup-01")
    path = f"/compute/v2.1/servers/{server}/os-volume_attachments"

    attached = sim.client.post(
        path, json={"volumeAttachment": {"volumeId": volume}}, headers=sim.headers
    )
    detached = sim.client.delete(f"{path}/{volume}", headers=sim.headers)
    during = sim.client.get(f"/volume/v3/x/volumes/{volume}", headers=sim.headers).json()["volume"][
        "status"
    ]
    sim.clock.advance(TRANSITION_SEC)
    after = sim.client.get(f"/volume/v3/x/volumes/{volume}", headers=sim.headers).json()["volume"]

    assert attached.status_code == 200
    assert detached.status_code == 202
    assert during == "detaching"
    assert after["status"] == "available"
    assert after["attachments"] == []


def test_a_volume_cannot_attach_across_projects(sim: Sim) -> None:
    server, volume = sim.id_of("server", "web-03"), sim.id_of("volume", "vol-backup-01")

    reply = sim.client.post(
        f"/compute/v2.1/servers/{server}/os-volume_attachments",
        json={"volumeAttachment": {"volumeId": volume}},
        headers=sim.headers,
    )

    assert reply.status_code == 400


def test_an_attached_volume_cannot_attach_again(sim: Sim) -> None:
    server, volume = sim.id_of("server", "app-01"), sim.id_of("volume", "vol-db-01")

    reply = sim.client.post(
        f"/compute/v2.1/servers/{server}/os-volume_attachments",
        json={"volumeAttachment": {"volumeId": volume}},
        headers=sim.headers,
    )

    assert reply.status_code == 409


def test_detaching_a_volume_from_the_wrong_server_is_404(sim: Sim) -> None:
    server, volume = sim.id_of("server", "app-01"), sim.id_of("volume", "vol-db-01")

    reply = sim.client.delete(
        f"/compute/v2.1/servers/{server}/os-volume_attachments/{volume}", headers=sim.headers
    )

    assert reply.status_code == 404


def test_volumes_list_by_project_for_an_admin(sim: Sim) -> None:
    project = sim.id_of("project", "saomai-prod")

    reply = sim.client.get(
        "/volume/v3/admin/volumes/detail",
        params={"all_tenants": 1, "project_id": project},
        headers=sim.headers,
    )

    assert {v["name"] for v in reply.json()["volumes"]} == {
        "vol-db-01",
        "vol-app-01",
        "vol-backup-01",
    }


def _task_state(sim: Sim, server: str) -> str | None:
    reply = sim.client.get(
        f"/compute/v2.1/servers/{sim.id_of('server', server)}", headers=sim.headers
    )
    task: str | None = reply.json()["server"]["OS-EXT-STS:task_state"]
    return task


def test_an_action_during_a_transition_is_409(sim: Sim) -> None:
    volume = sim.id_of("volume", "vol-backup-01")
    path = f"/compute/v2.1/servers/{sim.id_of('server', 'db-01')}/os-volume_attachments"
    assert _action(sim, "db-01", {"os-stop": None}) == 202

    assert _task_state(sim, "db-01") == "powering-off"
    assert _action(sim, "db-01", {"os-stop": None}) == 409
    assert _action(sim, "db-01", {"reboot": {"type": "SOFT"}}) == 409
    assert _action(sim, "db-01", {"reboot": {"type": "HARD"}}) == 409
    attach = {"volumeAttachment": {"volumeId": volume}}
    assert sim.client.post(path, json=attach, headers=sim.headers).status_code == 409
    data = sim.id_of("volume", "vol-db-01")
    assert sim.client.delete(f"{path}/{data}", headers=sim.headers).status_code == 409

    sim.clock.advance(TRANSITION_SEC)

    assert _status(sim, "db-01") == "SHUTOFF"
    assert _task_state(sim, "db-01") is None


def test_a_start_shows_powering_on_until_it_settles(sim: Sim) -> None:
    _action(sim, "db-01", {"os-stop": None})
    sim.clock.advance(TRANSITION_SEC)

    assert _action(sim, "db-01", {"os-start": None}) == 202
    assert _task_state(sim, "db-01") == "powering-on"
    assert _action(sim, "db-01", {"os-start": None}) == 409

    sim.clock.advance(TRANSITION_SEC)

    assert _status(sim, "db-01") == "ACTIVE"


def test_a_reattached_volume_takes_a_free_device_name(sim: Sim) -> None:
    server = sim.id_of("server", "db-01")
    data, backup = sim.id_of("volume", "vol-db-01"), sim.id_of("volume", "vol-backup-01")
    path = f"/compute/v2.1/servers/{server}/os-volume_attachments"

    def attach(volume: str) -> str:
        reply = sim.client.post(
            path, json={"volumeAttachment": {"volumeId": volume}}, headers=sim.headers
        )
        device: str = reply.json()["volumeAttachment"]["device"]
        return device

    second = attach(backup)
    sim.client.delete(f"{path}/{data}", headers=sim.headers)
    sim.clock.advance(TRANSITION_SEC)
    again = attach(data)

    assert second == "/dev/vdc"
    assert again == "/dev/vdb"


def test_a_hard_reboot_may_follow_a_soft_one(sim: Sim) -> None:
    assert _action(sim, "db-01", {"reboot": {"type": "SOFT"}}) == 202
    assert _action(sim, "db-01", {"reboot": {"type": "HARD"}}) == 202

    assert _task_state(sim, "db-01") == "rebooting_hard"
    assert _action(sim, "db-01", {"reboot": {"type": "SOFT"}}) == 409


def test_volumes_list_without_a_project_in_the_path(sim: Sim) -> None:
    project = sim.id_of("project", "hbr-web")

    every = sim.client.get("/volume/v3/volumes/detail", headers=sim.headers)
    one = sim.client.get(
        "/volume/v3/volumes/detail",
        params={"all_tenants": True, "project_id": project},
        headers=sim.headers,
    )
    volume = sim.client.get(
        f"/volume/v3/volumes/{sim.id_of('volume', 'vol-web-03')}", headers=sim.headers
    )

    assert len(every.json()["volumes"]) == len(sim.cloud.volumes)
    assert {v["name"] for v in one.json()["volumes"]} == {"vol-web-03"}
    assert volume.json()["volume"]["name"] == "vol-web-03"
