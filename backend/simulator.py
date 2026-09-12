"""Simulador do ESP32 do eyeWatcher (plano B caso o Wokwi falhe na avaliacao).

Publica no Mosquitto exatamente os mesmos topicos e o mesmo payload do firmware
(`docs/CONTRACT.md` secoes 2 e 3), com uma curva de temperatura realista ao longo
do dia (senoide com pico as 14h + ruido) e um modo de estresse que força um pico
critico.

Exemplos:
    python simulator.py                                  # rack01, a cada 5 s
    python simulator.py --rack-id rack02 --interval 2
    python simulator.py --stress                         # força status critical
    python simulator.py --backfill 12                    # popula 12 h de historico
    python simulator.py --backfill 24 --backfill-only    # so o historico, sem live

O `--backfill` escreve DIRETO no InfluxDB (com timestamps no passado), porque
mensagens MQTT sao carimbadas com a hora de chegada no backend.
"""

from __future__ import annotations

import argparse
import contextlib
import json
import logging
import math
import random
import signal
import sys
import time
from datetime import UTC, datetime, timedelta
from types import FrameType
from typing import Any, Final

import paho.mqtt.client as mqtt

from app.config import Settings, get_settings
from app.models import classify_status

logger = logging.getLogger("simulator")

# Curva diaria: pico as 14h, minimo as 2h.
BASE_TEMP_C: Final[float] = 27.5
TEMP_AMPLITUDE_C: Final[float] = 5.0
PEAK_HOUR: Final[float] = 14.0
TEMP_NOISE_C: Final[float] = 0.35

BASE_HUMIDITY: Final[float] = 52.0
HUM_AMPLITUDE: Final[float] = 9.0
HUM_NOISE: Final[float] = 0.8

#: Pico de estresse: quanto a temperatura sobe por ciclo e o teto do acrescimo.
STRESS_STEP_C: Final[float] = 1.5
STRESS_MAX_C: Final[float] = 13.0

#: Teto de pontos escritos no backfill (evita escrever 500k pontos sem querer).
MAX_BACKFILL_POINTS: Final[int] = 6000


# --------------------------------------------------------------------------- #
# Modelo fisico
# --------------------------------------------------------------------------- #
def heat_index_c(temperature_c: float, humidity: float) -> float:
    """Indice de calor (sensacao termica) em °C — formula NOAA/Rothfusz."""
    t_f = temperature_c * 9.0 / 5.0 + 32.0
    simple = 0.5 * (t_f + 61.0 + ((t_f - 68.0) * 1.2) + (humidity * 0.094))
    hi_f = simple
    if (simple + t_f) / 2.0 >= 80.0:
        hi_f = (
            -42.379
            + 2.04901523 * t_f
            + 10.14333127 * humidity
            - 0.22475541 * t_f * humidity
            - 0.00683783 * t_f * t_f
            - 0.05481717 * humidity * humidity
            + 0.00122874 * t_f * t_f * humidity
            + 0.00085282 * t_f * humidity * humidity
            - 0.00000199 * t_f * t_f * humidity * humidity
        )
        if humidity < 13.0 and 80.0 <= t_f <= 112.0:
            hi_f -= ((13.0 - humidity) / 4.0) * math.sqrt((17.0 - abs(t_f - 95.0)) / 17.0)
        elif humidity > 85.0 and 80.0 <= t_f <= 87.0:
            hi_f += ((humidity - 85.0) / 10.0) * ((87.0 - t_f) / 5.0)
    return (hi_f - 32.0) * 5.0 / 9.0


def _hour_of_day(moment: datetime) -> float:
    local = moment.astimezone()
    return local.hour + local.minute / 60.0 + local.second / 3600.0


