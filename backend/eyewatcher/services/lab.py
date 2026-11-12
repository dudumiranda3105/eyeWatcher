"""Laboratorio de dados: consome q.jobs.datagen e gera o dataset em segundo plano.

Escreve em parquet, um bloco por vez, publicando o progresso no barramento. Uma
amostra vai para o bucket `lab` do InfluxDB, separada dos dados ao vivo.
"""

from __future__ import annotations

import asyncio
import json
import logging
import shutil
import time
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Final

import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
from influxdb_client import InfluxDBClient, Point, WritePrecision
from influxdb_client.client.write_api import SYNCHRONOUS

from eyewatcher import physics, synthetic
from eyewatcher.bus import Bus, Envelope, make_envelope
from eyewatcher.healthcheck import configure_logging, heartbeat_loop
from eyewatcher.services.recorder import ensure_bucket
from eyewatcher.settings import Settings, get_settings

logger = logging.getLogger("eyewatcher.lab")

#: Pontos da amostra enviada ao InfluxDB e decimacao aplicada a cada equipamento.
LAB_SAMPLE_POINTS: Final[int] = 20_000
LAB_SAMPLE_STRIDE: Final[int] = 36

ProgressFn = Callable[[float, str], None]


def write_lab_sample(cfg: Settings, frame: pd.DataFrame) -> int:
    client = InfluxDBClient(url=cfg.influx_url, token=cfg.secret("influx"), org=cfg.influx_org)
    with client:
        ensure_bucket(client, cfg, cfg.influx_lab_bucket)
        writer = client.write_api(write_options=SYNCHRONOUS)
        now = datetime.now(UTC)
        latest = int(frame["step"].max())
        points = []
        for row in frame.itertuples():
            age = timedelta(minutes=(latest - int(row.step)) * physics.SAMPLE_MINUTES)
            point = Point("lab_equipment").tag("equipment", f"sim-{row.equipment_id:03d}")
            point = point.tag("mode", row.mode)
            for metric in physics.METRICS:
                value = float(getattr(row, metric))
                if np.isfinite(value):
                    point = point.field(metric, value)
            points.append(point.time(now - age, WritePrecision.S))
        writer.write(cfg.influx_lab_bucket, record=points)
    return len(frame)


def generate(
    cfg: Settings, job_id: str, params: synthetic.GenerationParams, progress: ProgressFn
) -> dict[str, Any]:
    started = time.monotonic()
    target = cfg.datasets_dir / job_id
    target.mkdir(parents=True, exist_ok=True)
    readings = rows = 0
    modes: dict[str, int] = {}
    sample: list[pd.DataFrame] = []
    sampled = 0
    writer: pq.ParquetWriter | None = None

    try:
        for index, frame in enumerate(synthetic.iter_equipment(params)):
            table = pa.Table.from_pandas(frame, preserve_index=False)
            if writer is None:
                writer = pq.ParquetWriter(target / "equipment.parquet", table.schema)
            writer.write_table(table)
            rows += len(frame)
            readings += len(frame) * len(physics.METRICS)
            mode = str(frame["mode"].iloc[0])
            modes[mode] = modes.get(mode, 0) + 1
            if sampled < LAB_SAMPLE_POINTS:
                piece = frame.iloc[::LAB_SAMPLE_STRIDE]
                sample.append(piece)
                sampled += len(piece)
            progress(0.8 * (index + 1) / params.equipment_count, f"equipamento {index + 1}")
    finally:
        if writer is not None:
            writer.close()

    progress(0.85, "sensores do ambiente")
    sensors = synthetic.simulate_sensors(params, np.random.default_rng(params.seed + 1))
    if not sensors.empty:
        sensors.to_parquet(target / "sensors.parquet", index=False)
        readings += len(sensors)

    progress(0.92, "amostra no InfluxDB")
    sample_points = write_lab_sample(cfg, pd.concat(sample).iloc[:LAB_SAMPLE_POINTS])

    meta = {
        "id": job_id,
        "params": params.model_dump(),
        "readings": readings,
        "equipment_rows": rows,
        "modes": modes,
        "lab_sample_points": sample_points,
        "seconds": round(time.monotonic() - started, 1),
        "created_at": datetime.now(UTC).isoformat(),
    }
    (target / "meta.json").write_text(json.dumps(meta), encoding="utf-8")
    return meta


def prune_datasets(root: Path, keep: int = 3) -> None:
    """Mantem so os mais recentes: cada dataset ocupa centenas de MB."""
    done = sorted(
        (path for path in root.iterdir() if (path / "meta.json").exists()),
        key=lambda path: path.stat().st_mtime,
    )
    for path in done[:-keep]:
        shutil.rmtree(path, ignore_errors=True)


class Lab:
    def __init__(self, cfg: Settings) -> None:
        self.cfg = cfg
        self.bus = Bus(cfg)

    async def report(self, job_id: str, **fields: Any) -> None:
        message = make_envelope("event", "lab", {"kind": "job", "job_id": job_id, **fields})
        await self.bus.publish(f"event.job.{job_id}", message)

    async def on_job(self, _routing_key: str, envelope: Envelope) -> None:
        job_id = str(envelope.payload["job_id"])
        loop = asyncio.get_running_loop()

        def progress(fraction: float, stage: str) -> None:
            asyncio.run_coroutine_threadsafe(
                self.report(job_id, status="running", progress=round(fraction, 3), stage=stage),
                loop,
            )

        await self.report(job_id, status="running", progress=0.0, stage="iniciando")
        try:
            params = synthetic.GenerationParams.model_validate(envelope.payload["params"])
            if params.estimated_readings() > synthetic.MAX_READINGS:
                raise ValueError("volume acima do teto configurado")
            meta = await asyncio.to_thread(generate, self.cfg, job_id, params, progress)
            await asyncio.to_thread(prune_datasets, self.cfg.datasets_dir)
        except Exception as exc:
            logger.exception("job %s falhou", job_id)
            await self.report(job_id, status="failed", progress=1.0, stage=str(exc))
            raise
        await self.report(job_id, status="done", progress=1.0, stage="concluido", result=meta)

    async def run(self) -> None:
        await self.bus.connect()
        await self.bus.consume("q.jobs.datagen", self.on_job, prefetch=1)
        await heartbeat_loop()


def main() -> None:
    cfg = get_settings()
    configure_logging(cfg)
    asyncio.run(Lab(cfg).run())


if __name__ == "__main__":
    main()
