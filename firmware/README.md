# eyeWatcher — Firmware (ESP32 no Wokwi)

Camada de **firmware** do projeto eyeWatcher: um ESP32 simulado lê temperatura e
umidade de um DHT22, classifica o estado do rack (`ok` / `warning` / `critical`),
sinaliza esse estado em LEDs + buzzer e publica a telemetria em JSON num broker
MQTT (Mosquitto).

> Fluxo completo do projeto:
> `ESP32 (Wokwi) → MQTT → Mosquitto → Python → InfluxDB → Web (Vue 3)`
>
> O formato dos tópicos, do payload e dos limiares é definido em
> [`../docs/CONTRACT.md`](../docs/CONTRACT.md). **Não altere nada disso aqui sem
> alterar o contrato.**

---

## 1. Arquivos desta pasta

| Arquivo | Para que serve |
|---|---|
| `sketch.ino` | O firmware em si (Arduino/C++), todo comentado em português |
| `diagram.json` | Desenho do circuito lido pelo simulador Wokwi |
| `libraries.txt` | Bibliotecas que o Wokwi deve instalar automaticamente |
| `wokwi.toml` | Configuração da extensão *Wokwi for VS Code* (aponta para o build do arduino-cli) |
| `README.md` | Este guia |

---

## 2. Como abrir no wokwi.com (navegador, sem instalar nada)

1. Acesse <https://wokwi.com> e faça login (conta gratuita).
2. Clique em **New Project → ESP32 → Arduino**. O Wokwi cria um projeto com
   `sketch.ino` e `diagram.json` vazios.
3. Na aba **`sketch.ino`**: apague o conteúdo de exemplo e cole o conteúdo do
   nosso `sketch.ino`.
4. Na aba **`diagram.json`**: apague o conteúdo e cole o nosso `diagram.json`.
   O circuito (ESP32 + DHT22 + 3 LEDs com resistores + buzzer) aparece desenhado
   imediatamente.
5. Bibliotecas — escolha **uma** das opções:
   - **Manual:** clique na aba **Library Manager** (ícone de biblioteca, no painel
     de arquivos) → **+** → adicione, uma a uma, as 4 bibliotecas listadas em
     `libraries.txt`.
   - **Colando o arquivo:** crie no projeto um arquivo chamado `libraries.txt` e
     cole o conteúdo do nosso. O Wokwi resolve as dependências ao rodar.
6. Ajuste o `#define MQTT_BROKER` conforme a seção 5 deste README
   (no navegador, use a opção **(b) ngrok** ou a **(c) broker público**).
7. Clique no botão **▶ (Start Simulation)**. O Serial Monitor abre sozinho
   (`"serialMonitor": { "display": "always" }` no `diagram.json`).
8. Para simular calor/seca e ver os LEDs mudarem: com a simulação rodando,
   **clique no DHT22** no diagrama — abre um painel onde você arrasta a
   temperatura e a umidade em tempo real.

### Alternativa: rodar pelo VS Code (recomendado, veja seção 5a)

```bash
# uma vez só
arduino-cli core install esp32:esp32
arduino-cli lib install "DHT sensor library" "Adafruit Unified Sensor" "PubSubClient" "ArduinoJson"

# a cada alteração no sketch (rode dentro de firmware/)
arduino-cli compile --fqbn esp32:esp32:esp32doit-devkit-v1 --output-dir build .
```

Depois, no VS Code com a extensão **Wokwi for VS Code** instalada:
`F1` → **Wokwi: Start Simulator**.

---

## 3. Esquema de ligação (pino → componente)

| GPIO do ESP32 | Componente | Pino do componente | Observações |
|---|---|---|---|
| `GPIO 15` | DHT22 (`dht1`) | `SDA` (dados) | Sensor de temperatura e umidade |
| `3V3` | DHT22 (`dht1`) | `VCC` | Alimentação do sensor |
| `GND` | DHT22 (`dht1`) | `GND` | Terra comum |
| `GPIO 25` | LED **verde** (`ledGreen`) | `A` (ânodo), via resistor 220 Ω | Status `ok` |
| `GPIO 26` | LED **amarelo** (`ledYellow`) | `A` (ânodo), via resistor 220 Ω | Status `warning` |
| `GPIO 27` | LED **vermelho** (`ledRed`) | `A` (ânodo), via resistor 220 Ω | Status `critical` |
| `GND` | Cátodo (`C`) dos 3 LEDs | `C` | Terra comum |
| `GPIO 4` | Buzzer (`bz1`) | `2` (positivo) | Apita **somente** em `critical` (tom de 2 kHz) |
| `GND` | Buzzer (`bz1`) | `1` (negativo) | Terra comum |

