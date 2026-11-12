"""Gera os segredos e a topologia do RabbitMQ na primeira subida do Compose.

Nada disto vai para o Git: tudo fica em `secrets/`, que esta no .gitignore. O
script e idempotente: o que ja existe e mantido, entao rodar de novo nao troca
senha nenhuma. Para recomecar do zero, apague `secrets/` e os volumes.

Cada servico recebe so a sua pasta (`secrets/<servico>/`), com apenas as
credenciais de que ele precisa.

Uso:  python infra/bootstrap/gen_secrets.py secrets
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import secrets as pysecrets
import sys
from pathlib import Path

VHOST = "eyewatcher"
EXCHANGE = "eyewatcher.topic"
DLX = "eyewatcher.dlx"
DLQ = "q.dlq"

#: Fila -> routing keys. A fila q.live.ws nao tem DLX de proposito: dado ao vivo
#: velho nao tem valor, entao ela so descarta o excesso.
QUEUES: dict[str, list[str]] = {
    "q.telemetry.influx": ["telemetry.#", "prediction.#"],
    "q.telemetry.inference": ["telemetry.*.equipment.*"],
    "q.telemetry.rules": ["telemetry.#"],
    "q.live.ws": ["telemetry.#", "prediction.#", "alert.#", "event.#"],
    "q.commands.device": ["command.#"],
    "q.jobs.datagen": ["job.datagen"],
    "q.jobs.training": ["job.training"],
    "q.api.persist": ["alert.#", "event.job.#", "event.model.#"],
    "q.inference.control": ["event.model.#"],
}

#: Usuario -> (configure, write, read, tags). Ninguem alem do admin declara nada:
#: a topologia inteira ja nasce pelo definitions.json.
RABBIT_USERS: dict[str, tuple[str, str, str, list[str]]] = {
    "gateway": ("^$", r"^eyewatcher\.(topic|dlx)$", r"^q\.commands\.device$", []),
    "recorder": ("^$", "^$", r"^q\.telemetry\.influx$", []),
    "inference": (
        "^$",
        r"^eyewatcher\.topic$",
        r"^q\.(telemetry\.inference|inference\.control)$",
        [],
    ),
    "lab": ("^$", r"^eyewatcher\.topic$", r"^q\.jobs\.datagen$", []),
    "trainer": ("^$", r"^eyewatcher\.topic$", r"^q\.jobs\.training$", []),
    "api": (
        "^$",
        r"^eyewatcher\.topic$",
        r"^q\.(live\.ws|telemetry\.rules|api\.persist|dlq)$",
        ["monitoring"],
    ),
    "admin": (".*", ".*", ".*", ["administrator"]),
}

MQTT_USERS = ("simulator", "gateway", "healthcheck")
DEMO_USERS = ("visualizador", "operador", "administrador")

#: Servico -> arquivo dentro da pasta dele -> nome do segredo mestre.
SERVICE_SECRETS: dict[str, dict[str, str]] = {
    "simulator": {"mqtt": "mqtt_simulator"},
    "gateway": {"mqtt": "mqtt_gateway", "amqp": "rabbit_gateway"},
    "recorder": {"amqp": "rabbit_recorder", "influx": "influx_token"},
    "inference": {"amqp": "rabbit_inference"},
    "lab": {"amqp": "rabbit_lab", "influx": "influx_token"},
    "trainer": {"amqp": "rabbit_trainer"},
    "api": {
        "amqp": "rabbit_api",
        "influx": "influx_token",
        "postgres": "postgres",
        "jwt": "jwt",
        "demo_visualizador": "demo_visualizador",
        "demo_operador": "demo_operador",
        "demo_administrador": "demo_administrador",
    },
    "postgres": {"password": "postgres"},
    "influxdb": {"password": "influx_admin", "token": "influx_token"},
    "mosquitto": {
        "simulator": "mqtt_simulator",
        "gateway": "mqtt_gateway",
        "healthcheck": "mqtt_healthcheck",
    },
}


def master_names() -> list[str]:
    names = [f"rabbit_{user}" for user in RABBIT_USERS]
    names += [f"mqtt_{user}" for user in MQTT_USERS]
    names += [f"demo_{user}" for user in DEMO_USERS]
    return [*names, "postgres", "influx_admin", "influx_token", "jwt"]


def write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    # Containers rodam com usuarios diferentes; quem protege e a pasta ignorada.
    os.chmod(path, 0o644)


def ensure_master(root: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for name in master_names():
        path = root / "_master" / name
        if not path.exists():
            write(path, pysecrets.token_urlsafe(32 if name in {"jwt", "influx_token"} else 18))
        values[name] = path.read_text(encoding="utf-8").strip()
    return values


def rabbit_hash(password: str) -> str:
    """Formato rabbit_password_hashing_sha256: base64(sal + sha256(sal + senha))."""
    salt = os.urandom(4)
    digest = hashlib.sha256(salt + password.encode("utf-8")).digest()
    return base64.b64encode(salt + digest).decode("ascii")


def rabbit_definitions(values: dict[str, str]) -> dict[str, object]:
    queues: list[dict[str, object]] = []
    bindings: list[dict[str, object]] = []
    for name, keys in QUEUES.items():
        arguments: dict[str, object] = {"x-dead-letter-exchange": DLX}
        if name == "q.live.ws":
            arguments = {"x-max-length": 2000}
        queues.append(
            {
                "name": name,
                "vhost": VHOST,
                "durable": True,
                "auto_delete": False,
                "arguments": arguments,
            }
        )
        bindings += [
            {
                "source": EXCHANGE,
                "vhost": VHOST,
                "destination": name,
                "destination_type": "queue",
                "routing_key": key,
                "arguments": {},
            }
            for key in keys
        ]
    queues.append(
        {
            "name": DLQ,
            "vhost": VHOST,
            "durable": True,
            "auto_delete": False,
            "arguments": {"x-max-length": 10000},
        }
    )
    bindings.append(
        {
            "source": DLX,
            "vhost": VHOST,
            "destination": DLQ,
            "destination_type": "queue",
            "routing_key": "",
            "arguments": {},
        }
    )
    return {
        "rabbit_version": "4",
        "users": [
            {
                "name": user,
                "password_hash": rabbit_hash(values[f"rabbit_{user}"]),
                "hashing_algorithm": "rabbit_password_hashing_sha256",
                "tags": tags,
                "limits": {},
            }
            for user, (_, _, _, tags) in RABBIT_USERS.items()
        ],
        "vhosts": [{"name": VHOST}],
        "permissions": [
            {"user": user, "vhost": VHOST, "configure": conf, "write": wr, "read": rd}
            for user, (conf, wr, rd, _) in RABBIT_USERS.items()
        ],
        "exchanges": [
            {
                "name": EXCHANGE,
                "vhost": VHOST,
                "type": "topic",
                "durable": True,
                "auto_delete": False,
                "internal": False,
                "arguments": {},
            },
            {
                "name": DLX,
                "vhost": VHOST,
                "type": "fanout",
                "durable": True,
                "auto_delete": False,
                "internal": False,
                "arguments": {},
            },
        ],
        "queues": queues,
        "bindings": bindings,
    }


def main() -> None:
    root = Path(sys.argv[1] if len(sys.argv) > 1 else "secrets")
    root.mkdir(parents=True, exist_ok=True)
    values = ensure_master(root)

    for service, files in SERVICE_SECRETS.items():
        for filename, master in files.items():
            write(root / service / filename, values[master])

    definitions = root / "rabbitmq" / "definitions.json"
    if not definitions.exists():
        write(definitions, json.dumps(rabbit_definitions(values), indent=2))

    lines = ["Usuarios de demonstracao do eyeWatcher (arquivo ignorado pelo Git)", ""]
    lines += [f"{user}: {values[f'demo_{user}']}" for user in DEMO_USERS]
    lines += [
        "",
        f"RabbitMQ (http://127.0.0.1:15672)  admin: {values['rabbit_admin']}",
        f"InfluxDB (http://127.0.0.1:8086)   eyewatcher: {values['influx_admin']}",
        f"PostgreSQL (http://127.0.0.1:8081) eyewatcher: {values['postgres']}",
    ]
    write(root / "CREDENCIAIS.txt", "\n".join(lines) + "\n")
    print(f"Segredos prontos em {root}/ (veja {root}/CREDENCIAIS.txt)")


if __name__ == "__main__":
    main()
