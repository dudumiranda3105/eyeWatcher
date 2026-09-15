<script setup lang="ts">
import { computed } from 'vue'
import { Line } from 'vue-chartjs'
import {
  CategoryScale,
  Chart as ChartJS,
  Filler,
  Legend,
  LinearScale,
  LineElement,
  PointElement,
  TimeScale,
  Tooltip,
  type Chart,
  type ChartData,
  type ChartOptions,
  type Plugin,
  type Point,
  type ScriptableLineSegmentContext,
  type TooltipItem,
} from 'chart.js'
import 'chartjs-adapter-date-fns'
import { ptBR } from 'date-fns/locale'
import type { HistoryPoint } from '@/types/api'
import { useThemeTokens } from '@/composables/useThemeTokens'
import { formatDecimal } from '@/utils/format'
import { THRESHOLDS } from '@/utils/thresholds'

ChartJS.register(
  LineElement,
  PointElement,
  LinearScale,
  CategoryScale,
  TimeScale,
  Tooltip,
  Legend,
  Filler,
)

const props = defineProps<{
  points: HistoryPoint[]
  /** Ativa o esqueleto de carregamento sobre o gráfico. */
  loading?: boolean
}>()

const tokens = useThemeTokens()

interface Threshold {
  value: number
  label: string
  color: () => string
}

const THRESHOLD_LINES: Threshold[] = [
  { value: THRESHOLDS.TEMP_WARN, label: `Alerta ${THRESHOLDS.TEMP_WARN} °C`, color: () => tokens.value.warn },
  { value: THRESHOLDS.TEMP_CRIT, label: `Crítico ${THRESHOLDS.TEMP_CRIT} °C`, color: () => tokens.value.crit },
]

/**
 * Desenha os limiares do contrato sobre a área do gráfico, no eixo da
 * temperatura. Plugin local: não interfere em outras instâncias do Chart.js.
 */
const thresholdPlugin: Plugin<'line'> = {
  id: 'eyewatcher-thresholds',
  afterDraw(chart: Chart<'line'>) {
    const scale = chart.scales.y
    if (!scale) return

    const { ctx, chartArea } = chart
    ctx.save()
    ctx.setLineDash([5, 4])
    ctx.lineWidth = 1.5
    ctx.font = '10px "Martian Mono", ui-monospace, monospace'
    ctx.textBaseline = 'bottom'

    for (const threshold of THRESHOLD_LINES) {
      if (threshold.value < scale.min || threshold.value > scale.max) continue

      const y = scale.getPixelForValue(threshold.value)
      const color = threshold.color()

      ctx.strokeStyle = color
      ctx.beginPath()
      ctx.moveTo(chartArea.left, y)
      ctx.lineTo(chartArea.right, y)
      ctx.stroke()

      ctx.fillStyle = color
      ctx.setLineDash([])
      ctx.fillText(threshold.label, chartArea.left + 6, y - 4)
      ctx.setLineDash([5, 4])
    }

    ctx.restore()
  },
}

const plugins = [thresholdPlugin]

/** Série sem os pontos nulos do contrato: o Chart.js recebe só medições reais. */
function toSeries(points: HistoryPoint[], metric: 'temperature' | 'humidity'): Point[] {
  const series: Point[] = []
  for (const point of points) {
    const value = point[metric]
    if (value === null) continue
    series.push({ x: new Date(point.time).getTime(), y: value })
  }
  return series
}

/** Espaçamento típico entre amostras — usado para reconhecer lacunas. */
function medianSpacing(series: Point[]): number {
  if (series.length < 3) return Number.POSITIVE_INFINITY
  const deltas: number[] = []
  for (let i = 1; i < series.length; i += 1) {
    const current = series[i]?.x
    const before = series[i - 1]?.x
    if (typeof current === 'number' && typeof before === 'number') deltas.push(current - before)
  }
  deltas.sort((a, b) => a - b)
  return deltas[Math.floor(deltas.length / 2)] ?? Number.POSITIVE_INFINITY
}

