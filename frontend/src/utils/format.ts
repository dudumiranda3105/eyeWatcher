import type { RangeKey } from '@/types/api'

const LOCALE = 'pt-BR'

const decimal1 = new Intl.NumberFormat(LOCALE, {
  minimumFractionDigits: 1,
  maximumFractionDigits: 1,
})

const integer = new Intl.NumberFormat(LOCALE, { maximumFractionDigits: 0 })

const clockFormatter = new Intl.DateTimeFormat(LOCALE, {
  hour: '2-digit',
  minute: '2-digit',
  second: '2-digit',
})

const dateTimeFormatter = new Intl.DateTimeFormat(LOCALE, {
  day: '2-digit',
  month: '2-digit',
  hour: '2-digit',
  minute: '2-digit',
  second: '2-digit',
})

const relativeFormatter = new Intl.RelativeTimeFormat(LOCALE, { numeric: 'auto', style: 'short' })

/** Número com uma casa decimal (padrão do contrato para temperatura e umidade). */
export function formatDecimal(value: number | null | undefined): string {
  if (value === null || value === undefined || Number.isNaN(value)) return '—'
  return decimal1.format(value)
}

export function formatInteger(value: number | null | undefined): string {
  if (value === null || value === undefined || Number.isNaN(value)) return '—'
  return integer.format(value)
}

/** hh:mm:ss — usado na tabela de alertas e no rodapé. */
export function formatClock(iso: string | null | undefined): string {
  const date = toDate(iso)
  return date ? clockFormatter.format(date) : '—'
}

/** dd/mm hh:mm:ss — para períodos longos, onde só a hora é ambígua. */
export function formatDateTime(iso: string | null | undefined): string {
  const date = toDate(iso)
  return date ? dateTimeFormatter.format(date) : '—'
}

/** "há 4 s", "há 2 min" — sempre no passado. */
export function formatRelative(iso: string | null | undefined, now: number = Date.now()): string {
  const date = toDate(iso)
  if (!date) return '—'

  const seconds = Math.round((date.getTime() - now) / 1000)
  const absolute = Math.abs(seconds)

  if (absolute < 60) return relativeFormatter.format(Math.min(seconds, 0), 'second')
  if (absolute < 3600) return relativeFormatter.format(Math.round(seconds / 60), 'minute')
  if (absolute < 86400) return relativeFormatter.format(Math.round(seconds / 3600), 'hour')
  return relativeFormatter.format(Math.round(seconds / 86400), 'day')
}

/** Segundos de uptime → "3 d 04 h 12 min". */
export function formatUptime(seconds: number | null | undefined): string {
  if (seconds === null || seconds === undefined || Number.isNaN(seconds)) return '—'

  const total = Math.max(0, Math.floor(seconds))
  const days = Math.floor(total / 86400)
  const hours = Math.floor((total % 86400) / 3600)
  const minutes = Math.floor((total % 3600) / 60)

  if (days > 0) return `${days} d ${String(hours).padStart(2, '0')} h`
  if (hours > 0) return `${hours} h ${String(minutes).padStart(2, '0')} min`
  return `${minutes} min`
}

export const RANGE_LABEL: Record<RangeKey, string> = {
  '15m': '15 min',
  '1h': '1 hora',
  '6h': '6 horas',
  '24h': '24 horas',
  '7d': '7 dias',
  '30d': '30 dias',
}

function toDate(iso: string | null | undefined): Date | null {
  if (!iso) return null
  const date = new Date(iso)
  return Number.isNaN(date.getTime()) ? null : date
}
