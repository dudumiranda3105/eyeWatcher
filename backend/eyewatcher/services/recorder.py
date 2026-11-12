"""Gravador: consome q.telemetry.influx e grava leituras e previsoes no InfluxDB.

Usa o instante da mensagem, nao o da gravacao. Por isso, quando o gravador fica
parado, a fila acumula e nada se perde: ao voltar, ele esvazia a fila e cada ponto
cai no lugar certo da serie.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from influxdb_client import InfluxDBClient, Point, WritePrecision
from influxdb_client.client.write_api import SYNCHRONOUS
from urllib3.exceptions import HTTPError

from eyewatcher.bus import Bus, Envelope, RetryLaterError
from eyewatcher.healthcheck import configure_logging, heartbeat_loop
from eyewatcher.settings import Settings, get_settings

logger = logging.getLogger("eyewatcher.recorder")


def ensure_bucket(client: InfluxDBClient, cfg: Settings, name: str) -> None:
    buckets = client.buckets_api()
    if buckets.find_bucket_by_name(name) is None:
        buckets.create_bucket(bucket_name=name, org=cfg.influx_org)
        logger.info("bucket %s criado", name)


def telemetry_point(routing_key: str, envelope: Envelope) -> Point:
    _, zone, kind, device = routing_key.split(".", 3)
    point = Point("telemetry").tag("device", device).tag("zone", zone).tag("type", kind)
    metrics: dict[str, Any] = envelope.payload["metrics"]
    if not metrics:
        raise ValueError("telemetria sem metricas")
    for name, value in metrics.items():
        point = point.field(name, float(value))
    return point.time(envelope.ts, WritePrecision.MS)


def prediction_point(routing_key: str, envelope: Envelope) -> Point:
    _, zone, device = routing_key.split(".", 2)
    point = Point("prediction").tag("device", device).tag("zone", zone)
    for name in ("health", "rul_h"):
        point = point.field(name, float(envelope.payload[name]))
    point = point.tag("model_version", str(envelope.payload["model_version"]))
    return point.time(envelope.ts, WritePrecision.MS)


class Recorder:
    def __init__(self, cfg: Settings) -> None:
        self.cfg = cfg
        self.bus = Bus(cfg)
        self.client = InfluxDBClient(
            url=cfg.influx_url, token=cfg.secret("influx"), org=cfg.influx_org
        )
        self.writer = self.client.write_api(write_options=SYNCHRONOUS)

    async def on_message(self, routing_key: str, envelope: Envelope) -> None:
        build = telemetry_point if envelope.type == "telemetry" else prediction_point
        point = build(routing_key, envelope)
        try:
            await asyncio.to_thread(self.writer.write, self.cfg.influx_bucket, record=point)
        except (OSError, HTTPError) as exc:
            raise RetryLaterError(f"InfluxDB indisponivel: {exc}") from exc

    async def run(self) -> None:
        await self.bus.connect()
        await asyncio.to_thread(ensure_bucket, self.client, self.cfg, self.cfg.influx_lab_bucket)
        await self.bus.consume("q.telemetry.influx", self.on_message, prefetch=100)
        await heartbeat_loop()


def main() -> None:
    cfg = get_settings()
    configure_logging(cfg)
    asyncio.run(Recorder(cfg).run())


if __name__ == "__main__":
    main()
