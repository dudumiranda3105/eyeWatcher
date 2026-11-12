<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import StatusBadge from '@/components/StatusBadge.vue'
import { errorMessage, http } from '@/services/api'
import { useLiveStore } from '@/stores/live'
import { useSessionStore } from '@/stores/session'
import type { Device, DeviceKind, Rule } from '@/types/api'

const live = useLiveStore()
const session = useSessionStore()
const admin = computed(() => session.can('admin'))

const rules = ref<Rule[]>([])
const error = ref('')

const KIND_LABEL: Record<DeviceKind, string> = {
  sensor: 'Sensor',
  actuator: 'Atuador',
  equipment: 'Equipamento',
}

const SENSOR_TYPES = ['temperature', 'humidity', 'luminosity', 'power', 'presence']

const emptyDevice = () => ({
  id: '',
  name: '',
  kind: 'sensor' as DeviceKind,
  type: 'temperature',
  unit: '',
  normal_min: null as number | null,
  normal_max: null as number | null,
  critical_min: null as number | null,
  critical_max: null as number | null,
  controllable: false,
})
const deviceForm = ref(emptyDevice())

const emptyRule = () => ({
  name: '',
  device_id: 'temp-rack02',
  metric: 'temperature',
  threshold: 35,
  clear_threshold: 31,
  actuator_id: 'fan-exaustor',
  severity: 'warning' as const,
})
const ruleForm = ref(emptyRule())

const actuators = computed(() => live.devices.filter((device) => device.kind === 'actuator'))
const measuring = computed(() => live.devices.filter((device) => device.kind !== 'actuator'))

async function loadRules(): Promise<void> {
  rules.value = (await http.get<Rule[]>('/rules')).data
}
onMounted(loadRules)

async function run(action: () => Promise<unknown>): Promise<void> {
  try {
    await action()
    error.value = ''
  } catch (cause) {
    error.value = errorMessage(cause)
  }
}

function createDevice(): Promise<void> {
  return run(async () => {
    await http.post('/devices', { ...deviceForm.value, unit: deviceForm.value.unit || null })
    deviceForm.value = emptyDevice()
    await live.loadDevices()
  })
}

function toggleDevice(device: Device): Promise<void> {
  return run(async () => {
    await http.put(`/devices/${device.id}`, { ...device, enabled: !device.enabled })
    await live.loadDevices()
  })
}

function removeDevice(device: Device): Promise<void> {
  if (!window.confirm(`Excluir ${device.id}? As regras ligadas a ele também serão removidas.`)) {
    return Promise.resolve()
  }
  return run(async () => {
    await http.delete(`/devices/${device.id}`)
    await Promise.all([live.loadDevices(), loadRules()])
  })
}

function createRule(): Promise<void> {
  return run(async () => {
    await http.post('/rules', ruleForm.value)
    ruleForm.value = emptyRule()
    await loadRules()
  })
}

function removeRule(rule: Rule): Promise<void> {
  return run(async () => {
    await http.delete(`/rules/${rule.id}`)
    await loadRules()
  })
}
</script>

