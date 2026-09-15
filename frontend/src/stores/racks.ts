import { computed, ref } from 'vue'
import { defineStore } from 'pinia'
import {
  ApiError,
  fetchAlerts,
  fetchHistory,
  fetchLatestReading,
  fetchStats,
} from '@/services/api'
import { LiveClient } from '@/services/ws'
import type {
  AlertItem,
  ConnectionState,
  HistoryPoint,
  RackStatus,
  RangeKey,
  Reading,
  StatsResponse,
  WsEvent,
} from '@/types/api'
import { humidityStatus, temperatureStatus, worstStatus } from '@/utils/thresholds'

const DEFAULT_RACK_ID = import.meta.env.VITE_RACK_ID ?? 'rack01'

/** Fallback de polling quando o WebSocket não está aberto. */
const FALLBACK_POLL_MS = 10_000
/** Atualização periódica de histórico/stats/alertas mesmo com o socket vivo. */
const DERIVED_REFRESH_MS = 60_000
/** Relógio interno para textos relativos ("há 4 s"). */
const CLOCK_TICK_MS = 1_000
/** Sem leitura por mais que isto, o painel considera o sensor mudo. */
const STALE_AFTER_MS = 20_000

/** Espaçamento mínimo entre pontos ao vivo, por período exibido. */
const LIVE_POINT_SPACING_MS: Record<RangeKey, number> = {
  '15m': 0,
  '1h': 15_000,
  '6h': 60_000,
  '24h': 120_000,
  '7d': 600_000,
  '30d': 1_800_000,
}

const MAX_LIVE_POINTS = 400

export interface MetricTrend {
  delta: number
  direction: 'up' | 'down' | 'flat'
}

