<script setup lang="ts">
import { nextTick, onBeforeUnmount, onMounted, ref } from 'vue'
import MarkdownIt from 'markdown-it'
import StatusBadge from '@/components/StatusBadge.vue'
import { http, readToken } from '@/services/api'
import type { Status } from '@/types/api'

interface Message {
  role: 'user' | 'assistant'
  content: string
}

// A saída do LLM é texto não confiável: sem HTML cru e sem imagens remotas.
const markdown = new MarkdownIt({ html: false, linkify: false }).disable(['image'])

const STATUS: Record<string, { status: Status; label: string }> = {
  ready: { status: 'ok', label: 'Modelo pronto' },
  loading: { status: 'warning', label: 'Carregando o modelo' },
  downloading: { status: 'warning', label: 'Baixando o modelo' },
  offline: { status: 'critical', label: 'LLM indisponível' },
}

const SUGGESTIONS = [
  'Qual equipamento está com a pior saúde?',
  'O que significa o alerta aberto e o que devo fazer?',
  'Explique as métricas do último treino em palavras simples.',
  'Como os dados fluem pela arquitetura?',
]

const messages = ref<Message[]>([])
const question = ref('')
const busy = ref(false)
const error = ref('')
const modelStatus = ref('offline')
const modelName = ref('')
const log = ref<HTMLElement>()

async function refreshStatus(): Promise<void> {
  try {
    const { data } = await http.get<{ status: string; model: string }>('/assistant/status')
    modelStatus.value = data.status
    modelName.value = data.model
  } catch {
    modelStatus.value = 'offline'
  }
}

let timer: number | undefined
onMounted(() => {
  void refreshStatus()
  timer = window.setInterval(() => void refreshStatus(), 4000)
})
onBeforeUnmount(() => window.clearInterval(timer))

async function scrollDown(): Promise<void> {
  await nextTick()
  log.value?.scrollTo({ top: log.value.scrollHeight })
}

async function ask(text: string): Promise<void> {
  const content = text.trim()
  if (!content || busy.value) return
  const history = messages.value.slice(-6)
  messages.value.push({ role: 'user', content })
  const answer = ref<Message>({ role: 'assistant', content: '' })
  messages.value.push(answer.value)
  const index = messages.value.length - 1
  question.value = ''
  busy.value = true
  error.value = ''
  await scrollDown()

  try {
    // fetch em vez de axios: precisamos ler a resposta enquanto ela chega.
    const response = await fetch('/api/assistant/chat', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${readToken() ?? ''}` },
      body: JSON.stringify({ question: content, history }),
    })
    if (!response.ok || !response.body) {
      const body = (await response.json().catch(() => ({}))) as { detail?: string }
      throw new Error(body.detail ?? 'o assistente não respondeu')
    }
    const reader = response.body.pipeThrough(new TextDecoderStream()).getReader()
    for (;;) {
      const { done, value } = await reader.read()
      if (done) break
      const target = messages.value[index]
      if (target) target.content += value
      await scrollDown()
    }
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : 'erro inesperado'
    messages.value.splice(index, 1)
  } finally {
    busy.value = false
  }
}
</script>

<template>
  <div class="page chat-page">
    <header class="page-head">
      <div>
        <h1>Assistente</h1>
        <p>LLM rodando no próprio Docker Compose: nenhum dado sai da máquina.</p>
      </div>
      <div class="status">
        <StatusBadge v-bind="STATUS[modelStatus] ?? STATUS.offline!" />
        <span class="mono muted">{{ modelName }}</span>
      </div>
    </header>

    <section ref="log" class="panel log" aria-live="polite">
      <div v-if="!messages.length" class="start">
        <p class="muted">Pergunte sobre o estado da sala, as previsões da IA, os modelos ou a arquitetura.</p>
        <button v-for="item in SUGGESTIONS" :key="item" class="btn" type="button" @click="ask(item)">
          {{ item }}
        </button>
      </div>
      <article v-for="(message, index) in messages" :key="index" class="message" :class="message.role">
        <span class="eyebrow">{{ message.role === 'user' ? 'Você' : 'Assistente' }}</span>
        <!-- eslint-disable-next-line vue/no-v-html -- markdown-it com html:false escapa todo HTML -->
        <div v-if="message.role === 'assistant' && message.content" class="md" v-html="markdown.render(message.content)" />
        <p v-else-if="message.role === 'assistant'" class="muted">
          {{ modelStatus === 'ready' ? 'Pensando…' : 'Carregando o modelo…' }}
        </p>
        <p v-else>{{ message.content }}</p>
      </article>
    </section>

    <p v-if="error" class="error">{{ error }}</p>
    <form class="ask" @submit.prevent="ask(question)">
      <input v-model="question" class="input" maxlength="500" placeholder="Escreva sua pergunta" aria-label="Pergunta" />
      <button class="btn btn-primary" type="submit" :disabled="busy || !question.trim()">Enviar</button>
    </form>
  </div>
</template>

<style scoped>
.chat-page {
  height: 100vh;
}

.status {
  display: flex;
  align-items: center;
  gap: 8px;
}

.log {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
  padding: 16px;
  display: flex;
  flex-direction: column;
  gap: 14px;
}

.start {
  display: flex;
  flex-direction: column;
  gap: 8px;
  align-items: flex-start;
}

.start .btn {
  text-align: left;
}

.message {
  max-width: 78ch;
}

.message.user {
  align-self: flex-end;
  background: var(--panel-sunk);
  padding: 8px 12px;
  border-radius: var(--radius-lg);
}

.message p {
  margin: 2px 0 0;
}

.md :deep(p) {
  margin: 4px 0;
}

.md :deep(ul),
.md :deep(ol) {
  margin: 4px 0;
  padding-left: 20px;
}

.ask {
  display: flex;
  gap: 8px;
}

@media (max-width: 860px) {
  .chat-page {
    height: calc(100vh - 60px);
  }
}
</style>
