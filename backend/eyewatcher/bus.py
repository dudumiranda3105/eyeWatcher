"""Barramento interno: envelope unico de mensagem e cliente do RabbitMQ.

Toda mensagem do sistema tem o mesmo formato (identificador, instante, tipo,
dispositivo e conteudo). Os servicos nao declaram filas: a topologia nasce pronta
no definitions.json e cada usuario so tem permissao para o que usa.
"""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import Any, Final, Literal
from uuid import uuid4

import aio_pika
from aio_pika.abc import AbstractChannel, AbstractConnection, AbstractIncomingMessage
from pydantic import BaseModel

from eyewatcher.settings import Settings

logger = logging.getLogger("eyewatcher.bus")

EXCHANGE: Final[str] = "eyewatcher.topic"
DLX: Final[str] = "eyewatcher.dlx"

RETRY_SECONDS: Final[float] = 3.0

MessageType = Literal["telemetry", "command", "prediction", "alert", "event", "job"]


class Envelope(BaseModel):
    id: str
    ts: datetime
    type: MessageType
    device: str
    payload: dict[str, Any]


def make_envelope(kind: MessageType, device: str, payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": str(uuid4()),
        "ts": datetime.now(UTC).isoformat(),
        "type": kind,
        "device": device,
        "payload": payload,
    }


class RetryLaterError(Exception):
    """A dependencia caiu: a mensagem volta para a fila em vez de ir para a DLQ."""


class BusUnavailableError(Exception):
    """Sem conexao com o RabbitMQ neste instante; a reconexao ja esta em curso."""


Handler = Callable[[str, Envelope], Awaitable[None]]


class Bus:
    """Conexao com reconexao propria.

    Quando o broker cai, a conexao e refeita e todos os consumidores registrados
    voltam a consumir as mesmas filas, sem reiniciar o servico.
    """

    def __init__(self, cfg: Settings) -> None:
        self._cfg = cfg
        self._connection: AbstractConnection | None = None
        self._channel: AbstractChannel | None = None
        self._consumers: list[tuple[str, Handler, int]] = []
        self._closing = False
        self._reconnect: asyncio.Task[None] | None = None
        self._closer: asyncio.Task[None] | None = None

    async def connect(self) -> None:
        cfg = self._cfg
        while not self._closing:
            try:
                connection = await aio_pika.connect(
                    host=cfg.amqp_host,
                    port=cfg.amqp_port,
                    login=cfg.service_name,
                    password=cfg.secret("amqp"),
                    virtualhost=cfg.amqp_vhost,
                    client_properties={"connection_name": cfg.service_name},
                )
                self._channel = await connection.channel()
                self._connection = connection
                for queue_name, handler, prefetch in self._consumers:
                    await self._start_consumer(queue_name, handler, prefetch)
                connection.close_callbacks.add(self._on_connection_closed)
                logger.info("conectado ao RabbitMQ como %s", cfg.service_name)
                return
            except (OSError, aio_pika.exceptions.AMQPError) as exc:
                logger.warning("RabbitMQ indisponivel (%s); tentando de novo", exc)
                await asyncio.sleep(RETRY_SECONDS)

    def _on_connection_closed(self, *_: object) -> None:
        if self._closing or (self._reconnect is not None and not self._reconnect.done()):
            return
        logger.warning("conexao com o RabbitMQ caiu; reconectando")
        self._connection = self._channel = None
        self._reconnect = asyncio.get_running_loop().create_task(self.connect())

    def _on_channel_closed(self, *_: object) -> None:
        """Um canal que fecha sozinho derruba a conexao: a reconexao religa tudo."""
        connection = self._connection
        if self._closing or connection is None or connection.is_closed:
            return
        self._closer = asyncio.get_running_loop().create_task(connection.close())

    async def close(self) -> None:
        self._closing = True
        if self._connection is not None:
            await self._connection.close()

    @property
    def connected(self) -> bool:
        return self._connection is not None and not self._connection.is_closed

    async def publish(self, routing_key: str, message: dict[str, Any]) -> None:
        await self.publish_raw(EXCHANGE, routing_key, json.dumps(message).encode("utf-8"))

    async def publish_raw(
        self,
        exchange: str,
        routing_key: str,
        body: bytes,
        headers: dict[str, Any] | None = None,
    ) -> None:
        channel = self._channel
        if channel is None or channel.is_closed:
            raise BusUnavailableError("sem conexao com o RabbitMQ")
        try:
            target = await channel.get_exchange(exchange, ensure=False)
            await target.publish(
                aio_pika.Message(
                    body,
                    content_type="application/json",
                    delivery_mode=aio_pika.DeliveryMode.PERSISTENT,
                    headers=headers or {},
                ),
                routing_key=routing_key,
            )
        except (aio_pika.exceptions.AMQPError, RuntimeError) as exc:
            raise BusUnavailableError(str(exc)) from exc

    async def consume(self, queue_name: str, handler: Handler, prefetch: int = 50) -> None:
        """Consome uma fila em canal proprio; o que falhar vai para a DLQ, preservado."""
        self._consumers.append((queue_name, handler, prefetch))
        await self._start_consumer(queue_name, handler, prefetch)

    async def _start_consumer(self, queue_name: str, handler: Handler, prefetch: int) -> None:
        assert self._connection is not None
        channel = await self._connection.channel()
        await channel.set_qos(prefetch_count=prefetch)
        queue = await channel.get_queue(queue_name, ensure=False)

        async def on_message(message: AbstractIncomingMessage) -> None:
            try:
                envelope = Envelope.model_validate_json(message.body)
                await handler(message.routing_key or "", envelope)
            except (RetryLaterError, BusUnavailableError) as exc:
                logger.warning("%s: tentando depois (%s)", queue_name, exc)
                await asyncio.sleep(2)
                await message.nack(requeue=True)
            except Exception as exc:
                logger.warning("%s: mensagem para a DLQ (%s)", queue_name, exc)
                await message.reject(requeue=False)
            else:
                await message.ack()

        await queue.consume(on_message)
        channel.close_callbacks.add(self._on_channel_closed)
        logger.info("consumindo %s", queue_name)
