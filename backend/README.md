# backend/ — API e ingestão do eyeWatcher

Camada Python do projeto. Ela faz três coisas:

1. **Ingere** a telemetria publicada pelo ESP32 no Mosquitto (MQTT);
2. **Valida, revalida o status e persiste** cada leitura no InfluxDB 2.x;
3. **Serve** a API HTTP e o WebSocket consumidos pelo frontend Vue 3.

```
ESP32 (Wokwi)  →  MQTT  →  Mosquitto  →  [ backend ]  →  InfluxDB  →  Web (Vue 3)
                                              │
                                              └── WebSocket /ws/live (tempo real)
```

Tudo aqui segue `docs/CONTRACT.md`. **Nomes de rota, campos e limiares não podem
ser alterados unilateralmente.**

---

## 1. Pré-requisitos

| O quê | Versão | Observação |
|---|---|---|
| Python | 3.13 ou 3.14 | testado em **3.14.7** no Windows 11 |
| Mosquitto | 2.x | porta `1883` |
| InfluxDB | 2.7 | porta `8086`, org `eyewatcher`, bucket `rack_metrics` |

O Mosquitto e o InfluxDB **não** são instalados por esta pasta. Use os scripts da
raiz do projeto (`scripts\install-windows.ps1`, `scripts\setup-influx.ps1`,
`scripts\start-all.ps1`) ou, se tiver Docker, o `infra\docker-compose.yml`.

> **Boa notícia:** o backend **sobe mesmo com o Mosquitto e o InfluxDB fora do
> ar.** Ele apenas registra o problema no log e continua tentando reconectar;
> `GET /api/health` mostra o estado real de cada subsistema.

---

## 2. Criar a venv e instalar

Na pasta `backend/`:

```powershell
# PowerShell (Windows)
cd C:\Users\Dudu\Documents\eyeWatcher\backend
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
```

```bash
# Git Bash / Linux / macOS
cd backend
python -m venv .venv
source .venv/Scripts/activate    # Linux/macOS: source .venv/bin/activate
python -m pip install --upgrade pip
pip install -r requirements.txt
```

### Nota sobre Python 3.14

Todas as dependências de `requirements.txt` têm **wheel pré-compilada para
CPython 3.14 (cp314) no Windows x64** — nada é compilado na sua máquina. As
versões foram fixadas exatamente nas que resolvem nesse ambiente:

| Pacote | Versão | Por quê |
|---|---|---|
| `fastapi` | 0.141.1 | primeira linha com suporte ao Starlette 1.x |
| `uvicorn[standard]` | 0.52.4 | traz `httptools`/`watchfiles` com wheel cp314 |
| `paho-mqtt` | 2.1.0 | **API de callbacks VERSION2** (obrigatória no 2.x) |
| `influxdb-client` | 1.50.0 | cliente oficial do InfluxDB 2.x |
| `pydantic` | 2.13.5 | `pydantic-core` 2.46.5 tem wheel cp314 |
| `pydantic-settings` | 2.15.0 | leitura tipada do `.env` |
| `python-dotenv` | 1.2.3 | carregamento do `.env` |
| `websockets` | 17.1 | transporte WebSocket do uvicorn |

Se você estiver em um Python mais antigo (3.11/3.12) e o pip reclamar, remova as
fixações (`==`) e deixe o resolvedor escolher — o código não usa nada exclusivo
do 3.14.

---

## 3. Configurar o `.env`

```powershell
Copy-Item .env.example .env       # PowerShell
# cp .env.example .env            # Git Bash
```

Depois edite o `.env` e coloque o **token do InfluxDB** em `INFLUX_TOKEN`.
Se você rodou `scripts\setup-influx.ps1`, o `backend\.env` já foi gerado com o
token correto e não há nada a fazer aqui.

Variáveis reconhecidas (todas com default sensato — veja `.env.example`):