Cada LED tem **resistor de 220 Ω em série** entre o GPIO e o ânodo (limitação de
corrente). Os três cátodos e o buzzer vão para o mesmo símbolo de terra (`gnd1`),
que por sua vez está ligado ao `GND` da placa.

### Sinalização visual

| Situação | Verde | Amarelo | Vermelho | Buzzer |
|---|---|---|---|---|
| `ok` | aceso | — | — | mudo |
| `warning` | — | aceso | — | mudo |
| `critical` | — | — | aceso | **apitando** |
| Falha de leitura do DHT (NaN) | aceso | aceso | aceso | mudo |

Na falha do sensor os **três LEDs acendem juntos por ~0,4 s** e **nenhuma
telemetria é publicada** naquele ciclo (dado inválido no InfluxDB é pior que
dado ausente) — o erro é registrado no Serial Monitor.

---

## 4. O que o firmware publica

| Tópico | Payload | QoS | Retain |
|---|---|---|---|
| `eyewatcher/rack01/telemetry` | JSON (abaixo) | 1 | false |
| `eyewatcher/rack01/status` | `online` / `offline` (texto puro) | 1 | **true** |

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

Intervalo: **5 s** (`PUBLISH_INTERVAL_MS = 5000`). Não há campo de timestamp —
quem carimba a hora é o backend, como manda o contrato.

**Last Will and Testament (LWT):** ao conectar, o ESP32 registra no broker um
"testamento" (`offline`, QoS 1, retain) no tópico de status. Se o dispositivo cair
sem se despedir, o **próprio broker** publica `offline` e o backend percebe a
queda. Logo após conectar com sucesso, o firmware publica `online` (também
retained) no mesmo tópico.

**Limiares** (idênticos aos do backend):

| Métrica | ok | warning | critical |
|---|---|---|---|
| Temperatura | `< 30 °C` | `30 – 34.9 °C` | `>= 35 °C` |
| Umidade | `30 – 70 %` | `20 – 29.9 %` ou `70.1 – 80 %` | `< 20 %` ou `> 80 %` |

O status final é o **pior** entre os dois.

> ℹ️ **Nota honesta sobre QoS:** a biblioteca `PubSubClient` publica sempre com
> **QoS 0** (ela só implementa QoS 1 na *assinatura* e no LWT). O LWT deste
> firmware usa QoS 1 + retain corretamente. Para a telemetria, o efeito prático
> é mínimo no simulador (mesma máquina, sem perda), e o campo `seq` existe
> justamente para o backend detectar qualquer pacote perdido.

---

## 5. Como conectar o ESP32 simulado ao seu Mosquitto

O simulador roda "na nuvem do Wokwi" ou dentro do VS Code — ele **não enxerga
`localhost`** da sua máquina. Existem três caminhos; todos se resumem a trocar
**uma linha** no topo do `sketch.ino`:

```c
#define MQTT_BROKER   "host.wokwi.internal"
#define MQTT_PORT     1883
```

### (a) Wokwi for VS Code + `host.wokwi.internal` — **recomendado**

É a forma que pontua "Mosquitto próprio" e a mais simples de demonstrar.

1. Instale a extensão **Wokwi for VS Code** (marketplace) e ative a licença
   gratuita (`F1` → *Wokwi: Request a New License*).
2. Suba o Mosquitto local (na porta 1883 — ver `infra/`).
3. Compile o sketch com o arduino-cli (comandos da seção 2) — o `wokwi.toml`
   já aponta para `build/sketch.ino.bin` / `.elf`.
4. Deixe o `#define` assim:

   ```c
   #define MQTT_BROKER   "host.wokwi.internal"   // <- máquina que roda o VS Code
   #define MQTT_PORT     1883
   ```

5. `F1` → **Wokwi: Start Simulator**.

