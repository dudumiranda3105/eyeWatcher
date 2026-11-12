<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import StatusBadge from '@/components/StatusBadge.vue'
import { errorMessage, http } from '@/services/api'
import { useLiveStore } from '@/stores/live'
import { useSessionStore } from '@/stores/session'
import type { Job, LabOptions, Status } from '@/types/api'
import { FAILURE_LABEL, fmtDateTime, fmtInt } from '@/utils/format'

const live = useLiveStore()
const session = useSessionStore()

const options = ref<LabOptions>()
const jobs = ref<Job[]>([])
const error = ref('')
const busy = ref(false)

const form = ref({
  equipment_count: 150,
  temperature_sensors: 4,
  humidity_sensors: 2,
  luminosity_sensors: 1,
  power_sensors: 2,
  days: 60,
  failure_pct: 60,
  failure_modes: [] as string[],
  sensor_fault_pct: 10,
  noise: 1,
  missing_pct: 1,
  outlier_pct: 0.3,
  seed: 42,
})

const FIELDS = [
  { key: 'equipment_count', label: 'Equipamentos', step: 1 },
  { key: 'days', label: 'Período simulado (dias)', step: 1 },
  { key: 'temperature_sensors', label: 'Sensores de temperatura', step: 1 },
  { key: 'humidity_sensors', label: 'Sensores de umidade', step: 1 },
  { key: 'luminosity_sensors', label: 'Sensores de luminosidade', step: 1 },
  { key: 'power_sensors', label: 'Sensores de corrente', step: 1 },
  { key: 'failure_pct', label: 'Equipamentos que falham (%)', step: 1 },
  { key: 'sensor_fault_pct', label: 'Sensores com defeito (%)', step: 1 },
  { key: 'noise', label: 'Nível de ruído', step: 0.1 },
  { key: 'missing_pct', label: 'Leituras faltantes (%)', step: 0.1 },
  { key: 'outlier_pct', label: 'Valores absurdos (%)', step: 0.1 },
  { key: 'seed', label: 'Semente aleatória', step: 1 },
] as const

const estimate = computed(() => {
  const value = form.value
  const steps = value.days * 144
  const sensors =
    value.temperature_sensors + value.humidity_sensors + value.luminosity_sensors + value.power_sensors
  return value.equipment_count * steps * 4 + sensors * steps
})

const volumeOk = computed(() => {
  const limits = options.value
  return !limits || (estimate.value >= limits.min_readings && estimate.value <= limits.max_readings)
})

async function loadJobs(): Promise<void> {
  jobs.value = (await http.get<Job[]>('/jobs', { params: { kind: 'datagen' } })).data
}

onMounted(async () => {
  options.value = (await http.get<LabOptions>('/lab/options')).data
  form.value.failure_modes = [...options.value.failure_modes]
  await loadJobs()
})

// O progresso chega pelo WebSocket; a lista se atualiza quando um job termina.
watch(
  () => live.jobs,
  () => {
    for (const job of jobs.value) {
      const update = live.jobs.get(job.id)
      if (update) Object.assign(job, update)
      if (update?.status === 'done' && !job.result) void loadJobs()
    }
  },
)

async function submit(): Promise<void> {
  busy.value = true
  error.value = ''
  try {
    await http.post('/lab/jobs', form.value)
    await loadJobs()
  } catch (cause) {
    error.value = errorMessage(cause)
  } finally {
    busy.value = false
  }
}

const JOB_STATUS: Record<Job['status'], { status: Status; label: string }> = {
  queued: { status: 'offline', label: 'Na fila' },
  running: { status: 'warning', label: 'Gerando' },
  done: { status: 'ok', label: 'Concluído' },
  failed: { status: 'critical', label: 'Falhou' },
}

function readings(job: Job): string {
  const value = job.result?.readings
  return typeof value === 'number' ? fmtInt(value) : '--'
}
</script>

<template>
  <div class="page">
    <header class="page-head">
      <div>
        <h1>Laboratório de dados</h1>
        <p>
          Simula a vida inteira de muitas máquinas para treinar a IA. Os dados ficam separados das
          leituras ao vivo, e a geração roda em segundo plano por fila do RabbitMQ.
        </p>
      </div>
    </header>

    <form class="panel panel-body" @submit.prevent="submit">
      <div class="grid fields">
        <label v-for="field in FIELDS" :key="field.key" class="field">
          {{ field.label }}
          <input v-model.number="form[field.key]" type="number" min="0" :step="field.step" required />
        </label>
      </div>

      <fieldset class="modes">
        <legend class="eyebrow">Modos de falha</legend>
        <label v-for="mode in options?.failure_modes ?? []" :key="mode">
          <input v-model="form.failure_modes" type="checkbox" :value="mode" />
          {{ FAILURE_LABEL[mode] ?? mode }}
        </label>
      </fieldset>

      <div class="submit">
        <div>
          <span class="eyebrow">Volume estimado</span>
          <strong class="mono">{{ fmtInt(estimate) }} leituras</strong>
          <p v-if="!volumeOk && options" class="error">
            O volume precisa ficar entre {{ fmtInt(options.min_readings) }} e {{ fmtInt(options.max_readings) }}.
          </p>
        </div>
        <button
          class="btn btn-primary"
          type="submit"
          :disabled="busy || !volumeOk || !session.can('admin')"
        >
          Gerar dados
        </button>
      </div>
      <p v-if="!session.can('admin')" class="note">Só o administrador pode gerar dados.</p>
      <p v-if="error" class="error">{{ error }}</p>
    </form>

    <section class="panel panel-body">
      <div class="panel-title"><h2>Gerações</h2></div>
      <div v-if="jobs.length" class="table-wrap">
        <table class="data">
          <thead>
            <tr><th>Quando</th><th>Situação</th><th>Progresso</th><th>Leituras</th><th>Por</th></tr>
          </thead>
          <tbody>
            <tr v-for="job in jobs" :key="job.id">
              <td class="mono">{{ fmtDateTime(job.created_at) }}</td>
              <td><StatusBadge v-bind="JOB_STATUS[job.status]" /></td>
              <td class="progress-cell">
                <div class="progress"><span :style="{ width: `${job.progress * 100}%` }" /></div>
                <span class="note">{{ job.stage }}</span>
              </td>
              <td class="mono">{{ readings(job) }}</td>
              <td>{{ job.created_by }}</td>
            </tr>
          </tbody>
        </table>
      </div>
      <p v-else class="empty">Nenhum dado gerado ainda.</p>
    </section>
  </div>
</template>

<style scoped>
.fields {
  --min: 190px;
}

.modes {
  border: 1px solid var(--line);
  border-radius: var(--radius);
  margin: 14px 0;
  padding: 10px 12px;
  display: flex;
  gap: 16px;
  flex-wrap: wrap;
  font-size: 14px;
}

.modes label {
  display: flex;
  gap: 6px;
  align-items: center;
}

.submit {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 12px;
  flex-wrap: wrap;
}

.submit > div {
  display: flex;
  flex-direction: column;
}

.progress-cell {
  min-width: 200px;
}
</style>
