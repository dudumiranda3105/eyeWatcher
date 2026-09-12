"""Wrapper do InfluxDB 2.x: escrita em batch + queries Flux usadas pela API.

Schema (CONTRACT.md secao 4):
  measurement `ambiente`      tags: device_id, rack_id, location, status
                              fields: temperature, humidity, heat_index (float), seq (int)
  measurement `device_status` tags: device_id, rack_id
                              fields: online (bool)

Regras de resiliencia:
  * criar o cliente NUNCA falha (o InfluxDB pode estar fora no start);
  * escrita usa o modo batching do influxdb-client (nao ha 1 request HTTP por leitura);
  * `healthy` reflete o ultimo ping/escrita e e re-testado periodicamente.
"""

from __future__ import annotations

import logging
import re
import threading
from datetime import UTC, datetime
from typing import Any, Final

from influxdb_client import InfluxDBClient, Point, WriteOptions
from influxdb_client.client.write_api import WriteApi

from app.config import Settings
from app.models import (
    AlertItem,
    HistoryPoint,
    MetricStats,
    Reading,
    build_alert_message,
    iso_z,
)

logger = logging.getLogger(__name__)

MEASUREMENT_AMBIENTE: Final[str] = "ambiente"
MEASUREMENT_DEVICE_STATUS: Final[str] = "device_status"
METRIC_FIELDS: Final[tuple[str, ...]] = ("temperature", "humidity", "heat_index")

#: Janela maxima usada nas buscas de "ultima leitura" / existencia do rack.
LOOKBACK: Final[str] = "-30d"

_RACK_ID_RE: Final[re.Pattern[str]] = re.compile(r"^[A-Za-z0-9_.:-]{1,64}$")
_WINDOW_RE: Final[re.Pattern[str]] = re.compile(r"^[1-9][0-9]{0,4}(ms|s|m|h|d)$")


class InfluxUnavailableError(RuntimeError):
    """InfluxDB inacessivel — a rota deve responder 503."""


def is_valid_rack_id(rack_id: str) -> bool:
    """Evita injecao de Flux e ids absurdos."""
    return bool(_RACK_ID_RE.match(rack_id))


def is_valid_window(window: str) -> bool:
    """Duracao Flux simples, ex.: `30s`, `1m`, `5m`, `1h`."""
    return bool(_WINDOW_RE.match(window))


def _round(value: Any, digits: int = 1) -> float | None:
    """Arredonda valores numericos; devolve None para lacunas/valores invalidos."""
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return round(float(value), digits)
    return None


def _time_of(values: dict[str, Any]) -> str:
    raw = values.get("_time")
    if isinstance(raw, datetime):
        return iso_z(raw)
    return iso_z(datetime.now(UTC))