export const useRacksStore = defineStore('racks', () => {
  // --- identificação ---------------------------------------------------
  const rackId = ref<string>(DEFAULT_RACK_ID)
  const deviceId = ref<string>('')
  const location = ref<string>('')

  // --- leitura atual ---------------------------------------------------
  const current = ref<Reading | null>(null)
  const previous = ref<Reading | null>(null)
  const uptimeSeconds = ref<number | null>(null)
  const lastSeq = ref<number | null>(null)
  const deviceOnline = ref<boolean>(false)

  // --- séries e agregados ----------------------------------------------
  const range = ref<RangeKey>('6h')
  const history = ref<HistoryPoint[]>([])
  const livePoints = ref<HistoryPoint[]>([])
  const stats = ref<StatsResponse | null>(null)
  const alerts = ref<AlertItem[]>([])
  const alertsCount = ref<number>(0)

  // --- estado de carregamento e erro -----------------------------------
  const initializing = ref<boolean>(true)
  const loadingHistory = ref<boolean>(false)
  const connectionError = ref<string | null>(null)
  const historyError = ref<string | null>(null)
  const hasBackendData = ref<boolean>(false)

  // --- conexão ----------------------------------------------------------
  const connection = ref<ConnectionState>('closed')
  const now = ref<number>(Date.now())

  let liveClient: LiveClient | null = null
  let fallbackTimer: ReturnType<typeof setInterval> | null = null
  let derivedTimer: ReturnType<typeof setInterval> | null = null
  let clockTimer: ReturnType<typeof setInterval> | null = null

  // --- getters ----------------------------------------------------------

  /** Sem leitura recente: o dispositivo pode estar mudo mesmo "online". */
  const isStale = computed<boolean>(() => {
    if (!current.value) return true
    return now.value - new Date(current.value.time).getTime() > STALE_AFTER_MS
  })

  const isOnline = computed<boolean>(() => deviceOnline.value && !isStale.value)

  const overallStatus = computed<RackStatus>(() => {
    const reading = current.value
    if (!reading) return 'ok'
    return worstStatus(temperatureStatus(reading.temperature), humidityStatus(reading.humidity))
  })

  const temperatureStatusValue = computed<RackStatus>(() =>
    current.value ? temperatureStatus(current.value.temperature) : 'ok',
  )

  const humidityStatusValue = computed<RackStatus>(() =>
    current.value ? humidityStatus(current.value.humidity) : 'ok',
  )

  /** Série exibida no gráfico: histórico agregado + cauda ao vivo. */
  const chartPoints = computed<HistoryPoint[]>(() => {
    if (livePoints.value.length === 0) return history.value
    return [...history.value, ...livePoints.value]
  })

  const hasHistory = computed<boolean>(() => chartPoints.value.length > 0)

  /** Backend responde, mas ainda não há nenhuma leitura gravada. */
  const awaitingFirstReading = computed<boolean>(
    () => !initializing.value && connectionError.value === null && !current.value && !hasHistory.value,
  )

  const usingFallback = computed<boolean>(() => connection.value !== 'open')

  function trendFor(metric: 'temperature' | 'humidity' | 'heat_index'): MetricTrend | null {
    const latest = current.value
    const before = previous.value
    if (!latest || !before) return null

    const delta = latest[metric] - before[metric]
    if (Math.abs(delta) < 0.05) return { delta: 0, direction: 'flat' }
    return { delta, direction: delta > 0 ? 'up' : 'down' }
  }

  const temperatureTrend = computed<MetricTrend | null>(() => trendFor('temperature'))
  const humidityTrend = computed<MetricTrend | null>(() => trendFor('humidity'))
  const heatIndexTrend = computed<MetricTrend | null>(() => trendFor('heat_index'))

  // --- carregamento -----------------------------------------------------

  function applyReading(reading: Reading): void {
    if (current.value && current.value.time !== reading.time) {
      previous.value = current.value
    }
    current.value = reading
    hasBackendData.value = true
  }

  async function refreshLatest(): Promise<void> {
    try {
      const data = await fetchLatestReading(rackId.value)
      deviceId.value = data.device_id
      location.value = data.location
      deviceOnline.value = data.online
      applyReading({
        time: data.time,
        temperature: data.temperature,
        humidity: data.humidity,
        heat_index: data.heat_index,
        status: data.status,
      })
      connectionError.value = null
    } catch (error) {
      if (error instanceof ApiError && error.isNotFound) {
        // Rack ainda sem dados: estado vazio, não é falha.
        connectionError.value = null
        current.value = null
        return
      }
      connectionError.value = error instanceof ApiError ? error.message : 'Falha ao ler a última medição.'
    }
  }

  async function refreshHistory(): Promise<void> {
    loadingHistory.value = true
    try {
      const data = await fetchHistory(rackId.value, range.value)
      history.value = data.points
      historyError.value = null
      if (data.points.length > 0) hasBackendData.value = true
    } catch (error) {
      if (error instanceof ApiError && error.isNotFound) {
        history.value = []
        historyError.value = null
      } else {
        historyError.value =
          error instanceof ApiError ? error.message : 'Falha ao carregar o histórico.'
      }
    } finally {
      loadingHistory.value = false
    }
  }

  async function refreshStats(): Promise<void> {
    try {
      stats.value = await fetchStats(rackId.value, range.value)
    } catch (error) {
      if (error instanceof ApiError && error.isNotFound) stats.value = null
    }
  }

  async function refreshAlerts(): Promise<void> {
    try {
      const data = await fetchAlerts(rackId.value, range.value)
      alerts.value = data.alerts
      alertsCount.value = data.count
    } catch (error) {
      if (error instanceof ApiError && error.isNotFound) {
        alerts.value = []
        alertsCount.value = 0
      }
    }
  }

  /** Recarrega tudo que depende do período selecionado. */
  async function refreshDerived(): Promise<void> {
    await Promise.all([refreshHistory(), refreshStats(), refreshAlerts()])
  }

  async function setRange(next: RangeKey): Promise<void> {
    if (next === range.value) return
    range.value = next
    livePoints.value = []
    await refreshDerived()
  }

  /** Botão "Tentar novamente" do estado de erro. */
  async function retry(): Promise<void> {
    initializing.value = true
    await refreshLatest()
    await refreshDerived()
    initializing.value = false
    liveClient?.connect()
  }

  // --- tempo real -------------------------------------------------------

  function appendLivePoint(point: HistoryPoint): void {
    const spacing = LIVE_POINT_SPACING_MS[range.value]
    const tail = livePoints.value[livePoints.value.length - 1]
    const previousTime = tail
      ? new Date(tail.time).getTime()
      : new Date(history.value[history.value.length - 1]?.time ?? 0).getTime()

    if (spacing > 0 && new Date(point.time).getTime() - previousTime < spacing) {
      if (tail) livePoints.value[livePoints.value.length - 1] = point
      return
    }

    livePoints.value = [...livePoints.value, point].slice(-MAX_LIVE_POINTS)
  }

  function handleEvent(event: WsEvent): void {
    if (event.data.rack_id !== rackId.value) return

    if (event.type === 'status') {
      deviceOnline.value = event.data.online
      return
    }

    const payload = event.data
    deviceOnline.value = true
    deviceId.value = payload.device_id || deviceId.value
    location.value = payload.location || location.value
    uptimeSeconds.value = payload.uptime_s
    lastSeq.value = payload.seq
    connectionError.value = null

    applyReading({
      time: payload.time,
      temperature: payload.temperature,
      humidity: payload.humidity,
      heat_index: payload.heat_index,
      status: payload.status,
    })

    appendLivePoint({
      time: payload.time,
      temperature: payload.temperature,
      humidity: payload.humidity,
      heat_index: payload.heat_index,
    })
  }

  function startLive(): void {
    if (liveClient) return
    liveClient = new LiveClient({
      onEvent: handleEvent,
      onStateChange: (state) => {
        connection.value = state
      },
    })
    liveClient.connect()
  }

  function startTimers(): void {
    clockTimer ??= setInterval(() => {
      now.value = Date.now()
    }, CLOCK_TICK_MS)

    // Fallback: enquanto o socket não estiver aberto, busca a última leitura por HTTP.
    fallbackTimer ??= setInterval(() => {
      if (connection.value === 'open') return
      void refreshLatest()
    }, FALLBACK_POLL_MS)

    derivedTimer ??= setInterval(() => {
      void refreshStats()
      void refreshAlerts()
      if (connection.value !== 'open') void refreshHistory()
    }, DERIVED_REFRESH_MS)
  }

  /** Chamado uma vez no onMounted do App. */
  async function initialize(): Promise<void> {
    initializing.value = true
    await refreshLatest()
    await refreshDerived()
    initializing.value = false
    startLive()
    startTimers()
  }

  /** Encerra socket e timers — chamado no onBeforeUnmount do App. */
  function dispose(): void {
    liveClient?.close()
    liveClient = null
    connection.value = 'closed'

    for (const timer of [fallbackTimer, derivedTimer, clockTimer]) {
      if (timer !== null) clearInterval(timer)
    }
    fallbackTimer = null
    derivedTimer = null
    clockTimer = null
  }

  return {
    // estado
    rackId,
    deviceId,
    location,
    current,
    previous,
    uptimeSeconds,
    lastSeq,
    deviceOnline,
    range,
    history,
    livePoints,
    stats,
    alerts,
    alertsCount,
    initializing,
    loadingHistory,
    connectionError,
    historyError,
    hasBackendData,
    connection,
    now,
    // getters
    isStale,
    isOnline,
    overallStatus,
    temperatureStatusValue,
    humidityStatusValue,
    chartPoints,
    hasHistory,
    awaitingFirstReading,
    usingFallback,
    temperatureTrend,
    humidityTrend,
    heatIndexTrend,
    // ações
    initialize,
    dispose,
    setRange,
    retry,
    refreshDerived,
    refreshLatest,
  }
})