| Variável | Default | Para que serve |
|---|---|---|
| `MQTT_HOST` | `localhost` | host do broker |
| `MQTT_PORT` | `1883` | porta TCP do broker |
| `MQTT_TOPIC` | `eyewatcher` | prefixo dos tópicos (`<prefixo>/+/telemetry`) |
| `MQTT_TOPIC_TELEMETRY` / `MQTT_TOPIC_STATUS` | *(vazio)* | override opcional dos filtros de assinatura |
| `MQTT_CLIENT_ID` | `eyewatcher-backend` | client id do backend no broker |
| `MQTT_USERNAME` / `MQTT_PASSWORD` | *(vazio)* | só se o broker exigir autenticação |
| `INFLUX_URL` | `http://localhost:8086` | endereço do InfluxDB |
| `INFLUX_TOKEN` | *(vazio)* | **obrigatório** para gravar/ler |
| `INFLUX_ORG` | `eyewatcher` | organização |
| `INFLUX_BUCKET` | `rack_metrics` | bucket (retenção 30d) |
| `TEMP_WARN` | `30` | °C a partir de onde é `warning` |
| `TEMP_CRIT` | `35` | °C a partir de onde é `critical` |
| `HUM_MIN_WARN` | `30` | % abaixo disso é `warning` |
| `HUM_MIN_CRIT` | `20` | % abaixo disso é `critical` |
| `HUM_MAX_WARN` | `70` | % acima disso é `warning` |
| `HUM_MAX_CRIT` | `80` | % acima disso é `critical` |
| `API_HOST` / `API_PORT` | `0.0.0.0` / `8000` | bind da API |
| `CORS_ORIGINS` | `http://localhost:5173,...` | origens liberadas (separadas por vírgula) |
| `LOG_LEVEL` | `INFO` | `DEBUG`, `INFO`, `WARNING`, `ERROR` |

Nenhum segredo fica no código — tudo vem do ambiente.

---

## 4. Rodar a API

Com a venv ativada, dentro de `backend/`:

```bash
python -m app.main                      # usa API_HOST/API_PORT do .env
```

ou, com auto-reload durante o desenvolvimento:

```bash
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

Documentação interativa gerada pelo FastAPI: <http://localhost:8000/docs>.

Teste rápido de que está no ar (funciona mesmo sem Mosquitto/InfluxDB):

```bash
curl http://localhost:8000/api/health
# {"status":"degraded","influx":false,"mqtt":false}   <- com a infra fora
# {"status":"ok","influx":true,"mqtt":true}           <- com tudo no ar
```

---

## 5. Rodar o simulador (plano B do Wokwi)

`simulator.py` emula o ESP32: mesmos tópicos, mesmo payload, mesmo intervalo.
É o seguro contra o Wokwi falhar no dia da apresentação.

Rode **a partir da pasta `backend/`** (ele importa `app.config` para reaproveitar
os limiares e o endereço do broker):

```bash
python simulator.py                                   # rack01, a cada 5 s
python simulator.py --rack-id rack02 --interval 2
python simulator.py --stress                          # força um pico crítico
python simulator.py --backfill 12                     # 12 h de histórico + ao vivo
python simulator.py --backfill 24 --backfill-only     # só o histórico e sai
python simulator.py --host 192.168.0.10 --port 1883   # broker em outra máquina
```

| Argumento | Default | Descrição |
|---|---|---|
| `--rack-id` | `rack01` | identificador do rack |
| `--device-id` | `esp32-<rack-id>` | id do dispositivo |
| `--location` | `Sala de Servidores A` | local exibido na UI |
| `--interval` | `5.0` | segundos entre publicações |
| `--host` / `--port` | `MQTT_HOST` / `MQTT_PORT` | broker MQTT |
| `--backfill HORAS` | `0` | grava N horas de histórico **direto no InfluxDB** |
| `--backfill-only` | — | faz só o backfill e sai |
| `--stress` | — | rampa de temperatura até estourar o limiar crítico |
| `--seed` | — | semente do ruído (resultados reproduzíveis) |
| `--log-level` | `INFO` | verbosidade |

**Curva de temperatura:** senoide de 24 h com pico às **14 h** (amplitude ±5 °C
sobre 27,5 °C) + ruído gaussiano; a umidade varia em oposição de fase. Isso
produz exatamente o padrão que o projeto quer mostrar ("pico térmico sempre às
14h"). Em `--stress`, a temperatura sobe 1,5 °C por ciclo até +13 °C, cruzando o
limiar crítico em poucos segundos.

**Por que o `--backfill` escreve direto no InfluxDB?** Porque o contrato manda o
backend carimbar a hora de *chegada* da mensagem MQTT — não dá para "publicar no
passado". Para o gráfico não nascer vazio na apresentação, o simulador grava os
pontos históricos com timestamps retroativos usando o `influxdb-client`.
Ele respeita `INFLUX_URL`, `INFLUX_TOKEN`, `INFLUX_ORG` e `INFLUX_BUCKET` do
`.env` e limita a 6000 pontos (aumentando o passo em backfills longos).

---

## 6. Rotas da API

Base: `http://localhost:8000`. Detalhes e formato exato em `docs/CONTRACT.md`.

