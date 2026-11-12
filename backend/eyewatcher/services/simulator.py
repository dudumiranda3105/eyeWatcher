"""Dispositivo simulado: sala de servidores com sensores, atuadores e dois CRACs.

So fala MQTT. Publica a telemetria no Mosquitto e escuta comandos; nao conhece
RabbitMQ nem banco. A lista de dispositivos vem do cadastro (topico retido
`eyewatcher/sim/config`), entao um sensor novo cadastrado na Web comeca a publicar
sem reiniciar nada.

Os atuadores mudam a fisica da sala: desligar os CRACs esquenta o ambiente, o
exaustor ajuda a esfriar, e a luz aumenta a luminosidade medida.

As mensagens levam apenas o que um sensor real mediria. O desgaste e o modo de
falha ficam aqui dentro e nunca sao publicados: a IA precisa descobri-los.
"""

from __future__ import annotations

import json
import logging
import signal
import threading
import zlib
from dataclasses import dataclass, field
from typing import Any, Final

import numpy as np
import paho.mqtt.client as mqtt

from eyewatcher import physics
from eyewatcher.bus import make_envelope
from eyewatcher.healthcheck import HEARTBEAT, configure_logging
from eyewatcher.settings import Settings, get_settings

logger = logging.getLogger("eyewatcher.simulator")

CONFIG_TOPIC: Final[str] = "eyewatcher/sim/config"
STATUS_TOPIC: Final[str] = "eyewatcher/sim/status"

#: Fracao da vida ja consumida quando uma falha e injetada na demonstracao.
DEFAULT_START_PROGRESS: Final[float] = 0.55
DEFAULT_DURATION_HOURS: Final[float] = 48.0

#: Velocidade com que a sala se aproxima da temperatura de equilibrio, por leitura.
THERMAL_RATE: Final[float] = 0.09


def scalar(values: np.ndarray) -> float:
    return float(np.asarray(values).reshape(-1)[0])


def arr(value: float) -> np.ndarray:
    return np.array([value], dtype=np.float64)


@dataclass
class Equipment:
    device_id: str
    bias: dict[str, float]
    on: bool = True
    failed: bool = False
    run_id: int = 0
    mode: str | None = None
    progress: float = 0.0
    progress_step: float = 0.0
    sensor_fault: str | None = None
    drift: float = 0.0
    stuck_value: float | None = None

    @property
    def wear(self) -> float:
        return scalar(physics.wear_curve(arr(self.progress))) if self.mode else 0.0

    @property
    def cooling(self) -> float:
        if not self.on or self.failed:
            return 0.0
        return 1.0 - 0.55 * self.wear


