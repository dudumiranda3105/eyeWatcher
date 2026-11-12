"""Rotas REST da aplicacao."""

from __future__ import annotations

import asyncio
import json
import re
from typing import Annotated, Any, Final, Literal
from urllib.parse import quote
from uuid import uuid4

import asyncpg
import httpx
from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from eyewatcher import physics, synthetic
from eyewatcher.api import assistant, db, influx, live
from eyewatcher.api.auth import User, client_ip, current_user, require
from eyewatcher.api.state import AppState, get_state
from eyewatcher.bus import make_envelope

router = APIRouter()

State = Annotated[AppState, Depends(get_state)]
Viewer = Annotated[User, Depends(current_user)]
Operator = Annotated[User, Depends(require("operator"))]
Admin = Annotated[User, Depends(require("admin"))]

RangeKey = Literal["15m", "1h", "6h", "24h", "7d", "30d"]
DEVICE_ID: Final[re.Pattern[str]] = re.compile(r"^[a-z0-9][a-z0-9-]{1,40}$")


async def get_device(state: AppState, device_id: str) -> dict[str, Any]:
    row = await state.db.fetchrow("SELECT * FROM devices WHERE id=$1", device_id)
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "dispositivo não encontrado")
    return dict(row)


# ---------------------------------------------------------------- saude


@router.get("/health", tags=["sistema"])
async def health(state: State) -> dict[str, Any]:
    ollama = await assistant.model_status(state)
    return {
        "status": "ok" if state.bus.connected else "degraded",
        "rabbitmq": state.bus.connected,
        "simulator": state.simulator_online,
        "llm": ollama,
    }


# ---------------------------------------------------------------- dispositivos


class DeviceBody(BaseModel):
    name: str = Field(min_length=2, max_length=80)
    kind: Literal["sensor", "actuator", "equipment"]
    type: str = Field(min_length=2, max_length=30)
    unit: str | None = None
    normal_min: float | None = None
    normal_max: float | None = None
    critical_min: float | None = None
    critical_max: float | None = None
    controllable: bool = False
    enabled: bool = True


class NewDeviceBody(DeviceBody):
    id: str


def device_metric(body: DeviceBody) -> str:
    if body.kind == "sensor":
        if body.type not in physics.SENSOR_METRICS:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY,
                f"tipo de sensor deve ser um de {sorted(physics.SENSOR_METRICS)}",
            )
        return physics.SENSOR_METRICS[body.type]
    return "vibration" if body.kind == "equipment" else "on"


@router.get("/devices", tags=["dispositivos"])
async def list_devices(state: State, _: Viewer) -> list[dict[str, Any]]:
    rows = await state.db.fetch("SELECT * FROM devices ORDER BY kind, id")
    return [dict(row) for row in rows]


@router.post("/devices", status_code=201, tags=["dispositivos"])
async def create_device(
    body: NewDeviceBody, state: State, user: Admin, request: Request
) -> dict[str, Any]:
    if not DEVICE_ID.match(body.id):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "id inválido: use a-z, 0-9 e -")
    try:
        row = await state.db.fetchrow(
            """INSERT INTO devices (id, name, kind, type, zone, metric, unit, normal_min, normal_max,
                   critical_min, critical_max, controllable, enabled)
               VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13) RETURNING *""",
            body.id,
            body.name,
            body.kind,
            "equipment" if body.kind == "equipment" else body.type,
            state.cfg.zone,
            device_metric(body),
            body.unit,
            body.normal_min,
            body.normal_max,
            body.critical_min,
            body.critical_max,
            body.controllable,
            body.enabled,
        )
    except asyncpg.UniqueViolationError as exc:
        raise HTTPException(
            status.HTTP_409_CONFLICT, "já existe um dispositivo com esse id"
        ) from exc
    await db.audit(state.db, user.username, "device_create", body.id, ip=client_ip(request))
    await live.publish_device_config(state)
    return dict(row)


@router.put("/devices/{device_id}", tags=["dispositivos"])
async def update_device(
    device_id: str, body: DeviceBody, state: State, user: Admin, request: Request
) -> dict[str, Any]:
    await get_device(state, device_id)
    row = await state.db.fetchrow(
        """UPDATE devices SET name=$2, unit=$3, normal_min=$4, normal_max=$5, critical_min=$6,
               critical_max=$7, controllable=$8, enabled=$9
           WHERE id=$1 RETURNING *""",
        device_id,
        body.name,
        body.unit,
        body.normal_min,
        body.normal_max,
        body.critical_min,
        body.critical_max,
        body.controllable,
        body.enabled,
    )
    await db.audit(state.db, user.username, "device_update", device_id, ip=client_ip(request))
    await live.publish_device_config(state)
    return dict(row)


