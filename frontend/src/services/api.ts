import axios, { AxiosError } from 'axios'

const TOKEN_KEY = 'eyewatcher.token'

export function readToken(): string | null {
  try {
    return sessionStorage.getItem(TOKEN_KEY)
  } catch {
    return null
  }
}

export function storeToken(token: string | null): void {
  try {
    if (token) sessionStorage.setItem(TOKEN_KEY, token)
    else sessionStorage.removeItem(TOKEN_KEY)
  } catch {
    /* Sem storage a sessão só vale até recarregar a página. */
  }
}

export const http = axios.create({ baseURL: '/api', timeout: 15000 })

http.interceptors.request.use((config) => {
  const token = readToken()
  if (token) config.headers.Authorization = `Bearer ${token}`
  return config
})

let onUnauthorized: () => void = () => undefined

export function setUnauthorizedHandler(handler: () => void): void {
  onUnauthorized = handler
}

http.interceptors.response.use(undefined, (error: AxiosError) => {
  if (error.response?.status === 401 && !error.config?.url?.includes('/auth/login')) {
    onUnauthorized()
  }
  return Promise.reject(error)
})

/** Mensagem legível de um erro da API. */
export function errorMessage(error: unknown): string {
  if (error instanceof AxiosError) {
    const detail = (error.response?.data as { detail?: unknown } | undefined)?.detail
    if (typeof detail === 'string') return detail
    if (Array.isArray(detail)) return String((detail[0] as { msg?: string }).msg ?? 'dados inválidos')
    return error.message
  }
  return error instanceof Error ? error.message : 'erro inesperado'
}
