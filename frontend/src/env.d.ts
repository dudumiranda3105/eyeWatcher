/// <reference types="vite/client" />

interface ImportMetaEnv {
  /** Alvo do proxy em dev (lido só pelo vite.config.ts). */
  readonly VITE_BACKEND_TARGET?: string
}

interface ImportMeta {
  readonly env: ImportMetaEnv
}
