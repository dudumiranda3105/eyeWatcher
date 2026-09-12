/*
 * ============================================================================
 *  eyeWatcher — Firmware ESP32 (simulação no Wokwi)
 * ============================================================================
 *  Monitoramento IoT de rack de servidores.
 *
 *  Fluxo do projeto (ver docs/CONTRACT.md):
 *      ESP32 (Wokwi) -> MQTT -> Mosquitto -> Python -> InfluxDB -> Web (Vue 3)
 *
 *  O que este firmware faz:
 *    1. Lê temperatura e umidade de um sensor DHT22 (GPIO 15).
 *    2. Calcula o índice de calor (sensação térmica) e o status do rack
 *       (ok / warning / critical) usando EXATAMENTE os limiares do contrato.
 *    3. Indica o status visualmente em 3 LEDs (verde / amarelo / vermelho)
 *       e dispara um buzzer apenas quando o status é "critical".
 *    4. Publica a telemetria em JSON no broker MQTT a cada 5 segundos.
 *    5. Mantém um tópico de presença (LWT) para o backend saber se o
 *       dispositivo está online ou caiu.
 *
 *  Todo o código é comentado em português porque este projeto é apresentado
 *  em uma avaliação acadêmica.
 * ============================================================================
 */

#include <WiFi.h>            // Pilha WiFi nativa do ESP32
#include <PubSubClient.h>    // Cliente MQTT (Nick O'Leary)
#include <DHT.h>             // DHT sensor library (Adafruit)
#include <ArduinoJson.h>     // ArduinoJson v7 — serialização do payload

/* ===========================================================================
 * 1) CONFIGURAÇÃO — é AQUI que você troca as coisas
 * ===========================================================================
 * Tudo o que muda de máquina para máquina / de rack para rack está nestes
 * #define. Não é preciso mexer em mais nada no resto do arquivo.
 */

/* --- WiFi -----------------------------------------------------------------
 * No simulador Wokwi a rede é sempre esta: SSID "Wokwi-GUEST", senha vazia.
 * O canal 6 é informado explicitamente porque acelera MUITO a associação
 * no Wokwi (sem ele, o ESP32 varre todos os canais e demora ~10 s).
 */
#define WIFI_SSID     "Wokwi-GUEST"
#define WIFI_PASS     ""
#define WIFI_CHANNEL  6

/* --- Broker MQTT ----------------------------------------------------------
 * TROQUE AQUI conforme a forma de conexão que você estiver usando
 * (as 3 opções estão explicadas em detalhe no README.md desta pasta):
 *
 *   (a) Wokwi for VS Code + Mosquitto local  ->  "host.wokwi.internal"  [recomendado]
 *   (b) wokwi.com no navegador + ngrok tcp   ->  "0.tcp.sa.ngrok.io" (e a porta gerada)
 *   (c) Demonstração de último recurso       ->  "test.mosquitto.org"
 *
 * A porta padrão TCP do Mosquitto é 1883 (definida no contrato, seção 7).
 * Com ngrok, troque MQTT_PORT para a porta que o ngrok gerar (ex.: 14732).
 */
#define MQTT_BROKER   "host.wokwi.internal"
#define MQTT_PORT     1883

/* --- Identidade deste dispositivo ----------------------------------------
 * RACK_ID  -> identifica o rack; entra no client id e nos tópicos MQTT.
 * LOCATION -> texto livre com a localização física do rack.
 * Ambos vão no payload JSON (campos "rack_id" e "location").
 */
#define RACK_ID       "rack01"
#define LOCATION      "Sala de Servidores A"

/* Client ID MQTT exigido pelo contrato: "esp32-<RACK_ID>".
 * Também é o campo "device_id" do payload. A concatenação de literais do
 * pré-processador garante que o texto bata caractere a caractere. */
#define DEVICE_ID     "esp32-" RACK_ID

/* --- Tópicos MQTT (contrato, seção 2) ------------------------------------
 *   eyewatcher/<rack_id>/telemetry  -> telemetria JSON, retain = false
 *   eyewatcher/<rack_id>/status     -> "online" / "offline", retain = true
 */
