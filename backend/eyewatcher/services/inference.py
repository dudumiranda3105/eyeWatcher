"""Inferencia: aplica os modelos a telemetria ao vivo e publica previsoes e alertas.

As features vem da mesma funcao do treino. Um modelo novo entra em uso sem
reiniciar: o treinador avisa pelo barramento e este servico recarrega do volume.
"""

from __future__ import annotations

import asyncio
import json
import logging
from collections import deque
from dataclasses import dataclass, field
from typing import Any, Final

import joblib
import numpy as np
import pandas as pd

from eyewatcher import physics
from eyewatcher.bus import Bus, Envelope, make_envelope
from eyewatcher.features import FEATURE_NAMES, LONG, MIN_HISTORY, build_features
from eyewatcher.healthcheck import configure_logging, heartbeat_loop
from eyewatcher.settings import Settings, get_settings

logger = logging.getLogger("eyewatcher.inference")

#: Saude e vida util que abrem alerta, e quantas previsoes seguidas confirmam.
HEALTH_WARNING: Final[float] = 65.0
HEALTH_CRITICAL: Final[float] = 40.0
RUL_CRITICAL_H: Final[float] = 24.0
TRIGGER_COUNT: Final[int] = 3
CLEAR_COUNT: Final[int] = 10

#: Suavizacao da previsao: evita que a saude pule a cada leitura.
SMOOTHING: Final[float] = 0.3

SEVERITY_RANK: Final[dict[str | None, int]] = {None: 0, "warning": 1, "critical": 2}


class AlertTracker:
    """Histerese: abre com 3 previsoes ruins seguidas, limpa com 10 boas."""

    def __init__(self) -> None:
        self.level: str | None = None
        self.worse = 0
        self.better = 0

    def update(self, severity: str | None) -> str | None:
        """Recebe a severidade da previsao; devolve 'open', 'clear' ou None."""
        if SEVERITY_RANK[severity] > SEVERITY_RANK[self.level]:
            self.better = 0
            self.worse += 1
            if self.worse >= TRIGGER_COUNT:
                self.level, self.worse = severity, 0
                return "open"
        elif SEVERITY_RANK[severity] < SEVERITY_RANK[self.level]:
            self.worse = 0
            self.better += 1
            if self.better >= CLEAR_COUNT:
                self.level, self.better = severity, 0
                return "open" if severity else "clear"
        else:
            self.worse = self.better = 0
        return None


def classify(health: float, rul_h: float) -> str | None:
    if health < HEALTH_CRITICAL or rul_h < RUL_CRITICAL_H:
        return "critical"
    if health < HEALTH_WARNING:
        return "warning"
    return None


@dataclass
class Track:
    readings: deque[dict[str, float]] = field(default_factory=lambda: deque(maxlen=LONG))
    health_history: deque[float] = field(
        default_factory=lambda: deque(maxlen=physics.SAMPLES_PER_DAY)
    )
    tracker: AlertTracker = field(default_factory=AlertTracker)
    run_id: int = 0
    health: float | None = None
    rul_h: float | None = None


