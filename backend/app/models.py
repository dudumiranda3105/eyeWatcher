"""Modelos pydantic de entrada (payload MQTT) e de saida (respostas da API).

Todos os nomes de campo seguem `docs/CONTRACT.md` — nao renomear.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.config import Settings

Status = Literal["ok", "warning", "critical"]

RANGE_VALUES: tuple[str, ...] = ("15m", "1h", "6h", "24h", "7d", "30d")
DEFAULT_RANGE: str = "6h"
DEFAULT_WINDOW: str = "1m"


def iso_z(dt: datetime) -> str:
    """Formata um datetime em ISO-8601 UTC com milissegundos e sufixo `Z`.

    Ex.: `2026-09-12T11:47:03.412Z` (formato exato exigido pelo contrato).
    """
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    dt = dt.astimezone(UTC)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


# --------------------------------------------------------------------------- #
# Entrada — payload MQTT
# --------------------------------------------------------------------------- #
class TelemetryPayload(BaseModel):
    """Payload de `eyewatcher/<rack_id>/telemetry`.

    Validacao **estrita**: campo faltando ou com tipo errado levanta
    `ValidationError` e a mensagem e descartada (com log de warning) pelo
    cliente MQTT, sem derrubar o servico.
    """

    model_config = ConfigDict(strict=True, extra="ignore")

    device_id: str = Field(min_length=1, max_length=64)
    rack_id: str = Field(min_length=1, max_length=64)
    location: str = Field(min_length=1, max_length=128)
    temperature: float
    humidity: float
    heat_index: float
    status: Status
    uptime_s: int = Field(ge=0)
    seq: int = Field(ge=0)


# --------------------------------------------------------------------------- #
# Saida — respostas da API
# --------------------------------------------------------------------------- #
class HealthOut(BaseModel):
    """`GET /api/health`."""

    status: Literal["ok", "degraded"]
    influx: bool
    mqtt: bool


class Reading(BaseModel):
    """Bloco `last_reading` do contrato."""

    time: str
    temperature: float | None = None
    humidity: float | None = None
    heat_index: float | None = None
    status: str = "ok"


class RackOut(BaseModel):
    """Item de `GET /api/racks`."""

    rack_id: str
    device_id: str
    location: str
    online: bool
    last_reading: Reading | None = None


class LatestOut(BaseModel):
    """`GET /api/readings/latest` — `last_reading` achatado + metadados do rack."""

    rack_id: str
    device_id: str
    location: str
    online: bool
    time: str
    temperature: float | None = None
    humidity: float | None = None
    heat_index: float | None = None
    status: str = "ok"


class HistoryPoint(BaseModel):
    """Ponto agregado da serie temporal (valores podem ser `null` em lacunas)."""

    time: str
    temperature: float | None = None
    humidity: float | None = None
    heat_index: float | None = None


class HistoryOut(BaseModel):
    """`GET /api/readings/history`."""

    rack_id: str
    range: str
    window: str
    points: list[HistoryPoint] = Field(default_factory=list)


class MetricStats(BaseModel):
    """min/max/avg/last de uma metrica."""

    min: float | None = None
    max: float | None = None
    avg: float | None = None
    last: float | None = None


class StatsOut(BaseModel):
    """`GET /api/readings/stats`."""

    rack_id: str
    range: str
    count: int
    temperature: MetricStats
    humidity: MetricStats


class AlertItem(BaseModel):
    """Leitura com `status != "ok"`."""

    time: str
    status: str
    temperature: float | None = None
    humidity: float | None = None
    message: str


class AlertsOut(BaseModel):
    """`GET /api/alerts`."""

    rack_id: str
    range: str
    count: int
    alerts: list[AlertItem] = Field(default_factory=list)


# --------------------------------------------------------------------------- #
# Regras de dominio — limiares (CONTRACT.md secao 3)
# --------------------------------------------------------------------------- #
_SEVERITY: dict[str, int] = {"ok": 0, "warning": 1, "critical": 2}


def classify_temperature(temperature: float, cfg: Settings) -> Status:
    """ok < TEMP_WARN | warning [TEMP_WARN, TEMP_CRIT) | critical >= TEMP_CRIT."""
    if temperature >= cfg.temp_crit:
        return "critical"
    if temperature >= cfg.temp_warn:
        return "warning"
    return "ok"


def classify_humidity(humidity: float, cfg: Settings) -> Status:
    """ok [HUM_MIN_WARN, HUM_MAX_WARN] | critical < HUM_MIN_CRIT ou > HUM_MAX_CRIT."""
    if humidity < cfg.hum_min_crit or humidity > cfg.hum_max_crit:
        return "critical"
    if humidity < cfg.hum_min_warn or humidity > cfg.hum_max_warn:
        return "warning"
    return "ok"


def worst(*statuses: Status) -> Status:
    """Pior status entre os informados (ok < warning < critical)."""
    return max(statuses, key=lambda s: _SEVERITY.get(s, 0))


def classify_status(temperature: float, humidity: float, cfg: Settings) -> Status:
    """Status final = o pior entre temperatura e umidade."""
    return worst(
        classify_temperature(temperature, cfg),
        classify_humidity(humidity, cfg),
    )


def build_alert_message(
    status: str,
    temperature: float | None,
    humidity: float | None,
    cfg: Settings,
) -> str:
    """Mensagem legivel do alerta, ex.: `Temperatura crítica: 36.8 °C`."""
    labels = {"warning": "em alerta", "critical": "crítica"}
    parts: list[str] = []

    if temperature is not None:
        temp_status = classify_temperature(temperature, cfg)
        if temp_status != "ok":
            parts.append(f"Temperatura {labels[temp_status]}: {temperature:.1f} °C")

    if humidity is not None:
        hum_status = classify_humidity(humidity, cfg)
        if hum_status != "ok":
            parts.append(f"Umidade {labels[hum_status]}: {humidity:.1f} %")

    if not parts:
        parts.append(f"Leitura com status {status}")
    return " | ".join(parts)
