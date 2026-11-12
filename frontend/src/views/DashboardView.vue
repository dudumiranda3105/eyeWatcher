<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { PhMoon, PhPause, PhPlay, PhSun } from '@phosphor-icons/vue'
import LineChart, { type Series } from '@/components/LineChart.vue'
import StatusBadge from '@/components/StatusBadge.vue'
import { useThemeTokens } from '@/composables/useThemeTokens'
import { errorMessage, http } from '@/services/api'
import { useLiveStore } from '@/stores/live'
import { useSessionStore } from '@/stores/session'
import type { Device, HistoryPoint, RangeKey, Status } from '@/types/api'
import {
  fmt1,
  fmtDateTime,
  fmtInt,
  fmtMetric,
  fmtSimHour,
  healthStatus,
  METRIC_LABEL,
} from '@/utils/format'

const live = useLiveStore()
const session = useSessionStore()
const tokens = useThemeTokens()

const RANGES: RangeKey[] = ['15m', '1h', '6h', '24h', '7d', '30d']

const sensors = computed(() =>
  live.devices.filter((device) => device.kind !== 'actuator' && device.enabled),
)
const controls = computed(() =>
  live.devices.filter((device) => device.kind !== 'sensor' && device.enabled),
)

const selectedDevice = ref('temp-rack01')
const selectedMetric = ref('temperature')
const range = ref<RangeKey>('15m')
const history = ref<HistoryPoint[]>([])
const stats = ref<{ min: number | null; max: number | null; mean: number | null; count: number | null }>()
const error = ref('')

const metricsOfDevice = computed(() => {
  const reading = live.readings.get(selectedDevice.value)
  if (reading) return Object.keys(reading.metrics)
  const device = live.deviceById(selectedDevice.value)
  return device?.metric ? [device.metric] : []
})

watch(metricsOfDevice, (metrics) => {
  const first = metrics[0]
  if (first && !metrics.includes(selectedMetric.value)) selectedMetric.value = first
})

async function loadHistory(): Promise<void> {
  const params = { device: selectedDevice.value, metric: selectedMetric.value, range: range.value }
  try {
    const [points, summary] = await Promise.all([
      http.get<{ points: HistoryPoint[] }>('/readings/history', { params }),
      http.get('/readings/stats', { params }),
    ])
    history.value = points.data.points
    stats.value = summary.data
    error.value = ''
  } catch (cause) {
    error.value = errorMessage(cause)
  }
}

watch([selectedDevice, selectedMetric, range], () => void loadHistory())

let timer: number | undefined
onMounted(() => {
  void loadHistory()
  timer = window.setInterval(() => void loadHistory(), 10000)
})
onBeforeUnmount(() => window.clearInterval(timer))

const historySeries = computed<Series[]>(() => {
  // O histórico vem do InfluxDB; as leituras mais novas chegam pelo WebSocket.
  const stored = history.value.map((point) => ({ x: Date.parse(point.time), y: point.value }))
  const lastStored = stored.at(-1)?.x ?? 0
  void live.readings
  const fresh = live
    .ring(selectedDevice.value, selectedMetric.value)
    .filter((point) => point.t > lastStored)
    .map((point) => ({ x: point.t, y: point.v }))
  return [{ label: METRIC_LABEL[selectedMetric.value] ?? selectedMetric.value, points: [...stored, ...fresh] }]
})

function primary(device: Device): string {
  const reading = live.readings.get(device.id)
  if (!reading || !device.metric || !live.isFresh(device.id)) return '--'
  const value = reading.metrics[device.metric]
  return value === undefined ? '--' : fmtMetric(device.metric, value)
}

function spark(device: Device): Series[] {
  void live.readings
  const points = live.ring(device.id, device.metric ?? '').map((p) => ({ x: p.t, y: p.v }))
  return [{ label: device.name, color: statusColor(live.status(device.id)), points }]
}

function isOn(device: Device): boolean {
  const reading = live.readings.get(device.id)
  if (!reading) return false
  return device.kind === 'equipment' ? reading.on : reading.metrics.on === 1
}

const commandError = ref('')

async function command(device: Device, action: 'on' | 'off'): Promise<void> {
  try {
    await http.post(`/devices/${device.id}/command`, { action })
    commandError.value = ''
  } catch (cause) {
    commandError.value = errorMessage(cause)
  }
}

