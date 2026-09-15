# eyeWatcher — Frontend

Painel web de monitoramento térmico de racks de servidores. Mostra a leitura atual,
o histórico agregado, o resumo do período e os alertas recentes de um rack, com
atualização em tempo real pelo WebSocket do backend.

Stack: **Vue 3** (`<script setup>`) + **TypeScript strict** + **Vite** + **Chart.js**
(via `vue-chartjs`), estado em **Pinia**, HTTP com **axios**.

---

## Requisitos

- Node.js 20.19+ ou 22.12+ (testado no Node 24)
- npm 10+
- Backend do eyeWatcher rodando em `http://localhost:8000` (FastAPI)

O painel funciona sem o backend: nesse caso ele mostra o estado de erro, continua
tentando a cada 10 segundos e reconecta o WebSocket sozinho.

---

## Instalar

```bash
cd frontend
npm install
```

## Rodar em desenvolvimento

```bash
npm run dev
```

Abre em <http://localhost:5173>. O Vite faz proxy de `/api` e `/ws` para
`http://localhost:8000`, então não há CORS nem URL fixa no código.

## Verificar tipos

```bash
npx vue-tsc --noEmit
```

## Gerar o build de produção

```bash
npm run build     # roda vue-tsc e gera dist/
npm run preview   # serve dist/ em http://localhost:4173
```

O `dist/` é estático: pode ser servido por qualquer HTTP server (nginx, Caddy,
`python -m http.server`). Em produção, o servidor precisa encaminhar `/api` e
`/ws` para o backend, já que o proxy do Vite só existe em desenvolvimento.

---

## Apontar para outro host de backend

Crie `frontend/.env.local` (não versionado) com o que precisar:

```bash
# Dev: destino do proxy do Vite para /api e /ws
VITE_BACKEND_TARGET=http://192.168.0.42:8000

# Produção (ou quando não quiser passar pelo proxy):
# base das rotas HTTP e URL completa do WebSocket
VITE_API_BASE_URL=http://192.168.0.42:8000/api
VITE_WS_URL=ws://192.168.0.42:8000/ws/live

# Rack exibido no painel (default: rack01)
VITE_RACK_ID=rack01
```

Reinicie o `npm run dev` depois de mudar o arquivo.

---

## Estrutura

```
src/
  types/api.ts            Interfaces espelhando docs/CONTRACT.md + validação do WS
  services/api.ts         Camada axios tipada, uma função por rota, erros em pt-BR
  services/ws.ts          Cliente /ws/live com reconexão exponencial (1s → 30s)
  stores/racks.ts         Store Pinia: leitura, histórico, stats, alertas, conexão
  composables/            Leitura dos tokens de cor para o Chart.js (canvas)
  components/
    StatusBanner.vue      Faixa de status geral + online/offline
    MetricCard.vue        Indicador com valor grande, tendência e faixa de limiares
    ThresholdBand.vue     A régua de limiares (30/35 °C, 20/30/70/80 %)
    TemperatureChart.vue  Linha dupla temperatura/umidade, dois eixos Y, eixo X temporal
    RangeSelector.vue     15m / 1h / 6h / 24h / 7d
    StatsPanel.vue        Mín / média / máx / atual do período
    AlertsTable.vue       Alertas recentes com horário pt-BR e badge de severidade
  utils/                  Formatação Intl pt-BR e limiares do contrato
  styles/theme.css        Tokens de cor e tipografia, claro e escuro
  App.vue                 Layout do dashboard e estados de carregando/erro/vazio
```

## Decisões que valem saber

- **O contrato manda.** `src/types/api.ts` espelha `docs/CONTRACT.md` campo a campo,
  incluindo os `null` de lacuna em `history.points`. Nada de `any` no projeto.
- **Tempo real com rede de segurança.** O WebSocket é a fonte primária; se ele cair,
  a store passa a consultar `/api/readings/latest` a cada 10 s e o cabeçalho diz qual
  dos dois está em uso. Histórico, stats e alertas se atualizam a cada 60 s.
- **Limiares visíveis.** Os limites de 30 °C e 35 °C aparecem como linhas tracejadas
  no gráfico e como zonas coloridas na régua de cada indicador — mesma informação,
  duas leituras.
- **Estados explícitos.** Histórico vazio mostra "aguardando a primeira leitura do
  sensor"; API fora do ar mostra o motivo e um botão para tentar de novo. A tela
  nunca fica em branco.
- **Claro e escuro.** O tema segue `prefers-color-scheme`. O claro é o padrão por ser
  o que sobrevive a um projetor.
