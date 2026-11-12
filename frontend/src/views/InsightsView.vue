<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { PhTrendDown, PhTrendUp, PhWarning, PhWrench } from '@phosphor-icons/vue'
import HealthGauge from '@/components/HealthGauge.vue'
import LineChart, { type Series } from '@/components/LineChart.vue'
import StatusBadge from '@/components/StatusBadge.vue'
import { useThemeTokens } from '@/composables/useThemeTokens'
import { errorMessage, http } from '@/services/api'
import { useLiveStore } from '@/stores/live'
import { useSessionStore } from '@/stores/session'
import type { Device, HistoryPoint } from '@/types/api'
import { FAILURE_LABEL, fmt1, fmtInt, healthStatus } from '@/utils/format'

const live = useLiveStore()
const session = useSessionStore()
const tokens = useThemeTokens()

const equipment = computed(() => live.devices.filter((device) => device.kind === 'equipment' && device.enabled))
const version = computed(() => [...live.predictions.values()][0]?.model_version)

const history = ref<Record<string, HistoryPoint[]>>({})
const mode = ref<Record<string, string>>({})
const error = ref('')

const STATE_LABEL: Record<string, string> = {
  off: 'Equipamento desligado.',
  no_model: 'Nenhum modelo treinado. Gere dados e treine na seção Inteligência.',
  warming_up: 'Juntando leituras para a primeira previsão.',
}

async function loadHistory(): Promise<void> {
  const entries = await Promise.all(
    equipment.value.map(async (device) => {
      const { data } = await http.get<{ points: HistoryPoint[] }>(`/insights/${device.id}/history`, {
        params: { field: 'health', range: '15m' },
      })
      return [device.id, data.points] as const
    }),
  )
  history.value = Object.fromEntries(entries)
}

let timer: number | undefined
onMounted(() => {
  void loadHistory().catch(() => undefined)
  timer = window.setInterval(() => void loadHistory().catch(() => undefined), 5000)
})
onBeforeUnmount(() => window.clearInterval(timer))

function series(device: Device, health: number): Series[] {
  const points = (history.value[device.id] ?? []).map((point) => ({ x: Date.parse(point.time), y: point.value }))
  const status = healthStatus(health)
  const color = status === 'critical' ? tokens.value.crit : status === 'warning' ? tokens.value.warn : tokens.value.ok
  return [{ label: 'Saúde', color, points }]
}

function deviceAlerts(id: string) {
  return live.alerts.filter((alert) => alert.device_id === id && !alert.cleared_at)
}

async function simulator(action: 'inject_fault' | 'repair', device: Device): Promise<void> {
  const body = { action, target: device.id, mode: mode.value[device.id] ?? 'bearing_wear' }
  try {
    await http.post('/simulator/command', body)
    error.value = ''
  } catch (cause) {
    error.value = errorMessage(cause)
  }
}
</script>

<template>
  <div class="page">
    <header class="page-head">
      <div>
        <h1>Insights</h1>
        <p>Saúde e vida útil previstas pela IA a partir da telemetria ao vivo. As horas são simuladas.</p>
      </div>
      <span v-if="version" class="badge">modelo em uso: {{ version }}</span>
    </header>
    <p v-if="error" class="error" role="alert">{{ error }}</p>

    <section class="grid cards">
      <article
        v-for="device in equipment"
        :key="device.id"
        class="panel card"
        :data-status="live.status(device.id)"
      >
        <div class="panel-title">
          <div>
            <h2>{{ device.name }}</h2>
            <span class="eyebrow">{{ device.id }}</span>
          </div>
          <StatusBadge :status="live.status(device.id)" />
        </div>

        <template v-if="live.predictions.get(device.id)">
          <div class="summary">
            <HealthGauge :value="live.predictions.get(device.id)!.health" />
            <dl>
              <div>
                <dt class="eyebrow">Vida útil restante</dt>
                <dd class="mono">
                  {{ fmtInt(live.predictions.get(device.id)!.rul_h) }}<span class="unit">h</span>
                </dd>
              </div>
              <div>
                <dt class="eyebrow">Tendência por hora</dt>
                <dd class="mono trend" :class="{ down: live.predictions.get(device.id)!.trend_per_h < -0.5 }">
                  <PhTrendDown v-if="live.predictions.get(device.id)!.trend_per_h < 0" :size="20" />
                  <PhTrendUp v-else :size="20" />
                  {{ fmt1(live.predictions.get(device.id)!.trend_per_h) }}
                </dd>
              </div>
            </dl>
          </div>
          <LineChart
            :series="series(device, live.predictions.get(device.id)!.health)"
            :height="150"
            :min="0"
            :max="100"
          />
        </template>
        <p v-else class="empty">
          {{ STATE_LABEL[live.inferenceStates.get(device.id)?.state ?? 'no_model'] }}
        </p>

        <ul v-if="deviceAlerts(device.id).length" class="alerts">
          <li v-for="alert in deviceAlerts(device.id)" :key="alert.id" :data-status="alert.severity">
            <PhWarning :size="18" weight="fill" />
            <span>{{ alert.message }}</span>
          </li>
        </ul>
        <p v-else class="note quiet">Nenhum alerta ativo.</p>

        <div v-if="session.can('operator')" class="fault">
          <select v-model="mode[device.id]" class="input" aria-label="Modo de falha">
            <option :value="undefined" disabled>Escolha o modo de falha</option>
            <option v-for="(label, key) in FAILURE_LABEL" :key="key" :value="key">{{ label }}</option>
          </select>
          <button class="btn btn-danger" type="button" @click="simulator('inject_fault', device)">
            <PhWarning :size="16" /> Injetar falha
          </button>
          <button class="btn" type="button" @click="simulator('repair', device)">
            <PhWrench :size="16" /> Reparar
          </button>
        </div>
      </article>
    </section>
  </div>
</template>

<style scoped>
.cards {
  --min: 440px;
}

.card {
  padding: 20px 22px;
  border-top: 3px solid var(--status, var(--line));
  transition: border-color 0.3s;
}

.panel-title {
  align-items: flex-start;
}

.panel-title h2 {
  font-size: 18px;
}

.summary {
  display: flex;
  align-items: center;
  gap: 24px;
  margin-bottom: 14px;
}

dl {
  display: flex;
  flex-direction: column;
  gap: 14px;
  margin: 0;
}

dd {
  margin: 2px 0 0;
  font-size: 28px;
  font-weight: 500;
  line-height: 1.1;
}

.unit {
  margin-left: 4px;
  font-size: 14px;
  color: var(--ink-muted);
}

.trend {
  display: flex;
  align-items: center;
  gap: 8px;
}

.trend.down {
  color: var(--crit);
}

.alerts {
  list-style: none;
  margin: 14px 0 0;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: 8px;
  font-size: 14px;
}

.alerts li {
  display: flex;
  gap: 10px;
  align-items: flex-start;
  padding: 10px 12px;
  border-radius: var(--radius);
  background: var(--status-wash);
}

.alerts svg {
  flex: none;
  margin-top: 2px;
  color: var(--status);
}

.quiet {
  margin-top: 14px;
}

.fault {
  display: flex;
  gap: 8px;
  margin-top: 16px;
  padding-top: 16px;
  border-top: 1px solid var(--line);
  flex-wrap: wrap;
}

.fault select {
  flex: 1;
  min-width: 170px;
  width: auto;
}

@media (max-width: 520px) {
  .cards {
    --min: 100%;
  }

  .summary {
    flex-direction: column;
    align-items: flex-start;
  }
}
</style>