async function simulator(action: 'pause' | 'resume'): Promise<void> {
  try {
    await http.post('/simulator/command', { action })
  } catch (cause) {
    commandError.value = errorMessage(cause)
  }
}

function statusColor(status: Status): string {
  if (status === 'critical') return tokens.value.crit
  if (status === 'warning') return tokens.value.warn
  return status === 'ok' ? tokens.value.accent : tokens.value.inkFaint
}

/** Separa o número da unidade, para a unidade aparecer menor no card. */
function parts(device: Device): { value: string; unit: string } {
  const [value = '--', unit = ''] = primary(device).split(' ')
  return { value, unit }
}

const clock = computed(() => {
  const first = [...live.readings.values()][0]
  if (!first || !live.anyLive) return { text: '--:--', day: true }
  return { text: fmtSimHour(first.simHour), day: first.simHour >= 6 && first.simHour < 18 }
})

const room = computed(() => {
  const device = live.deviceById('temp-rack01')
  const [value = '--', unit = ''] = (device ? primary(device) : '--').split(' ')
  return { value, unit, status: live.status('temp-rack01') }
})

const worst = computed<{ text: string; device: string; status: Status }>(() => {
  let lowest: { id: string; health: number } | undefined
  for (const [id, prediction] of live.predictions) {
    if (!lowest || prediction.health < lowest.health) lowest = { id, health: prediction.health }
  }
  if (!lowest) return { text: '--', device: 'sem previsão ainda', status: 'offline' }
  return { text: fmtInt(lowest.health), device: lowest.id, status: healthStatus(lowest.health) }
})

const openAlerts = computed<{ count: number; status: Status }>(() => {
  const open = live.alerts.filter((alert) => !alert.cleared_at)
  const critical = open.some((alert) => alert.severity === 'critical')
  return { count: open.length, status: critical ? 'critical' : open.length ? 'warning' : 'ok' }
})

const recentAlerts = computed(() => live.alerts.slice(0, 8))
</script>