| Método | Rota | Descrição |
|---|---|---|
| GET | `/api/health` | saúde dos subsistemas |
| GET | `/api/racks` | racks com a última leitura de cada |
| GET | `/api/readings/latest` | última leitura de um rack |
| GET | `/api/readings/history` | série temporal agregada (média) |
| GET | `/api/readings/stats` | min/max/avg/last de temperatura e umidade |
| GET | `/api/alerts` | leituras com `status != "ok"` |
| WS | `/ws/live` | push em tempo real de cada telemetria |

### Exemplos com `curl`

```bash
# Saúde dos subsistemas
curl http://localhost:8000/api/health
# {"status":"ok","influx":true,"mqtt":true}

# Lista de racks
curl http://localhost:8000/api/racks
# [{"rack_id":"rack01","device_id":"esp32-rack01","location":"Sala de Servidores A",
#   "online":true,"last_reading":{"time":"2026-09-12T11:47:03.412Z",
#   "temperature":34.5,"humidity":48.2,"heat_index":36.1,"status":"warning"}}]

# Última leitura
curl "http://localhost:8000/api/readings/latest?rack_id=rack01"

# Histórico das últimas 6 h, agregado em janelas de 1 min
curl "http://localhost:8000/api/readings/history?rack_id=rack01&range=6h&window=1m"

# Histórico de 7 dias em janelas de 1 h (gráfico mais leve)
curl "http://localhost:8000/api/readings/history?rack_id=rack01&range=7d&window=1h"

# Estatísticas das últimas 24 h
curl "http://localhost:8000/api/readings/stats?rack_id=rack01&range=24h"

# Alertas das últimas 24 h (no máximo 50)
curl "http://localhost:8000/api/alerts?rack_id=rack01&range=24h&limit=50"
```

### Parâmetros

- `range` aceita **somente** `15m`, `1h`, `6h`, `24h`, `7d`, `30d`.
  Qualquer outro valor devolve **422**:
  ```bash
  curl -i "http://localhost:8000/api/readings/history?rack_id=rack01&range=3h"
  # HTTP/1.1 422 Unprocessable Content
  # {"detail":"range inválido: use um de 15m, 1h, 6h, 24h, 7d, 30d"}
  ```
- `window` é a janela do `aggregateWindow` (`30s`, `1m`, `5m`, `1h`…). Default `1m`.
- `limit` em `/api/alerts`: 1 a 1000, default 50.

### Códigos de erro

