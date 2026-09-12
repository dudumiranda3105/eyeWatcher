"""Cliente MQTT do backend (paho-mqtt 2.x, API de callbacks VERSION2).

Roda em thread propria (`loop_start`), com reconexao automatica.
Para cada mensagem recebida:
  1. extrai o `rack_id` do topico `<prefix>/<rack_id>/telemetry|status`;
  2. valida o payload com pydantic (payload invalido -> warning + descarte);
  3. RE-CALCULA o status com os limiares do backend (nao confia no ESP32);
  4. grava no InfluxDB (batch);
  5. publica o evento para os websockets conectados.
"""

from __future__ import annotations

import json
import logging
import threading
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any, Final

import paho.mqtt.client as mqtt
from pydantic import ValidationError

from app.config import Settings
from app.influx import InfluxGateway
from app.models import TelemetryPayload, classify_status, iso_z

logger = logging.getLogger(__name__)

#: Callback usado para empurrar eventos aos websockets (thread-safe).
EventSink = Callable[[dict[str, Any]], None]

_STATUS_ONLINE: Final[str] = "online"
_STATUS_OFFLINE: Final[str] = "offline"


class MqttService:
    """Ingestao MQTT -> InfluxDB -> WebSocket."""

    def __init__(
        self,
        cfg: Settings,
        influx: InfluxGateway,
        event_sink: EventSink | None = None,
    ) -> None:
        self._cfg = cfg
        self._influx = influx
        self._event_sink: EventSink | None = event_sink
        self._connected = threading.Event()
        self._device_ids: dict[str, str] = {}
        self._lock = threading.Lock()
        self._started = False

        # paho-mqtt 2.x: a API de callbacks VERSION2 e obrigatoria explicitamente.
        self._client = mqtt.Client(
            mqtt.CallbackAPIVersion.VERSION2,
            client_id=cfg.mqtt_client_id,
            protocol=mqtt.MQTTv311,
            clean_session=True,
        )
        if cfg.mqtt_username:
            self._client.username_pw_set(cfg.mqtt_username, cfg.mqtt_password or None)
        self._client.reconnect_delay_set(min_delay=1, max_delay=30)
        self._client.on_connect = self._on_connect
        self._client.on_disconnect = self._on_disconnect
        self._client.on_message = self._on_message
        self._client.on_subscribe = self._on_subscribe

    # ------------------------------------------------------------------ #
    # Ciclo de vida
    # ------------------------------------------------------------------ #
    def set_event_sink(self, sink: EventSink | None) -> None:
        self._event_sink = sink

    @property
    def connected(self) -> bool:
        return self._connected.is_set()

    def start(self) -> None:
        """Inicia a thread de rede. Nao levanta excecao se o broker estiver fora."""
        if self._started:
            return
        cfg = self._cfg
        self._started = True
        try:
            # connect_async + loop_start nao bloqueia nem falha com o broker fora:
            # o paho fica tentando reconectar sozinho.
            self._client.connect_async(cfg.mqtt_host, cfg.mqtt_port, keepalive=cfg.mqtt_keepalive)
            self._client.loop_start()
            logger.info(
                "Cliente MQTT iniciado (broker=%s:%s, topicos=%s | %s)",
                cfg.mqtt_host,
                cfg.mqtt_port,
                cfg.topic_telemetry,
                cfg.topic_status,
            )
        except Exception:  # noqa: BLE001 — a API precisa subir mesmo assim
            logger.exception("Falha ao iniciar o cliente MQTT; a API segue no ar")

    def stop(self) -> None:
        """Encerra a conexao e a thread de rede."""
        if not self._started:
            return
        self._started = False
        try:
            self._client.disconnect()
        except Exception:  # noqa: BLE001
            logger.exception("Erro ao desconectar do broker MQTT")
        try:
            self._client.loop_stop()
        except Exception:  # noqa: BLE001
            logger.exception("Erro ao parar o loop MQTT")
        self._connected.clear()
        logger.info("Cliente MQTT encerrado")

    # ------------------------------------------------------------------ #
    # Callbacks paho 2.x (CallbackAPIVersion.VERSION2)
    # ------------------------------------------------------------------ #
    def _on_connect(
        self,
        client: mqtt.Client,
        userdata: Any,  # noqa: ANN401, ARG002
        flags: Any,  # noqa: ANN401, ARG002
        reason_code: Any,  # noqa: ANN401
        properties: Any = None,  # noqa: ANN401, ARG002
    ) -> None:
        if getattr(reason_code, "is_failure", False):
            self._connected.clear()
            logger.error("Conexao MQTT recusada: %s", reason_code)
            return
        self._connected.set()
        qos = self._cfg.mqtt_qos
        client.subscribe([(self._cfg.topic_telemetry, qos), (self._cfg.topic_status, qos)])
        logger.info("Conectado ao broker MQTT %s:%s", self._cfg.mqtt_host, self._cfg.mqtt_port)

    def _on_disconnect(
        self,
        client: mqtt.Client,  # noqa: ARG002
        userdata: Any,  # noqa: ANN401, ARG002
        flags: Any = None,  # noqa: ANN401, ARG002
        reason_code: Any = None,  # noqa: ANN401
        properties: Any = None,  # noqa: ANN401, ARG002
    ) -> None:
        self._connected.clear()
        logger.warning("Desconectado do broker MQTT (%s) — tentando reconectar", reason_code)

    def _on_subscribe(
        self,
        client: mqtt.Client,  # noqa: ARG002
        userdata: Any,  # noqa: ANN401, ARG002
        mid: int,
        reason_code_list: Any,  # noqa: ANN401
        properties: Any = None,  # noqa: ANN401, ARG002
    ) -> None:
        logger.debug("Assinatura confirmada (mid=%s): %s", mid, reason_code_list)

    def _on_message(
        self,
        client: mqtt.Client,  # noqa: ARG002
        userdata: Any,  # noqa: ANN401, ARG002
        message: mqtt.MQTTMessage,
    ) -> None:
        """Nunca deixa excecao escapar: um payload ruim nao pode matar a thread."""
        try:
            self._handle_message(message.topic, message.payload)
        except Exception:  # noqa: BLE001
            logger.exception("Erro inesperado ao processar mensagem de %s", message.topic)

    # ------------------------------------------------------------------ #
    # Processamento
    # ------------------------------------------------------------------ #
    def _parse_topic(self, topic: str) -> tuple[str, str] | None:
        """`<prefix>/<rack_id>/<kind>` -> (rack_id, kind).

        So aceita o formato de 3 niveis do contrato. O prefixo nao e comparado
        letra a letra porque ele pode ser sobrescrito por
        MQTT_TOPIC_TELEMETRY / MQTT_TOPIC_STATUS.
        """
        parts = topic.split("/")
        if len(parts) != 3:
            return None
        rack_id, kind = parts[1], parts[2]
        if not rack_id or kind not in ("telemetry", "status"):
            return None
        return rack_id, kind

    def _handle_message(self, topic: str, raw: bytes) -> None:
        parsed = self._parse_topic(topic)
        if parsed is None:
            logger.warning("Topico fora do contrato, mensagem descartada: %s", topic)
            return
        rack_id, kind = parsed
        if kind == "telemetry":
            self._handle_telemetry(rack_id, raw)
        elif kind == "status":
            self._handle_status(rack_id, raw)
        else:
            logger.debug("Topico ignorado: %s", topic)

    def _handle_telemetry(self, topic_rack_id: str, raw: bytes) -> None:
        try:
            decoded = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            logger.warning("Telemetria de %s descartada (JSON invalido): %s", topic_rack_id, exc)
            return
        if not isinstance(decoded, dict):
            logger.warning("Telemetria de %s descartada: payload nao e um objeto", topic_rack_id)
            return

        try:
            payload = TelemetryPayload.model_validate(decoded)
        except ValidationError as exc:
            logger.warning(
                "Telemetria de %s descartada (payload invalido): %s",
                topic_rack_id,
                exc.errors(include_url=False),
            )
            return

        if payload.rack_id != topic_rack_id:
            logger.warning(
                "rack_id do payload (%s) difere do topico (%s); usando o do topico",
                payload.rack_id,
                topic_rack_id,
            )

        rack_id = topic_rack_id
        received_at = datetime.now(UTC)

        # O backend NAO confia no status calculado pelo ESP32.
        status = classify_status(payload.temperature, payload.humidity, self._cfg)
        if status != payload.status:
            logger.info(
                "Status recalculado para %s: firmware=%s backend=%s (t=%.1f h=%.1f)",
                rack_id,
                payload.status,
                status,
                payload.temperature,
                payload.humidity,
            )

        with self._lock:
            self._device_ids[rack_id] = payload.device_id

        self._influx.write_reading(
            device_id=payload.device_id,
            rack_id=rack_id,
            location=payload.location,
            status=status,
            temperature=payload.temperature,
            humidity=payload.humidity,
            heat_index=payload.heat_index,
            seq=payload.seq,
            ts=received_at,
        )

        enriched: dict[str, Any] = payload.model_dump()
        enriched["rack_id"] = rack_id
        enriched["status"] = status
        enriched["time"] = iso_z(received_at)
        self._emit({"type": "telemetry", "data": enriched})

    def _handle_status(self, rack_id: str, raw: bytes) -> None:
        text = raw.decode("utf-8", errors="replace").strip().lower()
        if text not in (_STATUS_ONLINE, _STATUS_OFFLINE):
            logger.warning("Status de %s descartado (valor invalido): %r", rack_id, text)
            return
        online = text == _STATUS_ONLINE
        with self._lock:
            device_id = self._device_ids.get(rack_id, f"esp32-{rack_id}")

        logger.info("Rack %s ficou %s", rack_id, text)
        self._influx.write_device_status(
            device_id=device_id,
            rack_id=rack_id,
            online=online,
            ts=datetime.now(UTC),
        )
        self._emit({"type": "status", "data": {"rack_id": rack_id, "online": online}})

    def _emit(self, event: dict[str, Any]) -> None:
        sink = self._event_sink
        if sink is None:
            return
        try:
            sink(event)
        except Exception:  # noqa: BLE001
            logger.exception("Falha ao publicar evento para os websockets")
