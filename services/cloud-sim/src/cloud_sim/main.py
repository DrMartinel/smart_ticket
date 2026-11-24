"""The cloud-sim app: the OpenStack routes, the simulator's routes, `/metrics` and the telemetry ticker."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from datetime import UTC, datetime

from fastapi import FastAPI, Request, Response
from fastapi.responses import JSONResponse
from prometheus_client import CONTENT_TYPE_LATEST, CollectorRegistry, generate_latest

from cloud_sim.api import compute, errors, identity, network, sim, volume
from cloud_sim.cloud import Clock, Cloud
from cloud_sim.config import Settings
from cloud_sim.faults import FaultKind
from cloud_sim.seed import Seed
from cloud_sim.telemetry.export import Exporter
from cloud_sim.telemetry.metrics import CloudCollector, Telemetry
from cloud_sim.telemetry.signals import plan

log = logging.getLogger("cloud_sim")

# Path prefixes that are OpenStack's, where API faults apply.
_OPENSTACK = ("/identity", "/compute", "/volume", "/network")


def utc_now() -> datetime:
    return datetime.now(UTC)


def create_app(
    settings: Settings,
    *,
    clock: Clock = utc_now,
    exporter: Callable[[Cloud], Exporter] | None = None,
    tick: bool = True,
) -> FastAPI:
    """The app, with its cloud built from the packaged seed."""
    cloud = Cloud(
        Seed.packaged(),
        clock=clock,
        transition_sec=settings.transition_sec,
        service_user=settings.service_user,
        service_password=settings.service_password.get_secret_value(),
    )
    telemetry = Telemetry()
    registry = CollectorRegistry()
    registry.register(CloudCollector(cloud, telemetry))
    sender = (
        exporter(cloud) if exporter is not None else Exporter.otlp(cloud, settings.otlp_endpoint)
    )

    async def run_ticks() -> None:
        while True:
            await asyncio.sleep(settings.tick_sec)
            try:
                telemetry.advance(cloud, settings.tick_sec)
                emission = plan(cloud, telemetry.tick, cloud.now())
                await asyncio.to_thread(sender.send, emission)
            except Exception:
                log.exception("telemetry tick failed")

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        task = asyncio.create_task(run_ticks()) if tick else None
        yield
        if task is not None:
            task.cancel()
        sender.shutdown()

    app = FastAPI(title="cloud-sim", lifespan=lifespan)
    app.state.cloud = cloud
    app.state.telemetry = telemetry
    app.state.exporter = sender
    app.state.tokens = identity.Tokens(cloud, settings.token_ttl_sec)
    app.add_exception_handler(errors.ApiError, errors.handle)
    for router in (identity.router, compute.router, volume.router, network.router, sim.router):
        app.include_router(router)

    @app.middleware("http")
    async def api_faults(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        if request.url.path.startswith(_OPENSTACK):
            if cloud.fault_on(FaultKind.API_UNAVAILABLE, None) is not None:
                return JSONResponse({"message": "Service Unavailable"}, status_code=503)
            if (slow := cloud.fault_on(FaultKind.API_SLOW, None)) is not None:
                await asyncio.sleep(float(slow.params["delay_sec"]))
        return await call_next(request)

    @app.get("/metrics")
    def metrics() -> Response:
        return Response(generate_latest(registry), media_type=CONTENT_TYPE_LATEST)

    return app


# --- the served app ---


def served() -> FastAPI:
    """The app uvicorn serves, configured from the environment."""
    logging.basicConfig(level=logging.INFO)
    return create_app(Settings())  # type: ignore[call-arg]