#define TOPIC_TELEMETRY  "eyewatcher/" RACK_ID "/telemetry"
#define TOPIC_STATUS     "eyewatcher/" RACK_ID "/status"

/* Payloads do tópico de presença: texto puro, sem JSON. */
#define PAYLOAD_ONLINE   "online"
#define PAYLOAD_OFFLINE  "offline"

/* --- Pinos (GPIO) ---------------------------------------------------------
 * Veja a tabela de ligação no README.md e o desenho em diagram.json.
 */
#define PIN_DHT        15   // Sensor DHT22 (pino de dados)
#define PIN_LED_GREEN  25   // LED verde    -> status "ok"
#define PIN_LED_YELLOW 26   // LED amarelo  -> status "warning"
#define PIN_LED_RED    27   // LED vermelho -> status "critical"
#define PIN_BUZZER      4   // Buzzer       -> apita apenas em "critical"

/* --- Tempos ---------------------------------------------------------------
 * PUBLISH_INTERVAL_MS é fixado em 5000 ms pelo contrato (seção 2).
 * Os demais controlam a reconexão não-bloqueante.
 */
#define PUBLISH_INTERVAL_MS      5000   // intervalo de publicação (contrato)
#define WIFI_RETRY_BASE_MS       1000   // 1º intervalo de retentativa do WiFi
#define WIFI_RETRY_MAX_MS       30000   // teto do backoff do WiFi
#define MQTT_RETRY_BASE_MS       1000   // 1º intervalo de retentativa do MQTT
#define MQTT_RETRY_MAX_MS       30000   // teto do backoff do MQTT
#define SENSOR_ERROR_BLINK_MS     400   // duração do "pisca de erro" dos 3 LEDs

/* --- Limiares (contrato, seção 3) ----------------------------------------
 * Temperatura: ok < 30 | warning 30–34.9 | critical >= 35
 * Umidade:     ok 30–70 | warning 20–29.9 ou 70.1–80 | critical < 20 ou > 80
 * O status final é o PIOR entre os dois.
 * Os mesmos números existem como env no backend (TEMP_WARN, TEMP_CRIT, ...).
 */
#define TEMP_WARN      30.0f
#define TEMP_CRIT      35.0f
#define HUM_MIN_WARN   30.0f
#define HUM_MIN_CRIT   20.0f
#define HUM_MAX_WARN   70.0f
#define HUM_MAX_CRIT   80.0f

/* ===========================================================================
 * 2) OBJETOS GLOBAIS
 * ===========================================================================
 */

DHT dht(PIN_DHT, DHT22);        // Driver do sensor: pino de dados + modelo
WiFiClient wifiClient;          // Socket TCP puro (MQTT sem TLS, porta 1883)
PubSubClient mqtt(wifiClient);  // Cliente MQTT rodando sobre esse socket

/* Contador incremental de mensagens (campo "seq" do payload).
 * Serve para o backend detectar perda de pacotes. */
uint32_t seq = 0;

/* --- Estado da máquina de reconexão (tudo não-bloqueante) ----------------
 * A regra do projeto é: NENHUM delay() longo dentro do loop(). Em vez de
 * travar o processador esperando, guardamos "quando foi a última tentativa"
 * e "quanto tempo esperar até a próxima" (backoff exponencial).
 */
unsigned long lastPublishMs   = 0;                    // última telemetria enviada
unsigned long lastWifiTryMs   = 0;                    // última tentativa de WiFi
unsigned long wifiBackoffMs   = WIFI_RETRY_BASE_MS;   // espera atual do WiFi
unsigned long lastMqttTryMs   = 0;                    // última tentativa de MQTT
unsigned long mqttBackoffMs   = MQTT_RETRY_BASE_MS;   // espera atual do MQTT

/* Controle do "pisca de erro" (os 3 LEDs acesos quando o DHT falha). */
bool          sensorErrorBlinkOn    = false;
unsigned long sensorErrorBlinkStart = 0;