`host.wokwi.internal` é um nome especial que a extensão resolve para o **host que
está rodando o VS Code**. Ou seja, o ESP32 simulado fala direto com o Mosquitto
da sua máquina, sem expor nada para a internet.

> Se não conectar: confirme que o Mosquitto está ouvindo em `0.0.0.0:1883` (e não
> só em `127.0.0.1`) e que o `mosquitto.conf` tem `allow_anonymous true` +
> `listener 1883`. No Windows, libere a porta 1883 no Firewall.

### (b) wokwi.com (navegador) + túnel ngrok TCP

Use quando a apresentação tiver de rodar no site do Wokwi, mas você ainda quer
usar o **seu** Mosquitto.

1. Com o Mosquitto rodando localmente, abra um túnel TCP:

   ```bash
   ngrok tcp 1883
   ```

2. O ngrok imprime algo como:

   ```
   Forwarding  tcp://0.tcp.sa.ngrok.io:14732 -> localhost:1883
   ```

3. Troque **as duas linhas** no `sketch.ino` com o host e a porta que o ngrok
   gerou (a porta muda a cada vez que você reinicia o ngrok!):

   ```c
   #define MQTT_BROKER   "0.tcp.sa.ngrok.io"   // <- host gerado pelo ngrok
   #define MQTT_PORT     14732                 // <- porta gerada pelo ngrok
   ```

4. Rode a simulação no wokwi.com.

> ⚠️ Enquanto o túnel estiver aberto, **qualquer pessoa com a URL** consegue
> publicar no seu broker. Feche o ngrok (`Ctrl+C`) ao terminar a demonstração.
> O backend continua apontando para `localhost:1883` — o túnel só serve para o
> ESP32 entrar.

### (c) Broker público `test.mosquitto.org` — último recurso

Só para provar que o firmware funciona quando nada mais estiver disponível.

```c
#define MQTT_BROKER   "test.mosquitto.org"
#define MQTT_PORT     1883
```

> 🚨 **Atenção — isto NÃO pontua "Mosquitto próprio".** O requisito do projeto é
> um broker Mosquitto que **você** sobe (ver `infra/`); usar o broker público
> substitui essa peça da arquitetura e o backend deixaria de consumir do seu
> broker. Além disso, o `test.mosquitto.org` é **totalmente aberto**: qualquer
> pessoa no mundo pode ler a sua telemetria e publicar dados falsos em
> `eyewatcher/rack01/telemetry`. Se realmente precisar usar, troque o `RACK_ID`
> por algo improvável (ex.: `rack01-<seunome>-<numero>`) para reduzir colisão com
> outros usuários — **lembrando que isso muda os tópicos e você terá de ajustar o
> backend junto**.

---

## 6. Resumo dos `#define` que você pode querer trocar

| `#define` | Padrão | Quando mexer |
|---|---|---|
| `MQTT_BROKER` | `host.wokwi.internal` | Sempre que trocar de método de conexão (seção 5) |
| `MQTT_PORT` | `1883` | Apenas no caso do ngrok (porta gerada) |
| `RACK_ID` | `rack01` | Ao monitorar um segundo rack (muda tópicos e `device_id`) |
| `LOCATION` | `Sala de Servidores A` | Descrição física do rack (vai no payload) |
| `WIFI_SSID` / `WIFI_PASS` | `Wokwi-GUEST` / vazio | Só se sair do Wokwi para hardware real |
| `PUBLISH_INTERVAL_MS` | `5000` | **Não mexa** — é fixado pelo contrato |

---

## 7. Verificando que está tudo funcionando

No Serial Monitor você deve ver, a cada 5 segundos:

```
[LEITURA] T=28.0 C | UR=50.0 % | HI=28.0 C | status=ok (temp=ok, umid=ok)
[MQTT] -> eyewatcher/rack01/telemetry (188 bytes): {"device_id":"esp32-rack01",...}
```

E, em outro terminal, assinando o broker:

```bash
mosquitto_sub -h localhost -p 1883 -t 'eyewatcher/#' -v
```

Para testar o LWT: pare a simulação abruptamente (botão ⏹) e observe o
`mosquitto_sub` receber `eyewatcher/rack01/status offline`.