<template>
  <div class="page">
    <header class="page-head">
      <div>
        <h1>Dashboard</h1>
        <p>Cada leitura representa 10 minutos da sala: um dia inteiro passa em cerca de 5 minutos.</p>
      </div>
      <div v-if="session.can('operator')" class="sim">
        <button class="btn" type="button" @click="simulator('pause')">
          <PhPause :size="16" weight="fill" /> Parar simulador
        </button>
        <button class="btn" type="button" @click="simulator('resume')">
          <PhPlay :size="16" weight="fill" /> Retomar
        </button>
      </div>
    </header>

    <section class="panel overview">
      <div :data-status="room.status">
        <span class="eyebrow">Temperatura da sala</span>
        <strong class="mono">{{ room.value }}<span class="unit">{{ room.unit }}</span></strong>
      </div>
      <div :data-status="worst.status">
        <span class="eyebrow">Pior saúde prevista</span>
        <strong class="mono">{{ worst.text }}</strong>
        <span class="hint">{{ worst.device }}</span>
      </div>
      <div :data-status="openAlerts.status">
        <span class="eyebrow">Alertas abertos</span>
        <strong class="mono">{{ openAlerts.count }}</strong>
      </div>
      <div>
        <span class="eyebrow">Hora simulada</span>
        <strong class="mono clock">
          <PhSun v-if="clock.day" :size="22" />
          <PhMoon v-else :size="22" />
          {{ clock.text }}
        </strong>
      </div>
    </section>

    <section class="grid tiles">
      <article v-for="device in sensors" :key="device.id" class="panel tile" :data-status="live.status(device.id)">
        <div class="tile-head">
          <span class="name">{{ device.name }}</span>
          <StatusBadge :status="live.status(device.id)" />
        </div>
        <p class="reading mono">
          <strong>{{ parts(device).value }}</strong>
          <span class="unit">{{ parts(device).unit }}</span>
        </p>
        <LineChart :series="spark(device)" compact :height="42" />
        <span class="eyebrow">{{ device.id }}</span>
      </article>
    </section>

    <section class="split">
      <article class="panel panel-body">
        <div class="panel-title">
          <h2>Histórico das leituras</h2>
          <div class="filters">
            <select v-model="selectedDevice" class="input" aria-label="Dispositivo">
              <option v-for="device in sensors" :key="device.id" :value="device.id">{{ device.name }}</option>
            </select>
            <select v-model="selectedMetric" class="input" aria-label="Métrica">
              <option v-for="metric in metricsOfDevice" :key="metric" :value="metric">
                {{ METRIC_LABEL[metric] ?? metric }}
              </option>
            </select>
            <div class="ranges" role="group" aria-label="Período">
              <button
                v-for="item in RANGES"
                :key="item"
                type="button"
                class="mono"
                :aria-pressed="range === item"
                @click="range = item"
              >
                {{ item }}
              </button>
            </div>
          </div>
        </div>
        <p v-if="error" class="error" role="alert">{{ error }}</p>
        <LineChart :series="historySeries" :height="280" />
        <dl v-if="stats" class="stats">
          <div><dt class="eyebrow">Mínima</dt><dd class="mono">{{ stats.min === null ? '--' : fmt1(stats.min) }}</dd></div>
          <div><dt class="eyebrow">Média</dt><dd class="mono">{{ stats.mean === null ? '--' : fmt1(stats.mean) }}</dd></div>
          <div><dt class="eyebrow">Máxima</dt><dd class="mono">{{ stats.max === null ? '--' : fmt1(stats.max) }}</dd></div>
          <div><dt class="eyebrow">Leituras</dt><dd class="mono">{{ stats.count === null ? '--' : fmtInt(stats.count) }}</dd></div>
        </dl>
      </article>

      <article class="panel panel-body">
        <div class="panel-title"><h2>Atuadores</h2></div>
        <ul class="controls">
          <li v-for="device in controls" :key="device.id">
            <div class="about">
              <strong>{{ device.name }}</strong>
              <span class="hint">{{ device.controllable ? 'Controle pela Web' : 'Acionado por regra' }}</span>
            </div>
            <StatusBadge
              :status="live.isFresh(device.id) && isOn(device) ? 'ok' : 'offline'"
              :label="!live.isFresh(device.id) ? 'Sem dados' : isOn(device) ? 'Ligado' : 'Desligado'"
            />
            <button
              v-if="device.controllable && session.can('operator')"
              class="switch"
              type="button"
              role="switch"
              :aria-checked="isOn(device)"
              :aria-label="`Ligar ou desligar ${device.name}`"
              :disabled="!live.isFresh(device.id)"
              @click="command(device, isOn(device) ? 'off' : 'on')"
            />
          </li>
        </ul>
        <p v-if="commandError" class="error" role="alert">{{ commandError }}</p>
      </article>
    </section>

    <section class="panel panel-body">
      <div class="panel-title"><h2>Alertas recentes</h2></div>
      <div v-if="recentAlerts.length" class="table-wrap">
        <table class="data">
          <thead>
            <tr><th>Quando</th><th>Dispositivo</th><th>Severidade</th><th>Mensagem</th><th>Situação</th></tr>
          </thead>
          <tbody>
            <tr v-for="alert in recentAlerts" :key="alert.id" :class="{ closed: alert.cleared_at }">
              <td class="mono">{{ fmtDateTime(alert.opened_at) }}</td>
              <td class="mono">{{ alert.device_id }}</td>
              <td><StatusBadge :status="alert.severity" /></td>
              <td>{{ alert.message }}</td>
              <td>{{ alert.cleared_at ? 'Encerrado' : 'Aberto' }}</td>
            </tr>
          </tbody>
        </table>
      </div>
      <p v-else class="empty">Nenhum alerta registrado.</p>
    </section>
  </div>
</template>

<style scoped>
.sim {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
}

/* Resumo da sala: quatro números numa faixa só, separados por fios. */
.overview {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
}

.overview > div {
  display: flex;
  flex-direction: column;
  gap: 4px;
  padding: 18px 22px;
  border-left: 1px solid var(--line);
}

.overview > div:first-child {
  border-left: 0;
}

.overview strong {
  white-space: nowrap;
  font-size: 34px;
  font-weight: 500;
  line-height: 1.1;
  color: var(--status, var(--ink));
  transition: color 0.3s;
}

.overview [data-status='ok'] strong {
  color: var(--ink);
}

