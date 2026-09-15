/**
 * Tipos espelhando docs/CONTRACT.md campo a campo.
 * Qualquer divergência aqui é bug: o contrato é a fonte da verdade.
 */

/** Status calculado no ESP32 e revalidado no backend (seção 3 do contrato). */
export type RackStatus = 'ok' | 'warning' | 'critical'

/** Severidades possíveis em `/api/alerts` (leituras com status != ok). */
export type AlertSeverity = Exclude<RackStatus, 'ok'>

/** Valores aceitos pelo parâmetro `range` (qualquer outro devolve 422). */
export type RangeKey = '15m' | '1h' | '6h' | '24h' | '7d' | '30d'

export const RANGE_KEYS: readonly RangeKey[] = ['15m', '1h', '6h', '24h', '7d', '30d']

/** GET /api/health → `{status, influx, mqtt}` */
export interface HealthResponse {
  status: string
  influx: boolean | string
  mqtt: boolean | string
}

/** Bloco `last_reading` de /api/racks. */
export interface Reading {
  /** ISO-8601 UTC, carimbado na chegada ao backend. */
  time: string
  temperature: number
  humidity: number
  heat_index: number
  status: RackStatus
}

/** Item de GET /api/racks */
export interface Rack {
  rack_id: string
  device_id: string
  location: string
  online: boolean
  last_reading: Reading | null
}

export type RacksResponse = Rack[]

/** GET /api/readings/latest → `last_reading` + identificação do rack. */
export interface LatestReadingResponse extends Reading {
  rack_id: string
  device_id: string
  location: string
  online: boolean
}

/** Ponto agregado (mean) da série temporal. Lacunas chegam como `null`. */
export interface HistoryPoint {
  time: string
  temperature: number | null
  humidity: number | null
  heat_index: number | null
}

/** GET /api/readings/history */
export interface HistoryResponse {
  rack_id: string
  range: RangeKey
  window: string
  /** Ordenado crescente por `time`. */
  points: HistoryPoint[]
}

/** Agregados de uma métrica no período. */
export interface MetricStats {
  min: number
  max: number
  avg: number
  last: number
}

/** GET /api/readings/stats */
export interface StatsResponse {
  rack_id: string
  range: RangeKey
  count: number
  temperature: MetricStats
  humidity: MetricStats
}

/** Item de GET /api/alerts */
export interface AlertItem {
  time: string
  status: AlertSeverity
  temperature: number
  humidity: number
  message: string
}

/** GET /api/alerts */
export interface AlertsResponse {
  rack_id: string
  range: RangeKey
  count: number
  alerts: AlertItem[]
}

/** Payload MQTT de telemetria, enriquecido pelo backend com `time`. */
export interface TelemetryPayload {
  device_id: string
  rack_id: string
  location: string
  temperature: number
  humidity: number
  heat_index: number
  status: RackStatus
  uptime_s: number
  seq: number
  time: string
}

export interface WsTelemetryEvent {
  type: 'telemetry'
  data: TelemetryPayload
}

export interface WsStatusEvent {
  type: 'status'
  data: {
    rack_id: string
    online: boolean
  }
}

/** Union de tudo que WS /ws/live envia. */
export type WsEvent = WsTelemetryEvent | WsStatusEvent

/** Corpo de erro da API: 404 `rack não encontrado`, 503 `influxdb indisponível`. */
export interface ApiErrorBody {
  detail: string
}

/** Estado do socket exposto para a interface. */
export type ConnectionState = 'connecting' | 'open' | 'reconnecting' | 'closed'

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null
}

function isRackStatus(value: unknown): value is RackStatus {
  return value === 'ok' || value === 'warning' || value === 'critical'
}

/** Valida no runtime o que chega pelo socket antes de entrar no estado. */
export function parseWsEvent(raw: unknown): WsEvent | null {
  if (!isRecord(raw)) return null

  if (raw.type === 'telemetry' && isRecord(raw.data)) {
    const d = raw.data
    if (
      typeof d.rack_id === 'string' &&
      typeof d.temperature === 'number' &&
      typeof d.humidity === 'number' &&
      typeof d.time === 'string' &&
      isRackStatus(d.status)
    ) {
      return {
        type: 'telemetry',
        data: {
          device_id: typeof d.device_id === 'string' ? d.device_id : '',
          rack_id: d.rack_id,
          location: typeof d.location === 'string' ? d.location : '',
          temperature: d.temperature,
          humidity: d.humidity,
          heat_index: typeof d.heat_index === 'number' ? d.heat_index : d.temperature,
          status: d.status,
          uptime_s: typeof d.uptime_s === 'number' ? d.uptime_s : 0,
          seq: typeof d.seq === 'number' ? d.seq : 0,
          time: d.time,
        },
      }
    }
    return null
  }

  if (raw.type === 'status' && isRecord(raw.data)) {
    const d = raw.data
    if (typeof d.rack_id === 'string' && typeof d.online === 'boolean') {
      return { type: 'status', data: { rack_id: d.rack_id, online: d.online } }
    }
  }

  return null
}
