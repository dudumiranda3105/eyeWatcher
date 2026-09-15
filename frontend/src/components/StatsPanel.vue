<script setup lang="ts">
import { computed } from 'vue'
import type { MetricStats, RangeKey, StatsResponse } from '@/types/api'
import { formatDecimal, formatInteger, RANGE_LABEL } from '@/utils/format'

const props = defineProps<{
  stats: StatsResponse | null
  range: RangeKey
  loading?: boolean
}>()

interface StatRow {
  key: string
  metric: string
  unit: string
  accent: string
  data: MetricStats | null
}

const rows = computed<StatRow[]>(() => [
  {
    key: 'temperature',
    metric: 'Temperatura',
    unit: '°C',
    accent: 'var(--temp)',
    data: props.stats?.temperature ?? null,
  },
  {
    key: 'humidity',
    metric: 'Umidade',
    unit: '%',
    accent: 'var(--umid)',
    data: props.stats?.humidity ?? null,
  },
])

const sampleLabel = computed<string>(() => {
  if (!props.stats) return 'sem amostras'
  return `${formatInteger(props.stats.count)} amostras em ${RANGE_LABEL[props.range]}`
})
</script>

<template>
  <section class="stats" :class="{ 'stats--loading': loading }">
    <header class="stats__head">
      <span class="eyebrow">Resumo do período</span>
      <span class="stats__count mono">{{ sampleLabel }}</span>
    </header>

    <table class="stats__table">
      <thead>
        <tr>
          <th scope="col" class="eyebrow">Métrica</th>
          <th scope="col" class="eyebrow stats__num">Mín</th>
          <th scope="col" class="eyebrow stats__num">Média</th>
          <th scope="col" class="eyebrow stats__num">Máx</th>
          <th scope="col" class="eyebrow stats__num">Atual</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="row in rows" :key="row.key">
          <th scope="row" class="stats__metric">
            <span class="stats__swatch" :style="{ background: row.accent }" aria-hidden="true" />
            {{ row.metric }}
          </th>
          <td class="stats__num mono">{{ formatDecimal(row.data?.min ?? null) }}</td>
          <td class="stats__num mono">{{ formatDecimal(row.data?.avg ?? null) }}</td>
          <td class="stats__num mono stats__num--max">{{ formatDecimal(row.data?.max ?? null) }}</td>
          <td class="stats__num mono stats__num--last">
            {{ formatDecimal(row.data?.last ?? null) }}<span class="stats__unit">{{ row.unit }}</span>
          </td>
        </tr>
      </tbody>
    </table>
  </section>
</template>

<style scoped>
.stats--loading {
  opacity: 0.5;
}

.stats__head {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 8px;
}

.stats__count {
  font-size: 10px;
  color: var(--ink-faint);
}

.stats__table {
  width: 100%;
  border-collapse: collapse;
}

.stats__table th,
.stats__table td {
  padding: 7px 6px;
  text-align: left;
  border-bottom: 1px solid var(--line);
}

.stats__table tbody tr:last-child th,
.stats__table tbody tr:last-child td {
  border-bottom: none;
}

.stats__metric {
  display: flex;
  align-items: center;
  gap: 8px;
  font-family: var(--font-body);
  font-size: 13px;
  font-weight: 500;
  color: var(--ink);
}

.stats__swatch {
  width: 12px;
  height: 3px;
  border-radius: 2px;
}

.stats__num {
  text-align: right;
  font-size: 13px;
  color: var(--ink-muted);
  white-space: nowrap;
}

thead .stats__num {
  font-size: 10px;
}

.stats__num--max {
  color: var(--ink);
}

.stats__num--last {
  color: var(--ink);
  font-weight: 700;
}

.stats__unit {
  margin-left: 3px;
  font-size: 10px;
  font-weight: 400;
  color: var(--ink-faint);
}
</style>