<template>
  <div class="page">
    <header class="page-head">
      <div>
        <h1>Dispositivos e regras</h1>
        <p>O cadastro fica no PostgreSQL. Um sensor novo passa a publicar sem reiniciar o simulador.</p>
      </div>
    </header>
    <p v-if="error" class="error">{{ error }}</p>

    <section class="panel panel-body">
      <div class="panel-title"><h2>Dispositivos</h2></div>
      <div class="table-wrap">
        <table class="data">
          <thead>
            <tr>
              <th>Id</th><th>Nome</th><th>Tipo</th><th>Faixa normal</th><th>Estado</th>
              <th v-if="admin">Ações</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="device in live.devices" :key="device.id">
              <td class="mono">{{ device.id }}</td>
              <td>{{ device.name }}</td>
              <td>{{ KIND_LABEL[device.kind] }} · {{ device.type }}</td>
              <td class="mono">
                <template v-if="device.normal_min !== null">
                  {{ device.normal_min }} a {{ device.normal_max }} {{ device.unit ?? '' }}
                </template>
                <template v-else>--</template>
              </td>
              <td><StatusBadge :status="live.status(device.id)" /></td>
              <td v-if="admin" class="row-actions">
                <button class="btn" type="button" @click="toggleDevice(device)">
                  {{ device.enabled ? 'Desativar' : 'Ativar' }}
                </button>
                <button class="btn btn-danger" type="button" @click="removeDevice(device)">Excluir</button>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </section>

    <form v-if="admin" class="panel panel-body" @submit.prevent="createDevice">
      <div class="panel-title"><h2>Novo dispositivo</h2></div>
      <div class="grid fields">
        <label class="field">Id<input v-model="deviceForm.id" placeholder="temp-rack03" required /></label>
        <label class="field">Nome<input v-model="deviceForm.name" required /></label>
        <label class="field">
          Categoria
          <select v-model="deviceForm.kind">
            <option v-for="(label, key) in KIND_LABEL" :key="key" :value="key">{{ label }}</option>
          </select>
        </label>
        <label class="field">
          Tipo
          <select v-if="deviceForm.kind === 'sensor'" v-model="deviceForm.type">
            <option v-for="item in SENSOR_TYPES" :key="item">{{ item }}</option>
          </select>
          <input v-else v-model="deviceForm.type" required />
        </label>
        <label class="field">Unidade<input v-model="deviceForm.unit" /></label>
        <label class="field">Normal mín.<input v-model.number="deviceForm.normal_min" type="number" step="any" /></label>
        <label class="field">Normal máx.<input v-model.number="deviceForm.normal_max" type="number" step="any" /></label>
        <label class="field">Crítico mín.<input v-model.number="deviceForm.critical_min" type="number" step="any" /></label>
        <label class="field">Crítico máx.<input v-model.number="deviceForm.critical_max" type="number" step="any" /></label>
      </div>
      <button class="btn btn-primary save" type="submit">Cadastrar</button>
    </form>

    <section class="panel panel-body">
      <div class="panel-title"><h2>Regras automáticas</h2></div>
      <div class="table-wrap">
        <table class="data">
          <thead>
            <tr>
              <th>Regra</th><th>Condição</th><th>Desliga em</th><th>Atuador</th>
              <th v-if="admin">Ações</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="rule in rules" :key="rule.id">
              <td>{{ rule.name }}</td>
              <td class="mono">{{ rule.device_id }}.{{ rule.metric }} ≥ {{ rule.threshold }}</td>
              <td class="mono">≤ {{ rule.clear_threshold }}</td>
              <td class="mono">{{ rule.actuator_id }}</td>
              <td v-if="admin">
                <button class="btn btn-danger" type="button" @click="removeRule(rule)">Excluir</button>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </section>

    <form v-if="admin" class="panel panel-body" @submit.prevent="createRule">
      <div class="panel-title"><h2>Nova regra</h2></div>
      <div class="grid fields">
        <label class="field">Nome<input v-model="ruleForm.name" required /></label>
        <label class="field">
          Dispositivo
          <select v-model="ruleForm.device_id">
            <option v-for="device in measuring" :key="device.id">{{ device.id }}</option>
          </select>
        </label>
        <label class="field">Métrica<input v-model="ruleForm.metric" required /></label>
        <label class="field">Liga em (≥)<input v-model.number="ruleForm.threshold" type="number" step="any" required /></label>
        <label class="field">Desliga em (≤)<input v-model.number="ruleForm.clear_threshold" type="number" step="any" required /></label>
        <label class="field">
          Atuador
          <select v-model="ruleForm.actuator_id">
            <option v-for="device in actuators" :key="device.id">{{ device.id }}</option>
          </select>
        </label>
      </div>
      <button class="btn btn-primary save" type="submit">Criar regra</button>
    </form>
  </div>
</template>

<style scoped>
.fields {
  --min: 170px;
}

.save {
  margin-top: 12px;
}

.row-actions {
  display: flex;
  gap: 6px;
}
</style>