| Código | Quando | Corpo |
|---|---|---|
| `404` | o `rack_id` não tem dado nenhum | `{"detail":"rack não encontrado"}` |
| `422` | `range`, `window` ou `rack_id` inválido | `{"detail":"range inválido: ..."}` |
| `503` | InfluxDB inacessível | `{"detail":"influxdb indisponível"}` |

### WebSocket

```bash
# com websocat instalado
websocat ws://localhost:8000/ws/live
```

```js
// no navegador / frontend
const ws = new WebSocket("ws://localhost:8000/ws/live");
ws.onmessage = (e) => console.log(JSON.parse(e.data));
```

Eventos emitidos:

```json
{"type":"telemetry","data":{"device_id":"esp32-rack01","rack_id":"rack01",
 "location":"Sala de Servidores A","temperature":34.5,"humidity":48.2,
 "heat_index":36.1,"status":"warning","uptime_s":12345,"seq":42,
 "time":"2026-09-12T11:47:03.412Z"}}

{"type":"status","data":{"rack_id":"rack01","online":false}}
```

O `status` enviado é sempre o **recalculado pelo backend**, não o que veio do
ESP32. Clientes que caem são removidos automaticamente da lista de broadcast.

---

## 7. Estrutura

```
backend/
├── .env.example        # todas as variáveis documentadas
├── requirements.txt    # dependências com versão fixada
├── simulator.py        # simulador do ESP32 (MQTT + backfill)
├── README.md
└── app/
    ├── config.py       # Settings (pydantic-settings) lendo o .env
    ├── models.py       # payload MQTT, respostas da API e regras de limiar
    ├── influx.py       # escrita em batch + queries Flux
    ├── mqtt_client.py  # cliente MQTT em thread própria (paho 2.x)
    ├── api.py          # rotas FastAPI + WebSocket manager
    └── main.py         # app, CORS, lifespan, uvicorn
```

Decisões que valem menção na apresentação:

- **O backend não confia no `status` do ESP32.** Toda leitura é reclassificada
  com os limiares de `.env` (`classify_status` em `app/models.py`), então um
  firmware com bug não contamina o histórico.
- **Payload inválido é descartado, não derruba o serviço.** A validação é
  `strict` (tipo errado não é convertido); o erro vira um `WARNING` no log.
- **Escrita em batch.** O `influxdb-client` acumula pontos e envia em lote
  (`INFLUX_BATCH_SIZE` / `INFLUX_FLUSH_INTERVAL_MS`) — não é 1 request HTTP por
  leitura.
- **Reconexão automática.** `connect_async` + `loop_start` no MQTT e um watchdog
  que repinga o InfluxDB a cada `INFLUX_HEALTHCHECK_INTERVAL_S` segundos.
- **Queries bloqueantes saem do event loop** via `asyncio.to_thread`, então o
  WebSocket não engasga enquanto uma consulta Flux roda.

---

## 8. Problemas comuns

| Sintoma | Causa provável | Solução |
|---|---|---|
| `/api/health` com `"influx": false` | `INFLUX_TOKEN` ausente/errado, ou InfluxDB fora | rode `scripts\setup-influx.ps1` e confira `INFLUX_URL` |
| `/api/health` com `"mqtt": false` | Mosquitto fora ou porta errada | `scripts\start-all.ps1`; confira `MQTT_HOST`/`MQTT_PORT` |
| Rotas devolvendo `503` | InfluxDB inacessível | suba o InfluxDB; o backend reconecta sozinho |
| Rotas devolvendo `404` | nenhum dado para aquele `rack_id` | rode `python simulator.py --backfill 6` |
| Gráfico vazio na apresentação | bucket sem histórico | `python simulator.py --backfill 12` |
| `ModuleNotFoundError: app` ao rodar o simulador | executado de outra pasta | rode de dentro de `backend/` |
| Frontend bloqueado por CORS | origem fora da lista | acrescente a origem em `CORS_ORIGINS` |
| `.env` ignorado | arquivo salvo com BOM | salve como **UTF-8 sem BOM** |
