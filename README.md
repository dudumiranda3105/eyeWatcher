# eyeWatcher

Monitoramento de temperatura e umidade em racks de servidores usando ESP32, MQTT e
um dashboard web.

## O problema

Servidor caseiro, de laboratório ou de empresa pequena quase nunca fica numa sala
com climatização monitorada. Normalmente fica num armário, numa sala de apoio ou
em algum canto onde o ar-condicionado é desligado à noite. O resultado é sempre o
mesmo: a temperatura sobe devagar, o processador começa a reduzir a frequência,
e em algum momento alguma coisa desliga sozinha. Só aí alguém percebe que tinha
um problema.

O pior é que não sobra nenhum registro. Depois da queda não dá para saber se a
temperatura já vinha subindo há dias, se o pico acontece sempre no mesmo horário,
ou se aquele ventilador novo resolveu alguma coisa.

Termômetro de parede não guarda histórico e depende de alguém olhando. Os sensores
da própria placa medem o chip, não o ar do rack, e ficam indisponíveis justamente
quando a máquina cai. Sistema comercial de monitoramento de datacenter é caro
demais para esse tamanho de operação.

## A ideia

O eyeWatcher mede o ambiente do rack de 5 em 5 segundos com um dispositivo que
não depende do servidor monitorado. Essa é a parte que importa: se o servidor
travar ou desligar, o sensor continua medindo e avisando — que é exatamente
quando o dado tem valor.

As leituras vão para um banco de séries temporais e aparecem num dashboard web,
com gráfico do histórico, indicadores do estado atual e uma lista dos alertas
recentes.

Tem mais detalhe em [docs/PROBLEMA.md](docs/PROBLEMA.md).

## Como funciona

```
ESP32 + DHT22  --MQTT-->  Mosquitto  -->  Python (FastAPI)  -->  InfluxDB
   (Wokwi)                                     |                     |
                                               +--REST/WebSocket-----+--> Vue 3 + Chart.js
```

O ESP32 lê o sensor e publica um JSON num tópico MQTT. O Mosquitto entrega essa
mensagem para o backend em Python, que valida, classifica o estado (normal, alerta
ou crítico) e grava no InfluxDB. O dashboard consulta o backend por HTTP para
montar o gráfico e recebe as leituras novas por WebSocket.

Os diagramas estão em [docs/ARQUITETURA.md](docs/ARQUITETURA.md).

## O que já funciona

- Leitura de temperatura, umidade e sensação térmica a cada 5 segundos
- LED verde, amarelo ou vermelho no próprio rack, mais buzzer quando fica crítico
- Histórico guardado no InfluxDB, com janelas de 15 minutos até 7 dias
- Dashboard atualizando ao vivo por WebSocket, com volta automática para
  consulta periódica se a conexão cair
- Detecção de queda do dispositivo pelo Last Will do MQTT, então ficar sem dado
  também vira aviso
- Mínima, média e máxima do período e tabela dos alertas
- Um simulador em Python que publica igual ao ESP32, útil para desenvolver sem
  a placa e como reserva na hora de apresentar

## Tecnologias

| Camada | O que usamos |
|---|---|
| Dispositivo | ESP32 com DHT22, simulado no Wokwi |
| Comunicação | MQTT |
| Broker | Eclipse Mosquitto |
| Backend | Python com FastAPI e paho-mqtt |
| Banco | InfluxDB 2.x |
| Frontend | Vue 3, TypeScript e Vite |
| Gráficos | Chart.js |

## Organização das pastas

```
eyeWatcher/
├── firmware/   sketch do ESP32 e o diagrama do Wokwi
├── backend/    API em Python, cliente MQTT e o simulador
├── frontend/   dashboard em Vue
├── infra/      configuração do Mosquitto e docker-compose
├── scripts/    scripts de instalação e inicialização no Windows
└── docs/       documentação do projeto
```

## Rodando o projeto

Precisa de Python 3.11 ou mais novo, Node 18 ou mais novo, Mosquitto e InfluxDB 2.x.

No Windows dá para instalar o Mosquitto e o InfluxDB com:

```powershell
.\scripts\install-windows.ps1
```

Depois, para subir tudo de uma vez:

```powershell
.\scripts\start-all.ps1
```

Se preferir na mão:

```bash
# broker
mosquitto -c infra/mosquitto/config/mosquitto.conf -v

# banco
influxd
# e na primeira vez: .\scripts\setup-influx.ps1

# backend
cd backend
python -m venv .venv && source .venv/Scripts/activate
pip install -r requirements.txt
cp .env.example .env        # preencher o INFLUX_TOKEN
python -m app.main

# dashboard
cd frontend
npm install
npm run dev
```

O dashboard fica em http://localhost:5173 e a documentação da API em
http://localhost:8000/docs.

Para o ESP32, as instruções estão em [firmware/README.md](firmware/README.md).

## Sem a placa

O simulador publica exatamente o mesmo JSON nos mesmos tópicos:

```bash
python backend/simulator.py --backfill 12   # preenche 12h de histórico
python backend/simulator.py                 # publica ao vivo
python backend/simulator.py --stress        # força um pico crítico
```

## Portas

- 1883 e 9001: Mosquitto (TCP e WebSocket)
- 8086: InfluxDB
- 8000: backend
- 5173: dashboard

## Documentação

- [docs/PROBLEMA.md](docs/PROBLEMA.md) — o problema e a proposta
- [docs/ARQUITETURA.md](docs/ARQUITETURA.md) — diagramas e decisões técnicas
- [docs/CONTRACT.md](docs/CONTRACT.md) — tópicos, formato das mensagens e rotas
- [docs/APRESENTACAO.md](docs/APRESENTACAO.md) — roteiro da apresentação

## Próximo bimestre

A ideia é continuar daqui: vários racks ao mesmo tempo (os tópicos já estão
preparados para isso), notificação por e-mail ou Telegram, login no dashboard,
sensor de corrente e de porta aberta, e uma previsão simples de quando a
temperatura vai cruzar o limite.

## Autores

| Nome | GitHub |
|---|---|
| Eduardo Miranda | [@dudumiranda3105](https://github.com/dudumiranda3105) |
| Eduarda Roberta Borges da Silva | [@Eduarda-Borges-Silva](https://github.com/Eduarda-Borges-Silva) |
| Rebeca Souza Lúcio Chagas | [@RebecaSLChagas](https://github.com/RebecaSLChagas) |
| Edson Gabriel Klippel Pereira | - |
