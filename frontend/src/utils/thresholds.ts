import type { RackStatus } from '@/types/api'

/** Limiares da seção 3 do contrato. Não altere sem alterar firmware e backend. */
export const THRESHOLDS = {
  TEMP_WARN: 30,
  TEMP_CRIT: 35,
  HUM_MIN_CRIT: 20,
  HUM_MIN_WARN: 30,
  HUM_MAX_WARN: 70,
  HUM_MAX_CRIT: 80,
} as const

export interface ScaleBand {
  from: number
  to: number
  status: RackStatus
}

export interface MetricScale {
  min: number
  max: number
  bands: ScaleBand[]
  /** Marcas rotuladas exibidas sob a faixa. */
  ticks: number[]
}

/** Escala da temperatura: 15 °C a 45 °C cobre a operação real de um rack. */
export const TEMPERATURE_SCALE: MetricScale = {
  min: 15,
  max: 45,
  bands: [
    { from: 15, to: THRESHOLDS.TEMP_WARN, status: 'ok' },
    { from: THRESHOLDS.TEMP_WARN, to: THRESHOLDS.TEMP_CRIT, status: 'warning' },
    { from: THRESHOLDS.TEMP_CRIT, to: 45, status: 'critical' },
  ],
  ticks: [THRESHOLDS.TEMP_WARN, THRESHOLDS.TEMP_CRIT],
}

/** Escala da umidade: faixa completa, com as duas bordas de risco. */
export const HUMIDITY_SCALE: MetricScale = {
  min: 0,
  max: 100,
  bands: [
    { from: 0, to: THRESHOLDS.HUM_MIN_CRIT, status: 'critical' },
    { from: THRESHOLDS.HUM_MIN_CRIT, to: THRESHOLDS.HUM_MIN_WARN, status: 'warning' },
    { from: THRESHOLDS.HUM_MIN_WARN, to: THRESHOLDS.HUM_MAX_WARN, status: 'ok' },
    { from: THRESHOLDS.HUM_MAX_WARN, to: THRESHOLDS.HUM_MAX_CRIT, status: 'warning' },
    { from: THRESHOLDS.HUM_MAX_CRIT, to: 100, status: 'critical' },
  ],
  ticks: [THRESHOLDS.HUM_MIN_CRIT, THRESHOLDS.HUM_MIN_WARN, THRESHOLDS.HUM_MAX_WARN, THRESHOLDS.HUM_MAX_CRIT],
}

export function temperatureStatus(value: number): RackStatus {
  if (value >= THRESHOLDS.TEMP_CRIT) return 'critical'
  if (value >= THRESHOLDS.TEMP_WARN) return 'warning'
  return 'ok'
}

export function humidityStatus(value: number): RackStatus {
  if (value < THRESHOLDS.HUM_MIN_CRIT || value > THRESHOLDS.HUM_MAX_CRIT) return 'critical'
  if (value < THRESHOLDS.HUM_MIN_WARN || value > THRESHOLDS.HUM_MAX_WARN) return 'warning'
  return 'ok'
}

const SEVERITY: Record<RackStatus, number> = { ok: 0, warning: 1, critical: 2 }

/** Status final = o pior entre as métricas (regra do contrato). */
export function worstStatus(...values: RackStatus[]): RackStatus {
  return values.reduce<RackStatus>((worst, current) =>
    SEVERITY[current] > SEVERITY[worst] ? current : worst, 'ok')
}

export const STATUS_LABEL: Record<RackStatus, string> = {
  ok: 'Normal',
  warning: 'Alerta',
  critical: 'Crítico',
}

/** Posição percentual de um valor dentro da escala, limitada a 0–100. */
export function positionInScale(value: number, scale: MetricScale): number {
  const ratio = (value - scale.min) / (scale.max - scale.min)
  return Math.min(100, Math.max(0, ratio * 100))
}
