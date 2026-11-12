"""Ponte entre a borda (MQTT) e o barramento interno (RabbitMQ).

Sentido IoT -> aplicacao: le a telemetria do Mosquitto e republica no RabbitMQ com
a routing key `telemetry.<zona>.<tipo>.<id>`. O que chegar invalido vai direto para
a DLX, preservado, sem chegar a nenhum consumidor.

Sentido aplicacao -> IoT: consome q.commands.device e publica no topico MQTT do
dispositivo. A configuracao do simulador vai retida, para ele recebe-la ao subir.
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Final

import aiomqtt
from pydantic import ValidationError

from eyewatcher.bus import (
    DLX,
    Bus,
    BusUnavailableError,
    Envelope,
    RetryLaterError,
    make_envelope,
)
from eyewatcher.healthcheck import configure_logging, heartbeat_loop
from eyewatcher.settings import Settings, get_settings

logger = logging.getLogger("eyewatcher.gateway")

TELEMETRY_FILTER: Final[str] = "eyewatcher/+/+/+/telemetry"
STATUS_TOPIC: Final[str] = "eyewatcher/sim/status"
CONFIG_TOPIC: Final[str] = "eyewatcher/sim/config"


class Gateway:
    def __init__(self, cfg: Settings) -> None:
        self.cfg = cfg
        self.bus = Bus(cfg)
        self.mqtt: aiomqtt.Client | None = None

    async def on_command(self, routing_key: str, envelope: Envelope) -> None:
        """command.<zona>.<tipo>.<id> -> eyewatcher/<zona>/<tipo>/<id>/cmd."""
        if self.mqtt is None:
            raise RetryLaterError("MQTT desconectado")
        _, zone, kind, device = routing_key.split(".", 3)
        body = envelope.model_dump_json()
        try:
            if kind == "sim" and device == "config":
                await self.mqtt.publish(CONFIG_TOPIC, body, qos=1, retain=True)
            else:
                await self.mqtt.publish(f"eyewatcher/{zone}/{kind}/{device}/cmd", body, qos=1)
        except aiomqtt.MqttError as exc:
            raise RetryLaterError(str(exc)) from exc

    async def on_mqtt(self, topic: str, raw: bytes) -> None:
        if topic == STATUS_TOPIC:
            online = raw == b"online"
            message = make_envelope("event", "simulator", {"kind": "status", "online": online})
            await self.bus.publish(f"event.{self.cfg.zone}.simulator.status", message)
            return

        _, zone, kind, device, _ = topic.split("/")
        try:
            envelope = Envelope.model_validate_json(raw)
            if envelope.device != device:
                raise ValueError("dispositivo da mensagem difere do topico")
        except (ValidationError, ValueError) as exc:
            logger.warning("telemetria invalida em %s: %s", topic, exc)
            await self.bus.publish_raw(DLX, "", raw, headers={"x-origin-topic": topic})
            return
        await self.bus.publish(
            f"telemetry.{zone}.{kind}.{device}", json.loads(envelope.model_dump_json())
        )

    async def mqtt_loop(self) -> None:
        cfg = self.cfg
        while True:
            try:
                async with aiomqtt.Client(
                    cfg.mqtt_host,
                    cfg.mqtt_port,
                    username="gateway",
                    password=cfg.secret("mqtt"),
                    identifier="eyewatcher-gateway",
                ) as client:
                    self.mqtt = client
                    await client.subscribe(TELEMETRY_FILTER, qos=1)
                    await client.subscribe(STATUS_TOPIC, qos=1)
                    logger.info("conectado ao Mosquitto")
                    async for message in client.messages:
                        try:
                            await self.on_mqtt(str(message.topic), bytes(message.payload))
                        except BusUnavailableError:
                            # Telemetria e QoS 0: sem barramento, a leitura se perde
                            # e a seguinte chega em instantes.
                            logger.debug("RabbitMQ fora do ar; leitura descartada")
            except aiomqtt.MqttError as exc:
                self.mqtt = None
                logger.warning("Mosquitto indisponivel (%s); tentando de novo", exc)
                await asyncio.sleep(3)

    async def run(self) -> None:
        await self.bus.connect()
        await self.bus.consume("q.commands.device", self.on_command)
        await asyncio.gather(self.mqtt_loop(), heartbeat_loop())


def main() -> None:
    cfg = get_settings()
    configure_logging(cfg)
    asyncio.run(Gateway(cfg).run())


if __name__ == "__main__":
    main()
