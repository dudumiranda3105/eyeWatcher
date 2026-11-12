"""Modelo fisico da sala de servidores.

E o mesmo codigo para o gerador de dados sinteticos e para o simulador ao vivo.
Se cada um tivesse sua formula, o modelo seria treinado num mundo e usado em
outro. Tudo aqui trabalha com vetores numpy, entao o gerador processa blocos
inteiros e o simulador passa arrays de um elemento.

Cada leitura representa SAMPLE_MINUTES minutos da vida da maquina. E isso que
permite ver uma falha de dias acontecer em minutos durante a apresentacao.
"""

from __future__ import annotations

from typing import Final

import numpy as np
from numpy.typing import NDArray

Array = NDArray[np.float64]

#: Minutos simulados entre duas leituras consecutivas.
SAMPLE_MINUTES: Final[int] = 10
SAMPLES_PER_HOUR: Final[int] = 60 // SAMPLE_MINUTES
SAMPLES_PER_DAY: Final[int] = 24 * SAMPLES_PER_HOUR

#: Teto do alvo de vida util: acima disso o equipamento e tratado como saudavel.
RUL_CAP_HOURS: Final[float] = 240.0

METRICS: Final[tuple[str, ...]] = ("vibration", "current", "temperature", "rpm")

#: Faixa fisicamente possivel: o que sair dela e leitura absurda, nao medicao.
METRIC_LIMITS: Final[dict[str, tuple[float, float]]] = {
    "vibration": (0.0, 30.0),
    "current": (0.0, 40.0),
    "temperature": (0.0, 130.0),
    "rpm": (0.0, 2000.0),
}

BASE_LEVEL: Final[dict[str, float]] = {
    "vibration": 1.9,
    "current": 12.0,
    "temperature": 48.0,
    "rpm": 1450.0,
}

#: Ruido de cada variavel, em desvio padrao. E alto de proposito: maquinas boas e
#: ruins precisam se sobrepor, senao o modelo acerta tudo e nao ensina nada.
NOISE_LEVEL: Final[dict[str, float]] = {
    "vibration": 0.45,
    "current": 0.7,
    "temperature": 1.6,
    "rpm": 14.0,
}

#: Quanto cada modo de falha soma a cada variavel quando o desgaste chega em 1.
FAILURE_EFFECT: Final[dict[str, dict[str, float]]] = {
    "bearing_wear": {"vibration": 7.5, "current": 2.2, "temperature": 11.0, "rpm": -60.0},
    "clogging": {"vibration": 1.4, "current": 5.5, "temperature": 17.0, "rpm": -190.0},
    "overheating": {"vibration": 1.0, "current": 3.6, "temperature": 30.0, "rpm": -40.0},
    "imbalance": {"vibration": 9.0, "current": 1.4, "temperature": 5.0, "rpm": -90.0},
}

FAILURE_MODES: Final[tuple[str, ...]] = tuple(FAILURE_EFFECT)
SENSOR_FAULTS: Final[tuple[str, ...]] = ("sensor_drift", "sensor_stuck")

#: Tipo de sensor -> metrica publicada.
SENSOR_METRICS: Final[dict[str, str]] = {
    "temperature": "temperature",
    "humidity": "humidity",
    "luminosity": "luminosity",
    "power": "current",
    "presence": "presence",
}


def wear_curve(progress: Array, exponent: float | Array = 2.0) -> Array:
    """Desgaste de 0 a 1: comeca devagar e acelera perto da falha."""
    return np.clip(progress, 0.0, 1.0) ** exponent


def health_from_wear(wear: Array) -> Array:
    return 100.0 * (1.0 - np.clip(wear, 0.0, 1.0))


def rack_load(hour: Array) -> Array:
    """Carga dos servidores de 0 a 1, maior no horario comercial."""
    return 0.62 + 0.2 * np.sin((hour - 9.0) / 24.0 * 2 * np.pi)


def outside_temperature(hour: Array, day_of_year: Array) -> Array:
    """Temperatura externa, com ciclo diario (pico as 14h) e estacoes."""
    daily = 5.0 * np.cos((hour - 14.0) / 24.0 * 2 * np.pi)
    seasonal = 6.0 * np.cos((day_of_year - 15.0) / 365.0 * 2 * np.pi)
    return 25.0 + daily + seasonal


def daylight(hour: Array) -> Array:
    """Luz natural de 0 a 1: zero a noite, maxima ao meio-dia."""
    return np.clip(np.sin((hour - 6.0) / 12.0 * np.pi), 0.0, 1.0)


def room_temperature_target(
    hour: Array,
    day_of_year: Array,
    cooling: Array,
    exhaust_on: Array,
) -> Array:
    """Temperatura de equilibrio da sala; `cooling` soma a capacidade dos CRACs."""
    load = rack_load(hour)
    outside = outside_temperature(hour, day_of_year)
    return 38.0 + 6.0 * (load - 0.6) + 0.2 * (outside - 25.0) - 6.5 * cooling - 5.0 * exhaust_on


def room_humidity(room_temp: Array, hour: Array) -> Array:
    return 54.0 - 1.1 * (room_temp - 25.0) + 4.0 * np.cos((hour - 4.0) / 24.0 * 2 * np.pi)


def room_luminosity(hour: Array, light_on: Array) -> Array:
    return 320.0 * daylight(hour) + 430.0 * light_on + 3.0


def rack_current(hour: Array) -> Array:
    return 7.0 + 14.0 * rack_load(hour)


def equipment_metrics(
    wear: Array,
    mode: str,
    hour: Array,
    room_temp: Array,
    rng: np.random.Generator,
    noise: float = 1.0,
    unit_bias: dict[str, float] | None = None,
) -> dict[str, Array]:
    """Vibracao, corrente, temperatura e rotacao de um CRAC ligado."""
    size = wear.shape
    load = rack_load(hour)
    bias = unit_bias or {}
    effect = FAILURE_EFFECT.get(mode, {})
    shaped = wear**1.2

    out: dict[str, Array] = {}
    for metric in METRICS:
        value = BASE_LEVEL[metric] + bias.get(metric, 0.0) + effect.get(metric, 0.0) * shaped
        if metric == "current":
            value = value + 3.0 * (load - 0.6)
        elif metric == "temperature":
            value = value + 0.6 * (room_temp - 25.0) + 4.0 * (load - 0.6)
        elif metric == "vibration":
            value = value + 0.5 * (load - 0.6)
        out[metric] = value + rng.normal(0.0, NOISE_LEVEL[metric] * noise, size)

    # Picos curtos de vibracao tambem acontecem em maquina boa.
    spikes = rng.random(size) < 0.012
    out["vibration"] = out["vibration"] + spikes * rng.uniform(1.5, 4.0, size)
    return out


def unit_bias(rng: np.random.Generator) -> dict[str, float]:
    """Cada maquina tem seu proprio nivel normal, mesmo saindo da mesma fabrica."""
    return {
        "vibration": float(rng.normal(0.0, 0.35)),
        "current": float(rng.normal(0.0, 0.8)),
        "temperature": float(rng.normal(0.0, 2.0)),
        "rpm": float(rng.normal(0.0, 18.0)),
    }
