<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted } from 'vue'
import AlertsTable from '@/components/AlertsTable.vue'
import MetricCard from '@/components/MetricCard.vue'
import RangeSelector from '@/components/RangeSelector.vue'
import StatsPanel from '@/components/StatsPanel.vue'
import StatusBanner from '@/components/StatusBanner.vue'
import TemperatureChart from '@/components/TemperatureChart.vue'
import { useRacksStore } from '@/stores/racks'
import type { RangeKey } from '@/types/api'
import { apiBaseUrl } from '@/services/api'
import { formatClock, formatDecimal, formatUptime, RANGE_LABEL } from '@/utils/format'
import { HUMIDITY_SCALE, TEMPERATURE_SCALE, THRESHOLDS } from '@/utils/thresholds'

const store = useRacksStore()

const CONNECTION_LABEL: Record<string, string> = {
  connecting: 'Conectando',
  open: 'Ao vivo',
  reconnecting: 'Reconectando',
  closed: 'Desconectado',
}

const connectionLabel = computed<string>(() => CONNECTION_LABEL[store.connection] ?? 'Desconectado')

const heatIndexNote = computed<string>(() => {
  const reading = store.current
  if (!reading) return 'Calculada no ESP32 a partir de temperatura e umidade.'
  const delta = reading.heat_index - reading.temperature
  if (Math.abs(delta) < 0.05) return 'Igual à temperatura do ar medida agora.'
  const direction = delta > 0 ? 'acima' : 'abaixo'
  return `${formatDecimal(Math.abs(delta))} °C ${direction} da temperatura do ar.`
})

/** Estado do corpo do gráfico: uma única fonte para os quatro cenários. */
const chartState = computed<'chart' | 'loading' | 'empty' | 'error'>(() => {
  if (store.hasHistory) return 'chart'
  if (store.initializing || store.loadingHistory) return 'loading'
  if (store.historyError || store.connectionError) return 'error'
  return 'empty'
})

function onRangeChange(range: RangeKey): void {
  void store.setRange(range)
}

function onRetry(): void {
  void store.retry()
}

onMounted(() => {
  void store.initialize()
})

onBeforeUnmount(() => {
  store.dispose()
})
</script>

