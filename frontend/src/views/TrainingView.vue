<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { Bar, Scatter } from 'vue-chartjs'
import {
  BarElement,
  CategoryScale,
  Chart as ChartJS,
  LinearScale,
  LineElement,
  PointElement,
  Tooltip,
  type ChartData,
  type ChartOptions,
} from 'chart.js'
import StatusBadge from '@/components/StatusBadge.vue'
import { useThemeTokens } from '@/composables/useThemeTokens'
import { errorMessage, http } from '@/services/api'
import { useLiveStore } from '@/stores/live'
import { useSessionStore } from '@/stores/session'
import type { Job, ModelReport, ModelVersion } from '@/types/api'
import { fmt2, fmtDateTime, fmtInt } from '@/utils/format'

ChartJS.register(BarElement, CategoryScale, LinearScale, LineElement, PointElement, Tooltip)

const live = useLiveStore()
const session = useSessionStore()
const tokens = useThemeTokens()

const versions = ref<ModelVersion[]>([])
const selectedVersion = ref<string>()
const job = ref<Job>()
const error = ref('')
const busy = ref(false)
const target = ref<'rul' | 'health'>('health')

const MODEL_LABEL: Record<string, string> = {
  rul: 'Vida útil restante (horas)',
  health: 'Índice de saúde (0 a 100)',
}

const current = computed(() => versions.value.find((item) => item.promoted))
const shown = computed(
  () => versions.value.find((item) => item.version === selectedVersion.value) ?? versions.value[0],
)
const report = computed<ModelReport | undefined>(() => shown.value?.summary.models[target.value])

async function load(): Promise<void> {
  const [models, jobs] = await Promise.all([
    http.get<ModelVersion[]>('/training/models'),
    http.get<Job[]>('/jobs', { params: { kind: 'training', limit: 1 } }),
  ])
  versions.value = models.data
  job.value = jobs.data[0]
}

onMounted(load)

watch(
  () => live.jobs,
  () => {
    if (!job.value) return
    const update = live.jobs.get(job.value.id)
    if (!update) return
    Object.assign(job.value, update)
    if (update.status === 'done') window.setTimeout(() => void load(), 800)
  },
)

async function train(): Promise<void> {
  busy.value = true
  error.value = ''
  try {
    await http.post('/training/jobs', {})
    await load()
  } catch (cause) {
    error.value = errorMessage(cause)
  } finally {
    busy.value = false
  }
}

const running = computed(() => job.value?.status === 'queued' || job.value?.status === 'running')

const scatterData = computed<ChartData<'scatter'>>(() => {
  const points = report.value?.scatter.map((item) => ({ x: item.real, y: item.predicted })) ?? []
  const top = Math.max(1, ...points.map((point) => Math.max(point.x, point.y)))
  return {
    datasets: [
      { label: 'Leituras de teste', data: points, backgroundColor: tokens.value.umid, pointRadius: 2.5 },
      {
        label: 'Previsão perfeita',
        data: [{ x: 0, y: 0 }, { x: top, y: top }],
        type: 'line' as never,
        borderColor: tokens.value.inkFaint,
        borderDash: [6, 4],
        pointRadius: 0,
      },
    ],
  }
})

const scatterOptions = computed<ChartOptions<'scatter'>>(() => ({
  responsive: true,
  maintainAspectRatio: false,
  animation: false,
  plugins: { legend: { display: false } },
  scales: {
    x: {
      title: { display: true, text: 'Real', color: tokens.value.inkMuted },
      grid: { color: tokens.value.line },
      ticks: { color: tokens.value.inkFaint },
    },
    y: {
      title: { display: true, text: 'Previsto', color: tokens.value.inkMuted },
      grid: { color: tokens.value.line },
      ticks: { color: tokens.value.inkFaint },
    },
  },
}))

const importanceData = computed<ChartData<'bar'>>(() => ({
  labels: report.value?.importance.map((item) => item.feature) ?? [],
  datasets: [
    {
      label: 'Importância',
      data: report.value?.importance.map((item) => item.value) ?? [],
      backgroundColor: tokens.value.temp,
    },
  ],
}))

const importanceOptions = computed<ChartOptions<'bar'>>(() => ({
  responsive: true,
  maintainAspectRatio: false,
  animation: false,
  indexAxis: 'y',
  plugins: { legend: { display: false } },
  scales: {
    x: { grid: { color: tokens.value.line }, ticks: { color: tokens.value.inkFaint } },
    y: { grid: { display: false }, ticks: { color: tokens.value.inkMuted, font: { size: 11 } } },
  },
}))
</script>

