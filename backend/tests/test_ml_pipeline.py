"""Garantias que o enunciado exige da camada de IA."""

from __future__ import annotations

import numpy as np
import pandas as pd

from eyewatcher import physics, synthetic
from eyewatcher.features import FEATURE_NAMES, build_features
from eyewatcher.services.inference import CLEAR_COUNT, TRIGGER_COUNT, AlertTracker, classify
from eyewatcher.services.simulator import Room
from eyewatcher.training import split_by_equipment


def small_params(**changes: float) -> synthetic.GenerationParams:
    return synthetic.GenerationParams(equipment_count=6, days=20, **changes)


def test_generation_is_reproducible() -> None:
    first = pd.concat(synthetic.iter_equipment(small_params(seed=9)))
    second = pd.concat(synthetic.iter_equipment(small_params(seed=9)))
    pd.testing.assert_frame_equal(first, second)


def test_different_seed_changes_the_data() -> None:
    first = pd.concat(synthetic.iter_equipment(small_params(seed=1)))
    second = pd.concat(synthetic.iter_equipment(small_params(seed=2)))
    assert not first["vibration"].equals(second["vibration"])


def test_degradation_is_progressive() -> None:
    params = synthetic.GenerationParams(equipment_count=1, days=30, failure_pct=100, noise=0.2)
    frame = next(synthetic.iter_equipment(params))
    degrading = frame[frame["degrading"] == 1]
    third = len(degrading) // 3
    assert degrading["health"].is_monotonic_decreasing
    assert frame["rul_h"].iloc[-1] < 1.0
    early = degrading.iloc[:third][list(physics.METRICS[:3])].mean()
    late = degrading.iloc[-third:][list(physics.METRICS[:3])].mean()
    assert (late > early).all()


def test_healthy_and_sick_machines_overlap() -> None:
    """Dado perfeito demais nao ensina nada: ruido precisa cruzar as distribuicoes."""
    params = synthetic.GenerationParams(equipment_count=20, days=30, failure_pct=50)
    frame = pd.concat(synthetic.iter_equipment(params))
    healthy = frame.loc[frame["health"] == 100, "vibration"].dropna()
    early = frame.loc[frame["health"].between(60, 95), "vibration"].dropna()
    assert early.quantile(0.1) < healthy.quantile(0.9)


def test_features_only_look_at_the_past() -> None:
    rng = np.random.default_rng(0)
    frame = pd.DataFrame({m: rng.normal(5, 1, 300) for m in physics.METRICS})
    frame["hour"] = np.arange(300) % 24.0
    original = build_features(frame).iloc[:200]

    changed = frame.copy()
    changed.loc[200:, list(physics.METRICS)] = 999.0
    pd.testing.assert_frame_equal(original, build_features(changed).iloc[:200])


def test_impossible_readings_do_not_reach_the_windows() -> None:
    frame = pd.DataFrame({m: [5.0] * 10 for m in physics.METRICS})
    frame["hour"] = 1.0
    frame.loc[5, "vibration"] = 500.0
    assert build_features(frame)["vibration_medium"].max() == 5.0


def test_split_never_shares_equipment() -> None:
    frame = pd.DataFrame({"equipment_id": np.repeat(np.arange(20), 5), "value": 1})
    train, validation, test = split_by_equipment(frame)
    groups = [set(part["equipment_id"]) for part in (train, validation, test)]
    assert not groups[0] & groups[1]
    assert not groups[0] & groups[2]
    assert not groups[1] & groups[2]
    assert len(groups[0] | groups[1] | groups[2]) == 20


def test_labels_never_reach_live_payload() -> None:
    room = Room(rng=np.random.default_rng(1))
    room.sync_devices([{"id": "crac-01", "kind": "equipment", "type": "equipment"}])
    room.inject_fault("crac-01", "bearing_wear", 0.5, 48)
    room.step()
    reading = room.equipment_reading(room.equipment["crac-01"])
    assert set(reading) == set(physics.METRICS)


def test_turning_off_cooling_heats_the_room() -> None:
    room = Room(rng=np.random.default_rng(1))
    room.sync_devices(
        [
            {"id": "crac-01", "kind": "equipment", "type": "equipment"},
            {"id": "crac-02", "kind": "equipment", "type": "equipment"},
        ]
    )
    for _ in range(60):
        room.step()
    cooled = room.temperature
    for unit in room.equipment.values():
        unit.on = False
    for _ in range(40):
        room.step()
    assert room.temperature > 35.0 > cooled


def test_alert_hysteresis_needs_consecutive_predictions() -> None:
    tracker = AlertTracker()
    assert [tracker.update("warning") for _ in range(TRIGGER_COUNT - 1)] == [None] * (
        TRIGGER_COUNT - 1
    )
    assert tracker.update(None) is None
    changes = [tracker.update("warning") for _ in range(TRIGGER_COUNT)]
    assert changes[-1] == "open"

    changes = [tracker.update(None) for _ in range(CLEAR_COUNT)]
    assert changes[:-1] == [None] * (CLEAR_COUNT - 1)
    assert changes[-1] == "clear"


def test_alert_classification() -> None:
    assert classify(90, 200) is None
    assert classify(60, 200) == "warning"
    assert classify(30, 200) == "critical"
    assert classify(90, 10) == "critical"


def test_feature_names_are_stable() -> None:
    assert len(FEATURE_NAMES) == len(physics.METRICS) * 6 + 2
