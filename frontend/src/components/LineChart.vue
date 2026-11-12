<script setup lang="ts">
import { computed } from 'vue'
import { Line } from 'vue-chartjs'
import {
  Chart as ChartJS,
  Filler,
  Legend,
  LinearScale,
  LineElement,
  PointElement,
  TimeScale,
  Tooltip,
  type ChartData,
  type ChartOptions,
} from 'chart.js'
import { color as toColor } from 'chart.js/helpers'
import 'chartjs-adapter-date-fns'
import { ptBR } from 'date-fns/locale'
import { useThemeTokens } from '@/composables/useThemeTokens'

ChartJS.register(LineElement, PointElement, LinearScale, TimeScale, Tooltip, Legend, Filler)

export interface Series {
  label: string
  color?: string
  points: { x: number; y: number }[]
}

const props = withDefaults(
  defineProps<{ series: Series[]; height?: number; compact?: boolean; min?: number; max?: number }>(),
  { height: 260, compact: false, min: undefined, max: undefined },
)

const tokens = useThemeTokens()

const data = computed<ChartData<'line', { x: number; y: number }[]>>(() => ({
  datasets: props.series.map((series, index) => {
    const color = series.color ?? (index === 0 ? tokens.value.temp : tokens.value.umid)
    return {
      label: series.label,
      data: series.points,
      borderColor: color,
      // Uma série só ganha área preenchida; com duas, o preenchimento confunde.
      backgroundColor: toColor(color).alpha(props.compact ? 0.1 : 0.14).rgbString(),
      fill: props.series.length === 1 ? 'start' : false,
      borderWidth: props.compact ? 1.5 : 2,
      pointRadius: 0,
      pointHoverRadius: props.compact ? 0 : 4,
      pointHoverBackgroundColor: color,
      tension: 0.3,
    }
  }),
}))

const options = computed<ChartOptions<'line'>>(() => ({
  responsive: true,
  maintainAspectRatio: false,
  animation: false,
  parsing: false,
  interaction: { mode: 'nearest', axis: 'x', intersect: false },
  plugins: {
    legend: { display: props.series.length > 1, labels: { color: tokens.value.inkMuted, boxWidth: 12 } },
    tooltip: {
      enabled: !props.compact,
      backgroundColor: tokens.value.ink,
      titleColor: tokens.value.panel,
      bodyColor: tokens.value.panel,
      padding: 10,
      cornerRadius: 8,
      displayColors: false,
    },
  },
  scales: {
    x: {
      type: 'time',
      display: !props.compact,
      adapters: { date: { locale: ptBR } },
      time: {
        tooltipFormat: 'dd/MM HH:mm:ss',
        displayFormats: { second: 'HH:mm:ss', minute: 'HH:mm', hour: 'HH:mm', day: 'dd/MM' },
      },
      border: { display: false },
      grid: { display: false },
      ticks: { color: tokens.value.inkFaint, maxTicksLimit: 8, maxRotation: 0 },
    },
    y: {
      display: !props.compact,
      min: props.min,
      max: props.max,
      border: { display: false },
      grid: { color: tokens.value.line },
      ticks: { color: tokens.value.inkFaint, maxTicksLimit: 6 },
    },
  },
}))
</script>

<template>
  <div :style="{ height: `${height}px` }">
    <Line :data="data" :options="options" />
  </div>
</template>
