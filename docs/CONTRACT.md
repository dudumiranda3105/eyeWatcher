# CONTRATO TÉCNICO — eyeWatcher
Interface compartilhada entre firmware, backend e frontend.
**Nenhuma camada pode alterar este contrato unilateralmente.**

---

## 1. Identidade do projeto
- Nome: **eyeWatcher**
- Problema: racks de servidores (caseiros / pequenas empresas / laboratórios) superaquecem
  sem aviso; a falha só é descoberta quando o serviço já caiu. Não há histórico para
  identificar padrões (ex.: pico térmico sempre às 14h).
- Fluxo obrigatório: `ESP32 (Wokwi) → MQTT → Mosquitto → Python → InfluxDB → Web (Vue 3)`

## 2. MQTT

Broker: Mosquitto. Host/porta configuráveis por env.
- Porta TCP: `1883`
- Porta WebSocket: `9001`
- Client ID do ESP32: `esp32-<RACK_ID>`

### Tópicos
| Tópico | Quem publica | QoS | Retain |
|---|---|---|---|
| `eyewatcher/<rack_id>/telemetry` | ESP32 | 1 | false |
| `eyewatcher/<rack_id>/status`    | ESP32 (LWT + online) | 1 | **true** |
| `eyewatcher/+/telemetry`         | backend assina | 1 | - |
| `eyewatcher/+/status`            | backend assina | 1 | - |

`<rack_id>` do projeto base: `rack01`.

### Payload de `telemetry` (JSON, UTF-8)
```json
{
  "device_id": "esp32-rack01",
  "rack_id": "rack01",
  "location": "Sala de Servidores A",
  "temperature": 34.5,
  "humidity": 48.2,
  "heat_index": 36.1,
  "status": "ok",
  "uptime_s": 12345,
  "seq": 42
}
```
- `temperature` — °C, float, 1 casa decimal
- `humidity` — % RH, float, 1 casa decimal
- `heat_index` — °C, float, sensação térmica (calculada no ESP32)
- `status` — `"ok"` | `"warning"` | `"critical"` (calculado no ESP32, revalidado no backend)
- `uptime_s` — segundos desde o boot (int)
- `seq` — contador incremental de mensagens (int), para detectar perda de pacotes
- **NÃO** enviar timestamp: o backend carimba a hora de chegada (o ESP32 simulado não tem RTC confiável).

### Payload de `status` (LWT)
Texto puro: `online` ou `offline`. LWT configurado para publicar `offline` com retain.

### Intervalo de publicação
5 segundos (constante `PUBLISH_INTERVAL_MS = 5000`).

## 3. Limiares (thresholds)
Idênticos no firmware e no backend (backend lê de env):
| Métrica | ok | warning | critical |
|---|---|---|---|
| temperatura | < 30 °C | 30–34.9 °C | ≥ 35 °C |
| umidade | 30–70 % | 20–29.9 % ou 70.1–80 % | < 20 % ou > 80 % |

Status final = o **pior** entre temperatura e umidade.

Env do backend: `TEMP_WARN=30`, `TEMP_CRIT=35`, `HUM_MIN_WARN=30`, `HUM_MIN_CRIT=20`,
`HUM_MAX_WARN=70`, `HUM_MAX_CRIT=80`.

## 4. InfluxDB 2.x
- URL: `http://localhost:8086`
- Org: `eyewatcher`
- Bucket: `rack_metrics` (retenção 30d)
- Token: env `INFLUX_TOKEN`

### Schema
Measurement: **`ambiente`**
- Tags: `device_id`, `rack_id`, `location`, `status`
- Fields: `temperature` (float), `humidity` (float), `heat_index` (float), `seq` (int)
- Timestamp: hora de chegada no backend, precisão `ns`

Measurement: **`device_status`**
- Tags: `device_id`, `rack_id`
- Fields: `online` (bool)

## 5. API HTTP (FastAPI) — `http://localhost:8000`
Todas as rotas sob `/api`. CORS liberado para `http://localhost:5173`.

| Método | Rota | Descrição |
|---|---|---|
| GET | `/api/health` | `{status, influx, mqtt}` — saúde dos subsistemas |
| GET | `/api/racks` | lista de racks com a última leitura de cada |
| GET | `/api/readings/latest?rack_id=rack01` | última leitura |
| GET | `/api/readings/history?rack_id=rack01&range=6h&window=1m` | série temporal agregada (mean) |
| GET | `/api/readings/stats?rack_id=rack01&range=24h` | min/max/avg de temp e umidade |
| GET | `/api/alerts?rack_id=rack01&range=24h&limit=50` | leituras com status != ok |
| WS  | `/ws/live` | push em tempo real de cada telemetria recebida |

### Formatos de resposta

`GET /api/racks`
```json
[{
  "rack_id": "rack01", "device_id": "esp32-rack01",
  "location": "Sala de Servidores A", "online": true,
  "last_reading": {
    "time": "2026-09-12T11:47:03.412Z",
    "temperature": 34.5, "humidity": 48.2, "heat_index": 36.1, "status": "warning"
  }
}]
```

`GET /api/readings/latest` → o objeto `last_reading` acima + `rack_id`, `device_id`, `location`, `online`.

`GET /api/readings/history`
```json
{
  "rack_id": "rack01", "range": "6h", "window": "1m",
  "points": [
    {"time": "2026-09-12T05:47:00Z", "temperature": 28.4, "humidity": 52.0, "heat_index": 29.1}
  ]
}
```
`points` ordenado crescente por `time`. Valores podem ser `null` em lacunas.

`GET /api/readings/stats`
```json
{
  "rack_id": "rack01", "range": "24h", "count": 17280,
  "temperature": {"min": 24.1, "max": 38.9, "avg": 30.2, "last": 34.5},
  "humidity":    {"min": 40.0, "max": 61.3, "avg": 49.8, "last": 48.2}
}
```

`GET /api/alerts`
```json
{"rack_id":"rack01","range":"24h","count":12,"alerts":[
  {"time":"2026-09-12T11:40:00Z","status":"critical","temperature":36.8,"humidity":48.0,
   "message":"Temperatura crítica: 36.8 °C"}
]}
```

`WS /ws/live` — envia o JSON de telemetria **enriquecido**:
```json
{"type":"telemetry","data":{ ...payload..., "time":"2026-09-12T11:47:03.412Z" }}
```
e eventos `{"type":"status","data":{"rack_id":"rack01","online":false}}`.

### Erros
`404` quando `rack_id` não tem dados: `{"detail":"rack não encontrado"}`.
`503` quando o InfluxDB está inacessível: `{"detail":"influxdb indisponível"}`.

### Parâmetro `range`
Aceita `15m`, `1h`, `6h`, `24h`, `7d`, `30d`. Default `6h`. Validar e rejeitar outros com `422`.

## 6. Frontend — `http://localhost:5173`
- Vue 3 (`<script setup>`) + TypeScript **strict** + Vite
- Gráficos: **Chart.js** via `vue-chartjs`
- Estado: Pinia. HTTP: axios. Proxy Vite `/api` e `/ws` → `localhost:8000`
- Tipos TS espelhando as respostas acima em `src/types/api.ts`

## 7. Portas usadas
| Serviço | Porta |
|---|---|
| Mosquitto TCP | 1883 |
| Mosquitto WS | 9001 |
| InfluxDB | 8086 |
| Backend FastAPI | 8000 |
| Frontend Vite | 5173 |
