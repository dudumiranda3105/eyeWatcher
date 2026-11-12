"""Gerador de dados sinteticos: a vida inteira de muitas maquinas, em blocos numpy.

Cada equipamento e simulado de uma vez, com vetores do tamanho do seu periodo. Os
rotulos de verdade (`degrading`, `rul_h`, `health`) so existem aqui: vao para o
dataset de treino e nunca para as mensagens em tempo real.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Final

import numpy as np
import pandas as pd
from pydantic import BaseModel, Field, model_validator

from eyewatcher import physics

#: Teto de leituras por job, para nao travar a maquina.
MAX_READINGS: Final[int] = 30_000_000
MIN_READINGS: Final[int] = 1_000_000

#: Faixa de duracao da degradacao, em dias.
DEGRADATION_DAYS: Final[tuple[float, float]] = (1.5, 14.0)


class GenerationParams(BaseModel):
    equipment_count: int = Field(150, ge=1, le=1000)
    temperature_sensors: int = Field(4, ge=0, le=100)
    humidity_sensors: int = Field(2, ge=0, le=100)
    luminosity_sensors: int = Field(1, ge=0, le=100)
    power_sensors: int = Field(2, ge=0, le=100)
    days: int = Field(60, ge=1, le=730)
    failure_pct: float = Field(60.0, ge=0, le=100)
    failure_modes: list[str] = Field(default_factory=lambda: list(physics.FAILURE_MODES))
    sensor_fault_pct: float = Field(10.0, ge=0, le=100)
    noise: float = Field(1.0, ge=0, le=3)
    missing_pct: float = Field(1.0, ge=0, le=30)
    outlier_pct: float = Field(0.3, ge=0, le=10)
    seed: int = Field(42, ge=0)

    @model_validator(mode="after")
    def check_modes(self) -> GenerationParams:
        unknown = set(self.failure_modes) - set(physics.FAILURE_MODES)
        if unknown:
            raise ValueError(f"modos de falha desconhecidos: {sorted(unknown)}")
        if self.failure_pct > 0 and not self.failure_modes:
            raise ValueError("escolha pelo menos um modo de falha")
        return self

    @property
    def steps(self) -> int:
        return self.days * physics.SAMPLES_PER_DAY

    @property
    def sensor_count(self) -> int:
        return (
            self.temperature_sensors
            + self.humidity_sensors
            + self.luminosity_sensors
            + self.power_sensors
        )

    def estimated_readings(self) -> int:
        per_equipment = self.steps * len(physics.METRICS)
        return self.equipment_count * per_equipment + self.sensor_count * self.steps


def corrupt(values: np.ndarray, rng: np.random.Generator, params: GenerationParams) -> np.ndarray:
    """Aplica leituras faltantes e valores absurdos, como acontece no mundo real."""
    corrupted = values.copy()
    outliers = rng.random(values.shape) < params.outlier_pct / 100.0
    corrupted[outliers] = values[outliers] * rng.choice([-3.0, 8.0], outliers.sum())
    corrupted[rng.random(values.shape) < params.missing_pct / 100.0] = np.nan
    return corrupted


def apply_sensor_fault(temperature: np.ndarray, rng: np.random.Generator) -> np.ndarray:
    """Deriva ou travamento: a maquina esta boa, quem mente e o sensor."""
    faulty = temperature.copy()
    start = int(rng.integers(0, len(faulty)))
    if rng.random() < 0.5:
        faulty[start:] += np.linspace(0.0, rng.uniform(5.0, 15.0), len(faulty) - start)
    else:
        faulty[start:] = faulty[start]
    return faulty


def simulate_equipment(
    index: int, params: GenerationParams, rng: np.random.Generator
) -> pd.DataFrame:
    steps = params.steps
    step = np.arange(steps, dtype=np.float64)
    hour = (step * physics.SAMPLE_MINUTES / 60.0) % 24.0
    day_of_year = (rng.uniform(0, 365) + step / physics.SAMPLES_PER_DAY) % 365.0

    will_fail = rng.random() < params.failure_pct / 100.0
    wear = np.zeros(steps)
    mode = "healthy"
    rul = np.full(steps, physics.RUL_CAP_HOURS)
    last_step = steps

    if will_fail:
        mode = str(rng.choice(params.failure_modes))
        duration = rng.uniform(*DEGRADATION_DAYS) * physics.SAMPLES_PER_DAY
        duration = min(duration, steps * 0.9)
        failure_step = int(rng.uniform(duration, steps))
        onset = failure_step - duration
        exponent = rng.uniform(1.6, 2.4)
        wear = physics.wear_curve((step - onset) / duration, exponent)
        hours_left = (failure_step - step) / physics.SAMPLES_PER_HOUR
        rul = np.minimum(hours_left, physics.RUL_CAP_HOURS)
        last_step = failure_step

    # Sala: temperatura de equilibrio com dois CRACs, mais ruido de operacao.
    cooling = np.full(steps, 2.0) - 0.55 * wear
    room = physics.room_temperature_target(hour, day_of_year, cooling, np.zeros(steps))
    room = room + rng.normal(0.0, 0.4, steps)

    metrics = physics.equipment_metrics(
        wear, mode, hour, room, rng, noise=params.noise, unit_bias=physics.unit_bias(rng)
    )
    if mode == "healthy" and rng.random() < params.sensor_fault_pct / 100.0:
        metrics["temperature"] = apply_sensor_fault(metrics["temperature"], rng)
        mode = "sensor_fault"

    frame = pd.DataFrame(
        {
            "equipment_id": np.full(steps, index, dtype=np.int32),
            "step": step.astype(np.int32),
            "hour": hour.astype(np.float32),
            **{m: corrupt(metrics[m], rng, params).astype(np.float32) for m in physics.METRICS},
            "mode": mode,
            "degrading": (wear > 0).astype(np.int8),
            "rul_h": rul.astype(np.float32),
            "health": physics.health_from_wear(wear).astype(np.float32),
        }
    )
    # A maquina para ao falhar: nao existem leituras depois disso.
    return frame.iloc[:last_step]


def simulate_sensors(params: GenerationParams, rng: np.random.Generator) -> pd.DataFrame:
    """Sensores do ambiente, com ciclo de dia e noite e de estacoes."""
    steps = params.steps
    step = np.arange(steps, dtype=np.float64)
    hour = (step * physics.SAMPLE_MINUTES / 60.0) % 24.0
    day_of_year = (step / physics.SAMPLES_PER_DAY) % 365.0
    room = physics.room_temperature_target(hour, day_of_year, np.full(steps, 2.0), np.zeros(steps))

    groups = (
        ("temperature", params.temperature_sensors, lambda: room, 0.3),
        ("humidity", params.humidity_sensors, lambda: physics.room_humidity(room, hour), 1.0),
        (
            "luminosity",
            params.luminosity_sensors,
            lambda: physics.room_luminosity(hour, (rng.random(steps) < 0.2) * 1.0),
            6.0,
        ),
        ("power", params.power_sensors, lambda: physics.rack_current(hour), 0.4),
    )
    frames = []
    for sensor_type, count, source, sigma in groups:
        for index in range(count):
            values = source() + rng.normal(0.0, sigma * params.noise, steps)
            frames.append(
                pd.DataFrame(
                    {
                        "sensor": f"{sensor_type}-{index:03d}",
                        "type": sensor_type,
                        "step": step.astype(np.int32),
                        "value": corrupt(values, rng, params).astype(np.float32),
                    }
                )
            )
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()


def iter_equipment(params: GenerationParams) -> Iterator[pd.DataFrame]:
    """Gera um equipamento por vez; a semente fixa torna a geracao reproduzivel."""
    for index, seed in enumerate(np.random.SeedSequence(params.seed).spawn(params.equipment_count)):
        yield simulate_equipment(index, params, np.random.default_rng(seed))