/* ===========================================================================
 * 3) FUNÇÕES AUXILIARES
 * ===========================================================================
 */

/* ---------------------------------------------------------------------------
 * classificaTemperatura() / classificaUmidade()
 * Convertem uma leitura em um "nível de severidade" numérico:
 *     0 = ok        1 = warning        2 = critical
 * Trabalhar com número facilita pegar o PIOR dos dois com um simples max().
 * --------------------------------------------------------------------------- */
int classificaTemperatura(float t) {
  if (t >= TEMP_CRIT) return 2;   // >= 35 °C  -> critical
  if (t >= TEMP_WARN) return 1;   // 30–34.9   -> warning
  return 0;                       // < 30 °C   -> ok
}

int classificaUmidade(float h) {
  if (h < HUM_MIN_CRIT || h > HUM_MAX_CRIT) return 2;  // < 20% ou > 80%  -> critical
  if (h < HUM_MIN_WARN || h > HUM_MAX_WARN) return 1;  // 20–29.9 ou 70.1–80 -> warning
  return 0;                                            // 30–70%          -> ok
}

/* Traduz o nível numérico para o texto exato aceito pelo contrato. */
const char* nivelParaTexto(int nivel) {
  if (nivel == 2) return "critical";
  if (nivel == 1) return "warning";
  return "ok";
}

/* ---------------------------------------------------------------------------
 * atualizaIndicadores()
 * Acende apenas o LED correspondente ao status e liga o buzzer somente
 * quando o status é "critical" (requisito do projeto).
 * --------------------------------------------------------------------------- */
void atualizaIndicadores(int nivel) {
  digitalWrite(PIN_LED_GREEN,  nivel == 0 ? HIGH : LOW);
  digitalWrite(PIN_LED_YELLOW, nivel == 1 ? HIGH : LOW);
  digitalWrite(PIN_LED_RED,    nivel == 2 ? HIGH : LOW);

  // Buzzer: tom contínuo de 2 kHz em situação crítica, silêncio nos demais casos.
  if (nivel == 2) {
    tone(PIN_BUZZER, 2000);
  } else {
    noTone(PIN_BUZZER);
    digitalWrite(PIN_BUZZER, LOW);
  }
}

/* ---------------------------------------------------------------------------
 * arredonda1()
 * O contrato pede temperatura, umidade e índice de calor com 1 casa decimal.
 * Arredondamos ANTES de serializar para o JSON sair exatamente como o
 * backend e o frontend esperam.
 * --------------------------------------------------------------------------- */
float arredonda1(float valor) {
  return roundf(valor * 10.0f) / 10.0f;
}

/* ---------------------------------------------------------------------------
 * iniciaWiFi()
 * Dispara a associação à rede. Não bloqueia: quem verifica se conectou é o
 * loop(), através de garanteWiFi().
 * --------------------------------------------------------------------------- */
void iniciaWiFi() {
  Serial.printf("[WiFi] Conectando à rede \"%s\" (canal %d)...\n", WIFI_SSID, WIFI_CHANNEL);
  WiFi.mode(WIFI_STA);                          // ESP32 como estação (cliente)
  WiFi.setAutoReconnect(true);                  // deixa a pilha tentar sozinha também
  WiFi.begin(WIFI_SSID, WIFI_PASS, WIFI_CHANNEL);  // canal 6 -> associação rápida no Wokwi
}

/* ---------------------------------------------------------------------------
 * garanteWiFi()
 * Chamada a cada volta do loop(). Se o WiFi caiu, tenta reconectar
 * respeitando um backoff exponencial (1s, 2s, 4s, ... até 30s) — sem travar
 * o restante do firmware.
 * Retorna true se, neste instante, existe conexão WiFi.
 * --------------------------------------------------------------------------- */
