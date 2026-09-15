import { parseWsEvent, type ConnectionState, type WsEvent } from '@/types/api'

const WS_PATH = '/ws/live'
const BASE_DELAY_MS = 1000
const MAX_DELAY_MS = 30000

export interface LiveClientOptions {
  /** Chamado a cada evento válido recebido. Eventos malformados são descartados. */
  onEvent: (event: WsEvent) => void
  /** Chamado a cada transição de estado da conexão. */
  onStateChange?: (state: ConnectionState) => void
  /** Sobrescreve a URL; por padrão usa a origem atual + /ws/live (proxy do Vite). */
  url?: string
}

/** Monta a URL do socket a partir da origem atual, respeitando http/https. */
export function resolveWsUrl(): string {
  const configured = import.meta.env.VITE_WS_URL
  if (configured) return configured

  const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
  return `${protocol}//${window.location.host}${WS_PATH}`
}

/**
 * Cliente do /ws/live com reconexão exponencial (1s → 30s, com jitter).
 * Uma instância = uma conexão; chame `close()` no unmount.
 */
export class LiveClient {
  private socket: WebSocket | null = null
  private retryTimer: ReturnType<typeof setTimeout> | null = null
  private attempt = 0
  private disposed = false
  private state: ConnectionState = 'closed'

  private readonly url: string
  private readonly onEvent: (event: WsEvent) => void
  private readonly onStateChange: ((state: ConnectionState) => void) | undefined

  constructor(options: LiveClientOptions) {
    this.url = options.url ?? resolveWsUrl()
    this.onEvent = options.onEvent
    this.onStateChange = options.onStateChange
  }

  get currentState(): ConnectionState {
    return this.state
  }

  /** Abre a conexão. Idempotente enquanto houver socket vivo. */
  connect(): void {
    if (this.disposed) return
    if (this.socket && (this.socket.readyState === WebSocket.OPEN || this.socket.readyState === WebSocket.CONNECTING)) {
      return
    }

    this.setState(this.attempt === 0 ? 'connecting' : 'reconnecting')

    let socket: WebSocket
    try {
      socket = new WebSocket(this.url)
    } catch {
      this.scheduleReconnect()
      return
    }

    this.socket = socket

    socket.onopen = () => {
      this.attempt = 0
      this.setState('open')
    }

    socket.onmessage = (message: MessageEvent<unknown>) => {
      if (typeof message.data !== 'string') return
      let parsed: unknown
      try {
        parsed = JSON.parse(message.data)
      } catch {
        return
      }
      const event = parseWsEvent(parsed)
      if (event) this.onEvent(event)
    }

    socket.onerror = () => {
      // O fechamento vem logo em seguida; a reconexão é tratada em onclose.
    }

    socket.onclose = () => {
      this.socket = null
      if (this.disposed) return
      this.scheduleReconnect()
    }
  }

  /** Fecha a conexão e cancela retentativas. Seguro chamar mais de uma vez. */
  close(): void {
    this.disposed = true
    if (this.retryTimer !== null) {
      clearTimeout(this.retryTimer)
      this.retryTimer = null
    }
    if (this.socket) {
      this.socket.onopen = null
      this.socket.onmessage = null
      this.socket.onerror = null
      this.socket.onclose = null
      this.socket.close()
      this.socket = null
    }
    this.setState('closed')
  }

  /** Atraso da próxima tentativa, em ms — exposto para exibir na interface. */
  get nextDelayMs(): number {
    return Math.min(BASE_DELAY_MS * 2 ** this.attempt, MAX_DELAY_MS)
  }

  private scheduleReconnect(): void {
    if (this.retryTimer !== null) return

    const delay = this.nextDelayMs
    const jitter = Math.random() * 250
    this.attempt = Math.min(this.attempt + 1, 10)
    this.setState('reconnecting')

    this.retryTimer = setTimeout(() => {
      this.retryTimer = null
      this.connect()
    }, delay + jitter)
  }

  private setState(next: ConnectionState): void {
    if (this.state === next) return
    this.state = next
    this.onStateChange?.(next)
  }
}
