"""Estado compartilhado da API: conexoes e o ultimo valor conhecido de cada coisa."""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from typing import Any

import asyncpg
from fastapi import Request, WebSocket
from influxdb_client import InfluxDBClient

from eyewatcher.bus import Bus
from eyewatcher.settings import Settings


@dataclass
class AppState:
    cfg: Settings
    db: asyncpg.Pool
    bus: Bus
    influx: InfluxDBClient
    jwt_secret: str
    clients: set[WebSocket] = field(default_factory=set)
    latest: dict[str, dict[str, Any]] = field(default_factory=dict)
    predictions: dict[str, dict[str, Any]] = field(default_factory=dict)
    inference_state: dict[str, dict[str, Any]] = field(default_factory=dict)
    recent: deque[dict[str, Any]] = field(default_factory=lambda: deque(maxlen=60))
    simulator_online: bool = False
    rules: list[dict[str, Any]] = field(default_factory=list)
    rule_last_fired: dict[int, float] = field(default_factory=dict)


def get_state(request: Request) -> AppState:
    return request.app.state.eyewatcher  # type: ignore[no-any-return]
