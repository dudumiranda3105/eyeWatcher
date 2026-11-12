"""Consumidores da API: entrega ao WebSocket, regras de negocio e persistencia."""

from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import Any, Final

from fastapi import WebSocket, WebSocketDisconnect

from eyewatcher.api import db
from eyewatcher.api.state import AppState
from eyewatcher.bus import Envelope, make_envelope

logger = logging.getLogger("eyewatcher.api.live")

#: Espera entre comandos da mesma regra, para dar tempo de o estado do atuador mudar.
RULE_COOLDOWN_S: Final[float] = 6.0


async def publish_device_config(state: AppState) -> None:
    """Envia o cadastro ao simulador: e assim que um sensor novo passa a publicar."""
    rows = await state.db.fetch("SELECT id, kind, type, enabled FROM devices")
    message = make_envelope("command", "simulator", {"devices": [dict(row) for row in rows]})
    await state.bus.publish(f"command.{state.cfg.zone}.sim.config", message)


async def load_rules(state: AppState) -> None:
    rows = await state.db.fetch("SELECT * FROM rules WHERE enabled")
    state.rules = [dict(row) for row in rows]


async def send_device_command(state: AppState, device: dict[str, Any], action: str) -> None:
    message = make_envelope("command", device["id"], {"action": action})
    await state.bus.publish(f"command.{device['zone']}.{device['type']}.{device['id']}", message)


async def broadcast(state: AppState, message: dict[str, Any]) -> None:
    if not state.clients:
        return
    body = json.dumps(message, default=str)
    results = await asyncio.gather(
        *(client.send_text(body) for client in state.clients), return_exceptions=True
    )
    for client, result in zip(list(state.clients), results, strict=False):
        if isinstance(result, Exception):
            state.clients.discard(client)


async def on_live(state: AppState, routing_key: str, envelope: Envelope) -> None:
    """q.live.ws: atualiza o ultimo valor conhecido e repassa ao navegador."""
    message = {"routing_key": routing_key, **envelope.model_dump(mode="json")}
    payload = envelope.payload
    if envelope.type == "telemetry":
        state.latest[envelope.device] = message
        # Se chega leitura, o simulador esta no ar, mesmo que a API tenha subido depois dele.
        state.simulator_online = True
    elif envelope.type == "prediction":
        state.predictions[envelope.device] = message
        state.inference_state.pop(envelope.device, None)
    elif envelope.type == "event" and payload.get("kind") == "inference_state":
        state.inference_state[envelope.device] = message
    elif envelope.type == "event" and payload.get("kind") == "status":
        state.simulator_online = bool(payload["online"])

    if payload.get("kind") != "inference_state":
        state.recent.appendleft(message)
    await broadcast(state, message)


async def on_rules(state: AppState, _routing_key: str, envelope: Envelope) -> None:
    """q.telemetry.rules: aplica as regras com histerese (liga num limite, desliga em outro)."""
    metrics = envelope.payload["metrics"]
    for rule in state.rules:
        if rule["device_id"] != envelope.device or rule["metric"] not in metrics:
            continue
        value = float(metrics[rule["metric"]])
        last = state.latest.get(rule["actuator_id"])
        actuator_on = bool(last and last["payload"]["metrics"].get("on"))
        if value >= rule["threshold"] and not actuator_on:
            await fire_rule(state, rule, "on", value)
        elif value <= rule["clear_threshold"] and actuator_on:
            await fire_rule(state, rule, "off", value)


async def fire_rule(state: AppState, rule: dict[str, Any], action: str, value: float) -> None:
    now = time.monotonic()
    if now - state.rule_last_fired.get(rule["id"], 0.0) < RULE_COOLDOWN_S:
        return
    state.rule_last_fired[rule["id"]] = now

    device = await state.db.fetchrow("SELECT * FROM devices WHERE id=$1", rule["actuator_id"])
    if device is None:
        return
    await send_device_command(state, dict(device), action)
    await db.audit(
        state.db,
        "regra-automatica",
        f"rule_{action}",
        rule["actuator_id"],
        {"rule": rule["name"], "value": value},
    )
    alert = {
        "state": "open" if action == "on" else "clear",
        "severity": rule["severity"],
        "source": f"rule:{rule['id']}",
        "message": f"{rule['name']}: {rule['metric']} em {value:.1f} ({rule['actuator_id']} {action})",
    }
    await state.bus.publish(
        f"alert.{state.cfg.zone}.{rule['device_id']}",
        make_envelope("alert", rule["device_id"], alert),
    )


async def on_persist(state: AppState, routing_key: str, envelope: Envelope) -> None:
    """q.api.persist: a API e o unico servico que escreve no PostgreSQL."""
    payload = envelope.payload
    if envelope.type == "alert":
        await persist_alert(state, envelope)
    elif payload.get("kind") == "job":
        await state.db.execute(
            """UPDATE jobs
               SET status=$2, progress=$3, stage=$4, result=COALESCE($5, result),
                   finished_at=CASE WHEN $2 IN ('done', 'failed') THEN now() END
               WHERE id=$1""",
            payload["job_id"],
            payload["status"],
            float(payload["progress"]),
            payload.get("stage"),
            payload.get("result"),
        )
    elif payload.get("kind") == "model":
        await state.db.execute(
            """INSERT INTO model_versions (version, trained_at, dataset, promoted, summary)
               VALUES ($1, $2, $3, $4, $5) ON CONFLICT (version) DO NOTHING""",
            payload["version"],
            envelope.ts,
            payload["dataset"],
            payload["promoted"],
            payload,
        )
    else:
        raise ValueError(f"mensagem inesperada em {routing_key}")


async def persist_alert(state: AppState, envelope: Envelope) -> None:
    payload = envelope.payload
    device = envelope.device
    source = payload.get("source", "ia")
    if payload["state"] == "clear":
        await state.db.execute(
            """UPDATE alerts SET cleared_at=$3
               WHERE device_id=$1 AND source=$2 AND cleared_at IS NULL""",
            device,
            source,
            envelope.ts,
        )
        return
    updated = await state.db.execute(
        """UPDATE alerts SET severity=$3, message=$4
           WHERE device_id=$1 AND source=$2 AND cleared_at IS NULL""",
        device,
        source,
        payload["severity"],
        payload["message"],
    )
    if updated == "UPDATE 0":
        await state.db.execute(
            """INSERT INTO alerts (device_id, source, severity, message, opened_at)
               VALUES ($1, $2, $3, $4, $5)""",
            device,
            source,
            payload["severity"],
            payload["message"],
            envelope.ts,
        )


async def serve_websocket(state: AppState, websocket: WebSocket) -> None:
    """Manda a foto atual e depois so o que chegar pelo RabbitMQ."""
    await websocket.accept()
    await websocket.send_text(
        json.dumps(
            {
                "type": "snapshot",
                "latest": state.latest,
                "predictions": state.predictions,
                "inference_state": state.inference_state,
                "simulator_online": state.simulator_online,
            },
            default=str,
        )
    )
    state.clients.add(websocket)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        pass
    finally:
        state.clients.discard(websocket)
