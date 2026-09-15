<script setup lang="ts">
import { computed } from 'vue'
import type { AlertItem, RangeKey } from '@/types/api'
import { formatDateTime, formatDecimal, RANGE_LABEL } from '@/utils/format'
import { STATUS_LABEL } from '@/utils/thresholds'

const props = defineProps<{
  alerts: AlertItem[]
  count: number
  range: RangeKey
  loading?: boolean
}>()

/** Mostra os mais recentes primeiro, sem depender da ordem do backend. */
const ordered = computed<AlertItem[]>(() =>
  [...props.alerts].sort((a, b) => new Date(b.time).getTime() - new Date(a.time).getTime()),
)

const summary = computed<string>(() =>
  props.count === 1
    ? `1 alerta em ${RANGE_LABEL[props.range]}`
    : `${props.count} alertas em ${RANGE_LABEL[props.range]}`,
)
</script>

<template>
  <section class="alerts panel" :class="{ 'alerts--loading': loading }">
    <header class="alerts__head">
      <h3 class="alerts__title">Alertas recentes</h3>
      <span class="alerts__summary mono">{{ summary }}</span>
    </header>

    <div v-if="ordered.length === 0" class="alerts__empty">
      <p class="alerts__empty-title">Nenhum alerta no período.</p>
      <p class="alerts__empty-detail">
        Leituras fora dos limiares aparecem aqui com horário, severidade e causa.
      </p>
    </div>

    <div v-else class="alerts__scroll">
      <table class="alerts__table">
        <thead>
          <tr>
            <th scope="col" class="eyebrow">Horário</th>
            <th scope="col" class="eyebrow">Severidade</th>
            <th scope="col" class="eyebrow alerts__num">Temp.</th>
            <th scope="col" class="eyebrow alerts__num">Umid.</th>
            <th scope="col" class="eyebrow">Ocorrência</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="alert in ordered" :key="`${alert.time}-${alert.status}`" :data-status="alert.status">
            <td class="mono alerts__time">{{ formatDateTime(alert.time) }}</td>
            <td>
              <span class="alerts__badge mono">{{ STATUS_LABEL[alert.status] }}</span>
            </td>
            <td class="mono alerts__num">{{ formatDecimal(alert.temperature) }} °C</td>
            <td class="mono alerts__num">{{ formatDecimal(alert.humidity) }} %</td>
            <td class="alerts__message">{{ alert.message }}</td>
          </tr>
        </tbody>
      </table>
    </div>
  </section>
</template>

<style scoped>
.alerts {
  padding: 16px 18px;
}

.alerts--loading {
  opacity: 0.55;
}

.alerts__head {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 10px;
}

.alerts__title {
  font-size: 1rem;
  font-weight: 700;
}

.alerts__summary {
  font-size: 10px;
  letter-spacing: 0.06em;
  color: var(--ink-faint);
}

.alerts__empty {
  padding: 18px 0 6px;
  border-top: 1px solid var(--line);
}

.alerts__empty-title {
  margin: 0;
  font-weight: 600;
  color: var(--ink);
}

.alerts__empty-detail {
  margin: 4px 0 0;
  font-size: 13px;
  color: var(--ink-muted);
}

.alerts__scroll {
  max-height: 260px;
  overflow: auto;
  overscroll-behavior: contain;
}

.alerts__table {
  width: 100%;
  border-collapse: collapse;
}

.alerts__table th,
.alerts__table td {
  padding: 8px 10px;
  text-align: left;
  border-bottom: 1px solid var(--line);
  white-space: nowrap;
}

.alerts__table thead th {
  position: sticky;
  top: 0;
  background: var(--panel);
  border-bottom: 1px solid var(--line-strong);
  z-index: 1;
}

.alerts__table tbody tr:last-child td {
  border-bottom: none;
}

.alerts__time {
  font-size: 12px;
  color: var(--ink-muted);
}

.alerts__badge {
  display: inline-block;
  padding: 3px 8px;
  border-radius: 2px;
  background: var(--status-wash);
  color: var(--status);
  border: 1px solid var(--status);
  font-size: 10px;
  font-weight: 700;
  letter-spacing: 0.08em;
  text-transform: uppercase;
}

.alerts__num {
  text-align: right;
  font-size: 12px;
  color: var(--ink);
}

.alerts__message {
  width: 100%;
  font-size: 13px;
  color: var(--ink-muted);
  white-space: normal;
}

@media (max-width: 720px) {
  .alerts__table th:nth-child(3),
  .alerts__table td:nth-child(3),
  .alerts__table th:nth-child(4),
  .alerts__table td:nth-child(4) {
    display: none;
  }
}
</style>