def sample_environment(moment: datetime, stress_offset: float = 0.0) -> tuple[float, float, float]:
    """(temperatura, umidade, indice de calor) para um instante do dia."""
    phase = 2.0 * math.pi * (_hour_of_day(moment) - (PEAK_HOUR - 6.0)) / 24.0
    temperature = (
        BASE_TEMP_C
        + TEMP_AMPLITUDE_C * math.sin(phase)
        + random.gauss(0.0, TEMP_NOISE_C)
        + stress_offset
    )
    humidity = (
        BASE_HUMIDITY
        - HUM_AMPLITUDE * math.sin(phase)
        + random.gauss(0.0, HUM_NOISE)
        - stress_offset * 0.8
    )
    humidity = min(max(humidity, 5.0), 95.0)
    temperature = min(max(temperature, 5.0), 60.0)
    return (
        round(temperature, 1),
        round(humidity, 1),
        round(heat_index_c(temperature, humidity), 1),
    )


def build_payload(
    *,
    device_id: str,
    rack_id: str,
    location: str,
    temperature: float,
    humidity: float,
    heat_index: float,
    status: str,
    uptime_s: int,
    seq: int,
) -> dict[str, Any]:
    """Payload exatamente no formato do contrato."""
    return {
        "device_id": device_id,
        "rack_id": rack_id,
        "location": location,
        "temperature": temperature,
        "humidity": humidity,
        "heat_index": heat_index,
        "status": status,
        "uptime_s": uptime_s,
        "seq": seq,
    }


# --------------------------------------------------------------------------- #
# Backfill direto no InfluxDB
# --------------------------------------------------------------------------- #
def run_backfill(cfg: Settings, args: argparse.Namespace) -> None:
    """Escreve `--backfill` horas de historico no InfluxDB, com timestamps passados."""
    try:
        from influxdb_client import InfluxDBClient, Point, WritePrecision
        from influxdb_client.client.write_api import SYNCHRONOUS
    except ImportError:  # pragma: no cover
        logger.error("influxdb-client nao instalado; rode: pip install -r requirements.txt")
        return

    hours = float(args.backfill)
    step = float(args.interval)
    total = int(hours * 3600.0 / step)
    if total > MAX_BACKFILL_POINTS:
        step = hours * 3600.0 / MAX_BACKFILL_POINTS
        total = MAX_BACKFILL_POINTS
        logger.info("Backfill longo: usando passo de %.1f s para limitar a %d pontos", step, total)

    end = datetime.now(UTC)
    start = end - timedelta(hours=hours)
    logger.info(
        "Backfill de %.1f h (%d pontos, passo %.1f s) em %s/%s",
        hours,
        total,
        step,
        cfg.influx_url,
        cfg.influx_bucket,
    )

    points: list[Any] = []
    with InfluxDBClient(url=cfg.influx_url, token=cfg.influx_token, org=cfg.influx_org) as client:
        write_api = client.write_api(write_options=SYNCHRONOUS)
        for index in range(total):
            moment = start + timedelta(seconds=step * index)
            temperature, humidity, heat = sample_environment(moment)
            status = classify_status(temperature, humidity, cfg)
            points.append(
                Point("ambiente")
                .tag("device_id", args.device_id)
                .tag("rack_id", args.rack_id)
                .tag("location", args.location)
                .tag("status", status)
                .field("temperature", temperature)
                .field("humidity", humidity)
                .field("heat_index", heat)
                .field("seq", index)
                .time(moment, WritePrecision.NS)
            )
            if len(points) >= 1000:
                write_api.write(bucket=cfg.influx_bucket, org=cfg.influx_org, record=points)
                logger.info("... %d/%d pontos gravados", index + 1, total)
                points = []
        if points:
            write_api.write(bucket=cfg.influx_bucket, org=cfg.influx_org, record=points)
        write_api.write(
            bucket=cfg.influx_bucket,
            org=cfg.influx_org,
            record=Point("device_status")
            .tag("device_id", args.device_id)
            .tag("rack_id", args.rack_id)
            .field("online", True)
            .time(end, WritePrecision.NS),
        )
    logger.info("Backfill concluido: %d pontos gravados", total)


