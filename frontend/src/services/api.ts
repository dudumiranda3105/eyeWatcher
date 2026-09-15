import axios, { AxiosError, type AxiosInstance } from 'axios'
import type {
  AlertsResponse,
  ApiErrorBody,
  HealthResponse,
  HistoryResponse,
  LatestReadingResponse,
  RacksResponse,
  RangeKey,
  StatsResponse,
} from '@/types/api'

const BASE_URL = import.meta.env.VITE_API_BASE_URL ?? '/api'

/** Erro normalizado: mensagem já pronta para a interface, em pt-BR. */
export class ApiError extends Error {
  readonly status: number | null
  readonly route: string

  constructor(message: string, status: number | null, route: string) {
    super(message)
    this.name = 'ApiError'
    this.status = status
    this.route = route
  }

  /** 404 = rack sem dados ainda; a tela mostra "aguardando leitura" em vez de erro. */
  get isNotFound(): boolean {
    return this.status === 404
  }
}

const client: AxiosInstance = axios.create({
  baseURL: BASE_URL,
  timeout: 8000,
  headers: { Accept: 'application/json' },
})

function isApiErrorBody(value: unknown): value is ApiErrorBody {
  return typeof value === 'object' && value !== null && typeof (value as ApiErrorBody).detail === 'string'
}

function toApiError(error: unknown, route: string): ApiError {
  if (axios.isAxiosError(error)) {
    const axiosError: AxiosError<unknown> = error
    const status = axiosError.response?.status ?? null
    const body: unknown = axiosError.response?.data
    const detail = isApiErrorBody(body) ? body.detail : null

    if (status === null) {
      const timedOut = axiosError.code === 'ECONNABORTED'
      return new ApiError(
        timedOut
          ? 'O backend não respondeu a tempo. Confira se ele está processando as leituras.'
          : 'Sem resposta do backend. Inicie a API em localhost:8000 e recarregue.',
        null,
        route,
      )
    }

    switch (status) {
      case 404:
        return new ApiError(detail ?? 'Rack não encontrado.', status, route)
      case 422:
        return new ApiError(detail ?? 'Período inválido para esta consulta.', status, route)
      case 503:
        return new ApiError(
          detail ?? 'InfluxDB indisponível. O backend está no ar, mas não alcança o banco.',
          status,
          route,
        )
      case 502:
      case 504:
        // O proxy do Vite responde isto quando não alcança o FastAPI.
        return new ApiError(
          'O backend não está respondendo em localhost:8000. Suba a API e tente de novo.',
          status,
          route,
        )
      default:
        return new ApiError(detail ?? `A API respondeu ${status} em ${route}.`, status, route)
    }
  }

  return new ApiError('Falha inesperada ao consultar a API.', null, route)
}

async function get<T>(route: string, params?: Record<string, string | number>): Promise<T> {
  try {
    const response = await client.get<T>(route, { params })
    return response.data
  } catch (error) {
    throw toApiError(error, route)
  }
}

/** GET /api/health */
export function fetchHealth(): Promise<HealthResponse> {
  return get<HealthResponse>('/health')
}

/** GET /api/racks */
export function fetchRacks(): Promise<RacksResponse> {
  return get<RacksResponse>('/racks')
}

/** GET /api/readings/latest?rack_id= */
export function fetchLatestReading(rackId: string): Promise<LatestReadingResponse> {
  return get<LatestReadingResponse>('/readings/latest', { rack_id: rackId })
}

/** GET /api/readings/history?rack_id=&range=&window= */
export function fetchHistory(
  rackId: string,
  range: RangeKey,
  aggregationWindow?: string,
): Promise<HistoryResponse> {
  const params: Record<string, string> = { rack_id: rackId, range }
  if (aggregationWindow) params.window = aggregationWindow
  return get<HistoryResponse>('/readings/history', params)
}

/** GET /api/readings/stats?rack_id=&range= */
export function fetchStats(rackId: string, range: RangeKey): Promise<StatsResponse> {
  return get<StatsResponse>('/readings/stats', { rack_id: rackId, range })
}

/** GET /api/alerts?rack_id=&range=&limit= */
export function fetchAlerts(rackId: string, range: RangeKey, limit = 50): Promise<AlertsResponse> {
  return get<AlertsResponse>('/alerts', { rack_id: rackId, range, limit })
}

export const apiBaseUrl = BASE_URL
