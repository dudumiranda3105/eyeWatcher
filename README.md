<h1 align="center">👁️ eyeWatcher</h1>

<p align="center">
  <strong>Monitoramento IoT de temperatura e umidade em racks de servidores</strong><br/>
  <em>Porque quando o serviço cai por superaquecimento, já é tarde demais.</em>
</p>

<p align="center">
  <img alt="ESP32" src="https://img.shields.io/badge/ESP32-Wokwi-blue"/>
  <img alt="MQTT" src="https://img.shields.io/badge/MQTT-Mosquitto-660066"/>
  <img alt="Python" src="https://img.shields.io/badge/Python-FastAPI-3776AB"/>
  <img alt="InfluxDB" src="https://img.shields.io/badge/InfluxDB-2.x-22ADF6"/>
  <img alt="Vue" src="https://img.shields.io/badge/Vue-3%20%2B%20TypeScript-42B883"/>
</p>

---

## O problema

Servidores caseiros, de pequenas empresas e de laboratórios superaquecem **sem
aviso**. A falha só é descoberta quando o serviço já caiu — e não existe
histórico algum para descobrir se aquilo vinha acontecendo há semanas.

Termômetro de parede não registra nada. Os sensores da BIOS medem o chip, não o
ambiente do rack — e ficam indisponíveis justamente quando o servidor cai.
Solução comercial de DCIM é cara demais para esse porte.

## A solução

O **eyeWatcher** mede o ambiente do rack continuamente com um dispositivo
**independente do servidor monitorado**, guarda toda a série histórica e mostra
tudo em um dashboard web em tempo real.

> Leitura completa: [`docs/PROBLEMA.md`](docs/PROBLEMA.md)

## Arquitetura

```
ESP32 + DHT22  ──MQTT──►  Mosquitto  ──►  Python (FastAPI)  ──►  InfluxDB
   (Wokwi)                                      │                    │
                                                └──REST/WebSocket────┴──►  Vue 3 + Chart.js
```

> Diagramas detalhados: [`docs/ARQUITETURA.md`](docs/ARQUITETURA.md)

## Funcionalidades

- 📡 Leitura de temperatura, umidade e sensação térmica a cada 5 segundos
- 🚦 Classificação automática em `ok` / `warning` / `critical`, com LEDs e buzzer no próprio rack
- 📈 Histórico persistido em banco de séries temporais, com janelas de 15 min a 7 dias
- ⚡ Dashboard atualizado em tempo real via WebSocket, com fallback automático para polling
- 🔌 Detecção de queda do dispositivo via *Last Will Testament* do MQTT — **ausência de dado também é alerta**
- 📊 Mín / máx / média por período e tabela de alertas recentes
- 🧪 Simulador em Python que replica o ESP32, para desenvolvimento e como plano B na apresentação

## Stack

| Camada | Tecnologia |
|---|---|
| Dispositivo | ESP32 + DHT22 (simulado no Wokwi) |
| Protocolo | MQTT (QoS 1 + LWT) |
| Broker | Eclipse Mosquitto |
| Backend | Python · FastAPI · paho-mqtt |
| Banco | InfluxDB 2.x |
| Frontend | Vue 3 · TypeScript · Vite |
| Gráficos | Chart.js |

## Estrutura do repositório

```
eyeWatcher/
├── firmware/      # Sketch do ESP32 + diagrama do Wokwi
├── backend/       # FastAPI, cliente MQTT, escrita no InfluxDB, simulador
├── frontend/      # Dashboard Vue 3 + TypeScript + Vite
├── infra/         # mosquitto.conf e docker-compose
├── scripts/       # Scripts de instalação e inicialização (Windows)
└── docs/          # Problema, arquitetura, contrato e roteiro de apresentação
```

## Como executar

### Pré-requisitos

- Python 3.11+ · Node.js 18+ · Mosquitto · InfluxDB 2.x

No Windows, os dois últimos podem ser instalados com:

```powershell
.\scripts\install-windows.ps1
```

### Subir tudo de uma vez

```powershell
.\scripts\start-all.ps1
```

### Ou passo a passo

```bash
# 1. Broker MQTT
mosquitto -c infra/mosquitto/config/mosquitto.conf -v

# 2. InfluxDB (e configuração inicial da org/bucket/token)
influxd
# depois:  .\scripts\setup-influx.ps1

# 3. Backend
cd backend
python -m venv .venv && source .venv/Scripts/activate
pip install -r requirements.txt
cp .env.example .env          # preencha o INFLUX_TOKEN
python -m app.main

# 4. Frontend
cd frontend
npm install
npm run dev

# 5. Wokwi — ver instruções em firmware/README.md
```

Acesse o dashboard em **http://localhost:5173**

### Sem hardware? Use o simulador

```bash
python backend/simulator.py --backfill 24   # popula 24h de histórico
python backend/simulator.py                 # publica em tempo real
python backend/simulator.py --stress        # força um pico crítico
```

## Portas

| Serviço | Porta |
|---|---|
| Mosquitto (TCP / WebSocket) | 1883 / 9001 |
| InfluxDB | 8086 |
| Backend (API + Swagger em `/docs`) | 8000 |
| Frontend | 5173 |

## Documentação

| Documento | Conteúdo |
|---|---|
| [`docs/PROBLEMA.md`](docs/PROBLEMA.md) | Definição do problema e proposta da solução |
| [`docs/ARQUITETURA.md`](docs/ARQUITETURA.md) | Diagramas, modelo de dados e decisões de projeto |
| [`docs/CONTRATO.md`](docs/CONTRACT.md) | Contrato técnico entre as camadas (tópicos, payloads, rotas) |
| [`docs/APRESENTACAO.md`](docs/APRESENTACAO.md) | Roteiro de demonstração e checklist da avaliação |

## Roadmap — 2º bimestre

- [ ] Múltiplos racks simultâneos (a arquitetura de tópicos já suporta)
- [ ] Notificações ativas por e-mail e Telegram
- [ ] Autenticação de usuários e credenciais no Mosquitto
- [ ] Novos sensores: corrente elétrica e sensor de porta do rack
- [ ] Previsão de cruzamento de limiar a partir da série histórica

---

<p align="center"><sub>Projeto acadêmico — Aplicações Web integradas com IoT · 1º bimestre</sub></p>
