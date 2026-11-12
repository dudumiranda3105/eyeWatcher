"""Monta o FastAPI: conexoes, consumidores e rotas."""

from __future__ import annotations

import asyncio
import contextlib
import functools
from collections.abc import AsyncIterator

from fastapi import FastAPI, Request, WebSocket, status
from fastapi.responses import JSONResponse
from influxdb_client import InfluxDBClient

from eyewatcher.api import assistant, auth, db, live, routes
from eyewatcher.api.state import AppState
from eyewatcher.bus import Bus, BusUnavailableError
from eyewatcher.healthcheck import heartbeat_loop
from eyewatcher.settings import get_settings


@contextlib.asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    cfg = get_settings()
    pool = await db.connect(cfg)
    await db.migrate_and_seed(pool, cfg)

    bus = Bus(cfg)
    await bus.connect()
    state = AppState(
        cfg=cfg,
        db=pool,
        bus=bus,
        influx=InfluxDBClient(url=cfg.influx_url, token=cfg.secret("influx"), org=cfg.influx_org),
        jwt_secret=cfg.secret("jwt"),
    )
    app.state.eyewatcher = state

    await live.load_rules(state)
    await bus.consume("q.live.ws", functools.partial(live.on_live, state), prefetch=100)
    await bus.consume("q.telemetry.rules", functools.partial(live.on_rules, state))
    await bus.consume("q.api.persist", functools.partial(live.on_persist, state))
    await live.publish_device_config(state)

    tasks = [
        asyncio.create_task(heartbeat_loop()),
        asyncio.create_task(assistant.warm_model(state)),
    ]
    yield
    for task in tasks:
        task.cancel()
    await bus.close()
    await pool.close()
    state.influx.close()


def create_app() -> FastAPI:
    app = FastAPI(
        title="eyeWatcher",
        version="2.0.0",
        description="Monitoramento AIoT de salas de servidores.",
        lifespan=lifespan,
        docs_url="/api/docs",
        openapi_url="/api/openapi.json",
        redoc_url=None,
    )
    app.include_router(auth.router, prefix="/api")
    app.include_router(routes.router, prefix="/api")

    @app.exception_handler(BusUnavailableError)
    async def bus_unavailable(_request: Request, _exc: BusUnavailableError) -> JSONResponse:
        return JSONResponse({"detail": "RabbitMQ indisponível; tente de novo em instantes"}, 503)

    @app.websocket("/ws/live")
    async def websocket_live(websocket: WebSocket, ticket: str = "") -> None:
        if auth.tickets.redeem(ticket) is None:
            await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
            return
        await live.serve_websocket(app.state.eyewatcher, websocket)

    return app
