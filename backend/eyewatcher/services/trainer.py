"""Treinamento: consome q.jobs.training e publica a nova versao dos modelos.

Um modelo que nao vence a base simples nao entra em uso: a versao fica registrada
com as metricas, mas `current.json` continua apontando para a anterior.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import joblib

from eyewatcher.bus import Bus, Envelope, make_envelope
from eyewatcher.features import FEATURE_NAMES
from eyewatcher.healthcheck import configure_logging, heartbeat_loop
from eyewatcher.settings import Settings, get_settings
from eyewatcher.training import ProgressFn, train_all

logger = logging.getLogger("eyewatcher.trainer")


def latest_dataset(root: Path) -> Path:
    done = [path for path in root.iterdir() if (path / "meta.json").exists()]
    if not done:
        raise ValueError("nenhum dataset gerado ainda: use o Laboratório de Dados primeiro")
    return max(done, key=lambda path: path.stat().st_mtime)


def next_version(root: Path) -> str:
    numbers = [int(p.name[1:]) for p in root.glob("v*") if p.name[1:].isdigit()]
    return f"v{max(numbers, default=0) + 1}"


def run_training(cfg: Settings, dataset_id: str | None, progress: ProgressFn) -> dict[str, Any]:
    root = cfg.datasets_dir
    dataset = root / dataset_id if dataset_id else latest_dataset(root)
    models, summary = train_all(dataset, progress)

    progress(0.92, "salvando a nova versao")
    version = next_version(cfg.models_dir)
    target = cfg.models_dir / version
    target.mkdir(parents=True)
    for name, model in models.items():
        joblib.dump(model, target / f"{name}.joblib")

    promoted = all(report["beats_baseline"] for report in summary["models"].values())
    summary |= {
        "version": version,
        "dataset": dataset.name,
        "promoted": promoted,
        "features": list(FEATURE_NAMES),
        "trained_at": datetime.now(UTC).isoformat(),
    }
    (target / "metrics.json").write_text(json.dumps(summary), encoding="utf-8")

    if promoted:
        # Troca atomica: a inferencia nunca le um arquivo pela metade.
        temporary = cfg.models_dir / "current.json.tmp"
        temporary.write_text(json.dumps({"version": version}), encoding="utf-8")
        os.replace(temporary, cfg.models_dir / "current.json")
    return summary


class Trainer:
    def __init__(self, cfg: Settings) -> None:
        self.cfg = cfg
        self.bus = Bus(cfg)

    async def report(self, job_id: str, **fields: Any) -> None:
        message = make_envelope("event", "trainer", {"kind": "job", "job_id": job_id, **fields})
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
            summary = await asyncio.to_thread(
                run_training, self.cfg, envelope.payload.get("dataset_id"), progress
            )
        except Exception as exc:
            logger.exception("treino %s falhou", job_id)
            await self.report(job_id, status="failed", progress=1.0, stage=str(exc))
            raise
        await self.report(job_id, status="done", progress=1.0, stage="concluido")
        message = make_envelope("event", "trainer", {"kind": "model", **summary})
        await self.bus.publish(f"event.model.{summary['version']}", message)

    async def run(self) -> None:
        await self.bus.connect()
        await self.bus.consume("q.jobs.training", self.on_job, prefetch=1)
        await heartbeat_loop()


def main() -> None:
    cfg = get_settings()
    configure_logging(cfg)
    asyncio.run(Trainer(cfg).run())


if __name__ == "__main__":
    main()
