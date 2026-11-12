"""Consultas ao InfluxDB: historico e estatisticas das leituras e das previsoes."""

from __future__ import annotations

import asyncio
from typing import Any, Final

from influxdb_client import InfluxDBClient

from eyewatcher.settings import Settings

#: Periodo -> janela de agregacao; mantem os graficos com poucas centenas de pontos.
RANGES: Final[dict[str, str]] = {
    "15m": "10s",
    "1h": "30s",
    "6h": "2m",
    "24h": "10m",
    "7d": "1h",
    "30d": "6h",
}


def _query(client: InfluxDBClient, flux: str, params: dict[str, Any]) -> list[Any]:
    return list(client.query_api().query(flux, params=params))


def _history_sync(
    client: InfluxDBClient, cfg: Settings, measurement: str, device: str, field: str, range_key: str
) -> list[dict[str, Any]]:
    flux = f"""
    from(bucket: "{cfg.influx_bucket}")
      |> range(start: -{range_key})
      |> filter(fn: (r) => r._measurement == measure and r.device == device and r._field == field)
      |> group()
      |> aggregateWindow(every: {RANGES[range_key]}, fn: mean, createEmpty: false)
    """
    params = {"measure": measurement, "device": device, "field": field}
    return [
        {"time": record.get_time().isoformat(), "value": record.get_value()}
        for table in _query(client, flux, params)
        for record in table.records
    ]


async def history(
    client: InfluxDBClient,
    cfg: Settings,
    measurement: str,
    device: str,
    field: str,
    range_key: str,
) -> list[dict[str, Any]]:
    return await asyncio.to_thread(
        _history_sync, client, cfg, measurement, device, field, range_key
    )


def _stats_sync(
    client: InfluxDBClient, cfg: Settings, device: str, field: str, range_key: str
) -> dict[str, float | int | None]:
    base = f"""
    data = from(bucket: "{cfg.influx_bucket}")
      |> range(start: -{range_key})
      |> filter(fn: (r) => r._measurement == "telemetry" and r.device == device and r._field == field)
      |> group()
    """
    params = {"device": device, "field": field}
    result: dict[str, float | int | None] = {}
    for name in ("min", "max", "mean", "count"):
        tables = _query(client, f"{base}\ndata |> {name}()", params)
        values = [record.get_value() for table in tables for record in table.records]
        result[name] = values[0] if values else None
    return result


async def stats(
    client: InfluxDBClient, cfg: Settings, device: str, field: str, range_key: str
) -> dict[str, float | int | None]:
    return await asyncio.to_thread(_stats_sync, client, cfg, device, field, range_key)