class Inference:
    def __init__(self, cfg: Settings) -> None:
        self.cfg = cfg
        self.bus = Bus(cfg)
        self.models: dict[str, Any] = {}
        self.version: str | None = None
        self.tracks: dict[str, Track] = {}

    def load_models(self) -> None:
        pointer = self.cfg.models_dir / "current.json"
        if not pointer.exists():
            logger.info("nenhum modelo treinado ainda")
            return
        version = json.loads(pointer.read_text(encoding="utf-8"))["version"]
        if version == self.version:
            return
        folder = self.cfg.models_dir / version
        self.models = {
            "rul": joblib.load(folder / "rul.joblib"),
            "health": joblib.load(folder / "health.joblib"),
        }
        self.version = version
        logger.info("modelos %s em uso", version)

    async def on_control(self, _routing_key: str, _envelope: Envelope) -> None:
        await asyncio.to_thread(self.load_models)

    def predict(self, track: Track) -> tuple[float, float]:
        frame = pd.DataFrame(track.readings)
        row = build_features(frame).iloc[[-1]][list(FEATURE_NAMES)]
        health = float(np.clip(self.models["health"].predict(row)[0], 0.0, 100.0))
        rul_h = float(np.clip(self.models["rul"].predict(row)[0], 0.0, physics.RUL_CAP_HOURS))
        track.health = (
            health
            if track.health is None
            else (SMOOTHING * health + (1 - SMOOTHING) * track.health)
        )
        track.rul_h = (
            rul_h if track.rul_h is None else (SMOOTHING * rul_h + (1 - SMOOTHING) * track.rul_h)
        )
        return track.health, track.rul_h

    async def on_telemetry(self, routing_key: str, envelope: Envelope) -> None:
        _, zone, _, device = routing_key.split(".", 3)
        track = self.tracks.setdefault(device, Track())
        payload = envelope.payload
        run_id = int(payload.get("run_id", 0))
        if run_id != track.run_id:
            # Equipamento reparado: o historico anterior nao descreve mais a maquina.
            fresh = Track(run_id=run_id, tracker=track.tracker)
            track = self.tracks[device] = fresh
        if payload.get("failed"):
            # A maquina parou: nao ha o que prever, a vida util acabou.
            track.health = track.rul_h = 0.0
            await self.publish_prediction(zone, device, track, 0.0, 0.0)
            if track.tracker.level != "critical":
                track.tracker.level = "critical"
                await self.publish_alert(zone, device, "open", "critical", 0.0, 0.0)
            return
        if not payload.get("on", True):
            await self.publish_state(zone, device, "off")
            return
        if not self.models:
            await self.publish_state(zone, device, "no_model")
            return

        track.readings.append({**payload["metrics"], "hour": float(payload["sim_hour"])})
        if len(track.readings) < MIN_HISTORY:
            await self.publish_state(zone, device, "warming_up")
            return

        health, rul_h = await asyncio.to_thread(self.predict, track)
        track.health_history.append(health)
        await self.publish_prediction(zone, device, track, health, rul_h)

        severity = classify(health, rul_h)
        change = track.tracker.update(severity)
        if change:
            await self.publish_alert(zone, device, change, track.tracker.level, health, rul_h)

    def trend(self, track: Track) -> float:
        """Variacao da saude por hora simulada, na janela recente."""
        history = track.health_history
        span = min(len(history), physics.SAMPLES_PER_HOUR * 3)
        if span < 2:
            return 0.0
        return (history[-1] - history[-span]) / (span / physics.SAMPLES_PER_HOUR)

    async def publish_state(self, zone: str, device: str, state: str) -> None:
        payload = {"state": state, "model_version": self.version}
        await self.bus.publish(
            f"event.{zone}.inference.{device}",
            make_envelope("event", device, {"kind": "inference_state", **payload}),
        )

    async def publish_prediction(
        self, zone: str, device: str, track: Track, health: float, rul_h: float
    ) -> None:
        payload = {
            "health": round(health, 1),
            "rul_h": round(rul_h, 1),
            "trend_per_h": round(self.trend(track), 2),
            "model_version": self.version,
        }
        await self.bus.publish(
            f"prediction.{zone}.{device}", make_envelope("prediction", device, payload)
        )

    async def publish_alert(
        self,
        zone: str,
        device: str,
        change: str,
        severity: str | None,
        health: float,
        rul_h: float,
    ) -> None:
        payload = {
            "state": change,
            "severity": severity,
            "health": round(health, 1),
            "rul_h": round(rul_h, 1),
            "message": alert_message(device, change, severity, health, rul_h),
        }
        await self.bus.publish(f"alert.{zone}.{device}", make_envelope("alert", device, payload))
        logger.info("alerta %s em %s: %s", change, device, severity)

    async def run(self) -> None:
        await self.bus.connect()
        await asyncio.to_thread(self.load_models)
        await self.bus.consume("q.inference.control", self.on_control, prefetch=1)
        await self.bus.consume("q.telemetry.inference", self.on_telemetry, prefetch=20)
        await heartbeat_loop()


def alert_message(
    device: str, change: str, severity: str | None, health: float, rul_h: float
) -> str:
    if change == "clear":
        return f"{device} voltou ao normal (saúde {health:.0f})."
    label = "crítica" if severity == "critical" else "em atenção"
    return (
        f"{device} com saúde {label}: {health:.0f}/100, falha prevista em cerca de {rul_h:.0f} h."
    )


def main() -> None:
    cfg = get_settings()
    configure_logging(cfg)
    asyncio.run(Inference(cfg).run())


if __name__ == "__main__":
    main()