@router.delete("/devices/{device_id}", status_code=204, tags=["dispositivos"])
async def delete_device(device_id: str, state: State, user: Admin, request: Request) -> None:
    await get_device(state, device_id)
    await state.db.execute("DELETE FROM devices WHERE id=$1", device_id)
    state.latest.pop(device_id, None)
    await db.audit(state.db, user.username, "device_delete", device_id, ip=client_ip(request))
    await live.load_rules(state)
    await live.publish_device_config(state)


class CommandBody(BaseModel):
    action: Literal["on", "off"]


@router.post("/devices/{device_id}/command", status_code=202, tags=["dispositivos"])
async def command_device(
    device_id: str, body: CommandBody, state: State, user: Operator, request: Request
) -> dict[str, str]:
    device = await get_device(state, device_id)
    if not device["controllable"]:
        raise HTTPException(status.HTTP_409_CONFLICT, "este atuador é controlado por regra")
    await live.send_device_command(state, device, body.action)
    await db.audit(
        state.db,
        user.username,
        "device_command",
        device_id,
        {"action": body.action},
        client_ip(request),
    )
    return {"status": "enviado"}


# ---------------------------------------------------------------- regras


class RuleBody(BaseModel):
    name: str = Field(min_length=2, max_length=80)
    device_id: str
    metric: str
    threshold: float
    clear_threshold: float
    actuator_id: str
    severity: Literal["warning", "critical"] = "warning"
    enabled: bool = True


@router.get("/rules", tags=["regras"])
async def list_rules(state: State, _: Viewer) -> list[dict[str, Any]]:
    return [dict(row) for row in await state.db.fetch("SELECT * FROM rules ORDER BY id")]


@router.post("/rules", status_code=201, tags=["regras"])
async def create_rule(
    body: RuleBody, state: State, user: Admin, request: Request
) -> dict[str, Any]:
    await get_device(state, body.device_id)
    await get_device(state, body.actuator_id)
    if body.clear_threshold >= body.threshold:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "o limite de desligar deve ser menor que o de ligar",
        )
    row = await state.db.fetchrow(
        """INSERT INTO rules (name, device_id, metric, threshold, clear_threshold, actuator_id,
               severity, enabled)
           VALUES ($1, $2, $3, $4, $5, $6, $7, $8) RETURNING *""",
        body.name,
        body.device_id,
        body.metric,
        body.threshold,
        body.clear_threshold,
        body.actuator_id,
        body.severity,
        body.enabled,
    )
    await db.audit(state.db, user.username, "rule_create", body.name, ip=client_ip(request))
    await live.load_rules(state)
    return dict(row)


@router.delete("/rules/{rule_id}", status_code=204, tags=["regras"])
async def delete_rule(rule_id: int, state: State, user: Admin, request: Request) -> None:
    await state.db.execute("DELETE FROM rules WHERE id=$1", rule_id)
    await db.audit(state.db, user.username, "rule_delete", str(rule_id), ip=client_ip(request))
    await live.load_rules(state)


# ---------------------------------------------------------------- leituras


@router.get("/readings/history", tags=["leituras"])
async def readings_history(
    state: State,
    _: Viewer,
    device: str,
    metric: str,
    range: RangeKey = "1h",  # noqa: A002
) -> dict[str, Any]:
    points = await influx.history(state.influx, state.cfg, "telemetry", device, metric, range)
    return {"device": device, "metric": metric, "range": range, "points": points}


@router.get("/readings/stats", tags=["leituras"])
async def readings_stats(
    state: State,
    _: Viewer,
    device: str,
    metric: str,
    range: RangeKey = "1h",  # noqa: A002
) -> dict[str, Any]:
    values = await influx.stats(state.influx, state.cfg, device, metric, range)
    return {"device": device, "metric": metric, "range": range, **values}


@router.get("/alerts", tags=["alertas"])
async def list_alerts(
    state: State, _: Viewer, only_open: bool = False, limit: int = Query(50, le=200)
) -> list[dict[str, Any]]:
    where = "WHERE cleared_at IS NULL" if only_open else ""
    rows = await state.db.fetch(
        f"SELECT * FROM alerts {where} ORDER BY opened_at DESC LIMIT $1", limit
    )
    return [dict(row) for row in rows]


@router.get("/audit", tags=["sistema"])
async def list_audit(
    state: State, _: Admin, limit: int = Query(100, le=500)
) -> list[dict[str, Any]]:
    rows = await state.db.fetch("SELECT * FROM audit_log ORDER BY ts DESC LIMIT $1", limit)
    return [dict(row) for row in rows]


# ---------------------------------------------------------------- simulador


class SimulatorBody(BaseModel):
    action: Literal["pause", "resume", "inject_fault", "repair"]
    target: str | None = None
    mode: str | None = None