.clock {
  display: flex;
  align-items: center;
  gap: 10px;
}

.clock svg {
  flex: none;
  color: var(--ink-muted);
}

.overview .unit {
  margin-left: 6px;
  font-size: 16px;
}

.hint {
  font-size: 12px;
  color: var(--ink-muted);
}

.tiles {
  --min: 215px;
}

.tile {
  position: relative;
  display: flex;
  flex-direction: column;
  gap: 6px;
  padding: 14px 16px 12px;
  overflow: hidden;
}

/* Fio lateral: só aparece quando o sensor sai do normal. */
.tile::before {
  content: '';
  position: absolute;
  inset: 0 auto 0 0;
  width: 3px;
  background: var(--status);
  opacity: 0;
  transition: opacity 0.3s;
}

.tile[data-status='warning']::before,
.tile[data-status='critical']::before {
  opacity: 1;
}

.tile-head {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  gap: 8px;
}

.name {
  font-size: 13px;
  font-weight: 500;
  line-height: 1.3;
  color: var(--ink-muted);
}

.reading {
  display: flex;
  align-items: baseline;
  gap: 6px;
  margin: 0;
}

.reading strong {
  font-size: 30px;
  font-weight: 500;
  line-height: 1.1;
}

.unit {
  font-size: 13px;
  color: var(--ink-muted);
}

.split {
  display: grid;
  gap: var(--gap);
  grid-template-columns: minmax(0, 2fr) minmax(300px, 1fr);
}

.filters {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
}

.filters select {
  width: auto;
}

.ranges {
  display: flex;
  padding: 3px;
  gap: 2px;
  background: var(--panel-sunk);
  border: 1px solid var(--line);
  border-radius: var(--radius);
}

.ranges button {
  border: 0;
  background: transparent;
  padding: 4px 9px;
  border-radius: 5px;
  font-size: 11px;
  color: var(--ink-muted);
  cursor: pointer;
  transition:
    background-color 0.15s,
    color 0.15s;
}

.ranges button:hover {
  color: var(--ink);
}

.ranges button[aria-pressed='true'] {
  background: var(--panel);
  color: var(--accent);
  box-shadow: 0 1px 2px rgba(15, 33, 42, 0.14);
}

.stats {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 8px;
  margin: 16px 0 0;
  padding-top: 14px;
  border-top: 1px solid var(--line);
}

.stats dd {
  margin: 2px 0 0;
  font-size: 18px;
}

.controls {
  list-style: none;
  margin: 0;
  padding: 0;
  display: flex;
  flex-direction: column;
}

.controls li {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 12px 0;
  border-bottom: 1px solid var(--line);
}

.controls li:first-child {
  padding-top: 0;
}

.controls li:last-child {
  border-bottom: 0;
  padding-bottom: 0;
}

.about {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
  line-height: 1.3;
}

.about strong {
  font-size: 14px;
  font-weight: 600;
}

.switch {
  position: relative;
  flex: none;
  width: 42px;
  height: 24px;
  border-radius: 999px;
  border: 1px solid var(--line-strong);
  background: var(--panel-sunk);
  cursor: pointer;
  transition:
    background-color 0.2s,
    border-color 0.2s;
}

.switch::after {
  content: '';
  position: absolute;
  top: 2px;
  left: 2px;
  width: 18px;
  height: 18px;
  border-radius: 50%;
  background: var(--ink-faint);
  transition:
    transform 0.25s var(--ease),
    background-color 0.2s;
}

.switch[aria-checked='true'] {
  background: var(--accent);
  border-color: var(--accent);
}

.switch[aria-checked='true']::after {
  transform: translateX(18px);
  background: var(--accent-ink);
}

.switch:disabled {
  opacity: 0.45;
  cursor: not-allowed;
}

tr.closed td {
  color: var(--ink-muted);
}

@media (max-width: 1000px) {
  .split {
    grid-template-columns: minmax(0, 1fr);
  }
}

@media (max-width: 760px) {
  .overview {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }

  .overview > div:nth-child(3) {
    border-left: 0;
  }

  .overview > div:nth-child(n + 3) {
    border-top: 1px solid var(--line);
  }

  .overview strong {
    font-size: 26px;
  }
}
</style>
