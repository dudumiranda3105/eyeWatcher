"""PostgreSQL: usuarios, dispositivos, regras, alertas, jobs, modelos e auditoria.

Leituras NAO ficam aqui: telemetria e papel do InfluxDB.
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any, Final

import asyncpg
import bcrypt

from eyewatcher.settings import Settings

logger = logging.getLogger("eyewatcher.api.db")

SCHEMA: Final[str] = """
CREATE TABLE IF NOT EXISTS users (
    id            SERIAL PRIMARY KEY,
    username      TEXT UNIQUE NOT NULL,
    password_hash TEXT NOT NULL,
    role          TEXT NOT NULL CHECK (role IN ('viewer', 'operator', 'admin')),
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS devices (
    id           TEXT PRIMARY KEY,
    name         TEXT NOT NULL,
    kind         TEXT NOT NULL CHECK (kind IN ('sensor', 'actuator', 'equipment')),
    type         TEXT NOT NULL,
    zone         TEXT NOT NULL,
    metric       TEXT,
    unit         TEXT,
    normal_min   DOUBLE PRECISION,
    normal_max   DOUBLE PRECISION,
    critical_min DOUBLE PRECISION,
    critical_max DOUBLE PRECISION,
    controllable BOOLEAN NOT NULL DEFAULT false,
    enabled      BOOLEAN NOT NULL DEFAULT true,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS rules (
    id              SERIAL PRIMARY KEY,
    name            TEXT NOT NULL,
    device_id       TEXT NOT NULL REFERENCES devices(id) ON DELETE CASCADE,
    metric          TEXT NOT NULL,
    threshold       DOUBLE PRECISION NOT NULL,
    clear_threshold DOUBLE PRECISION NOT NULL,
    actuator_id     TEXT NOT NULL REFERENCES devices(id) ON DELETE CASCADE,
    severity        TEXT NOT NULL DEFAULT 'warning',
    enabled         BOOLEAN NOT NULL DEFAULT true
);

CREATE TABLE IF NOT EXISTS alerts (
    id         BIGSERIAL PRIMARY KEY,
    device_id  TEXT NOT NULL,
    source     TEXT NOT NULL,
    severity   TEXT NOT NULL,
    message    TEXT NOT NULL,
    opened_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    cleared_at TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS alerts_open ON alerts (device_id, source) WHERE cleared_at IS NULL;

CREATE TABLE IF NOT EXISTS jobs (
    id          TEXT PRIMARY KEY,
    kind        TEXT NOT NULL,
    status      TEXT NOT NULL,
    progress    DOUBLE PRECISION NOT NULL DEFAULT 0,
    stage       TEXT,
    params      JSONB NOT NULL DEFAULT '{}',
    result      JSONB,
    created_by  TEXT NOT NULL,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    finished_at TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS model_versions (
    version    TEXT PRIMARY KEY,
    trained_at TIMESTAMPTZ NOT NULL,
    dataset    TEXT NOT NULL,
    promoted   BOOLEAN NOT NULL,
    summary    JSONB NOT NULL
);

CREATE TABLE IF NOT EXISTS audit_log (
    id       BIGSERIAL PRIMARY KEY,
    ts       TIMESTAMPTZ NOT NULL DEFAULT now(),
    username TEXT NOT NULL,
    action   TEXT NOT NULL,
    target   TEXT,
    detail   JSONB NOT NULL DEFAULT '{}',
    ip       TEXT
);
CREATE INDEX IF NOT EXISTS audit_ts ON audit_log (ts DESC);
"""

#: Cadastro inicial: (id, nome, kind, type, metrica, unidade, faixa normal, faixa critica, comando).
SEED_DEVICES: Final[list[tuple[Any, ...]]] = [
    ("temp-rack01", "Temperatura do rack 01", "sensor", "temperature", "temperature", "°C", 18, 30, 10, 35, False),
    ("temp-rack02", "Temperatura do rack 02", "sensor", "temperature", "temperature", "°C", 18, 30, 10, 35, False),
    ("hum-sala", "Umidade da sala", "sensor", "humidity", "humidity", "%", 30, 70, 20, 80, False),
    ("lux-sala", "Luminosidade da sala", "sensor", "luminosity", "luminosity", "lux", 0, 1000, 0, 2000, False),
    ("pwr-rack01", "Corrente do rack 01", "sensor", "power", "current", "A", 0, 22, 0, 28, False),
    ("door-sala", "Presença na sala", "sensor", "presence", "presence", None, 0, 1, 0, 1, False),
    ("crac-01", "Ar-condicionado de precisão 01", "equipment", "equipment", "vibration", "mm/s", 0, 4.5, 0, 7.1, True),
    ("crac-02", "Ar-condicionado de precisão 02", "equipment", "equipment", "vibration", "mm/s", 0, 4.5, 0, 7.1, True),
    ("fan-exaustor", "Exaustor de emergência", "actuator", "fan", "on", None, None, None, None, None, False),
    ("light-sala", "Iluminação da sala", "actuator", "light", "on", None, None, None, None, None, True),
    ("siren-sala", "Sirene de alerta", "actuator", "siren", "on", None, None, None, None, None, False),
]  # fmt: skip

SEED_RULES: Final[list[tuple[Any, ...]]] = [
    (
        "Exaustor com rack quente",
        "temp-rack01",
        "temperature",
        35.0,
        31.0,
        "fan-exaustor",
        "warning",
    ),
    ("Sirene com rack crítico", "temp-rack01", "temperature", 38.0, 35.0, "siren-sala", "critical"),
]

DEMO_ROLES: Final[dict[str, str]] = {
    "visualizador": "viewer",
    "operador": "operator",
    "administrador": "admin",
}


async def connect(cfg: Settings) -> asyncpg.Pool:
    while True:
        try:
            pool = await asyncpg.create_pool(
                host=cfg.postgres_host,
                port=cfg.postgres_port,
                user=cfg.postgres_user,
                database=cfg.postgres_db,
                password=cfg.secret("postgres"),
                init=_init_connection,
            )
            assert pool is not None
            return pool
        except (OSError, asyncpg.PostgresError) as exc:
            logger.warning("PostgreSQL indisponivel (%s); tentando de novo", exc)
            await asyncio.sleep(3)


async def _init_connection(connection: asyncpg.Connection) -> None:
    await connection.set_type_codec(
        "jsonb", encoder=json.dumps, decoder=json.loads, schema="pg_catalog"
    )


async def migrate_and_seed(pool: asyncpg.Pool, cfg: Settings) -> None:
    async with pool.acquire() as connection:
        await connection.execute(SCHEMA)

        for username, role in DEMO_ROLES.items():
            exists = await connection.fetchval("SELECT 1 FROM users WHERE username=$1", username)
            if not exists:
                password = cfg.secret(f"demo_{username}").encode("utf-8")
                hashed = await asyncio.to_thread(bcrypt.hashpw, password, bcrypt.gensalt())
                await connection.execute(
                    "INSERT INTO users (username, password_hash, role) VALUES ($1, $2, $3)",
                    username,
                    hashed.decode("ascii"),
                    role,
                )

        if not await connection.fetchval("SELECT count(*) FROM devices"):
            await connection.executemany(
                """INSERT INTO devices (id, name, kind, type, metric, unit, normal_min, normal_max,
                       critical_min, critical_max, controllable, zone)
                   VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12)""",
                [(*device, cfg.zone) for device in SEED_DEVICES],
            )
            await connection.executemany(
                """INSERT INTO rules (name, device_id, metric, threshold, clear_threshold,
                       actuator_id, severity)
                   VALUES ($1, $2, $3, $4, $5, $6, $7)""",
                SEED_RULES,
            )


async def audit(
    pool: asyncpg.Pool,
    username: str,
    action: str,
    target: str | None = None,
    detail: dict[str, Any] | None = None,
    ip: str | None = None,
) -> None:
    await pool.execute(
        "INSERT INTO audit_log (username, action, target, detail, ip) VALUES ($1, $2, $3, $4, $5)",
        username,
        action,
        target,
        detail or {},
        ip,
    )
