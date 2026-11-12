<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { errorMessage, http } from '@/services/api'
import type { AuditEntry } from '@/types/api'
import { fmtDateTime } from '@/utils/format'

const entries = ref<AuditEntry[]>([])
const error = ref('')

async function load(): Promise<void> {
  try {
    entries.value = (await http.get<AuditEntry[]>('/audit', { params: { limit: 200 } })).data
    error.value = ''
  } catch (cause) {
    error.value = errorMessage(cause)
  }
}

onMounted(load)
</script>

<template>
  <div class="page">
    <header class="page-head">
      <div>
        <h1>Auditoria</h1>
        <p>Logins, comandos, jobs e perguntas ao assistente, registrados no PostgreSQL.</p>
      </div>
      <button class="btn" type="button" @click="load">Atualizar</button>
    </header>
    <p v-if="error" class="error">{{ error }}</p>
    <section class="panel panel-body">
      <div class="table-wrap">
        <table class="data">
          <thead>
            <tr><th>Quando</th><th>Usuário</th><th>Ação</th><th>Alvo</th><th>Detalhe</th><th>IP</th></tr>
          </thead>
          <tbody>
            <tr v-for="entry in entries" :key="entry.id">
              <td class="mono">{{ fmtDateTime(entry.ts) }}</td>
              <td>{{ entry.username }}</td>
              <td class="mono">{{ entry.action }}</td>
              <td class="mono">{{ entry.target ?? '--' }}</td>
              <td class="mono detail">{{ JSON.stringify(entry.detail) }}</td>
              <td class="mono">{{ entry.ip ?? '--' }}</td>
            </tr>
          </tbody>
        </table>
      </div>
    </section>
  </div>
</template>

<style scoped>
.detail {
  font-size: 12px;
  max-width: 360px;
  word-break: break-word;
}
</style>
