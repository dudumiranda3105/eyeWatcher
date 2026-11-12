"""Treino dos modelos de regressao, separado do servico para ser testavel.

Dois alvos continuos: vida util restante (`rul_h`) e indice de saude (`health`).
A divisao e por equipamento: linhas vizinhas da mesma maquina sao quase iguais, e
dividir por linha deixaria o teste parecido demais com o treino.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any, Final

import numpy as np
import pandas as pd
from sklearn.dummy import DummyRegressor
from sklearn.ensemble import HistGradientBoostingRegressor
from sklearn.inspection import permutation_importance
from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score

from eyewatcher import physics
from eyewatcher.features import FEATURE_NAMES, build_features

TARGETS: Final[dict[str, str]] = {"rul": "rul_h", "health": "health"}

#: Teto de linhas no treino, para o job caber em CPU comum.
MAX_TRAIN_ROWS: Final[int] = 700_000
SCATTER_POINTS: Final[int] = 400
IMPORTANCE_ROWS: Final[int] = 4000
TOP_FEATURES: Final[int] = 10
DEGRADING_WEIGHT: Final[float] = 4.0

ProgressFn = Callable[[float, str], None]


def load_features(dataset: Path) -> pd.DataFrame:
    """Features de cada equipamento, calculadas pela mesma funcao usada ao vivo."""
    frame = pd.read_parquet(dataset / "equipment.parquet")
    pieces = []
    for _, group in frame.groupby("equipment_id", sort=False):
        features = build_features(group).astype(np.float32)
        features["equipment_id"] = group["equipment_id"]
        for label in ("rul_h", "health", "degrading"):
            features[label] = group[label]
        pieces.append(features)
    return pd.concat(pieces, ignore_index=True)


def split_by_equipment(
    frame: pd.DataFrame, seed: int = 7
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """70/15/15 por equipamento, nunca por linha."""
    ids = frame["equipment_id"].unique()
    np.random.default_rng(seed).shuffle(ids)
    cut_train = max(1, int(len(ids) * 0.7))
    cut_val = max(cut_train + 1, int(len(ids) * 0.85))
    groups = (ids[:cut_train], ids[cut_train:cut_val], ids[cut_val:])
    return tuple(frame[frame["equipment_id"].isin(group)] for group in groups)  # type: ignore[return-value]


def score(truth: np.ndarray, predicted: np.ndarray) -> dict[str, float]:
    return {
        "mae": float(mean_absolute_error(truth, predicted)),
        "rmse": float(np.sqrt(mean_squared_error(truth, predicted))),
        "r2": float(r2_score(truth, predicted)),
    }


def train_target(
    name: str,
    train: pd.DataFrame,
    validation: pd.DataFrame,
    test: pd.DataFrame,
) -> tuple[HistGradientBoostingRegressor, dict[str, Any]]:
    target = TARGETS[name]
    columns = list(FEATURE_NAMES)
    sample = train
    if len(train) > MAX_TRAIN_ROWS:
        sample = train.sample(MAX_TRAIN_ROWS, random_state=11)

    # Folhas grandes e regularizacao: linhas da mesma maquina sao quase iguais, e sem
    # isso o modelo decora o nivel normal de cada unidade em vez de aprender a falha.
    model = HistGradientBoostingRegressor(
        max_iter=220,
        learning_rate=0.06,
        max_leaf_nodes=24,
        min_samples_leaf=400,
        l2_regularization=5.0,
        random_state=11,
    )
    # Quase toda linha e de maquina saudavel; sem peso, o modelo ignoraria a degradacao.
    weights = np.where(sample["degrading"] == 1, DEGRADING_WEIGHT, 1.0)
    model.fit(sample[columns], sample[target], sample_weight=weights)

    baseline = DummyRegressor(strategy="mean").fit(sample[columns], sample[target])
    predicted = model.predict(test[columns])
    truth = test[target].to_numpy()

    degrading = test["degrading"].to_numpy() == 1
    near = score(truth[degrading], predicted[degrading]) if degrading.any() else None
    baseline_predicted = baseline.predict(test[columns])
    near_baseline = (
        score(truth[degrading], baseline_predicted[degrading]) if degrading.any() else None
    )

    picks = np.random.default_rng(3).choice(
        np.flatnonzero(degrading) if degrading.sum() > SCATTER_POINTS else np.arange(len(test)),
        size=min(SCATTER_POINTS, len(test)),
        replace=False,
    )
    rows = test.sample(min(IMPORTANCE_ROWS, len(test)), random_state=5)
    importance = permutation_importance(
        model, rows[columns], rows[target], n_repeats=3, random_state=5, n_jobs=1
    )
    ranked = sorted(
        zip(columns, importance.importances_mean, strict=True), key=lambda item: -item[1]
    )

    test_metrics = score(truth, predicted)
    baseline_metrics = score(truth, baseline_predicted)
    report = {
        "target": target,
        "validation": score(validation[target].to_numpy(), model.predict(validation[columns])),
        "test": test_metrics,
        "test_degrading": near,
        "baseline": baseline_metrics,
        "baseline_degrading": near_baseline,
        # RMSE e R2 pesam os erros grandes: a media acerta as maquinas boas de graca e
        # erra justamente as que importam, entao MAE sozinho favoreceria a base.
        "beats_baseline": test_metrics["rmse"] < baseline_metrics["rmse"]
        and test_metrics["r2"] > 0,
        "importance": [
            {"feature": feature, "value": round(float(value), 5)}
            for feature, value in ranked[:TOP_FEATURES]
        ],
        "scatter": [
            {"real": round(float(truth[i]), 2), "predicted": round(float(predicted[i]), 2)}
            for i in picks
        ],
    }
    return model, report


def train_all(
    dataset: Path, progress: ProgressFn
) -> tuple[dict[str, HistGradientBoostingRegressor], dict[str, Any]]:
    progress(0.05, "calculando as features")
    frame = load_features(dataset)
    train, validation, test = split_by_equipment(frame)

    models: dict[str, HistGradientBoostingRegressor] = {}
    reports: dict[str, Any] = {}
    for index, name in enumerate(TARGETS):
        progress(0.25 + 0.35 * index, f"treinando o modelo {name}")
        models[name], reports[name] = train_target(name, train, validation, test)

    summary = {
        "rows": {"train": len(train), "validation": len(validation), "test": len(test)},
        "equipment": {
            "train": int(train["equipment_id"].nunique()),
            "validation": int(validation["equipment_id"].nunique()),
            "test": int(test["equipment_id"].nunique()),
        },
        "rul_cap_hours": physics.RUL_CAP_HOURS,
        "models": reports,
    }
    return models, summary