@router.post("/simulator/command", status_code=202, tags=["simulador"])
async def simulator_command(
    body: SimulatorBody, state: State, user: Operator, request: Request
) -> dict[str, str]:
    needs_target = body.action in {"inject_fault", "repair"}
    if needs_target and (
        body.target is None or (await get_device(state, body.target))["kind"] != "equipment"
    ):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "escolha um equipamento")
    if body.action == "inject_fault" and body.mode not in (
        *physics.FAILURE_MODES,
        *physics.SENSOR_FAULTS,
    ):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "modo de falha desconhecido")
    message = make_envelope("command", "simulator", body.model_dump(exclude_none=True))
    await state.bus.publish(f"command.{state.cfg.zone}.sim.simulator", message)
    await db.audit(
        state.db,
        user.username,
        f"simulator_{body.action}",
        body.target,
        {"mode": body.mode},
        client_ip(request),
    )
    return {"status": "enviado"}


# ---------------------------------------------------------------- laboratorio e treino


async def enqueue_job(
    state: AppState, kind: str, routing_key: str, payload: dict[str, Any], user: User, ip: str
) -> dict[str, str]:
    job_id = uuid4().hex[:12]
    await state.db.execute(
        "INSERT INTO jobs (id, kind, status, params, created_by) VALUES ($1, $2, 'queued', $3, $4)",
        job_id,
        kind,
        payload,
        user.username,
    )
    await state.bus.publish(routing_key, make_envelope("job", kind, {"job_id": job_id, **payload}))
    await db.audit(state.db, user.username, f"job_{kind}", job_id, payload, ip)
    return {"job_id": job_id}


@router.get("/lab/options", tags=["laboratorio"])
async def lab_options(_: Viewer) -> dict[str, Any]:
    return {
        "failure_modes": list(physics.FAILURE_MODES),
        "defaults": synthetic.GenerationParams().model_dump(),
        "min_readings": synthetic.MIN_READINGS,
        "max_readings": synthetic.MAX_READINGS,
        "sample_minutes": physics.SAMPLE_MINUTES,
    }


@router.post("/lab/jobs", status_code=202, tags=["laboratorio"])
async def create_lab_job(
    params: synthetic.GenerationParams, state: State, user: Admin, request: Request
) -> dict[str, str]:
    readings = params.estimated_readings()
    if not synthetic.MIN_READINGS <= readings <= synthetic.MAX_READINGS:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            f"o volume ({readings:,}) precisa ficar entre {synthetic.MIN_READINGS:,} "
            f"e {synthetic.MAX_READINGS:,} leituras",
        )
    return await enqueue_job(
        state, "datagen", "job.datagen", {"params": params.model_dump()}, user, client_ip(request)
    )


@router.get("/jobs", tags=["laboratorio"])
async def list_jobs(
    state: State, _: Viewer, kind: str | None = None, limit: int = Query(20, le=100)
) -> list[dict[str, Any]]:
    rows = await state.db.fetch(
        """SELECT * FROM jobs WHERE ($1::text IS NULL OR kind=$1)
           ORDER BY created_at DESC LIMIT $2""",
        kind,
        limit,
    )
    return [dict(row) for row in rows]


class TrainingBody(BaseModel):
    dataset_id: str | None = None


@router.post("/training/jobs", status_code=202, tags=["treinamento"])
async def create_training_job(
    body: TrainingBody, state: State, user: Admin, request: Request
) -> dict[str, str]:
    payload = {"dataset_id": body.dataset_id} if body.dataset_id else {}
    return await enqueue_job(state, "training", "job.training", payload, user, client_ip(request))


@router.get("/training/models", tags=["treinamento"])
async def list_models(state: State, _: Viewer) -> list[dict[str, Any]]:
    rows = await state.db.fetch("SELECT * FROM model_versions ORDER BY trained_at DESC LIMIT 10")
    return [dict(row) for row in rows]


# ---------------------------------------------------------------- insights


@router.get("/insights", tags=["insights"])
async def insights(state: State, _: Viewer) -> list[dict[str, Any]]:
    equipment = await state.db.fetch(
        "SELECT id, name FROM devices WHERE kind='equipment' ORDER BY id"
    )
    return [
        {
            **dict(row),
            "prediction": state.predictions.get(row["id"]),
            "state": state.inference_state.get(row["id"]),
        }
        for row in equipment
    ]


@router.get("/insights/{device_id}/history", tags=["insights"])
async def insight_history(
    device_id: str,
    state: State,
    _: Viewer,
    field: Literal["health", "rul_h"] = "health",
    range: RangeKey = "1h",  # noqa: A002
) -> dict[str, Any]:
    points = await influx.history(state.influx, state.cfg, "prediction", device_id, field, range)
    return {"device": device_id, "field": field, "range": range, "points": points}


# ---------------------------------------------------------------- mensageria