@dataclass
class Room:
    rng: np.random.Generator
    minutes: float = 8 * 60.0
    temperature: float = 25.5
    day_of_year: float = 120.0
    devices: dict[str, dict[str, Any]] = field(default_factory=dict)
    actuators: dict[str, bool] = field(default_factory=dict)
    equipment: dict[str, Equipment] = field(default_factory=dict)
    paused: bool = False

    @property
    def hour(self) -> float:
        return (self.minutes / 60.0) % 24.0

    def sync_devices(self, devices: list[dict[str, Any]]) -> None:
        self.devices = {d["id"]: d for d in devices if d.get("enabled", True)}
        for device_id, device in self.devices.items():
            if device["kind"] == "equipment" and device_id not in self.equipment:
                seed = zlib.crc32(device_id.encode())
                self.equipment[device_id] = Equipment(
                    device_id, physics.unit_bias(np.random.default_rng(seed))
                )
            elif device["kind"] == "actuator":
                self.actuators.setdefault(device_id, False)
        for device_id in set(self.equipment) - set(self.devices):
            del self.equipment[device_id]
        for device_id in set(self.actuators) - set(self.devices):
            del self.actuators[device_id]
        logger.info("cadastro sincronizado: %d dispositivos", len(self.devices))

    def actuator_on(self, actuator_type: str) -> bool:
        return any(
            on and self.devices[device_id]["type"] == actuator_type
            for device_id, on in self.actuators.items()
        )

    def step(self) -> None:
        """Avanca a sala em SAMPLE_MINUTES minutos."""
        self.minutes += physics.SAMPLE_MINUTES
        self.day_of_year = (self.day_of_year + physics.SAMPLE_MINUTES / 1440.0) % 365.0
        cooling = sum(unit.cooling for unit in self.equipment.values())
        target = scalar(
            physics.room_temperature_target(
                arr(self.hour),
                arr(self.day_of_year),
                arr(cooling),
                arr(1.0 if self.actuator_on("fan") else 0.0),
            )
        )
        self.temperature += THERMAL_RATE * (target - self.temperature)

        for unit in self.equipment.values():
            if unit.mode and unit.on and not unit.failed:
                unit.progress = min(1.0, unit.progress + unit.progress_step)
                if unit.progress >= 1.0:
                    unit.failed = True
                    logger.warning("%s falhou (%s)", unit.device_id, unit.mode)
            if unit.sensor_fault == "sensor_drift":
                unit.drift += 0.12

    def sensor_reading(self, device: dict[str, Any]) -> dict[str, float]:
        rng = self.rng
        offset = (zlib.crc32(device["id"].encode()) % 100) / 100.0
        kind = device["type"]
        hour = arr(self.hour)
        if kind == "temperature":
            value = self.temperature + offset * 2.0 + rng.normal(0.0, 0.12)
        elif kind == "humidity":
            value = scalar(physics.room_humidity(arr(self.temperature), hour)) + rng.normal(
                0.0, 0.5
            )
        elif kind == "luminosity":
            light = 1.0 if self.actuator_on("light") else 0.0
            value = scalar(physics.room_luminosity(hour, arr(light))) + rng.normal(0.0, 4.0)
        elif kind == "power":
            value = scalar(physics.rack_current(hour)) + offset + rng.normal(0.0, 0.25)
        else:
            business_hours = 8.0 <= self.hour <= 18.0
            value = 1.0 if rng.random() < (0.35 if business_hours else 0.03) else 0.0
        metric = physics.SENSOR_METRICS[kind]
        return {metric: round(max(float(value), 0.0), 2)}

    def equipment_reading(self, unit: Equipment) -> dict[str, float]:
        if not unit.on or unit.failed:
            return dict.fromkeys(physics.METRICS, 0.0) | {"temperature": round(self.temperature, 2)}
        raw = physics.equipment_metrics(
            arr(unit.wear),
            unit.mode or "",
            arr(self.hour),
            arr(self.temperature),
            self.rng,
            unit_bias=unit.bias,
        )
        metrics = {metric: round(scalar(raw[metric]), 2) for metric in physics.METRICS}
        if unit.sensor_fault == "sensor_drift":
            metrics["temperature"] = round(metrics["temperature"] + unit.drift, 2)
        elif unit.sensor_fault == "sensor_stuck":
            if unit.stuck_value is None:
                unit.stuck_value = metrics["temperature"]
            metrics["temperature"] = unit.stuck_value
        return metrics

    def inject_fault(self, device_id: str, mode: str, start: float, duration_h: float) -> None:
        unit = self.equipment[device_id]
        if mode in physics.SENSOR_FAULTS:
            unit.sensor_fault, unit.drift, unit.stuck_value = mode, 0.0, None
            return
        if mode not in physics.FAILURE_MODES:
            raise ValueError(f"modo de falha desconhecido: {mode}")
        unit.mode = mode
        unit.progress = start
        unit.progress_step = 1.0 / (duration_h * physics.SAMPLES_PER_HOUR)
        logger.info("falha injetada em %s: %s", device_id, mode)

    def repair(self, device_id: str) -> None:
        unit = self.equipment[device_id]
        unit.mode, unit.progress, unit.failed = None, 0.0, False
        unit.sensor_fault, unit.drift, unit.stuck_value = None, 0.0, None
        unit.run_id += 1


