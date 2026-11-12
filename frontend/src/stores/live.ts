import { computed, ref, shallowRef, triggerRef } from 'vue'
import { defineStore } from 'pinia'
import { http } from '@/services/api'
import type {
  Alert,
  BusMessage,
  Device,
  InferenceStatePayload,
  Job,
  PredictionPayload,
  Snapshot,
  Status,
  TelemetryPayload,
} from '@/types/api'

/** Sem leitura há este tempo, o dispositivo passa a "sem dados". */
const STALE_AFTER_MS = 8000
const RING_SIZE = 90
const RECONNECT_MAX_MS = 10000

export type Connection = 'connecting' | 'open' | 'reconnecting' | 'closed'

export interface Reading {
  metrics: Record<string, number>
  simHour: number
  on: boolean
  failed: boolean
  at: number
}

export interface Prediction extends PredictionPayload {
  at: number
}

export const useLiveStore = defineStore('live', () => {
  const connection = ref<Connection>('closed')
  const devices = ref<Device[]>([])
  const alerts = ref<Alert[]>([])
  const simulatorOnline = ref(false)
  const now = ref(Date.now())

  // Mapas com gatilho manual: chegam várias mensagens por segundo, e a cena 3D lê
  // estes dados direto no laço de animação, sem passar pela reatividade do Vue.
  const readings = shallowRef(new Map<string, Reading>())
  const predictions = shallowRef(new Map<string, Prediction>())
  const inferenceStates = shallowRef(new Map<string, InferenceStatePayload>())
  const jobs = shallowRef(new Map<string, Partial<Job>>())
  const rings = new Map<string, { t: number; v: number }[]>()

  let socket: WebSocket | null = null
  let retry = 0
  let retryTimer: number | undefined
  let clockTimer: number | undefined
  let wanted = false

  const anyLive = computed(() => {
    for (const reading of readings.value.values()) {
      if (now.value - reading.at < STALE_AFTER_MS) return true
    }
    return false
  })

  function deviceById(id: string): Device | undefined {
    return devices.value.find((device) => device.id === id)
  }

  function isFresh(id: string): boolean {
    const reading = readings.value.get(id)
    return reading !== undefined && now.value - reading.at < STALE_AFTER_MS
  }

  function ring(id: string, metric: string): { t: number; v: number }[] {
    return rings.get(`${id}/${metric}`) ?? []
  }

  function storeReading(message: BusMessage<TelemetryPayload>, at: number): void {
    const { metrics, sim_hour: simHour, on, failed } = message.payload
    readings.value.set(message.device, {
      metrics,
      simHour,
      on: on ?? true,
      failed: failed ?? false,
      at,
    })
    for (const [metric, value] of Object.entries(metrics)) {
      const key = `${message.device}/${metric}`
      const points = rings.get(key) ?? []
      points.push({ t: at, v: value })
      if (points.length > RING_SIZE) points.shift()
      rings.set(key, points)
    }
  }

  function applySnapshot(snapshot: Snapshot): void {
    simulatorOnline.value = snapshot.simulator_online
    for (const message of Object.values(snapshot.latest)) {
      storeReading(message, Date.parse(message.ts))
    }
    for (const message of Object.values(snapshot.predictions)) {
      predictions.value.set(message.device, { ...message.payload, at: Date.parse(message.ts) })
    }
    for (const message of Object.values(snapshot.inference_state)) {
      inferenceStates.value.set(message.device, message.payload)
    }
    triggerRef(readings)
    triggerRef(predictions)
    triggerRef(inferenceStates)
  }

  function applyMessage(message: BusMessage): void {
    const payload = message.payload as Record<string, unknown>
    if (message.type === 'telemetry') {
      storeReading(message as unknown as BusMessage<TelemetryPayload>, Date.now())
      triggerRef(readings)
    } else if (message.type === 'prediction') {
      predictions.value.set(message.device, {
        ...(message.payload as unknown as PredictionPayload),
        at: Date.now(),
      })
      inferenceStates.value.delete(message.device)
      triggerRef(predictions)
      triggerRef(inferenceStates)
    } else if (message.type === 'alert') {
      void loadAlerts()
    } else if (payload.kind === 'inference_state') {
      inferenceStates.value.set(message.device, message.payload as unknown as InferenceStatePayload)
      predictions.value.delete(message.device)
      triggerRef(predictions)
      triggerRef(inferenceStates)
    } else if (payload.kind === 'status') {
      simulatorOnline.value = Boolean(payload.online)
    } else if (payload.kind === 'job') {
      jobs.value.set(String(payload.job_id), payload as Partial<Job>)
      triggerRef(jobs)
    }
  }

  function status(id: string): Status {
    const device = deviceById(id)
    const reading = readings.value.get(id)
    if (!device || !reading || !isFresh(id)) return 'offline'

    if (device.kind === 'equipment') {
      if (reading.failed) return 'critical'
      const open = alerts.value.filter((alert) => alert.device_id === id && !alert.cleared_at)
      if (open.some((alert) => alert.severity === 'critical')) return 'critical'
      if (open.length > 0) return 'warning'
    }

    if (device.kind === 'actuator' || !device.metric) return 'ok'
    const value = reading.metrics[device.metric]
    if (value === undefined) return 'offline'
    const { critical_min: cMin, critical_max: cMax, normal_min: nMin, normal_max: nMax } = device
    if ((cMin !== null && value < cMin) || (cMax !== null && value > cMax)) return 'critical'
    if ((nMin !== null && value < nMin) || (nMax !== null && value > nMax)) return 'warning'
    return 'ok'
  }

  async function loadDevices(): Promise<void> {
    devices.value = (await http.get<Device[]>('/devices')).data
  }

  async function loadAlerts(): Promise<void> {
    alerts.value = (await http.get<Alert[]>('/alerts', { params: { limit: 50 } })).data
  }

  async function open(): Promise<void> {
    if (!wanted) return
    connection.value = retry === 0 ? 'connecting' : 'reconnecting'
    try {
      // Ticket curto de uso único: o token de sessão nunca aparece na URL.
      const { data } = await http.post<{ ticket: string }>('/auth/ws-ticket')
      const scheme = location.protocol === 'https:' ? 'wss' : 'ws'
      socket = new WebSocket(`${scheme}://${location.host}/ws/live?ticket=${data.ticket}`)
    } catch {
      scheduleRetry()
      return
    }
    socket.onopen = () => {
      retry = 0
      connection.value = 'open'
    }
    socket.onmessage = (event: MessageEvent<string>) => {
      const message = JSON.parse(event.data) as BusMessage | Snapshot
      if (message.type === 'snapshot') applySnapshot(message)
      else applyMessage(message)
    }
    socket.onclose = () => {
      socket = null
      if (wanted) scheduleRetry()
    }
  }

  function scheduleRetry(): void {
    connection.value = 'reconnecting'
    retry += 1
    retryTimer = window.setTimeout(() => void open(), Math.min(1000 * retry, RECONNECT_MAX_MS))
  }

  async function start(): Promise<void> {
    if (wanted) return
    wanted = true
    clockTimer = window.setInterval(() => (now.value = Date.now()), 1000)
    await Promise.all([loadDevices(), loadAlerts()])
    await open()
  }

  function stop(): void {
    wanted = false
    window.clearTimeout(retryTimer)
    window.clearInterval(clockTimer)
    socket?.close()
    socket = null
    connection.value = 'closed'
  }

  return {
    connection,
    devices,
    alerts,
    simulatorOnline,
    now,
    readings,
    predictions,
    inferenceStates,
    jobs,
    anyLive,
    deviceById,
    isFresh,
    ring,
    status,
    loadDevices,
    loadAlerts,
    start,
    stop,
  }
})
