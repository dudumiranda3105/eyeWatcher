/// <reference types="vite/client" />

interface ImportMetaEnv {
  /** Base das rotas HTTP. Default `/api` (passa pelo proxy do Vite). */
  readonly VITE_API_BASE_URL?: string
  /** URL completa do WebSocket. Default: mesma origem + `/ws/live`. */
  readonly VITE_WS_URL?: string
  /** Rack exibido no painel. Default `rack01`. */
  readonly VITE_RACK_ID?: string
  /** Alvo do proxy em dev (lido só pelo vite.config.ts). */
  readonly VITE_BACKEND_TARGET?: string
}

interface ImportMeta {
  readonly env: ImportMetaEnv
}
