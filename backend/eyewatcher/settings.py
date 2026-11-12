"""Configuracao compartilhada por todos os servicos.

Valores comuns vem do ambiente; senhas vem de arquivos em `/run/eyewatcher`, a
pasta que o Compose monta so com os segredos daquele servico.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    service_name: str = "dev"
    log_level: str = "INFO"
    secrets_dir: Path = Path("/run/eyewatcher")
    zone: str = "sala-a"

    mqtt_host: str = "mosquitto"
    mqtt_port: int = 1883

    amqp_host: str = "rabbitmq"
    amqp_port: int = 5672
    amqp_vhost: str = "eyewatcher"
    rabbit_mgmt_url: str = "http://rabbitmq:15672"

    postgres_host: str = "postgres"
    postgres_port: int = 5432
    postgres_db: str = "eyewatcher"
    postgres_user: str = "eyewatcher"

    influx_url: str = "http://influxdb:8086"
    influx_org: str = "eyewatcher"
    influx_bucket: str = "telemetry"
    influx_lab_bucket: str = "lab"

    ollama_url: str = "http://ollama:11434"
    ollama_model: str = "llama3.2:3b"

    datasets_dir: Path = Path("/data/datasets")
    models_dir: Path = Path("/data/models")

    #: Intervalo real entre leituras do simulador, em segundos.
    tick_seconds: float = 2.0

    jwt_ttl_minutes: int = 480
    assistant_per_minute: int = 8

    def secret(self, name: str) -> str:
        return (self.secrets_dir / name).read_text(encoding="utf-8").strip()


@lru_cache
def get_settings() -> Settings:
    return Settings()
