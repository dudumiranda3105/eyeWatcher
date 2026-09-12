# Definição do Problema e Proposta de Solução IoT

> Critério de avaliação: **1,0 ponto** — *Definição do problema e proposta da solução IoT*

---

## 1. O problema real

Servidores caseiros (*homelabs*), racks de pequenas empresas e laboratórios de
instituições de ensino quase nunca possuem a infraestrutura de climatização
monitorada que existe em um *data center* profissional. Na prática, esses
equipamentos ficam em salas de apoio, almoxarifados adaptados ou até em
armários — ambientes em que a temperatura oscila muito ao longo do dia e o
ar-condicionado frequentemente é desligado fora do horário comercial.

O resultado é um padrão de falha conhecido e recorrente:

1. A temperatura interna do rack sobe lentamente ao longo de horas.
2. Os processadores entram em *thermal throttling* e o desempenho cai — sem
   nenhum aviso visível ao usuário.
3. A fonte ou o disco atinge a temperatura de desligamento por proteção.
4. **O serviço cai.** Só então alguém descobre que havia um problema térmico.

### Por que isso é grave

- **Detecção tardia.** O problema é percebido pelo *sintoma* (serviço fora do ar),
  não pela *causa* (temperatura). Quando o alerta chega, o dano já ocorreu.
- **Redução da vida útil do hardware.** Segundo a regra prática de Arrhenius
  aplicada à eletrônica, cada 10 °C acima da faixa recomendada tende a reduzir
  pela metade a vida útil de componentes eletrônicos. O desgaste é silencioso e
  cumulativo.
- **Umidade também importa.** Umidade relativa muito baixa favorece descargas
  eletrostáticas; muito alta favorece corrosão e condensação. Praticamente
  ninguém mede isso em ambientes pequenos.
- **Ausência total de histórico.** Sem série temporal, é impossível responder a
  perguntas básicas de diagnóstico:
  - *A temperatura já estava subindo antes da queda de ontem?*
  - *O pico acontece sempre no mesmo horário?* (ex.: sol da tarde na parede)
  - *O ar-condicionado realmente ficou ligado no fim de semana?*
  - *A troca do ventilador melhorou alguma coisa, ou foi impressão?*

### Por que as alternativas existentes não resolvem

| Alternativa | Limitação |
|---|---|
| Termômetro de parede | Não registra histórico e exige alguém olhando |
| Sensores da BIOS / IPMI | Medem o chip, não o **ambiente do rack**; não cobrem umidade; indisponíveis quando o servidor cai |
| Solução comercial de DCIM | Custo e complexidade incompatíveis com o porte desses ambientes |
| Planilha preenchida manualmente | Baixa frequência de amostragem e sujeita a esquecimento |

O problema é, portanto, de **instrumentação contínua e independente do
servidor monitorado** — exatamente o tipo de lacuna que a Internet das Coisas
preenche bem.

---

## 2. A solução proposta: eyeWatcher

O **eyeWatcher** é um sistema IoT de monitoramento ambiental de racks que mede
temperatura e umidade de forma contínua, armazena a série histórica e apresenta
tudo em um dashboard Web.

O ponto central do projeto é que o dispositivo de medição é **independente do
servidor monitorado**: mesmo que o servidor esteja desligado, travado ou
superaquecido, o ESP32 continua medindo e reportando — que é justamente o
momento em que o dado tem mais valor.

### Arquitetura da solução

```
┌───────────────┐    MQTT     ┌────────────┐   MQTT    ┌──────────────┐
│    ESP32      │  publish    │            │ subscribe │   Backend    │
│   + DHT22     ├────────────►│ Mosquitto  ├──────────►│   Python     │
│ (rack físico) │  QoS 1      │  (Broker)  │           │  (FastAPI)   │
└───────────────┘             └────────────┘           └──────┬───────┘
      mede a cada 5s                                          │ escreve
                                                              ▼
┌─────────────────┐        HTTP/WebSocket          ┌──────────────────┐
│   Dashboard     │◄───────────────────────────────┤     InfluxDB     │
│ Vue 3 + Chart.js│      consulta histórico        │ (séries temporais)│
└─────────────────┘                                └──────────────────┘
```

### Como cada dor vira uma funcionalidade

| Dor identificada | Funcionalidade do eyeWatcher |
|---|---|
| Descoberta tardia do superaquecimento | Leitura a cada 5 s com classificação imediata em `ok` / `warning` / `critical`, sinalizada por LEDs no próprio rack e no banner do dashboard |
| Falta de histórico para achar padrões | Todas as leituras persistidas no InfluxDB (retenção de 30 dias) e gráfico com janelas de 15 min a 7 dias |
| Umidade ignorada | Medida pelo mesmo sensor DHT22, com faixa segura própria e limiares independentes |
| "Foi impressão minha ou piorou?" | Painel de mín / máx / média por período, permitindo comparação objetiva antes e depois de uma intervenção |
| Não saber se o sensor parou de reportar | *Last Will Testament* do MQTT marca o dispositivo como `offline` automaticamente se ele cair — ausência de dado também é informação |

### Por que MQTT e não HTTP direto

MQTT foi escolhido por ser o protocolo padrão de IoT para este cenário:
é leve (cabe com folga na memória do ESP32), usa uma conexão TCP persistente em
vez de abrir uma requisição a cada leitura, oferece QoS 1 (garantia de entrega
com retransmissão) e, principalmente, desacopla produtor e consumidor — o
backend pode ser reiniciado sem que o ESP32 precise saber ou ser reconfigurado.
O recurso de *Last Will Testament*, que detecta queda do dispositivo sem custo
adicional, não tem equivalente direto em HTTP.

### Por que um banco de séries temporais

As leituras são um fluxo append-only indexado por tempo, consultado quase sempre
por intervalo e de forma agregada ("média por minuto nas últimas 6 horas").
O InfluxDB é construído para esse padrão: compacta bem dados numéricos
repetitivos, tem *downsampling* nativo (`aggregateWindow`) e aplica políticas de
retenção automáticas — três coisas que exigiriam código manual em um banco
relacional.

---

## 3. Escopo do 1º bimestre

Entregue nesta etapa:

- [x] 1 dispositivo (ESP32 simulado no Wokwi) com sensor DHT22
- [x] Publicação MQTT com QoS 1 e LWT
- [x] Broker Mosquitto com listeners TCP e WebSocket
- [x] Backend Python que assina, valida e persiste as leituras
- [x] Persistência no InfluxDB com tags e campos modelados
- [x] API REST + WebSocket para consulta do histórico e tempo real
- [x] Dashboard Vue 3 + TypeScript + Vite com gráfico Chart.js e indicadores
- [x] Código versionado em Git

## 4. Continuidade prevista para o 2º bimestre

O projeto foi estruturado para crescer sem reescrita:

- **Múltiplos racks** — os tópicos já usam `eyewatcher/<rack_id>/...` e o backend
  já assina com o coringa `+`, então adicionar um segundo dispositivo não exige
  mudança de código.
- **Notificações ativas** — e-mail/Telegram disparados quando o status entrar em
  `critical` por N leituras consecutivas.
- **Autenticação** — usuários e perfis no dashboard, e credenciais no Mosquitto.
- **Novos sensores** — corrente elétrica (consumo do rack) e sensor de porta
  aberta, reaproveitando o mesmo payload.
- **Previsão** — regressão simples sobre a série do InfluxDB para estimar quando
  a temperatura cruzará o limiar crítico e alertar *antes* do evento.