<template>
  <div class="shell">
    <header class="masthead">
      <div class="masthead__id">
        <h1 class="masthead__name">eyeWatcher</h1>
        <p class="masthead__sub mono">
          {{ store.rackId }}
          <span aria-hidden="true">·</span>
          {{ store.location || 'localização não informada' }}
          <span aria-hidden="true">·</span>
          {{ store.deviceId || 'dispositivo não identificado' }}
        </p>
      </div>

      <div class="masthead__link" :data-live="store.connection === 'open'">
        <span class="masthead__pip" aria-hidden="true" />
        <span class="mono masthead__state">{{ connectionLabel }}</span>
        <span class="masthead__fallback mono">
          {{ store.usingFallback ? 'consultando a API a cada 10 s' : 'WebSocket /ws/live' }}
        </span>
      </div>
    </header>

    <StatusBanner
      :status="store.overallStatus"
      :online="store.isOnline"
      :stale="store.isStale"
      :last-reading-time="store.current?.time ?? null"
      :now="store.now"
      :temperature="store.current?.temperature ?? null"
      :humidity="store.current?.humidity ?? null"
      :api-down="store.connectionError !== null"
    />

    <div v-if="store.connectionError" class="notice" role="alert">
      <div class="notice__body">
        <p class="notice__title">A API não respondeu</p>
        <p class="notice__detail">{{ store.connectionError }}</p>
      </div>
      <button type="button" class="notice__action mono" @click="onRetry">Tentar novamente</button>
    </div>

    <main class="board">
      <div class="board__metrics">
        <MetricCard
          label="Temperatura do ar"
          :value="store.current?.temperature ?? null"
          unit="°C"
          :status="store.current ? store.temperatureStatusValue : null"
          :trend="store.temperatureTrend"
          :scale="TEMPERATURE_SCALE"
          primary
        />
        <MetricCard
          label="Umidade relativa"
          :value="store.current?.humidity ?? null"
          unit="%"
          :status="store.current ? store.humidityStatusValue : null"
          :trend="store.humidityTrend"
          :scale="HUMIDITY_SCALE"
        />
        <MetricCard
          label="Sensação térmica"
          :value="store.current?.heat_index ?? null"
          unit="°C"
          :trend="store.heatIndexTrend"
          :note="heatIndexNote"
        />
      </div>

      <section class="board__chart panel">
        <header class="chart__head">
          <div>
            <h2 class="chart__title">Histórico do rack</h2>
            <p class="chart__sub">
              Média por janela em {{ RANGE_LABEL[store.range] }}, com os limiares de
              {{ THRESHOLDS.TEMP_WARN }} °C e {{ THRESHOLDS.TEMP_CRIT }} °C marcados.
            </p>
          </div>
          <RangeSelector
            :model-value="store.range"
            :disabled="store.loadingHistory"
            @update:model-value="onRangeChange"
          />
        </header>

        <div class="chart__body">
          <TemperatureChart
            v-if="chartState === 'chart'"
            :points="store.chartPoints"
            :loading="store.loadingHistory"
          />

          <div v-else class="placeholder">
            <template v-if="chartState === 'loading'">
              <span class="placeholder__bar" aria-hidden="true" />
              <p class="placeholder__title">Carregando o histórico…</p>
              <p class="placeholder__detail">Consultando {{ apiBaseUrl }}/readings/history.</p>
            </template>

            <template v-else-if="chartState === 'error'">
              <p class="placeholder__title">Histórico indisponível</p>
              <p class="placeholder__detail">
                {{ store.historyError ?? store.connectionError }}
              </p>
              <button type="button" class="placeholder__action mono" @click="onRetry">
                Tentar novamente
              </button>
            </template>

            <template v-else>
              <p class="placeholder__title">Aguardando a primeira leitura do sensor</p>
              <p class="placeholder__detail">
                O gráfico começa a desenhar assim que o ESP32 publicar em
                <code>eyewatcher/{{ store.rackId }}/telemetry</code>. O painel publica a cada
                5 segundos.
              </p>
            </template>
          </div>
        </div>

        <footer class="chart__foot">
          <StatsPanel :stats="store.stats" :range="store.range" :loading="store.loadingHistory" />
        </footer>
      </section>
    </main>

    <AlertsTable
      :alerts="store.alerts"
      :count="store.alertsCount"
      :range="store.range"
      :loading="store.loadingHistory"
    />

    <footer class="colophon mono">
      <span>Fluxo ESP32 → MQTT → Python → InfluxDB → Vue 3</span>
      <span class="colophon__sep" aria-hidden="true">/</span>
      <span>uptime do dispositivo {{ formatUptime(store.uptimeSeconds) }}</span>
      <span class="colophon__sep" aria-hidden="true">/</span>
      <span>seq {{ store.lastSeq ?? '—' }}</span>
      <span class="colophon__sep" aria-hidden="true">/</span>
      <span>atualizado às {{ formatClock(store.current?.time ?? null) }}</span>
    </footer>
  </div>
</template>

<style scoped>
.shell {
  display: flex;
  flex-direction: column;
  gap: var(--gap);
  max-width: 1600px;
  margin: 0 auto;
  padding: 20px clamp(16px, 2.4vw, 32px) 28px;
}

/* ---------- cabeçalho ---------- */

.masthead {
  display: flex;
  align-items: flex-end;
  justify-content: space-between;
  gap: 16px;
  padding-bottom: 12px;
  border-bottom: 2px solid var(--ink);
}

.masthead__name {
  font-size: clamp(1.5rem, 2.6vw, 2.1rem);
  font-weight: 700;
  letter-spacing: -0.03em;
  line-height: 1;
}

.masthead__sub {
  margin: 6px 0 0;
  font-size: 10px;
  letter-spacing: 0.08em;
  color: var(--ink-muted);
  text-transform: uppercase;
}

.masthead__link {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 6px 12px;
  border: 1px solid var(--line-strong);
  border-radius: 999px;
  background: var(--panel);
  white-space: nowrap;
}

.masthead__pip {
  width: 7px;
  height: 7px;
  border-radius: 50%;
  background: var(--ink-faint);
}

