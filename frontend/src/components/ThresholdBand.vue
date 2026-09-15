<script setup lang="ts">
import { computed } from 'vue'
import type { MetricScale } from '@/utils/thresholds'
import { positionInScale } from '@/utils/thresholds'
import { formatDecimal } from '@/utils/format'

const props = defineProps<{
  /** Faixas de limiar desta métrica, vindas do contrato. */
  scale: MetricScale
  /** Valor atual; `null` mantém a régua visível, sem marcador. */
  value: number | null
  /** Sufixo exibido nas marcas rotuladas (ex.: "°C", "%"). */
  unit: string
}>()

interface RenderedBand {
  status: string
  left: number
  width: number
}

const bands = computed<RenderedBand[]>(() =>
  props.scale.bands.map((band) => ({
    status: band.status,
    left: positionInScale(band.from, props.scale),
    width: positionInScale(band.to, props.scale) - positionInScale(band.from, props.scale),
  })),
)

const markerPosition = computed<number | null>(() =>
  props.value === null ? null : positionInScale(props.value, props.scale),
)

const bandDescription = computed<string>(() => {
  const limits = props.scale.ticks.map((tick) => `${formatDecimal(tick).replace(',0', '')} ${props.unit}`)
  return `Faixa de limiares: ${limits.join(', ')}`
})

const ticks = computed(() =>
  props.scale.ticks.map((tick) => ({
    value: tick,
    left: positionInScale(tick, props.scale),
  })),
)
</script>

<template>
  <div class="band">
    <div class="band__track" role="img" :aria-label="bandDescription">
      <span
        v-for="band in bands"
        :key="`${band.left}-${band.status}`"
        class="band__zone"
        :data-status="band.status"
        :style="{ left: `${band.left}%`, width: `${band.width}%` }"
      />
      <span
        v-if="markerPosition !== null"
        class="band__marker"
        :style="{ left: `${markerPosition}%` }"
      />
    </div>
    <div class="band__ticks mono">
      <span
        v-for="tick in ticks"
        :key="tick.value"
        class="band__tick"
        :style="{ left: `${tick.left}%` }"
      >
        {{ formatDecimal(tick.value).replace(',0', '') }}
      </span>
    </div>
  </div>
</template>

<style scoped>
.band {
  margin-top: 14px;
}

.band__track {
  position: relative;
  height: 10px;
  border-radius: 2px;
  overflow: hidden;
  background: var(--panel-sunk);
}

.band__zone {
  position: absolute;
  top: 0;
  bottom: 0;
  background: var(--status-wash);
  border-right: 1px solid var(--panel);
}

.band__zone:last-of-type {
  border-right: none;
}

.band__marker {
  position: absolute;
  top: -3px;
  bottom: -3px;
  width: 3px;
  margin-left: -1.5px;
  background: var(--ink);
  border-radius: 1px;
  transition: left 400ms cubic-bezier(0.22, 1, 0.36, 1);
}

.band__ticks {
  position: relative;
  height: 14px;
  margin-top: 4px;
  font-size: 9px;
  color: var(--ink-faint);
}

.band__tick {
  position: absolute;
  top: 0;
  transform: translateX(-50%);
  white-space: nowrap;
}

.band__tick::before {
  content: '';
  position: absolute;
  top: -5px;
  left: 50%;
  width: 1px;
  height: 3px;
  background: var(--line-strong);
}
</style>