<template>
  <div class="page">
    <header class="page-head">
      <div>
        <h1>Treinamento</h1>
        <p>
          O treino usa o dataset mais recente, divide por equipamento e só coloca em uso o modelo que
          vence a base simples. A troca acontece sem reiniciar a inferência.
        </p>
      </div>
      <div class="head-actions">
        <span class="badge mono">em uso: {{ current?.version ?? 'nenhum' }}</span>
        <button class="btn btn-primary" type="button" :disabled="busy || running || !session.can('admin')" @click="train">
          Treinar modelos
        </button>
      </div>
    </header>
    <p v-if="error" class="error">{{ error }}</p>

    <section v-if="job && job.status !== 'done'" class="panel panel-body">
      <div class="panel-title">
        <h2>Treino em andamento</h2>
        <StatusBadge
          :status="job.status === 'failed' ? 'critical' : 'warning'"
          :label="job.status === 'failed' ? 'Falhou' : 'Treinando'"
        />
      </div>
      <div class="progress"><span :style="{ width: `${job.progress * 100}%` }" /></div>
      <p class="note">{{ job.stage }}</p>
    </section>

    <template v-if="shown && report">
      <section class="panel panel-body">
        <div class="panel-title">
          <div class="pick">
            <select v-model="selectedVersion" class="input" aria-label="Versão">
              <option :value="undefined" disabled>Versão</option>
              <option v-for="item in versions" :key="item.version" :value="item.version">
                {{ item.version }}, {{ fmtDateTime(item.trained_at) }}
              </option>
            </select>
            <select v-model="target" class="input" aria-label="Modelo">
              <option v-for="(label, key) in MODEL_LABEL" :key="key" :value="key">{{ label }}</option>
            </select>
          </div>
          <StatusBadge
            :status="report.beats_baseline ? 'ok' : 'critical'"
            :label="report.beats_baseline ? 'Vence a base simples' : 'Não vence a base simples'"
          />
        </div>

        <div class="table-wrap">
          <table class="data">
            <thead>
              <tr><th>Conjunto</th><th>MAE</th><th>RMSE</th><th>R²</th></tr>
            </thead>
            <tbody>
              <tr>
                <td><strong>Modelo, no teste</strong></td>
                <td class="mono">{{ fmt2(report.test.mae) }}</td>
                <td class="mono">{{ fmt2(report.test.rmse) }}</td>
                <td class="mono">{{ fmt2(report.test.r2) }}</td>
              </tr>
              <tr>
                <td>Base simples (sempre a média), no teste</td>
                <td class="mono">{{ fmt2(report.baseline.mae) }}</td>
                <td class="mono">{{ fmt2(report.baseline.rmse) }}</td>
                <td class="mono">{{ fmt2(report.baseline.r2) }}</td>
              </tr>
              <tr v-if="report.test_degrading && report.baseline_degrading">
                <td>Modelo, só máquinas degradando</td>
                <td class="mono">{{ fmt2(report.test_degrading.mae) }}</td>
                <td class="mono">{{ fmt2(report.test_degrading.rmse) }}</td>
                <td class="mono">{{ fmt2(report.test_degrading.r2) }}</td>
              </tr>
              <tr v-if="report.baseline_degrading">
                <td>Base simples, só máquinas degradando</td>
                <td class="mono">{{ fmt2(report.baseline_degrading.mae) }}</td>
                <td class="mono">{{ fmt2(report.baseline_degrading.rmse) }}</td>
                <td class="mono">{{ fmt2(report.baseline_degrading.r2) }}</td>
              </tr>
              <tr>
                <td>Modelo, na validação</td>
                <td class="mono">{{ fmt2(report.validation.mae) }}</td>
                <td class="mono">{{ fmt2(report.validation.rmse) }}</td>
                <td class="mono">{{ fmt2(report.validation.r2) }}</td>
              </tr>
            </tbody>
          </table>
        </div>
        <p class="note split-note">
          Divisão por equipamento: {{ shown.summary.equipment.train }} no treino,
          {{ shown.summary.equipment.validation }} na validação e {{ shown.summary.equipment.test }} no teste
          ({{ fmtInt(shown.summary.rows.train ?? 0) }} linhas de treino).
        </p>
      </section>

      <section class="grid charts">
        <article class="panel panel-body">
          <div class="panel-title"><h2>Previsto contra real</h2></div>
          <div class="chart"><Scatter :data="scatterData" :options="scatterOptions" /></div>
        </article>
        <article class="panel panel-body">
          <div class="panel-title"><h2>Importância dos atributos</h2></div>
          <div class="chart"><Bar :data="importanceData" :options="importanceOptions" /></div>
        </article>
      </section>
    </template>
    <p v-else class="panel empty">Nenhum modelo treinado. Gere dados no Laboratório e clique em Treinar modelos.</p>
  </div>
</template>

<style scoped>
.head-actions {
  display: flex;
  align-items: center;
  gap: 10px;
}

.pick {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
}

.pick select {
  width: auto;
}

.split-note {
  margin-top: 10px;
}

.charts {
  --min: 380px;
}

.chart {
  height: 320px;
}

@media (max-width: 520px) {
  .charts {
    --min: 100%;
  }
}
</style>
