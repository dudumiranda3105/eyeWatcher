<script setup lang="ts">
import { computed } from 'vue'
import { fmtInt, healthStatus } from '@/utils/format'

const props = defineProps<{ value: number }>()

/** Arco de 270 graus: o vão fica embaixo, como num manômetro. */
const RADIUS = 52
const SWEEP = 0.75
const LENGTH = 2 * Math.PI * RADIUS

const clamped = computed(() => Math.min(100, Math.max(0, props.value)))
const dash = computed(() => `${(clamped.value / 100) * LENGTH * SWEEP} ${LENGTH}`)
const track = `${LENGTH * SWEEP} ${LENGTH}`
</script>

<template>
  <div
    class="gauge"
    :data-status="healthStatus(clamped)"
    role="meter"
    aria-valuemin="0"
    aria-valuemax="100"
    :aria-valuenow="Math.round(clamped)"
    aria-label="Saúde prevista"
  >
    <svg viewBox="0 0 120 120" aria-hidden="true">
      <circle class="track" cx="60" cy="60" :r="RADIUS" :stroke-dasharray="track" />
      <circle class="fill" cx="60" cy="60" :r="RADIUS" :stroke-dasharray="dash" />
    </svg>
    <div class="center">
      <strong class="mono">{{ fmtInt(clamped) }}</strong>
      <span class="eyebrow">Saúde</span>
    </div>
  </div>
</template>

<style scoped>
.gauge {
  position: relative;
  width: 132px;
  aspect-ratio: 1;
  flex: none;
}

svg {
  width: 100%;
  height: 100%;
  transform: rotate(135deg);
}

circle {
  fill: none;
  stroke-width: 9;
  stroke-linecap: round;
}

.track {
  stroke: var(--panel-sunk);
}

.fill {
  stroke: var(--status);
  transition:
    stroke-dasharray 0.6s var(--ease),
    stroke 0.3s;
}

.center {
  position: absolute;
  inset: 0;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 2px;
}

.center strong {
  font-size: 32px;
  font-weight: 500;
  line-height: 1;
  color: var(--status);
}
</style>
