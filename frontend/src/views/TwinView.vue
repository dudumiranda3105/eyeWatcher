<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import LineChart, { type Series } from '@/components/LineChart.vue'
import StatusBadge from '@/components/StatusBadge.vue'
import { errorMessage, http } from '@/services/api'
import { useLiveStore } from '@/stores/live'
import { useSessionStore } from '@/stores/session'
import { createTwin, type Twin } from '@/three/twin'
import { fmt1, fmtClock, fmtInt, fmtMetric, healthStatus, METRIC_LABEL } from '@/utils/format'

const live = useLiveStore()
const session = useSessionStore()

const canvas = ref<HTMLCanvasElement>()
const selected = ref<string | null>(null)
const error = ref('')
let twin: Twin | undefined

function freshMetrics(id: string): Record<string, number> | undefined {
  const reading = live.readings.get(id)
  return reading && Date.now() - reading.at < 8000 ? reading.metrics : undefined
}

onMounted(() => {
  if (!canvas.value) return
  twin = createTwin(
    canvas.value,
    {
      devices: () => live.devices.filter((device) => device.enabled),
      status: (id) => live.status(id),
      metrics: freshMetrics,
      temperature: () => freshMetrics('temp-rack01')?.temperature,
    },
    (id) => (selected.value = id),
  )
})

onBeforeUnmount(() => twin?.dispose())
watch(selected, (id) => twin?.select(id))

const device = computed(() => (selected.value ? live.deviceById(selected.value) : undefined))
const reading = computed(() => (selected.value ? live.readings.get(selected.value) : undefined))
const prediction = computed(() => (selected.value ? live.predictions.get(selected.value) : undefined))

const series = computed<Series[]>(() => {
  void live.readings
  const metric = device.value?.metric
  if (!device.value || !metric) return []
  const points = live.ring(device.value.id, metric).map((point) => ({ x: point.t, y: point.v }))
  return [{ label: METRIC_LABEL[metric] ?? metric, points }]
})

const isOn = computed(() => {
  if (!device.value || !reading.value) return false
  return device.value.kind === 'equipment' ? reading.value.on : reading.value.metrics.on === 1
})

async function command(action: 'on' | 'off'): Promise<void> {
  if (!device.value) return
  try {
    await http.post(`/devices/${device.value.id}/command`, { action })
    error.value = ''
  } catch (cause) {
    error.value = errorMessage(cause)
  }
}

const LEGEND = [
  { status: 'ok', label: 'Normal' },
  { status: 'warning', label: 'Atenção' },
  { status: 'critical', label: 'Crítico' },
  { status: 'offline', label: 'Sem dados' },
] as const
</script>

<template>
  <div class="twin">
    <canvas ref="canvas" aria-label="Gêmeo digital 3D da sala de servidores" />

    <header class="overlay top panel">
      <strong>Gêmeo digital</strong>
      <div class="legend">
        <StatusBadge v-for="item in LEGEND" :key="item.status" :status="item.status" :label="item.label" />
      </div>
    </header>

    <div v-if="!live.anyLive" class="overlay nodata panel" role="status">
      <strong>Sem dados em tempo real</strong>
      <span class="muted">A cena está parada até voltarem as leituras do simulador.</span>
    </div>

    <aside v-if="device" class="overlay detail panel">
      <div class="panel-title">
        <div>
          <span class="eyebrow">{{ device.id }}</span>
          <h2>{{ device.name }}</h2>
        </div>
        <button class="btn" type="button" aria-label="Fechar painel" @click="selected = null">Fechar</button>
      </div>
      <StatusBadge :status="live.status(device.id)" />

      <dl v-if="reading && live.isFresh(device.id)" class="metrics">
        <div v-for="(value, metric) in reading.metrics" :key="metric">
          <dt class="eyebrow">{{ METRIC_LABEL[metric] ?? metric }}</dt>
          <dd class="mono">{{ fmtMetric(String(metric), value) }}</dd>
        </div>
      </dl>
      <p v-else class="note">Sem leitura recente deste item.</p>
      <p v-if="reading" class="note">Última leitura às {{ fmtClock(reading.at) }}</p>

      <LineChart v-if="series.length" :series="series" compact :height="70" />

      <div v-if="device.kind === 'equipment'" class="health">
        <template v-if="prediction">
          <div>
            <span class="eyebrow">Saúde prevista</span>
            <StatusBadge :status="healthStatus(prediction.health)" :label="`${fmt1(prediction.health)} / 100`" />
          </div>
          <div>
            <span class="eyebrow">Vida útil restante</span>
            <strong class="mono">{{ fmtInt(prediction.rul_h) }} h</strong>
          </div>
        </template>
        <p v-else class="note">Sem previsão da IA: treine um modelo na página Treinamento.</p>
      </div>

      <div v-if="device.controllable && session.can('operator')" class="actions">
        <button class="btn" type="button" :disabled="isOn" @click="command('on')">Ligar</button>
        <button class="btn" type="button" :disabled="!isOn" @click="command('off')">Desligar</button>
      </div>
      <p v-else-if="device.kind === 'actuator'" class="note">Estado: {{ isOn ? 'ligado' : 'desligado' }}</p>
      <p v-if="error" class="error">{{ error }}</p>
    </aside>
  </div>
