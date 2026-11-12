export type Role = 'viewer' | 'operator' | 'admin'
export type Status = 'ok' | 'warning' | 'critical' | 'offline'
export type DeviceKind = 'sensor' | 'actuator' | 'equipment'
export type RangeKey = '15m' | '1h' | '6h' | '24h' | '7d' | '30d'

export interface Device {
  id: string
  name: string
  kind: DeviceKind
  type: string
  zone: string
  metric: string | null
  unit: string | null
  normal_min: number | null
  normal_max: number | null
  critical_min: number | null
  critical_max: number | null
  controllable: boolean
  enabled: boolean
}

export interface Rule {
  id: number
  name: string
  device_id: string
  metric: string
  threshold: number
  clear_threshold: number
  actuator_id: string
  severity: 'warning' | 'critical'
  enabled: boolean
}

/** Mensagem do barramento, com o formato único do sistema. */
export interface BusMessage<T = Record<string, unknown>> {
  routing_key: string
  id: string
  ts: string
  type: 'telemetry' | 'command' | 'prediction' | 'alert' | 'event' | 'job'
  device: string
  payload: T
}

export interface TelemetryPayload {
  metrics: Record<string, number>
  sim_hour: number
  on?: boolean
  failed?: boolean
}

export interface PredictionPayload {
  health: number
  rul_h: number
  trend_per_h: number
  model_version: string
}

export interface InferenceStatePayload {
  kind: 'inference_state'
  state: 'off' | 'no_model' | 'warming_up'
  model_version: string | null
}

export interface Snapshot {
  type: 'snapshot'
  latest: Record<string, BusMessage<TelemetryPayload>>
  predictions: Record<string, BusMessage<PredictionPayload>>
  inference_state: Record<string, BusMessage<InferenceStatePayload>>
  simulator_online: boolean
}

export interface Alert {
  id: number
  device_id: string
  source: string
  severity: 'warning' | 'critical'
  message: string
  opened_at: string
  cleared_at: string | null
}

export interface Job {
  id: string
  kind: 'datagen' | 'training'
  status: 'queued' | 'running' | 'done' | 'failed'
  progress: number
  stage: string | null
  params: Record<string, unknown>
  result: Record<string, unknown> | null
  created_by: string
  created_at: string
  finished_at: string | null
}

export interface Score {
  mae: number
  rmse: number
  r2: number
}

export interface ModelReport {
  target: string
  validation: Score
  test: Score
  test_degrading: Score | null
  baseline: Score
  baseline_degrading: Score | null
  beats_baseline: boolean
  importance: { feature: string; value: number }[]
  scatter: { real: number; predicted: number }[]
}

export interface ModelVersion {
  version: string
  trained_at: string
  dataset: string
  promoted: boolean
  summary: {
    rows: Record<string, number>
    equipment: Record<string, number>
    models: Record<string, ModelReport>
  }
}

export interface QueueInfo {
  name: string
  messages: number
  ready: number
  unacked: number
  consumers: number
  publish_rate: number
  deliver_rate: number
}

export interface MessagingOverview {
  publish_rate: number
  deliver_rate: number
  queues: QueueInfo[]
  consumers: { queue: string; tag: string; service: string | null }[]
  recent: BusMessage[]
}

export interface DlqMessage {
  routing_key: string
  payload: string
  death: { queue: string; reason: string; count: number }[] | null
  origin: string | null
}

export interface AuditEntry {
  id: number
  ts: string
  username: string
  action: string
  target: string | null
  detail: Record<string, unknown>
  ip: string | null
}

export interface HistoryPoint {
  time: string
  value: number
}

export interface LabOptions {
  failure_modes: string[]
  defaults: Record<string, unknown>
  min_readings: number
  max_readings: number
  sample_minutes: number
}
