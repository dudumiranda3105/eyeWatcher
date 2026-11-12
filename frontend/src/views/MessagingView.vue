<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import StatusBadge from '@/components/StatusBadge.vue'
import { errorMessage, http } from '@/services/api'
import { useSessionStore } from '@/stores/session'
import type { DlqMessage, MessagingOverview } from '@/types/api'
import { fmt1, fmtClock, fmtInt } from '@/utils/format'

const session = useSessionStore()

const overview = ref<MessagingOverview>()
const dlq = ref<DlqMessage[]>([])
const error = ref('')

const QUEUE_ROLE: Record<string, string> = {
  'q.telemetry.influx': 'Gravação no InfluxDB',
  'q.telemetry.inference': 'Inferência da IA',
  'q.telemetry.rules': 'Regras de negócio',
  'q.live.ws': 'Entrega ao WebSocket',
  'q.commands.device': 'Comandos para o dispositivo',
  'q.jobs.datagen': 'Job de geração de dados',
  'q.jobs.training': 'Job de treino',
  'q.api.persist': 'Alertas e jobs no PostgreSQL',
  'q.inference.control': 'Troca de modelo em uso',
  'q.dlq': 'Mensagens mortas (DLQ)',
}

const deepest = computed(() => Math.max(1, ...(overview.value?.queues.map((queue) => queue.messages) ?? [])))

async function refresh(): Promise<void> {
  try {
    const [main, dead] = await Promise.all([
      http.get<MessagingOverview>('/messaging/overview'),
      http.get<DlqMessage[]>('/messaging/dlq'),
    ])
    overview.value = main.data
    dlq.value = dead.data
    error.value = ''
  } catch (cause) {
    error.value = errorMessage(cause)
  }
}

let timer: number | undefined
onMounted(() => {
  void refresh()
  timer = window.setInterval(() => void refresh(), 2000)
})
onBeforeUnmount(() => window.clearInterval(timer))

async function poison(): Promise<void> {
  try {
    await http.post('/messaging/poison')
  } catch (cause) {
    error.value = errorMessage(cause)
  }
}

function describeDeath(message: DlqMessage): string {
  const death = message.death?.[0]
  if (death) return `${death.queue}: ${death.reason}`
  return message.origin ? `gateway, tópico ${message.origin}` : 'desconhecida'
}
</script>

<template>
  <div class="page">
    <header class="page-head">
      <div>
        <h1>Mensageria</h1>
        <p>
          Estado ao vivo do RabbitMQ. Pare um consumidor com
          <code>docker compose stop recorder</code> e veja a fila crescer; ao subir de novo, ela esvazia.
        </p>
      </div>
      <div class="rates" v-if="overview">
        <div><span class="eyebrow">Publicação</span><strong class="mono">{{ fmt1(overview.publish_rate) }}/s</strong></div>
        <div><span class="eyebrow">Entrega</span><strong class="mono">{{ fmt1(overview.deliver_rate) }}/s</strong></div>
      </div>
    </header>
    <p v-if="error" class="error">{{ error }}</p>

    <section v-if="overview" class="panel panel-body">
      <div class="panel-title"><h2>Filas</h2></div>
      <div class="table-wrap">
        <table class="data">
          <thead>
            <tr><th>Fila</th><th>Papel</th><th>Mensagens</th><th>Consumidores</th><th>Publicação</th><th>Entrega</th></tr>
          </thead>
          <tbody>
            <tr v-for="queue in overview.queues" :key="queue.name">
              <td class="mono">{{ queue.name }}</td>
              <td>{{ QUEUE_ROLE[queue.name] ?? '' }}</td>
              <td class="depth">
                <span class="mono">{{ fmtInt(queue.messages) }}</span>
                <div class="progress"><span :style="{ width: `${(queue.messages / deepest) * 100}%` }" /></div>
              </td>
              <td>
                <StatusBadge
                  :status="queue.consumers > 0 ? 'ok' : queue.name === 'q.dlq' ? 'offline' : 'critical'"
                  :label="String(queue.consumers)"
                />
              </td>
              <td class="mono">{{ fmt1(queue.publish_rate) }}/s</td>
              <td class="mono">{{ fmt1(queue.deliver_rate) }}/s</td>
            </tr>
          </tbody>
        </table>
      </div>
    </section>

    <section class="grid lists">
      <article v-if="overview" class="panel panel-body">
        <div class="panel-title"><h2>Consumidores conectados</h2></div>
        <div class="table-wrap">
          <table class="data">
            <thead><tr><th>Serviço</th><th>Fila</th></tr></thead>
            <tbody>
              <tr v-for="item in overview.consumers" :key="item.tag">
                <td>{{ item.service }}</td>
                <td class="mono">{{ item.queue }}</td>
              </tr>
            </tbody>
          </table>
        </div>
      </article>

      <article class="panel panel-body">
        <div class="panel-title">
          <h2>DLQ: mensagens que falharam</h2>
          <button v-if="session.can('operator')" class="btn" type="button" @click="poison">
            Publicar mensagem inválida
          </button>
        </div>
        <ul v-if="dlq.length" class="messages">
          <li v-for="(message, index) in dlq" :key="index">
            <span class="note">Origem: {{ describeDeath(message) }}</span>
            <code class="mono">{{ message.payload }}</code>
          </li>
        </ul>
        <p v-else class="empty">Nenhuma mensagem morta.</p>
      </article>
    </section>

    <section v-if="overview" class="panel panel-body">
      <div class="panel-title"><h2>Últimas mensagens</h2></div>
      <div class="table-wrap">
        <table class="data">
          <thead><tr><th>Instante</th><th>Tipo</th><th>Routing key</th><th>Conteúdo</th></tr></thead>
          <tbody>
            <tr v-for="message in overview.recent" :key="message.id">
              <td class="mono">{{ fmtClock(message.ts) }}</td>
              <td>{{ message.type }}</td>
              <td class="mono">{{ message.routing_key }}</td>
              <td class="mono payload">{{ JSON.stringify(message.payload) }}</td>
            </tr>
          </tbody>
        </table>
      </div>
    </section>
  </div>
</template>

<style scoped>
.rates {
  display: flex;
  gap: 18px;
}

.rates > div {
  display: flex;
  flex-direction: column;
}

.rates strong {
  font-size: 20px;
}

.depth {
  min-width: 130px;
}

.lists {
  --min: 380px;
}

.messages {
  list-style: none;
  margin: 0;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: 10px;
  max-height: 280px;
  overflow-y: auto;
}

.messages li {
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.messages code {
  font-size: 12px;
  word-break: break-all;
}

.payload {
  font-size: 12px;
  max-width: 460px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

@media (max-width: 520px) {
  .lists {
    --min: 100%;
  }
}
</style>