class InfluxGateway:
    """Fachada sincrona sobre o InfluxDB. Use via `asyncio.to_thread` nas rotas."""

    def __init__(self, cfg: Settings) -> None:
        self._cfg = cfg
        self._client: InfluxDBClient | None = None
        self._write_api: WriteApi | None = None
        self._healthy: bool = False
        self._lock = threading.Lock()

    # ------------------------------------------------------------------ #
    # Ciclo de vida
    # ------------------------------------------------------------------ #
    def connect(self) -> bool:
        """Cria o cliente e tenta um ping. Nunca levanta excecao."""
        cfg = self._cfg
        try:
            client = InfluxDBClient(
                url=cfg.influx_url,
                token=cfg.influx_token,
                org=cfg.influx_org,
                timeout=5_000,
            )
            write_api = client.write_api(
                write_options=WriteOptions(
                    batch_size=cfg.influx_batch_size,
                    flush_interval=cfg.influx_flush_interval_ms,
                    jitter_interval=0,
                    retry_interval=5_000,
                    max_retries=5,
                    max_retry_delay=30_000,
                    exponential_base=2,
                ),
                success_callback=self._on_write_success,
                error_callback=self._on_write_error,
                retry_callback=self._on_write_retry,
            )
        except Exception:  # noqa: BLE001 — nunca derrubar o servico no start
            logger.exception("Falha ao construir o cliente do InfluxDB")
            self._healthy = False
            return False

        with self._lock:
            self._client = client
            self._write_api = write_api

        ok = self.ping()
        if ok:
            logger.info("InfluxDB conectado em %s (bucket=%s)", cfg.influx_url, cfg.influx_bucket)
        else:
            logger.warning(
                "InfluxDB indisponivel em %s — a API segue no ar e tentara reconectar",
                cfg.influx_url,
            )
        return ok

    def close(self) -> None:
        """Faz flush do batch pendente e fecha o cliente."""
        with self._lock:
            write_api, client = self._write_api, self._client
            self._write_api, self._client = None, None
        if write_api is not None:
            try:
                write_api.close()
            except Exception:  # noqa: BLE001
                logger.exception("Erro ao fechar o write_api do InfluxDB")
        if client is not None:
            try:
                client.close()
            except Exception:  # noqa: BLE001
                logger.exception("Erro ao fechar o cliente do InfluxDB")
        self._healthy = False
        logger.info("Conexao com o InfluxDB encerrada")

    # ------------------------------------------------------------------ #
    # Saude
    # ------------------------------------------------------------------ #
    @property
    def healthy(self) -> bool:
        return self._healthy

    def ping(self) -> bool:
        """Testa o InfluxDB e atualiza o estado de saude."""
        client = self._client
        if client is None:
            self._healthy = False
            return False
        try:
            ok = bool(client.ping())
        except Exception as exc:  # noqa: BLE001
            if self._healthy:
                logger.warning("InfluxDB ficou indisponivel: %s", exc)
            self._healthy = False
            return False
        if ok and not self._healthy:
            logger.info("InfluxDB disponivel novamente")
        self._healthy = ok
        return ok

    def ensure_connection(self) -> bool:
        """Ping periodico; recria o cliente se ele nao existir."""
        if self._client is None:
            return self.connect()
        return self.ping()

    # ------------------------------------------------------------------ #
    # Escrita
    # ------------------------------------------------------------------ #
    def _on_write_success(self, conf: tuple[str, str, str], data: str) -> None:  # noqa: ARG002
        self._healthy = True

    def _on_write_error(
        self,
        conf: tuple[str, str, str],  # noqa: ARG002
        data: str,  # noqa: ARG002
        exception: Exception,
    ) -> None:
        self._healthy = False
        logger.error("Falha ao gravar lote no InfluxDB: %s", exception)

    def _on_write_retry(
        self,
        conf: tuple[str, str, str],  # noqa: ARG002
        data: str,  # noqa: ARG002
        exception: Exception,
    ) -> None:
        logger.warning("Reenviando lote ao InfluxDB apos erro: %s", exception)

    def write_reading(
        self,
        *,
        device_id: str,
        rack_id: str,
        location: str,
        status: str,
        temperature: float,
        humidity: float,
        heat_index: float,
        seq: int,
        ts: datetime,
    ) -> None:
        """Enfileira um ponto `ambiente` no batch de escrita."""
        write_api = self._write_api
        if write_api is None:
            logger.debug("Escrita ignorada: cliente do InfluxDB nao inicializado")
            return
        point = (
            Point(MEASUREMENT_AMBIENTE)
            .tag("device_id", device_id)
            .tag("rack_id", rack_id)
            .tag("location", location)
            .tag("status", status)
            .field("temperature", float(temperature))
            .field("humidity", float(humidity))
            .field("heat_index", float(heat_index))
            .field("seq", int(seq))
            .time(ts)
        )
        try:
            write_api.write(bucket=self._cfg.influx_bucket, org=self._cfg.influx_org, record=point)
        except Exception:  # noqa: BLE001
            self._healthy = False
            logger.exception("Erro ao enfileirar leitura para o InfluxDB")

    def write_device_status(
        self,
        *,
        device_id: str,
        rack_id: str,
        online: bool,
        ts: datetime,
    ) -> None:
        """Enfileira um ponto `device_status`."""
        write_api = self._write_api
        if write_api is None:
            return
        point = (
            Point(MEASUREMENT_DEVICE_STATUS)
            .tag("device_id", device_id)
            .tag("rack_id", rack_id)
            .field("online", bool(online))
            .time(ts)
        )
        try:
            write_api.write(bucket=self._cfg.influx_bucket, org=self._cfg.influx_org, record=point)
        except Exception:  # noqa: BLE001
            self._healthy = False
            logger.exception("Erro ao enfileirar status de device para o InfluxDB")

    # ------------------------------------------------------------------ #
    # Leitura
    # ------------------------------------------------------------------ #
    def _query(self, flux: str) -> list[dict[str, Any]]:
        """Executa Flux e devolve os registros como dicts. 503 se o Influx cair."""
        client = self._client
        if client is None:
            raise InfluxUnavailableError("cliente do InfluxDB nao inicializado")
        try:
            tables = client.query_api().query(query=flux, org=self._cfg.influx_org)
        except Exception as exc:
            self._healthy = False
            logger.warning("Query Flux falhou: %s", exc)
            raise InfluxUnavailableError(str(exc)) from exc
        self._healthy = True
        rows: list[dict[str, Any]] = []
        for table in tables:
            for record in table.records:
                rows.append(dict(record.values))
        return rows

    @property
    def _bucket(self) -> str:
        return self._cfg.influx_bucket.replace('"', '\\"')

    def _metric_filter(self) -> str:
        conditions = " or ".join(f'r._field == "{f}"' for f in METRIC_FIELDS)
        return f"filter(fn: (r) => {conditions})"

    # -- ultima leitura ------------------------------------------------- #
    def query_latest_rows(self, rack_id: str | None = None) -> list[dict[str, Any]]:
        """Ultimo ponto `ambiente` por rack (todos os racks se `rack_id` for None)."""
        rack_filter = (
            f'\n  |> filter(fn: (r) => r.rack_id == "{rack_id}")' if rack_id else ""
        )
        flux = f"""
from(bucket: "{self._bucket}")
  |> range(start: {LOOKBACK})
  |> filter(fn: (r) => r._measurement == "{MEASUREMENT_AMBIENTE}"){rack_filter}
  |> {self._metric_filter()}
  |> last()
  |> pivot(rowKey: ["_time"], columnKey: ["_field"], valueColumn: "_value")
  |> group(columns: ["rack_id"])
  |> sort(columns: ["_time"], desc: true)
  |> limit(n: 1)
"""
        return self._query(flux)

    def query_online_map(self) -> dict[str, bool]:
        """Ultimo `device_status.online` por rack."""
        flux = f"""
from(bucket: "{self._bucket}")
  |> range(start: {LOOKBACK})
  |> filter(fn: (r) => r._measurement == "{MEASUREMENT_DEVICE_STATUS}")
  |> filter(fn: (r) => r._field == "online")
  |> last()
  |> group(columns: ["rack_id"])
  |> sort(columns: ["_time"], desc: true)
  |> limit(n: 1)
"""
        result: dict[str, bool] = {}
        for row in self._query(flux):
            rack_id = row.get("rack_id")
            if isinstance(rack_id, str):
                result[rack_id] = bool(row.get("_value"))
        return result

    def rack_exists(self, rack_id: str) -> bool:
        """Ha algum dado desse rack na janela de retencao?"""
        return bool(self.query_latest_rows(rack_id))

    @staticmethod
    def row_to_reading(row: dict[str, Any]) -> Reading:
        return Reading(
            time=_time_of(row),
            temperature=_round(row.get("temperature")),
            humidity=_round(row.get("humidity")),
            heat_index=_round(row.get("heat_index")),
            status=str(row.get("status") or "ok"),
        )

    # -- historico ------------------------------------------------------ #
    def query_history(self, rack_id: str, range_: str, window: str) -> list[HistoryPoint]:
        """Serie agregada por `aggregateWindow(mean)`, crescente por tempo."""
        flux = f"""
from(bucket: "{self._bucket}")
  |> range(start: -{range_})
  |> filter(fn: (r) => r._measurement == "{MEASUREMENT_AMBIENTE}")
  |> filter(fn: (r) => r.rack_id == "{rack_id}")
  |> {self._metric_filter()}
  |> group(columns: ["_field"])
  |> aggregateWindow(every: {window}, fn: mean, createEmpty: true)
  |> pivot(rowKey: ["_time"], columnKey: ["_field"], valueColumn: "_value")
  |> sort(columns: ["_time"])
"""
        points = [
            HistoryPoint(
                time=_time_of(row),
                temperature=_round(row.get("temperature")),
                humidity=_round(row.get("humidity")),
                heat_index=_round(row.get("heat_index")),
            )
            for row in self._query(flux)
        ]
        points.sort(key=lambda p: p.time)
        return points

    # -- estatisticas --------------------------------------------------- #
    def query_stats(self, rack_id: str, range_: str) -> tuple[int, MetricStats, MetricStats]:
        """(count, stats de temperatura, stats de umidade) na janela pedida."""
        flux = f"""
base = from(bucket: "{self._bucket}")
  |> range(start: -{range_})
  |> filter(fn: (r) => r._measurement == "{MEASUREMENT_AMBIENTE}")
  |> filter(fn: (r) => r.rack_id == "{rack_id}")
  |> filter(fn: (r) => r._field == "temperature" or r._field == "humidity")
  |> group(columns: ["_field"])

base |> min() |> yield(name: "min")
base |> max() |> yield(name: "max")
base |> mean() |> yield(name: "mean")
base |> last() |> yield(name: "last")
base |> count() |> yield(name: "count")
"""
        acc: dict[str, dict[str, Any]] = {
            "temperature": {},
            "humidity": {},
        }
        for row in self._query(flux):
            field = row.get("_field")
            kind = row.get("result")
            if not isinstance(field, str) or field not in acc or not isinstance(kind, str):
                continue
            acc[field][kind] = row.get("_value")

        def to_stats(field: str) -> MetricStats:
            data = acc[field]
            return MetricStats(
                min=_round(data.get("min")),
                max=_round(data.get("max")),
                avg=_round(data.get("mean")),
                last=_round(data.get("last")),
            )

        raw_count = acc["temperature"].get("count")
        count = int(raw_count) if isinstance(raw_count, (int, float)) else 0
        return count, to_stats("temperature"), to_stats("humidity")

    # -- alertas -------------------------------------------------------- #
    def query_alerts(self, rack_id: str, range_: str, limit: int) -> list[AlertItem]:
        """Leituras com `status != "ok"`, mais recentes primeiro."""
        flux = f"""
from(bucket: "{self._bucket}")
  |> range(start: -{range_})
  |> filter(fn: (r) => r._measurement == "{MEASUREMENT_AMBIENTE}")
  |> filter(fn: (r) => r.rack_id == "{rack_id}")
  |> filter(fn: (r) => r.status != "ok")
  |> filter(fn: (r) => r._field == "temperature" or r._field == "humidity")
  |> pivot(rowKey: ["_time"], columnKey: ["_field"], valueColumn: "_value")
  |> group()
  |> sort(columns: ["_time"], desc: true)
  |> limit(n: {int(limit)})
"""
        alerts: list[AlertItem] = []
        for row in self._query(flux):
            temperature = _round(row.get("temperature"))
            humidity = _round(row.get("humidity"))
            status = str(row.get("status") or "warning")
            alerts.append(
                AlertItem(
                    time=_time_of(row),
                    status=status,
                    temperature=temperature,
                    humidity=humidity,
                    message=build_alert_message(status, temperature, humidity, self._cfg),
                )
            )
        return alerts