bool garanteWiFi() {
  if (WiFi.status() == WL_CONNECTED) {
    wifiBackoffMs = WIFI_RETRY_BASE_MS;   // conectou: zera o backoff
    return true;
  }

  unsigned long agora = millis();
  if (agora - lastWifiTryMs >= wifiBackoffMs) {
    lastWifiTryMs = agora;
    Serial.printf("[WiFi] Sem conexão. Nova tentativa (próxima espera: %lu ms)...\n", wifiBackoffMs);
    WiFi.disconnect();
    WiFi.begin(WIFI_SSID, WIFI_PASS, WIFI_CHANNEL);

    wifiBackoffMs *= 2;                                     // backoff exponencial
    if (wifiBackoffMs > WIFI_RETRY_MAX_MS) wifiBackoffMs = WIFI_RETRY_MAX_MS;
  }
  return false;
}

/* ---------------------------------------------------------------------------
 * garanteMQTT()
 * Mantém a sessão MQTT viva. Também não-bloqueante, com o mesmo esquema de
 * backoff exponencial.
 *
 * Ponto importante para a apresentação — Last Will and Testament (LWT):
 * ao conectar, informamos ao broker um "testamento": se o ESP32 sumir sem se
 * despedir (queda de energia, cabo, travamento), o PRÓPRIO BROKER publica
 * "offline" com retain no tópico de status. Assim o backend descobre a queda
 * mesmo sem receber nada do dispositivo. Logo após conectar, publicamos
 * "online" (também retained) sobrescrevendo o valor anterior.
 * --------------------------------------------------------------------------- */
bool garanteMQTT() {
  if (mqtt.connected()) {
    mqttBackoffMs = MQTT_RETRY_BASE_MS;   // conectado: zera o backoff
    return true;
  }

  unsigned long agora = millis();
  if (agora - lastMqttTryMs < mqttBackoffMs) {
    return false;                         // ainda dentro da janela de espera
  }
  lastMqttTryMs = agora;

  Serial.printf("[MQTT] Conectando em %s:%d como \"%s\"...\n", MQTT_BROKER, MQTT_PORT, DEVICE_ID);

  /* Assinatura usada:
   *   connect(clientId, user, pass, willTopic, willQos, willRetain, willMessage, cleanSession)
   * Usuário e senha vão NULL porque o Mosquitto do projeto está sem autenticação.
   * O testamento usa QoS 1 e retain true, exatamente como manda o contrato. */
  bool ok = mqtt.connect(
      DEVICE_ID,        // client id  -> "esp32-rack01"
      NULL, NULL,       // sem usuário/senha
      TOPIC_STATUS,     // tópico do testamento
      1,                // QoS 1
      true,             // retain true
      PAYLOAD_OFFLINE,  // mensagem "offline"
      true              // clean session
  );

  if (ok) {
    Serial.println("[MQTT] Conectado com sucesso.");
    // Presença: avisa que está vivo. retain=true para quem assinar depois
    // já receber o último estado conhecido imediatamente.
    mqtt.publish(TOPIC_STATUS, PAYLOAD_ONLINE, true);
    Serial.printf("[MQTT] Publicado \"%s\" (retained) em %s\n", PAYLOAD_ONLINE, TOPIC_STATUS);
    mqttBackoffMs = MQTT_RETRY_BASE_MS;
    return true;
  }

  // rc: -4 timeout, -3 conexão perdida, -2 falha de conexão, -1 desconectado,
  //      1..5 recusado pelo broker (versão/id/indisponível/credenciais/não autorizado)
  Serial.printf("[MQTT] Falha ao conectar (rc=%d). Nova tentativa em %lu ms.\n",
                mqtt.state(), mqttBackoffMs);

  mqttBackoffMs *= 2;                                     // backoff exponencial
  if (mqttBackoffMs > MQTT_RETRY_MAX_MS) mqttBackoffMs = MQTT_RETRY_MAX_MS;
  return false;
}

/* ---------------------------------------------------------------------------
 * publicaTelemetria()
 * Monta o JSON EXATAMENTE no formato do contrato (seção 2) e publica.
 *
 * Formato esperado:
 * {
 *   "device_id": "esp32-rack01",
 *   "rack_id": "rack01",
 *   "location": "Sala de Servidores A",
 *   "temperature": 34.5,
 *   "humidity": 48.2,
 *   "heat_index": 36.1,
 *   "status": "ok",
 *   "uptime_s": 12345,
 *   "seq": 42
 * }
 * Obs.: o contrato PROÍBE enviar timestamp — quem carimba a hora é o backend.
 * --------------------------------------------------------------------------- */
