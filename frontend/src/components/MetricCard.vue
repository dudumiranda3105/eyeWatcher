<script setup lang="ts">
import { computed } from 'vue'
import ThresholdBand from '@/components/ThresholdBand.vue'
import type { RackStatus } from '@/types/api'
import type { MetricTrend } from '@/stores/racks'
import type { MetricScale } from '@/utils/thresholds'
import { STATUS_LABEL } from '@/utils/thresholds'
import { formatDecimal } from '@/utils/format'

const props = withDefaults(
  defineProps<{
    label: string
    value: number | null
    unit: string
    status?: RackStatus | null
    trend?: MetricTrend | null
    /** Sem escala, o card não desenha a faixa de limiares. */
    scale?: MetricScale | null
    /** Linha de apoio sob a leitura (ex.: origem do dado). */
    note?: string
    /** Destaca o card principal do painel. */
    primary?: boolean
  }>(),
  {
    status: null,
    trend: null,
    scale: null,
    note: '',
    primary: false,
  },
)

const displayValue = computed<string>(() => formatDecimal(props.value))

const statusKey = computed<string>(() => props.status ?? 'offline')

const trendLabel = computed<string>(() => {
  const trend = props.trend
  if (!trend) return 'sem leitura anterior'
  if (trend.direction === 'flat') return 'estável'
  const sign = trend.delta > 0 ? '+' : '−'
  return `${sign}${formatDecimal(Math.abs(trend.delta))} ${props.unit}`
})

const trendArrow = computed<string>(() => {
  const direction = props.trend?.direction
  if (direction === 'up') return '▲'
  if (direction === 'down') return '▼'
  return '■'
})
</script>

<template>
  <article class="card" :class="{ 'card--primary': primary }" :data-status="statusKey">
    <header class="card__head">
      <span class="eyebrow">{{ label }}</span>
      <span v-if="status" class="card__status mono">{{ STATUS_LABEL[status] }}</span>
    </header>

    <p class="card__readout mono">
      <span class="card__value" :class="{ 'card__value--empty': value === null }">
        {{ displayValue }}
      </span>
      <span class="card__unit">{{ unit }}</span>
    </p>

    <p class="card__trend mono" :data-direction="trend?.direction ?? 'none'">
      <span aria-hidden="true">{{ trendArrow }}</span>
      <span>{{ trendLabel }}</span>
    </p>

    <ThresholdBand v-if="scale" :scale="scale" :value="value" :unit="unit" />

    <p v-if="note" class="card__note">{{ note }}</p>
  </article>
</template>

<style scoped>
.card {
  position: relative;
  padding: 14px 18px 16px 22px;
  background: var(--panel);
  border: 1px solid var(--line);
  border-radius: var(--radius-lg);
  box-shadow: var(--shadow);
  overflow: hidden;
}

/* Trilho de status na lateral: o rack tem trilhos, o card também. */
.card::before {
  content: '';
  position: absolute;
  inset: 0 auto 0 0;
  width: 6px;
  background: var(--status);
  transition: background-color 300ms ease;
}

.card__head {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: 8px;
}

.card__status {
  font-size: 10px;
  font-weight: 700;
  letter-spacing: 0.08em;
  text-transform: uppercase;
  color: var(--status);
}

.card__readout {
  display: flex;
  align-items: baseline;
  gap: 6px;
  margin: 6px 0 0;
  color: var(--ink);
}

/* A leitura grande sai do mono para o display: no tamanho de projetor o
   avanço fixo do Martian Mono separa demais a vírgula decimal. */
.card__value {
  font-family: var(--font-display);
  font-variant-numeric: tabular-nums;
  font-size: clamp(2rem, 3.4vw, 2.9rem);
  font-weight: 700;
  line-height: 1;
  letter-spacing: -0.03em;
}

.card__value--empty {
  color: var(--line-strong);
}

.card--primary .card__value {
  font-size: clamp(2.6rem, 4.6vw, 4rem);
}

.card__unit {
  font-size: 0.95rem;
  font-weight: 500;
  color: var(--ink-muted);
}

.card__trend {
  display: flex;
  align-items: center;
  gap: 6px;
  margin: 8px 0 0;
  font-size: 10px;
  letter-spacing: 0.04em;
  color: var(--ink-faint);
}

.card__trend[data-direction='up'] {
  color: var(--temp);
}

.card__trend[data-direction='down'] {
  color: var(--umid);
}

.card__note {
  margin: 12px 0 0;
  font-size: 12px;
  line-height: 1.35;
  color: var(--ink-muted);
}
</style>
