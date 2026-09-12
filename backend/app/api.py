"""Rotas HTTP e WebSocket do eyeWatcher (ver `docs/CONTRACT.md` secao 5)."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from typing import Any

from fastapi import APIRouter, HTTPException, Query, WebSocket, WebSocketDisconnect

from app.config import Settings
from app.influx import (
    InfluxGateway,
    InfluxUnavailableError,
    is_valid_rack_id,
    is_valid_window,
)
from app.models import (
    DEFAULT_RANGE,
    DEFAULT_WINDOW,
    RANGE_VALUES,
    AlertsOut,
    HealthOut,
    HistoryOut,
    LatestOut,
    MetricStats,
    RackOut,
    StatsOut,
)
from app.mqtt_client import MqttService

logger = logging.getLogger(__name__)

router = APIRouter()

DETAIL_RACK_NOT_FOUND = "rack não encontrado"
DETAIL_INFLUX_DOWN = "influxdb indisponível"


# --------------------------------------------------------------------------- #
# WebSocket — gerenciador de conexoes
# --------------------------------------------------------------------------- #
class ConnectionManager:
    """Mantem os websockets conectados e faz broadcast removendo os mortos."""

    def __init__(self) -> None:
        self._clients: set[WebSocket] = set()
        self._loop: asyncio.AbstractEventLoop | None = None

    def bind_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        """Guarda o event loop para permitir broadcast a partir da thread MQTT."""
        self._loop = loop

    @property
    def count(self) -> int:
        return len(self._clients)

    async def connect(self, websocket: WebSocket) -> None:
        await websocket.accept()
        self._clients.add(websocket)
        logger.info("WebSocket conectado (%d cliente(s))", len(self._clients))

    def disconnect(self, websocket: WebSocket) -> None:
        self._clients.discard(websocket)
        logger.info("WebSocket desconectado (%d cliente(s))", len(self._clients))

    async def broadcast(self, event: dict[str, Any]) -> None:
        """Envia o evento a todos os clientes; remove os que falharem."""
        if not self._clients:
            return
        dead: list[WebSocket] = []
        for websocket in list(self._clients):
            try:
                await websocket.send_json(event)
            except Exception:  # noqa: BLE001 — cliente caiu/fechou
                dead.append(websocket)
        for websocket in dead:
            self._clients.discard(websocket)
        if dead:
            logger.info("Removidos %d websocket(s) desconectado(s)", len(dead))

    def broadcast_threadsafe(self, event: dict[str, Any]) -> None:
        """Ponte thread MQTT -> event loop asyncio."""
        loop = self._loop
        if loop is None or loop.is_closed() or not self._clients:
            return
        try:
            asyncio.run_coroutine_threadsafe(self.broadcast(event), loop)
        except RuntimeError as exc:
            logger.debug("Broadcast ignorado (loop indisponivel): %s", exc)


ws_manager = ConnectionManager()


# --------------------------------------------------------------------------- #
# Injecao de dependencias (preenchida por main.py no startup)
# --------------------------------------------------------------------------- #
_influx: InfluxGateway | None = None
_mqtt: MqttService | None = None
_settings: Settings | None = None


def configure(influx: InfluxGateway, mqtt_service: MqttService, cfg: Settings) -> None:
    """Liga as rotas aos servicos criados no lifespan da aplicacao."""
    global _influx, _mqtt, _settings
    _influx, _mqtt, _settings = influx, mqtt_service, cfg


def get_influx() -> InfluxGateway:
    if _influx is None:
        raise HTTPException(
            status_code=503, detail=DETAIL_INFLUX_DOWN
        )
    return _influx


# --------------------------------------------------------------------------- #
# Validacao de parametros
# --------------------------------------------------------------------------- #
def validate_range(range_: str) -> str:
    if range_ not in RANGE_VALUES:
        raise HTTPException(
            status_code=422,
            detail=f"range inválido: use um de {', '.join(RANGE_VALUES)}",
        )
    return range_


def validate_rack_id(rack_id: str) -> str:
    if not is_valid_rack_id(rack_id):
        raise HTTPException(
            status_code=422,
            detail="rack_id inválido",
        )
    return rack_id


def validate_window(window: str) -> str:
    if not is_valid_window(window):
        raise HTTPException(
            status_code=422,
            detail="window inválido: use uma duração como 30s, 1m, 5m ou 1h",
        )
    return window


async def run_query(func: Callable[..., Any], *args: Any) -> Any:
    """Executa uma query sincrona fora do event loop, traduzindo falhas em 503."""
    try:
        return await asyncio.to_thread(func, *args)
    except InfluxUnavailableError as exc:
        logger.warning("InfluxDB indisponivel ao atender requisicao: %s", exc)
        raise HTTPException(
            status_code=503, detail=DETAIL_INFLUX_DOWN
        ) from exc


async def ensure_rack_exists(influx: InfluxGateway, rack_id: str) -> None:
    exists = await run_query(influx.rack_exists, rack_id)
    if not exists:
        raise HTTPException(
            status_code=404, detail=DETAIL_RACK_NOT_FOUND
        )


# --------------------------------------------------------------------------- #
# Rotas
# --------------------------------------------------------------------------- #
@router.get("/api/health", response_model=HealthOut, tags=["sistema"])
async def health() -> HealthOut:
    """Saude dos subsistemas. Responde 200 mesmo com MQTT/Influx fora."""
    influx_ok = _influx.healthy if _influx is not None else False
    mqtt_ok = _mqtt.connected if _mqtt is not None else False
    return HealthOut(
        status="ok" if (influx_ok and mqtt_ok) else "degraded",
        influx=influx_ok,
        mqtt=mqtt_ok,
    )


@router.get("/api/racks", response_model=list[RackOut], tags=["racks"])
async def list_racks() -> list[RackOut]:
    """Lista de racks com a ultima leitura de cada um."""
    influx = get_influx()
    rows = await run_query(influx.query_latest_rows, None)
    online_map: dict[str, bool] = await run_query(influx.query_online_map)

    racks: list[RackOut] = []
    for row in rows:
        rack_id = str(row.get("rack_id") or "")
        if not rack_id:
            continue
        racks.append(
            RackOut(
                rack_id=rack_id,
                device_id=str(row.get("device_id") or f"esp32-{rack_id}"),
                location=str(row.get("location") or ""),
                online=bool(online_map.get(rack_id, False)),
                last_reading=InfluxGateway.row_to_reading(row),
            )
        )
    racks.sort(key=lambda r: r.rack_id)
    return racks


@router.get("/api/readings/latest", response_model=LatestOut, tags=["leituras"])
async def latest_reading(
    rack_id: str = Query(..., description="Identificador do rack, ex.: rack01"),
) -> LatestOut:
    """Ultima leitura do rack."""
    influx = get_influx()
    validate_rack_id(rack_id)
    rows = await run_query(influx.query_latest_rows, rack_id)
    if not rows:
        raise HTTPException(
            status_code=404, detail=DETAIL_RACK_NOT_FOUND
        )
    row = rows[0]
    reading = InfluxGateway.row_to_reading(row)
    online_map: dict[str, bool] = await run_query(influx.query_online_map)
    return LatestOut(
        rack_id=rack_id,
        device_id=str(row.get("device_id") or f"esp32-{rack_id}"),
        location=str(row.get("location") or ""),
        online=bool(online_map.get(rack_id, False)),
        time=reading.time,
        temperature=reading.temperature,
        humidity=reading.humidity,
        heat_index=reading.heat_index,
        status=reading.status,
    )


@router.get("/api/readings/history", response_model=HistoryOut, tags=["leituras"])
async def readings_history(
    rack_id: str = Query(..., description="Identificador do rack"),
    range: str = Query(DEFAULT_RANGE, description=f"Um de: {', '.join(RANGE_VALUES)}"),
    window: str = Query(DEFAULT_WINDOW, description="Janela de agregacao, ex.: 1m"),
) -> HistoryOut:
    """Serie temporal agregada por media (`aggregateWindow`)."""
    influx = get_influx()
    validate_rack_id(rack_id)
    range_ = validate_range(range)
    window_ = validate_window(window)

    points = await run_query(influx.query_history, rack_id, range_, window_)
    if not points:
        await ensure_rack_exists(influx, rack_id)
    return HistoryOut(rack_id=rack_id, range=range_, window=window_, points=points)


@router.get("/api/readings/stats", response_model=StatsOut, tags=["leituras"])
async def readings_stats(
    rack_id: str = Query(..., description="Identificador do rack"),
    range: str = Query("24h", description=f"Um de: {', '.join(RANGE_VALUES)}"),
) -> StatsOut:
    """min/max/avg/last de temperatura e umidade na janela pedida."""
    influx = get_influx()
    validate_rack_id(rack_id)
    range_ = validate_range(range)

    count, temperature, humidity = await run_query(influx.query_stats, rack_id, range_)
    if count == 0:
        await ensure_rack_exists(influx, rack_id)
        return StatsOut(
            rack_id=rack_id,
            range=range_,
            count=0,
            temperature=MetricStats(),
            humidity=MetricStats(),
        )
    return StatsOut(
        rack_id=rack_id,
        range=range_,
        count=count,
        temperature=temperature,
        humidity=humidity,
    )


@router.get("/api/alerts", response_model=AlertsOut, tags=["alertas"])
async def list_alerts(
    rack_id: str = Query(..., description="Identificador do rack"),
    range: str = Query("24h", description=f"Um de: {', '.join(RANGE_VALUES)}"),
    limit: int = Query(50, ge=1, le=1000, description="Maximo de alertas retornados"),
) -> AlertsOut:
    """Leituras com `status != "ok"`, mais recentes primeiro."""
    influx = get_influx()
    validate_rack_id(rack_id)
    range_ = validate_range(range)

    alerts = await run_query(influx.query_alerts, rack_id, range_, limit)
    if not alerts:
        await ensure_rack_exists(influx, rack_id)
    return AlertsOut(rack_id=rack_id, range=range_, count=len(alerts), alerts=alerts)


@router.websocket("/ws/live")
async def ws_live(websocket: WebSocket) -> None:
    """Push em tempo real de cada telemetria/status recebidos via MQTT."""
    await ws_manager.connect(websocket)
    try:
        while True:
            # Nao esperamos comandos do cliente; o receive mantem a conexao viva
            # e detecta o fechamento.
            await websocket.receive_text()
    except WebSocketDisconnect:
        ws_manager.disconnect(websocket)
    except Exception:  # noqa: BLE001
        logger.debug("WebSocket encerrado com erro", exc_info=True)
        ws_manager.disconnect(websocket)