class Simulator:
    def __init__(self, cfg: Settings) -> None:
        self.cfg = cfg
        self.room = Room(rng=np.random.default_rng())
        self.lock = threading.Lock()
        self.stop = threading.Event()
        self.client = mqtt.Client(
            mqtt.CallbackAPIVersion.VERSION2, client_id="eyewatcher-simulator"
        )
        self.client.username_pw_set("simulator", cfg.secret("mqtt"))
        self.client.will_set(STATUS_TOPIC, "offline", qos=1, retain=True)
        self.client.on_connect = self.on_connect
        self.client.on_message = self.on_message

    def on_connect(self, client: mqtt.Client, *_: Any) -> None:
        logger.info("conectado ao Mosquitto")
        client.subscribe([(CONFIG_TOPIC, 1), (f"eyewatcher/{self.cfg.zone}/+/+/cmd", 1)])
        client.publish(STATUS_TOPIC, "online", qos=1, retain=True)

    def on_message(self, _client: mqtt.Client, _userdata: Any, msg: mqtt.MQTTMessage) -> None:
        try:
            body = json.loads(msg.payload)
            with self.lock:
                if msg.topic == CONFIG_TOPIC:
                    self.room.sync_devices(body["payload"]["devices"])
                else:
                    self.handle_command(body["device"], body["payload"])
        except (ValueError, KeyError) as exc:
            logger.warning("mensagem ignorada em %s: %s", msg.topic, exc)

    def handle_command(self, device_id: str, payload: dict[str, Any]) -> None:
        action = payload["action"]
        room = self.room
        if device_id == "simulator":
            if action == "pause":
                room.paused = True
            elif action == "resume":
                room.paused = False
            elif action == "inject_fault":
                room.inject_fault(
                    payload["target"],
                    payload["mode"],
                    float(payload.get("start", DEFAULT_START_PROGRESS)),
                    float(payload.get("duration_h", DEFAULT_DURATION_HOURS)),
                )
            elif action == "repair":
                room.repair(payload["target"])
            return
        turn_on = action == "on"
        if device_id in room.equipment:
            room.equipment[device_id].on = turn_on
        elif device_id in room.actuators:
            room.actuators[device_id] = turn_on
        logger.info("comando recebido: %s -> %s", device_id, action)

    def publish_all(self) -> None:
        room = self.room
        for device_id, device in room.devices.items():
            kind = device["kind"]
            payload: dict[str, Any] = {"sim_hour": round(room.hour, 2)}
            if kind == "sensor":
                payload["metrics"] = room.sensor_reading(device)
            elif kind == "actuator":
                payload["metrics"] = {"on": 1.0 if room.actuators[device_id] else 0.0}
            else:
                unit = room.equipment[device_id]
                payload["metrics"] = room.equipment_reading(unit)
                payload["on"] = unit.on
                payload["failed"] = unit.failed
                payload["run_id"] = unit.run_id
            topic = f"eyewatcher/{self.cfg.zone}/{device['type']}/{device_id}/telemetry"
            message = make_envelope("telemetry", device_id, payload)
            self.client.publish(topic, json.dumps(message), qos=0)

    def run(self) -> None:
        self.client.connect_async(self.cfg.mqtt_host, self.cfg.mqtt_port, keepalive=30)
        self.client.loop_start()
        while not self.stop.wait(self.cfg.tick_seconds):
            HEARTBEAT.touch()
            with self.lock:
                if self.room.paused:
                    continue
                self.room.step()
                self.publish_all()
        self.client.publish(STATUS_TOPIC, "offline", qos=1, retain=True).wait_for_publish(2)
        self.client.loop_stop()


def main() -> None:
    cfg = get_settings()
    configure_logging(cfg)
    simulator = Simulator(cfg)
    signal.signal(signal.SIGTERM, lambda *_: simulator.stop.set())
    signal.signal(signal.SIGINT, lambda *_: simulator.stop.set())
    simulator.run()


if __name__ == "__main__":
    main()
