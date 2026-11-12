# Contrato técnico

Interface compartilhada entre os serviços. Mudar algo aqui exige mudar todos os lados.

## Mensagem

Toda mensagem, em MQTT ou em AMQP, é um JSON com este formato:

```json
{
  "id": "6f1c0c1e-4a43-4a57-9a6b-2d3c1f6e8a10",
  "ts": "2026-11-16T14:03:22.410000+00:00",
  "type": "telemetry",
  "device": "crac-01",
  "payload": {}
}
```

`type` é um de `telemetry`, `command`, `prediction`, `alert`, `event` ou `job`.

### Payload de cada tipo

Telemetria de sensor:

```json
{"metrics": {"temperature": 26.4}, "sim_hour": 14.5}
```

Telemetria de equipamento:

```json
{
  "metrics": {"vibration": 2.1, "current": 12.3, "temperature": 48.6, "rpm": 1447.0},
  "sim_hour": 14.5, "on": true, "failed": false, "run_id": 0
}
```

Previsão:

```json
{"health": 62.8, "rul_h": 73.1, "trend_per_h": -3.61, "model_version": "v1"}
```

Alerta:

```json
{"state": "open", "severity": "warning", "health": 62.8, "rul_h": 73.1, "message": "..."}
```

## MQTT

| Tópico | Quem publica | Retido |
|---|---|---|
| `eyewatcher/<zona>/<tipo>/<id>/telemetry` | Simulador | Não |
| `eyewatcher/<zona>/<tipo>/<id>/cmd` | Gateway | Não |
| `eyewatcher/sim/status` | Simulador, com Last Will | Sim |
| `eyewatcher/sim/config` | Gateway | Sim |

## RabbitMQ

Vhost `eyewatcher`, exchange `eyewatcher.topic` (topic) e `eyewatcher.dlx` (fanout).

| Routing key | Significado |
|---|---|
| `telemetry.<zona>.<tipo>.<id>` | Leitura de um dispositivo |
| `command.<zona>.<tipo>.<id>` | Comando para um dispositivo |
| `prediction.<zona>.<id>` | Previsão da IA |
| `alert.<zona>.<id>` | Alerta aberto ou encerrado |
| `event.job.<id>` | Progresso de um job |
| `event.model.<versao>` | Modelo novo treinado |
| `job.datagen`, `job.training` | Jobs em segundo plano |

As filas estão em [ARQUITETURA.md](ARQUITETURA.md).

## InfluxDB

Org `eyewatcher`, buckets `telemetry` (ao vivo) e `lab` (amostra sintética).

| Measurement | Tags | Fields |
|---|---|---|
| `telemetry` | `device`, `zone`, `type` | As métricas da leitura |
| `prediction` | `device`, `zone`, `model_version` | `health`, `rul_h` |
| `lab_equipment` | `equipment`, `mode` | As métricas da leitura |

## API

A documentação completa fica em http://localhost:8080/api/docs. Todas as rotas exigem
`Authorization: Bearer <jwt>`, menos `/api/auth/login` e `/api/health`.

| Rota | Papel mínimo |
|---|---|
| `POST /api/auth/login` | Nenhum |
| `POST /api/auth/ws-ticket` | Visualizador |
| `GET /api/devices`, `/rules`, `/alerts`, `/insights`, `/jobs` | Visualizador |
| `GET /api/readings/history`, `/readings/stats` | Visualizador |
| `GET /api/messaging/overview`, `/messaging/dlq` | Visualizador |
| `POST /api/assistant/chat` | Visualizador |
| `POST /api/devices/{id}/command` | Operador |
| `POST /api/simulator/command` | Operador |
| `POST /api/messaging/poison` | Operador |
| `POST`, `PUT`, `DELETE` em `/api/devices` e `/api/rules` | Administrador |
| `POST /api/lab/jobs`, `/api/training/jobs` | Administrador |
| `GET /api/audit` | Administrador |

## WebSocket

`GET /ws/live?ticket=<ticket>`. O ticket vem de `POST /api/auth/ws-ticket`, vale 30
segundos e só uma vez.

A primeira mensagem é uma foto do estado atual (`type: snapshot`). As seguintes são
as mensagens do barramento, com `routing_key` junto.
