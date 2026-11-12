import type { Status } from '@/types/api'

export const STATUS_LABEL: Record<Status, string> = {
  ok: 'Normal',
  warning: 'Atenção',
  critical: 'Crítico',
  offline: 'Sem dados',
}

export const METRIC_LABEL: Record<string, string> = {
  temperature: 'Temperatura',
  humidity: 'Umidade',
  luminosity: 'Luminosidade',
  current: 'Corrente',
  presence: 'Presença',
  vibration: 'Vibração',
  rpm: 'Rotação',
  on: 'Ligado',
}

export const METRIC_UNIT: Record<string, string> = {
  temperature: '°C',
  humidity: '%',
  luminosity: 'lux',
  current: 'A',
  vibration: 'mm/s',
  rpm: 'rpm',
}

export const FAILURE_LABEL: Record<string, string> = {
  bearing_wear: 'Desgaste de rolamento',
  clogging: 'Entupimento do filtro',
  overheating: 'Superaquecimento',
  imbalance: 'Desbalanceamento',
  sensor_drift: 'Deriva do sensor',
  sensor_stuck: 'Sensor travado',
}

const number1 = new Intl.NumberFormat('pt-BR', { maximumFractionDigits: 1, minimumFractionDigits: 1 })
const number2 = new Intl.NumberFormat('pt-BR', { maximumFractionDigits: 2, minimumFractionDigits: 2 })
const integer = new Intl.NumberFormat('pt-BR', { maximumFractionDigits: 0 })
const clock = new Intl.DateTimeFormat('pt-BR', { timeStyle: 'medium' })
const dateTime = new Intl.DateTimeFormat('pt-BR', { dateStyle: 'short', timeStyle: 'medium' })

export const fmt1 = (value: number): string => number1.format(value)
export const fmt2 = (value: number): string => number2.format(value)
export const fmtInt = (value: number): string => integer.format(value)
export const fmtClock = (value: string | number): string => clock.format(new Date(value))
export const fmtDateTime = (value: string | number): string => dateTime.format(new Date(value))

export function fmtSimHour(hour: number): string {
  const whole = Math.floor(hour)
  const minutes = Math.floor((hour - whole) * 60)
  return `${String(whole).padStart(2, '0')}:${String(minutes).padStart(2, '0')}`
}

export function fmtMetric(metric: string, value: number): string {
  if (metric === 'on' || metric === 'presence') return value >= 0.5 ? 'Sim' : 'Não'
  const unit = METRIC_UNIT[metric]
  const text = metric === 'rpm' || metric === 'luminosity' ? fmtInt(value) : fmt1(value)
  return unit ? `${text} ${unit}` : text
}

export function healthStatus(health: number): Status {
  if (health < 40) return 'critical'
  if (health < 65) return 'warning'
  return 'ok'
}
