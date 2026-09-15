import { onBeforeUnmount, onMounted, ref, type Ref } from 'vue'

export interface ThemeTokens {
  ink: string
  inkMuted: string
  inkFaint: string
  line: string
  panel: string
  temp: string
  umid: string
  tempFill: string
  umidFill: string
  warn: string
  crit: string
}

const TOKEN_MAP: Record<keyof ThemeTokens, string> = {
  ink: '--ink',
  inkMuted: '--ink-muted',
  inkFaint: '--ink-faint',
  line: '--line',
  panel: '--panel',
  temp: '--temp',
  umid: '--umid',
  tempFill: '--temp-fill',
  umidFill: '--umid-fill',
  warn: '--warn',
  crit: '--crit',
}

const FALLBACK: ThemeTokens = {
  ink: '#0f212a',
  inkMuted: '#4c6672',
  inkFaint: '#74909c',
  line: '#ccd8dd',
  panel: '#ffffff',
  temp: '#dd5620',
  umid: '#2a74bd',
  tempFill: 'rgba(221, 86, 32, 0.12)',
  umidFill: 'rgba(42, 116, 189, 0.1)',
  warn: '#b9720a',
  crit: '#c3341f',
}

function readTokens(): ThemeTokens {
  if (typeof window === 'undefined') return FALLBACK

  const styles = window.getComputedStyle(document.documentElement)
  const entries = Object.entries(TOKEN_MAP) as [keyof ThemeTokens, string][]

  return entries.reduce<ThemeTokens>((tokens, [key, cssVar]) => {
    const value = styles.getPropertyValue(cssVar).trim()
    if (value) tokens[key] = value
    return tokens
  }, { ...FALLBACK })
}

/**
 * Lê as cores do tema atual para alimentar o Chart.js (que desenha em canvas
 * e não enxerga variáveis CSS) e reage à troca de claro/escuro do sistema.
 */
export function useThemeTokens(): Ref<ThemeTokens> {
  const tokens = ref<ThemeTokens>(FALLBACK)
  const media = typeof window !== 'undefined' ? window.matchMedia('(prefers-color-scheme: dark)') : null

  const sync = (): void => {
    tokens.value = readTokens()
  }

  onMounted(() => {
    sync()
    media?.addEventListener('change', sync)
  })

  onBeforeUnmount(() => {
    media?.removeEventListener('change', sync)
  })

  return tokens
}