async def rabbit_get(client: httpx.AsyncClient, path: str) -> Any:
    response = await client.get(path)
    response.raise_for_status()
    return response.json()


def rabbit_client(state: AppState) -> httpx.AsyncClient:
    return httpx.AsyncClient(
        base_url=state.cfg.rabbit_mgmt_url,
        auth=("api", state.cfg.secret("amqp")),
        timeout=5.0,
    )


def rate(stats: dict[str, Any] | None, name: str) -> float:
    return float(((stats or {}).get(f"{name}_details") or {}).get("rate", 0.0))


@router.get("/messaging/overview", tags=["mensageria"])
async def messaging_overview(state: State, _: Viewer) -> dict[str, Any]:
    """O navegador nunca fala com o broker: a API consulta o gerenciamento por ele."""
    vhost = quote(state.cfg.amqp_vhost, safe="")
    try:
        async with rabbit_client(state) as client:
            queues, consumers, overview = await asyncio.gather(
                rabbit_get(client, f"/api/queues/{vhost}"),
                rabbit_get(client, f"/api/consumers/{vhost}"),
                rabbit_get(client, "/api/overview"),
            )
    except httpx.HTTPError as exc:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "RabbitMQ indisponível") from exc

    totals = overview.get("message_stats")
    return {
        "publish_rate": rate(totals, "publish"),
        "deliver_rate": rate(totals, "deliver_get"),
        "queues": [
            {
                "name": queue["name"],
                "messages": queue.get("messages", 0),
                "ready": queue.get("messages_ready", 0),
                "unacked": queue.get("messages_unacknowledged", 0),
                "consumers": queue.get("consumers", 0),
                "publish_rate": rate(queue.get("message_stats"), "publish"),
                "deliver_rate": rate(queue.get("message_stats"), "deliver_get"),
            }
            for queue in sorted(queues, key=lambda item: item["name"])
        ],
        "consumers": [
            {
                "queue": item["queue"]["name"],
                "tag": item["consumer_tag"],
                "service": (item.get("channel_details") or {}).get("user"),
            }
            for item in consumers
        ],
        "recent": list(state.recent)[:25],
    }


@router.get("/messaging/dlq", tags=["mensageria"])
async def messaging_dlq(state: State, _: Viewer) -> list[dict[str, Any]]:
    """Le a DLQ sem consumir: as mensagens continuam preservadas na fila."""
    vhost = quote(state.cfg.amqp_vhost, safe="")
    body = {"count": 20, "ackmode": "ack_requeue_true", "encoding": "auto"}
    async with rabbit_client(state) as client:
        response = await client.post(f"/api/queues/{vhost}/q.dlq/get", json=body)
    response.raise_for_status()
    return [
        {
            "routing_key": item["routing_key"],
            "payload": item["payload"],
            "death": (item["properties"].get("headers") or {}).get("x-death"),
            "origin": (item["properties"].get("headers") or {}).get("x-origin-topic"),
        }
        for item in response.json()
    ]


@router.post("/messaging/poison", status_code=202, tags=["mensageria"])
async def messaging_poison(state: State, user: Operator, request: Request) -> dict[str, str]:
    """Publica uma mensagem fora do formato, para demonstrar a DLQ."""
    body = json.dumps({"mensagem": "fora do formato unico", "por": user.username}).encode("utf-8")
    await state.bus.publish_raw(
        "eyewatcher.topic", f"telemetry.{state.cfg.zone}.invalid.demo", body
    )
    await db.audit(state.db, user.username, "dlq_demo", ip=client_ip(request))
    return {"status": "enviada"}


# ---------------------------------------------------------------- assistente


class ChatBody(BaseModel):
    question: str = Field(min_length=1, max_length=500)
    history: list[dict[str, str]] = Field(default_factory=list, max_length=12)


@router.get("/assistant/status", tags=["assistente"])
async def assistant_status(state: State, _: Viewer) -> dict[str, str]:
    return {"status": await assistant.model_status(state), "model": state.cfg.ollama_model}


@router.post("/assistant/chat", tags=["assistente"])
async def assistant_chat(
    body: ChatBody, state: State, user: Viewer, request: Request
) -> StreamingResponse:
    if not assistant.allow_question(user.username, state.cfg.assistant_per_minute):
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS, "limite de perguntas por minuto atingido"
        )
    await db.audit(
        state.db,
        user.username,
        "assistant_question",
        detail={"question": body.question},
        ip=client_ip(request),
    )
    history = [
        {"role": item["role"], "content": item["content"][:1000]}
        for item in body.history
        if item.get("role") in {"user", "assistant"} and "content" in item
    ]
    return StreamingResponse(
        assistant.stream_answer(state, body.question, history),
        media_type="text/plain; charset=utf-8",
    )