.masthead__link[data-live='true'] .masthead__pip {
  background: var(--ok);
}

.masthead__state {
  font-size: 11px;
  font-weight: 700;
  letter-spacing: 0.06em;
  text-transform: uppercase;
}

.masthead__fallback {
  font-size: 10px;
  color: var(--ink-faint);
  border-left: 1px solid var(--line);
  padding-left: 8px;
}

/* ---------- aviso de erro ---------- */

.notice {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  padding: 12px 16px;
  background: var(--crit-wash);
  border: 1px solid var(--crit);
  border-radius: var(--radius-lg);
}

.notice__title {
  margin: 0;
  font-family: var(--font-display);
  font-weight: 700;
  color: var(--ink);
}

.notice__detail {
  margin: 2px 0 0;
  font-size: 13px;
  color: var(--ink-muted);
}

.notice__action,
.placeholder__action {
  flex: none;
  padding: 8px 14px;
  background: var(--ink);
  color: var(--panel);
  border: none;
  border-radius: var(--radius);
  font-size: 11px;
  font-weight: 700;
  letter-spacing: 0.06em;
  text-transform: uppercase;
  cursor: pointer;
}

.notice__action:hover,
.placeholder__action:hover {
  opacity: 0.88;
}

/* ---------- grade principal ---------- */

.board {
  display: grid;
  grid-template-columns: minmax(280px, 340px) minmax(0, 1fr);
  gap: var(--gap);
  align-items: start;
}

.board__metrics {
  display: flex;
  flex-direction: column;
  gap: var(--gap);
}

.board__chart {
  display: flex;
  flex-direction: column;
  padding: 16px 18px;
  min-height: 460px;
}

.chart__head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 16px;
  flex-wrap: wrap;
  padding-bottom: 12px;
  border-bottom: 1px solid var(--line);
}

.chart__title {
  font-size: 1rem;
  font-weight: 700;
}

.chart__sub {
  margin: 3px 0 0;
  font-size: 12px;
  color: var(--ink-muted);
  max-width: 52ch;
}

.chart__body {
  flex: 1 1 auto;
  min-height: 260px;
  padding: 10px 0 4px;
}

.chart__foot {
  border-top: 1px solid var(--line);
  padding-top: 12px;
}

/* ---------- estados vazio / carregando / erro ---------- */

.placeholder {
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  justify-content: center;
  gap: 6px;
  height: 100%;
  min-height: 240px;
  padding: 24px;
  border: 1px dashed var(--line-strong);
  border-radius: var(--radius);
  background: var(--panel-sunk);
}

.placeholder__title {
  margin: 0;
  font-family: var(--font-display);
  font-size: 1.05rem;
  font-weight: 600;
  color: var(--ink);
}

.placeholder__detail {
  margin: 0;
  max-width: 60ch;
  font-size: 13px;
  color: var(--ink-muted);
}

.placeholder__detail code {
  font-family: var(--font-mono);
  font-size: 11px;
  padding: 1px 5px;
  border-radius: 2px;
  background: var(--panel);
  border: 1px solid var(--line);
}

.placeholder__action {
  margin-top: 10px;
}

.placeholder__bar {
  width: 120px;
  height: 3px;
  border-radius: 2px;
  background: linear-gradient(90deg, var(--line) 0%, var(--ink-faint) 50%, var(--line) 100%);
  background-size: 200% 100%;
  animation: sweep 1.4s linear infinite;
}

@keyframes sweep {
  from {
    background-position: 200% 0;
  }
  to {
    background-position: -200% 0;
  }
}

/* ---------- rodapé ---------- */

.colophon {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  padding-top: 4px;
  font-size: 10px;
  letter-spacing: 0.05em;
  color: var(--ink-faint);
}

.colophon__sep {
  color: var(--line-strong);
}

/* ---------- responsivo ---------- */

@media (max-width: 1180px) {
  .board {
    grid-template-columns: 1fr;
  }

  .board__metrics {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(240px, 1fr));
  }
}

@media (max-width: 720px) {
  .masthead {
    flex-direction: column;
    align-items: flex-start;
    gap: 10px;
  }

  .notice {
    flex-direction: column;
    align-items: flex-start;
  }
}
</style>