void publicaTelemetria(float temperatura, float umidade, float heatIndex, const char* status) {
  JsonDocument doc;   // ArduinoJson v7: documento com alocação elástica

  doc["device_id"]   = DEVICE_ID;
  doc["rack_id"]     = RACK_ID;
  doc["location"]    = LOCATION;
  doc["temperature"] = temperatura;
  doc["humidity"]    = umidade;
  doc["heat_index"]  = heatIndex;
  doc["status"]      = status;
  doc["uptime_s"]    = (uint32_t)(millis() / 1000UL);  // segundos desde o boot
  doc["seq"]         = seq;                            // contador incremental

  char payload[256];
  size_t tamanho = serializeJson(doc, payload, sizeof(payload));

  if (mqtt.publish(TOPIC_TELEMETRY, payload)) {   // retain = false (padrão)
    Serial.printf("[MQTT] -> %s (%u bytes): %s\n", TOPIC_TELEMETRY, (unsigned)tamanho, payload);
    seq++;                                        // só avança se realmente saiu
  } else {
    Serial.println("[MQTT] ERRO: falha ao publicar a telemetria (buffer cheio ou conexão caiu).");
  }
}

/* ---------------------------------------------------------------------------
 * sinalizaErroSensor()
 * Quando o DHT22 devolve NaN (sensor desconectado, ruído, leitura inválida),
 * acendemos os 3 LEDs ao mesmo tempo por um instante — um sinal visual que
 * não se confunde com nenhum dos status normais.
 * A apagada é feita depois, no loop(), sem delay().
 * --------------------------------------------------------------------------- */
void sinalizaErroSensor() {
  digitalWrite(PIN_LED_GREEN,  HIGH);
  digitalWrite(PIN_LED_YELLOW, HIGH);
  digitalWrite(PIN_LED_RED,    HIGH);
  noTone(PIN_BUZZER);
  digitalWrite(PIN_BUZZER, LOW);

  sensorErrorBlinkOn    = true;
  sensorErrorBlinkStart = millis();
}

/* ===========================================================================
 * 4) SETUP — roda uma única vez no boot
 * ===========================================================================
 */
void setup() {
  Serial.begin(115200);
  delay(200);   // pequena pausa só para o monitor serial do Wokwi "pegar" o início

  Serial.println();
  Serial.println("==========================================");
  Serial.println("  eyeWatcher - Firmware ESP32");
  Serial.printf ("  Dispositivo: %s\n", DEVICE_ID);
  Serial.printf ("  Rack: %s | Local: %s\n", RACK_ID, LOCATION);
  Serial.printf ("  Broker: %s:%d\n", MQTT_BROKER, MQTT_PORT);
  Serial.println("==========================================");

  // --- Pinos de saída: LEDs e buzzer ---
  pinMode(PIN_LED_GREEN,  OUTPUT);
  pinMode(PIN_LED_YELLOW, OUTPUT);
  pinMode(PIN_LED_RED,    OUTPUT);
  pinMode(PIN_BUZZER,     OUTPUT);
  digitalWrite(PIN_LED_GREEN,  LOW);
  digitalWrite(PIN_LED_YELLOW, LOW);
  digitalWrite(PIN_LED_RED,    LOW);
  digitalWrite(PIN_BUZZER,     LOW);
  Serial.println("[GPIO] LEDs (25/26/27) e buzzer (4) configurados como saída.");

  // --- Sensor ---
  dht.begin();
  Serial.println("[DHT22] Sensor inicializado no GPIO 15.");

  // --- Rede ---
  iniciaWiFi();

  // --- MQTT ---
  mqtt.setServer(MQTT_BROKER, MQTT_PORT);
  mqtt.setKeepAlive(15);        // keepalive curto: o broker percebe a queda rápido
  mqtt.setBufferSize(512);      // o payload cabe folgado (padrão da lib são 256 B)
  Serial.println("[MQTT] Cliente configurado. A conexão acontece no loop().");

  Serial.println("[SETUP] Concluído. Entrando no loop principal.\n");
}