</template>

<style scoped>
.twin {
  position: relative;
  height: 100vh;
  min-height: 520px;
  overflow: hidden;
  background: #050505;
}

canvas {
  display: block;
  width: 100%;
  height: 100%;
}

.overlay {
  position: absolute;
  z-index: 2;
}

.top {
  top: 12px;
  left: 12px;
  display: flex;
  align-items: center;
  gap: 14px;
  padding: 8px 12px;
  flex-wrap: wrap;
  max-width: calc(100% - 24px);
}

.legend {
  display: flex;
  gap: 6px;
  flex-wrap: wrap;
}

.nodata {
  top: 50%;
  left: 50%;
  transform: translate(-50%, -50%);
  display: flex;
  flex-direction: column;
  gap: 2px;
  padding: 14px 18px;
  text-align: center;
  border-color: var(--warn);
}

.detail {
  top: 12px;
  right: 12px;
  bottom: 12px;
  width: min(320px, calc(100% - 24px));
  overflow-y: auto;
  display: flex;
  flex-direction: column;
  gap: 10px;
  padding: 14px;
  align-items: stretch;
}

.detail .badge {
  align-self: flex-start;
}

.panel-title {
  margin-bottom: 0;
  flex-wrap: nowrap;
  align-items: flex-start;
}

.metrics {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 8px;
  margin: 0;
}

.metrics dd {
  margin: 0;
  font-size: 16px;
}

.health {
  display: flex;
  flex-direction: column;
  gap: 8px;
  padding-top: 10px;
  border-top: 1px solid var(--line);
}

.health > div {
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.actions {
  display: flex;
  gap: 8px;
}
</style>

<style>
/* Etiquetas da cena 3D: são criadas pelo three.js, fora do escopo do componente. */
.twin-labels {
  position: absolute;
  top: 0;
  left: 0;
  /* Contexto próprio: as etiquetas nunca passam por cima dos painéis. */
  z-index: 1;
  isolation: isolate;
  pointer-events: none;
}

.twin-label {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 3px 9px 3px 7px;
  border: 1px solid rgba(255, 255, 255, 0.16);
  border-radius: 999px;
  background: rgba(8, 8, 10, 0.72);
  backdrop-filter: blur(6px);
  color: #f2f3f5;
  font-family: var(--font-mono);
  font-size: 10px;
  letter-spacing: 0.04em;
  white-space: nowrap;
  cursor: pointer;
  pointer-events: auto;
  transition:
    border-color 0.15s,
    background-color 0.15s;
}

.twin-label:hover,
.twin-label[aria-pressed='true'] {
  border-color: #5aa8ff;
  background: rgba(8, 8, 10, 0.92);
}

.twin-label i {
  width: 7px;
  height: 7px;
  border-radius: 50%;
  background: #6b7280;
}

.twin-label[data-status='ok'] i {
  background: #2ed0ba;
}

.twin-label[data-status='warning'] i {
  background: #f6b53f;
}

.twin-label[data-status='critical'] i {
  background: #ff4a36;
}

.twin-label[data-status='warning'],
.twin-label[data-status='critical'] {
  border-color: currentColor;
}

.twin-label[data-status='warning'] {
  color: #f6b53f;
}

.twin-label[data-status='critical'] {
  color: #ff8a7a;
}
</style>