# --------------------------------------------------------------------------- #
# Publicacao ao vivo via MQTT
# --------------------------------------------------------------------------- #
class Simulator:
    """Publica telemetria periodica emulando o ESP32."""

    def __init__(self, cfg: Settings, args: argparse.Namespace) -> None:
        self._cfg = cfg
        self._args = args
        self._running = True
        self._seq = 0
        self._started_at = time.monotonic()
        self._stress_offset = 0.0

        prefix = cfg.topic_prefix
        self._topic_telemetry = f"{prefix}/{args.rack_id}/telemetry"
        self._topic_status = f"{prefix}/{args.rack_id}/status"

        self._client = mqtt.Client(
            mqtt.CallbackAPIVersion.VERSION2,
            client_id=f"{args.device_id}-sim",
            protocol=mqtt.MQTTv311,
            clean_session=True,
        )
        if cfg.mqtt_username:
            self._client.username_pw_set(cfg.mqtt_username, cfg.mqtt_password or None)
        self._client.will_set(self._topic_status, payload="offline", qos=1, retain=True)
        self._client.reconnect_delay_set(min_delay=1, max_delay=30)
        self._client.on_connect = self._on_connect
        self._client.on_disconnect = self._on_disconnect

    def _on_connect(
        self,
        client: mqtt.Client,
        userdata: Any,  # noqa: ANN401, ARG002
        flags: Any,  # noqa: ANN401, ARG002
        reason_code: Any,  # noqa: ANN401
        properties: Any = None,  # noqa: ANN401, ARG002
    ) -> None:
        if getattr(reason_code, "is_failure", False):
            logger.error("Broker recusou a conexao: %s", reason_code)
            return
        logger.info("Conectado ao broker %s:%s", self._args.host, self._args.port)
        client.publish(self._topic_status, payload="online", qos=1, retain=True)

    def _on_disconnect(
        self,
        client: mqtt.Client,  # noqa: ARG002
        userdata: Any,  # noqa: ANN401, ARG002
        flags: Any = None,  # noqa: ANN401, ARG002
        reason_code: Any = None,  # noqa: ANN401
        properties: Any = None,  # noqa: ANN401, ARG002
    ) -> None:
        logger.warning("Desconectado do broker (%s) — tentando reconectar", reason_code)

    def stop(self, *_: object) -> None:
        self._running = False

    def run(self) -> None:
        args = self._args
        logger.info(
            "Simulador iniciado: rack=%s device=%s intervalo=%.1fs stress=%s",
            args.rack_id,
            args.device_id,
            args.interval,
            args.stress,
        )
        self._client.connect_async(args.host, args.port, keepalive=60)
        self._client.loop_start()
        try:
            while self._running:
                self._publish_once()
                self._sleep(args.interval)
        finally:
            self._shutdown()

    def _publish_once(self) -> None:
        args = self._args
        if args.stress:
            self._stress_offset = min(self._stress_offset + STRESS_STEP_C, STRESS_MAX_C)

        now = datetime.now(UTC)
        temperature, humidity, heat = sample_environment(now, self._stress_offset)
        status = classify_status(temperature, humidity, self._cfg)
        payload = build_payload(
            device_id=args.device_id,
            rack_id=args.rack_id,
            location=args.location,
            temperature=temperature,
            humidity=humidity,
            heat_index=heat,
            status=status,
            uptime_s=int(time.monotonic() - self._started_at),
            seq=self._seq,
        )
        self._seq += 1
        info = self._client.publish(
            self._topic_telemetry,
            json.dumps(payload, ensure_ascii=False),
            qos=1,
            retain=False,
        )
        if info.rc != mqtt.MQTT_ERR_SUCCESS:
            logger.warning("Publicacao falhou (rc=%s) — broker fora?", info.rc)
            return
        logger.info(
            "seq=%d t=%.1f°C h=%.1f%% hi=%.1f°C status=%s",
            payload["seq"],
            temperature,
            humidity,
            heat,
            status,
        )

    def _sleep(self, seconds: float) -> None:
        """Sleep fatiado para responder rapido ao Ctrl+C."""
        deadline = time.monotonic() + seconds
        while self._running and time.monotonic() < deadline:
            time.sleep(min(0.2, max(0.0, deadline - time.monotonic())))

    def _shutdown(self) -> None:
        logger.info("Encerrando simulador")
        try:
            self._client.publish(self._topic_status, payload="offline", qos=1, retain=True)
            time.sleep(0.3)
            self._client.disconnect()
        except Exception:  # noqa: BLE001
            logger.exception("Erro ao encerrar a conexao MQTT")
        finally:
            self._client.loop_stop()


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #
def parse_args(cfg: Settings, argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="simulator.py",
        description="Simulador do ESP32 do eyeWatcher (MQTT + backfill no InfluxDB).",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("--rack-id", default="rack01", help="Identificador do rack")
    parser.add_argument("--device-id", default=None, help="Padrao: esp32-<rack-id>")
    parser.add_argument("--location", default="Sala de Servidores A", help="Local do rack")
    parser.add_argument(
        "--interval", type=float, default=5.0, help="Intervalo entre publicacoes (s)"
    )
    parser.add_argument("--host", default=cfg.mqtt_host, help="Host do broker MQTT")
    parser.add_argument("--port", type=int, default=cfg.mqtt_port, help="Porta TCP do broker")
    parser.add_argument(
        "--backfill",
        type=float,
        default=0.0,
        metavar="HORAS",
        help="Popula o InfluxDB com N horas de historico antes de iniciar",
    )
    parser.add_argument(
        "--backfill-only",
        action="store_true",
        help="Faz apenas o backfill e sai (nao publica ao vivo)",
    )
    parser.add_argument(
        "--stress", action="store_true", help="Força um pico critico de temperatura"
    )
    parser.add_argument("--seed", type=int, default=None, help="Semente do gerador aleatorio")
    parser.add_argument("--log-level", default="INFO", help="DEBUG | INFO | WARNING | ERROR")

    args = parser.parse_args(argv)
    if not args.device_id:
        args.device_id = f"esp32-{args.rack_id}"
    if args.interval <= 0:
        parser.error("--interval precisa ser maior que zero")
    return args


def main(argv: list[str] | None = None) -> int:
    cfg = get_settings()
    args = parse_args(cfg, argv)
    logging.basicConfig(
        level=getattr(logging, str(args.log_level).upper(), logging.INFO),
        format="%(asctime)s | %(levelname)-8s | %(message)s",
        datefmt="%H:%M:%S",
    )
    if args.seed is not None:
        random.seed(args.seed)

    if args.backfill > 0:
        try:
            run_backfill(cfg, args)
        except Exception as exc:  # noqa: BLE001
            logger.error(
                "Backfill falhou (InfluxDB fora ou INFLUX_TOKEN invalido?): %s", exc
            )
            logger.debug("Detalhes do erro de backfill", exc_info=True)
            if args.backfill_only:
                return 1
    elif args.backfill_only:
        logger.error("--backfill-only exige --backfill HORAS")
        return 2

    if args.backfill_only:
        return 0

    simulator = Simulator(cfg, args)

    def handler(signum: int, frame: FrameType | None) -> None:  # noqa: ARG001
        logger.info("Sinal %s recebido, encerrando...", signum)
        simulator.stop()

    for sig in (signal.SIGINT, signal.SIGTERM):
        # Plataformas sem o sinal (ex.: SIGTERM no Windows) simplesmente o ignoram.
        with contextlib.suppress(ValueError, OSError):
            signal.signal(sig, handler)

    simulator.run()
    return 0


if __name__ == "__main__":
    sys.exit(main())
