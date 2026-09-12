# Roteiro de Apresentação e Checklist de Avaliação

> A pontuação depende do **funcionamento demonstrado**, não da presença da
> tecnologia no código. Este documento mapeia cada critério ao que precisa
> aparecer na tela durante a avaliação.

---

## Checklist por critério (10,0 pontos)

### 1. Definição do problema e proposta da solução IoT — 1,0
- [ ] Abrir `docs/PROBLEMA.md` e explicar o cenário em ~1 minuto
- [ ] Mostrar o diagrama de arquitetura (`docs/ARQUITETURA.md`)
- [ ] **Frase-chave:** "o sensor é independente do servidor monitorado — ele
      continua reportando exatamente quando o servidor cai"

### 2. Frontend Vue 3 + TypeScript + Vite — 2,0
- [ ] Dashboard aberto em `http://localhost:5173` com dados reais
- [ ] Mostrar no terminal que o Vite está rodando (`npm run dev`)
- [ ] Abrir `src/types/api.ts` e um componente `.vue` provando o TypeScript
- [ ] Rodar `npx vue-tsc --noEmit` ao vivo se questionarem a tipagem
- [ ] Trocar o período (15m → 24h) e mostrar o gráfico se redesenhando

### 3. Dispositivo IoT no Wokwi — 1,5
- [ ] Simulação rodando com o ESP32 e o DHT22 visíveis
- [ ] Abrir o Serial Monitor mostrando os logs de conexão e publicação
- [ ] **Mexer no slider do DHT22 ao vivo** para subir a temperatura
- [ ] Mostrar os LEDs mudando de verde → amarelo → vermelho e o buzzer tocando

### 4. Comunicação MQTT + Mosquitto — 2,0
- [ ] Mostrar o Mosquitto rodando (serviço ativo ou janela do broker)
- [ ] Rodar `scripts/test-mqtt.ps1`, ou em um terminal:
      `mosquitto_sub -h localhost -t "eyewatcher/#" -v`
      e deixar as mensagens aparecendo ao vivo durante a apresentação
- [ ] Explicar QoS 1 e mostrar o Last Will: **parar a simulação do Wokwi** e o
      dashboard mudar para "offline" sozinho — essa é a demonstração mais forte
- [ ] Mostrar `infra/mosquitto/config/mosquitto.conf`

### 5. Backend Python recebendo e processando — 1,0
- [ ] Logs do backend no terminal mostrando cada mensagem recebida e gravada
- [ ] Abrir a documentação automática em `http://localhost:8000/docs`
- [ ] Executar uma rota pelo Swagger ao vivo
- [ ] Mostrar `app/mqtt_client.py` — validação do payload e recálculo do status

### 6. Persistência no InfluxDB — 1,5
- [ ] Abrir `http://localhost:8086` → Data Explorer
- [ ] Rodar a query e mostrar os pontos chegando:
```flux
from(bucket: "rack_metrics")
  |> range(start: -1h)
  |> filter(fn: (r) => r._measurement == "ambiente")
  |> filter(fn: (r) => r._field == "temperature")
```
- [ ] Mostrar as tags (`rack_id`, `status`) no painel lateral
- [ ] Explicar por que série temporal e não SQL (ver `docs/ARQUITETURA.md` §6)

### 7. Dashboard com gráfico ou indicador — 1,0
- [ ] Gráfico de linha com temperatura e umidade e as linhas de limiar
- [ ] Cards de indicador (valor atual + tendência)
- [ ] Painel de mín/máx/média e a tabela de alertas
- [ ] Mostrar a atualização em tempo real via WebSocket enquanto o Wokwi publica

---

## Roteiro sugerido (8–10 minutos)

| Tempo | O que fazer |
|---|---|
| 0:00–1:00 | **Problema.** Quem tem servidor em casa/laboratório já perdeu serviço por calor sem saber. Mostrar o diagrama. |
| 1:00–2:00 | **Wokwi.** Circuito, Serial Monitor conectando ao WiFi e ao broker, primeira publicação. |
| 2:00–3:00 | **MQTT.** Terminal com `mosquitto_sub` mostrando o JSON chegando em tempo real. |
| 3:00–4:00 | **Backend.** Logs processando, `/docs` do FastAPI, executar uma rota. |
| 4:00–5:00 | **InfluxDB.** Data Explorer com os pontos e as tags. |
| 5:00–7:00 | **Dashboard.** Indicadores, gráfico, troca de período, tabela de alertas. |
| 7:00–8:00 | **Demonstração ao vivo.** Subir o slider do DHT22 → LED vermelho + buzzer → card fica vermelho → alerta aparece na tabela. |
| 8:00–9:00 | **Resiliência.** Parar o Wokwi → LWT marca offline no dashboard. Depois mostrar o Git e o roadmap do 2º bimestre. |

---

## Ordem de inicialização (decorar)

```
1. Mosquitto      → porta 1883
2. InfluxDB       → porta 8086
3. Backend        → porta 8000   (uvicorn)
4. Frontend       → porta 5173   (npm run dev)
5. Wokwi          → iniciar a simulação
```

Ou simplesmente: `.\scripts\start-all.ps1`

---

## Antes de apresentar

- [ ] Rodar `python backend/simulator.py --backfill 24` para que o gráfico já
      tenha 24 h de histórico — um gráfico com 3 pontos não impressiona ninguém
- [ ] Confirmar que o Wokwi conecta **na rede do local da apresentação**
      (o WiFi da faculdade pode bloquear a porta 1883 — testar antes!)
- [ ] Deixar 4 terminais já abertos e posicionados: Mosquitto, backend,
      frontend e `mosquitto_sub`
- [ ] Ter o `simulator.py` pronto como **plano B** caso o Wokwi não conecte na
      hora — ele publica no mesmo tópico e todo o resto da pilha funciona igual
- [ ] Fazer o push final para o GitHub e abrir o repositório numa aba

## Plano B (se o Wokwi não conectar na hora)

Não entre em pânico e **não fique mexendo no firmware na frente do avaliador**.
Diga: *"a rede aqui bloqueia a porta do broker; vou demonstrar com o publicador
equivalente em Python, que usa exatamente o mesmo tópico e o mesmo payload"* —
e rode:

```
python backend/simulator.py --stress
```

Em seguida mostre o Wokwi rodando e publicando no Serial Monitor, mesmo sem
chegar ao broker, para comprovar que o firmware funciona. Os critérios de MQTT,
backend, InfluxDB e dashboard continuam integralmente demonstráveis.
