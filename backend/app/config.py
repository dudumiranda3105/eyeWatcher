"""Configuracao do backend (lida de variaveis de ambiente / arquivo .env)."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

# backend/app/config.py -> backend/
BACKEND_DIR: Path = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    """Configuracao tipada. Todos os campos tem default sensato para dev local."""

    model_config = SettingsConfigDict(
        env_file=(BACKEND_DIR / ".env"),
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ---------- MQTT ----------
    mqtt_host: str = "localhost"
    mqtt_port: int = 1883
    mqtt_topic: str = "eyewatcher"
    # Overrides opcionais: `scripts/setup-influx.ps1` gera o .env com estes nomes.
    # Se vazios, os topicos sao derivados de MQTT_TOPIC.
    mqtt_topic_telemetry: str = ""
    mqtt_topic_status: str = ""
    mqtt_client_id: str = "eyewatcher-backend"
    mqtt_keepalive: int = 60
    mqtt_qos: int = 1
    mqtt_username: str = ""
    mqtt_password: str = ""

    # ---------- InfluxDB ----------
    influx_url: str = "http://localhost:8086"
    influx_token: str = ""
    influx_org: str = "eyewatcher"
    influx_bucket: str = "rack_metrics"
    influx_batch_size: int = 50
    influx_flush_interval_ms: int = 2000
    influx_healthcheck_interval_s: int = 15

    # ---------- Limiares ----------
    temp_warn: float = 30.0
    temp_crit: float = 35.0
    hum_min_warn: float = 30.0
    hum_min_crit: float = 20.0
    hum_max_warn: float = 70.0
    hum_max_crit: float = 80.0

    # ---------- API ----------
    api_host: str = "0.0.0.0"
    api_port: int = 8000
    cors_origins: str = "http://localhost:5173,http://127.0.0.1:5173"

    # ---------- Logging ----------
    log_level: str = "INFO"

    # ---------- Derivados ----------
    @property
    def topic_prefix(self) -> str:
        """Prefixo dos topicos, sem barra no final."""
        return self.mqtt_topic.strip().rstrip("/") or "eyewatcher"

    @property
    def topic_telemetry(self) -> str:
        return self.mqtt_topic_telemetry.strip() or f"{self.topic_prefix}/+/telemetry"

    @property
    def topic_status(self) -> str:
        return self.mqtt_topic_status.strip() or f"{self.topic_prefix}/+/status"

    @property
    def cors_origins_list(self) -> list[str]:
        """CORS_ORIGINS como lista (aceita valores separados por virgula)."""
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Instancia unica de Settings (cacheada)."""
    return Settings()


settings: Settings = get_settings()
