"""Calculo das variaveis de entrada dos modelos.

Este e o UNICO lugar onde as features sao calculadas: o treino e a inferencia ao
vivo chamam a mesma funcao, entao nao ha como divergirem. Todas as janelas sao
`rolling`, que olha so para tras: nada aqui enxerga o futuro.

As janelas contam leituras, nao segundos. Como cada leitura vale SAMPLE_MINUTES
na vida da maquina, a mesma janela serve para os dados sinteticos e para o ao vivo.
"""

from __future__ import annotations

from typing import Final

import numpy as np
import pandas as pd

from eyewatcher.physics import METRIC_LIMITS, METRICS, SAMPLES_PER_DAY, SAMPLES_PER_HOUR

SHORT: Final[int] = SAMPLES_PER_HOUR
MEDIUM: Final[int] = 6 * SAMPLES_PER_HOUR
LONG: Final[int] = SAMPLES_PER_DAY

#: Leituras minimas antes de confiar numa previsao ao vivo.
MIN_HISTORY: Final[int] = SHORT * 2


def clean(frame: pd.DataFrame) -> pd.DataFrame:
    """Leitura fisicamente impossivel vira faltante, em vez de contaminar a janela."""
    cleaned = frame.copy()
    for metric in METRICS:
        low, high = METRIC_LIMITS[metric]
        series = cleaned[metric]
        cleaned[metric] = series.where(series.between(low, high))
    return cleaned


def build_features(frame: pd.DataFrame) -> pd.DataFrame:
    """Recebe as leituras de UM equipamento, em ordem, e devolve uma linha por leitura."""
    data = clean(frame)
    columns: dict[str, pd.Series] = {}

    for metric in METRICS:
        series = data[metric]
        short = series.rolling(SHORT, min_periods=1).median()
        medium = series.rolling(MEDIUM, min_periods=1).mean()
        long = series.rolling(LONG, min_periods=1).mean()
        columns[f"{metric}_short"] = short
        columns[f"{metric}_medium"] = medium
        columns[f"{metric}_long"] = long
        columns[f"{metric}_std"] = series.rolling(MEDIUM, min_periods=2).std()
        columns[f"{metric}_max"] = series.rolling(MEDIUM, min_periods=1).max()
        # Tendencia: quanto a media recente se afastou da media do dia.
        columns[f"{metric}_trend"] = medium - long

    radians = data["hour"] / 24.0 * 2 * np.pi
    columns["hour_sin"] = np.sin(radians)
    columns["hour_cos"] = np.cos(radians)
    return pd.DataFrame(columns, index=frame.index)


FEATURE_NAMES: Final[tuple[str, ...]] = tuple(
    build_features(pd.DataFrame({**{m: [1.0] for m in METRICS}, "hour": [0.0]})).columns
)