/* ===========================================================================
 * 5) LOOP — roda continuamente
 * ===========================================================================
 * Estrutura do loop (tudo não-bloqueante):
 *   a) garante WiFi          -> se caiu, tenta reconectar com backoff
 *   b) garante MQTT          -> idem
 *   c) mqtt.loop()           -> processa keepalive/pacotes pendentes
 *   d) apaga o pisca de erro -> se já passou o tempo
 *   e) a cada 5 s: lê o sensor, calcula status, atualiza LEDs/buzzer, publica
 */
void loop() {
  // (a) e (b) — conectividade
  bool wifiOk = garanteWiFi();
  bool mqttOk = false;
  if (wifiOk) {
    mqttOk = garanteMQTT();
    // (c) mantém a sessão MQTT viva (PINGREQ/PINGRESP, fila de saída)
    if (mqttOk) mqtt.loop();
  }

  unsigned long agora = millis();

  // (d) — desliga o "pisca de erro" dos 3 LEDs depois do tempo combinado
  if (sensorErrorBlinkOn && (agora - sensorErrorBlinkStart >= SENSOR_ERROR_BLINK_MS)) {
    digitalWrite(PIN_LED_GREEN,  LOW);
    digitalWrite(PIN_LED_YELLOW, LOW);
    digitalWrite(PIN_LED_RED,    LOW);
    sensorErrorBlinkOn = false;
  }

  // (e) — ciclo de medição/publicação a cada PUBLISH_INTERVAL_MS (5 s)
  if (agora - lastPublishMs < PUBLISH_INTERVAL_MS) {
    return;   // ainda não deu a hora: sai e deixa o loop girar de novo
  }
  lastPublishMs = agora;

  // --- Leitura do sensor ---
  float umidade     = dht.readHumidity();      // % RH
  float temperatura = dht.readTemperature();   // °C (false/omisso = Celsius)

  // --- Tratamento de falha de leitura ---
  // O DHT devolve NaN quando a leitura falha. Nesse caso NÃO publicamos nada
  // (dado ruim no InfluxDB é pior que dado ausente) e sinalizamos nos LEDs.
  if (isnan(umidade) || isnan(temperatura)) {
    Serial.println("[DHT22] ERRO: leitura inválida (NaN). Sensor desconectado ou com falha.");
    Serial.println("[DHT22] Telemetria NÃO publicada neste ciclo. Sinalizando nos 3 LEDs.");
    sinalizaErroSensor();
    return;
  }

  // --- Índice de calor (sensação térmica) ---
  // O terceiro parâmetro 'false' indica que as entradas estão em Celsius.
  float heatIndex = dht.computeHeatIndex(temperatura, umidade, false);

  // --- Arredondamento para 1 casa decimal (exigência do contrato) ---
  temperatura = arredonda1(temperatura);
  umidade     = arredonda1(umidade);
  heatIndex   = arredonda1(heatIndex);

  // --- Cálculo do status: o PIOR entre temperatura e umidade ---
  int nivelTemp = classificaTemperatura(temperatura);
  int nivelUmid = classificaUmidade(umidade);
  int nivelFinal = max(nivelTemp, nivelUmid);
  const char* status = nivelParaTexto(nivelFinal);

  // --- Indicação local (LEDs + buzzer) ---
  atualizaIndicadores(nivelFinal);

  Serial.printf("[LEITURA] T=%.1f C | UR=%.1f %% | HI=%.1f C | status=%s (temp=%s, umid=%s)\n",
                temperatura, umidade, heatIndex, status,
                nivelParaTexto(nivelTemp), nivelParaTexto(nivelUmid));

  // --- Publicação ---
  if (mqttOk) {
    publicaTelemetria(temperatura, umidade, heatIndex, status);
  } else {
    Serial.println("[MQTT] Offline: leitura exibida apenas no Serial (nada publicado).");
  }
}