const chartData = computed<ChartData<'line', Point[]>>(() => {
  const temperature = toSeries(props.points, 'temperature')
  const humidity = toSeries(props.points, 'humidity')

  // Lacunas (`null` no contrato) viram traço pontilhado, não linha cheia:
  // o gráfico não finge ter medido o que não mediu.
  const gapAfter = medianSpacing(temperature) * 2.5
  const dashOnGap = (ctx: ScriptableLineSegmentContext): number[] | undefined => {
    const from = ctx.p0.parsed.x
    const to = ctx.p1.parsed.x
    if (typeof from !== 'number' || typeof to !== 'number') return undefined
    return to - from > gapAfter ? [3, 3] : undefined
  }

  return {
    datasets: [
      // Temperatura é a protagonista: linha grossa, desenhada por cima.
      {
        label: 'Temperatura (°C)',
        data: temperature,
        borderColor: tokens.value.temp,
        backgroundColor: tokens.value.temp,
        yAxisID: 'y',
        order: 2,
        borderWidth: 2.6,
        pointRadius: 0,
        pointHoverRadius: 5,
        pointHoverBorderWidth: 2,
        pointHoverBackgroundColor: tokens.value.panel,
        pointHoverBorderColor: tokens.value.temp,
        tension: 0.3,
        fill: false,
        segment: { borderDash: dashOnGap },
      },
      // Umidade é contexto: área preenchida ao fundo, para os dois eixos
      // continuarem legíveis mesmo quando as séries se cruzam.
      {
        label: 'Umidade (%)',
        data: humidity,
        borderColor: tokens.value.umid,
        backgroundColor: tokens.value.umidFill,
        yAxisID: 'y1',
        order: 1,
        borderWidth: 1.5,
        pointRadius: 0,
        pointHoverRadius: 5,
        pointHoverBorderWidth: 2,
        pointHoverBackgroundColor: tokens.value.panel,
        pointHoverBorderColor: tokens.value.umid,
        tension: 0.3,
        fill: 'origin',
        segment: { borderDash: dashOnGap },
      },
    ],
  }
})

const chartOptions = computed<ChartOptions<'line'>>(() => ({
  responsive: true,
  maintainAspectRatio: false,
  animation: { duration: 250 },
  interaction: { mode: 'index', intersect: false },
  layout: { padding: { top: 8, right: 4, bottom: 0, left: 0 } },
  scales: {
    x: {
      type: 'time',
      adapters: { date: { locale: ptBR } },
      time: {
        tooltipFormat: "dd/MM 'às' HH:mm:ss",
        displayFormats: {
          millisecond: 'HH:mm:ss',
          second: 'HH:mm:ss',
          minute: 'HH:mm',
          hour: 'HH:mm',
          day: 'dd/MM',
          week: 'dd/MM',
          month: 'MM/yyyy',
        },
      },
      grid: { color: tokens.value.line, drawTicks: false },
      border: { color: tokens.value.line },
      ticks: {
        color: tokens.value.inkFaint,
        font: { family: 'Martian Mono, ui-monospace, monospace', size: 10 },
        maxRotation: 0,
        autoSkipPadding: 44,
        padding: 8,
      },
    },
    y: {
      type: 'linear',
      position: 'left',
      suggestedMin: 24,
      // Garante que a linha crítica de 35 °C esteja sempre visível.
      suggestedMax: 38,
      grid: { color: tokens.value.line, drawTicks: false },
      border: { display: false },
      title: {
        display: true,
        text: 'Temperatura (°C)',
        color: tokens.value.temp,
        font: { family: 'Martian Mono, ui-monospace, monospace', size: 10, weight: 500 },
      },
      ticks: {
        color: tokens.value.inkMuted,
        font: { family: 'Martian Mono, ui-monospace, monospace', size: 10 },
        maxTicksLimit: 7,
        padding: 8,
      },
    },
    y1: {
      type: 'linear',
      position: 'right',
      min: 0,
      max: 100,
      grid: { display: false },
      border: { display: false },
      title: {
        display: true,
        text: 'Umidade (%)',
        color: tokens.value.umid,
        font: { family: 'Martian Mono, ui-monospace, monospace', size: 10, weight: 500 },
      },
      ticks: {
        color: tokens.value.inkMuted,
        font: { family: 'Martian Mono, ui-monospace, monospace', size: 10 },
        stepSize: 25,
        padding: 8,
      },
    },
  },
  plugins: {
    legend: {
      display: true,
      position: 'top',
      align: 'end',
      // Compensa o `order` dos datasets: temperatura primeiro na legenda.
      reverse: true,
      labels: {
        color: tokens.value.inkMuted,
        boxWidth: 14,
        boxHeight: 3,
        usePointStyle: false,
        font: { family: 'Public Sans, system-ui, sans-serif', size: 12 },
      },
    },
    tooltip: {
      backgroundColor: tokens.value.ink,
      titleColor: tokens.value.panel,
      bodyColor: tokens.value.panel,
      borderColor: tokens.value.line,
      borderWidth: 1,
      padding: 10,
      displayColors: true,
      titleFont: { family: 'Martian Mono, ui-monospace, monospace', size: 11 },
      bodyFont: { family: 'Public Sans, system-ui, sans-serif', size: 13 },
      callbacks: {
        label: (item: TooltipItem<'line'>) => {
          const value = item.parsed.y
          const unit = item.dataset.yAxisID === 'y1' ? '%' : '°C'
          return Number.isFinite(value)
            ? `${item.dataset.label}: ${formatDecimal(value)} ${unit}`
            : `${item.dataset.label}: sem dado`
        },
      },
    },
  },
}))
</script>

<template>
  <div class="chart" :class="{ 'chart--loading': loading }">
    <Line :data="chartData" :options="chartOptions" :plugins="plugins" />
  </div>
</template>

<style scoped>
.chart {
  position: relative;
  height: 100%;
  min-height: 240px;
}

.chart--loading {
  opacity: 0.45;
}
</style>
