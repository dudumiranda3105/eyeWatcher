"""Ponto de entrada da API do eyeWatcher.

Monta o FastAPI, CORS, o lifespan (startup: InfluxDB + MQTT; shutdown: fecha
limpo) e uma tarefa de fundo que fica re-testando o InfluxDB.

O servico NAO morre se o Mosquitto ou o InfluxDB estiverem fora no start:
ele apenas loga e segue tentando reconectar; `/api/health` reflete o estado real.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from collections.abc import AsyncIterator

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app import api
from app.config import Settings, get_settings
from app.influx import InfluxGateway
from app.mqtt_client import MqttService

logger = logging.getLogger("eyewatcher")

LOG_FORMAT = "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s"


def configure_logging(cfg: Settings) -> None:
    """Logging via modulo `logging` (nunca `print`)."""
    logging.basicConfig(
        level=getattr(logging, cfg.log_level.upper(), logging.INFO),
        format=LOG_FORMAT,
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    # O batching do influxdb-client e barulhento em DEBUG.
    logging.getLogger("influxdb_client.client.write.retry").setLevel(logging.WARNING)


async def _influx_watchdog(influx: InfluxGateway, interval_s: int) -> None:
    """Re-testa o InfluxDB periodicamente para que /api/health fique correto."""
    while True:
        try:
            await asyncio.sleep(max(interval_s, 5))
            await asyncio.to_thread(influx.ensure_connection)
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001
            logger.exception("Erro no watchdog do InfluxDB")


def create_app(cfg: Settings | None = None) -> FastAPI:
    """Fabrica da aplicacao (facilita testes)."""
    settings = cfg or get_settings()
    configure_logging(settings)

    influx = InfluxGateway(settings)
    mqtt_service = MqttService(settings, influx, event_sink=api.ws_manager.broadcast_threadsafe)
    api.configure(influx, mqtt_service, settings)

    @contextlib.asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        logger.info("Iniciando o backend do eyeWatcher")
        api.ws_manager.bind_loop(asyncio.get_running_loop())

        # Conectar sem bloquear o event loop; falhas sao apenas logadas.
        await asyncio.to_thread(influx.connect)
        mqtt_service.start()

        watchdog = asyncio.create_task(
            _influx_watchdog(influx, settings.influx_healthcheck_interval_s),
            name="influx-watchdog",
        )
        try:
            yield
        finally:
            logger.info("Encerrando o backend do eyeWatcher")
            watchdog.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await watchdog
            mqtt_service.stop()
            await asyncio.to_thread(influx.close)

    application = FastAPI(
        title="eyeWatcher API",
        description="Monitoramento IoT de rack de servidores (ESP32 -> MQTT -> InfluxDB -> Web).",
        version="1.0.0",
        lifespan=lifespan,
    )
    application.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins_list,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    application.include_router(api.router)
    return application


app: FastAPI = create_app()


if __name__ == "__main__":
    import uvicorn

    _cfg = get_settings()
    uvicorn.run(
        "app.main:app",
        host=_cfg.api_host,
        port=_cfg.api_port,
        reload=False,
        log_level=_cfg.log_level.lower(),
    )
