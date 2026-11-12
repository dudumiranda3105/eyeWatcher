import { nextTick, onMounted, ref, watch, type Ref } from 'vue'
import { theme } from '@/composables/useTheme'

export interface ThemeTokens {
  ink: string
  inkMuted: string
  inkFaint: string
  line: string
  panel: string
  accent: string
  temp: string
  umid: string
  tempFill: string
  umidFill: string
  ok: string
  warn: string
  crit: string
}

const TOKEN_MAP: Record<keyof ThemeTokens, string> = {
  ink: '--ink',
  inkMuted: '--ink-muted',
  inkFaint: '--ink-faint',
  line: '--line',
  panel: '--panel',
  accent: '--accent',
  temp: '--temp',
  umid: '--umid',
  tempFill: '--temp-fill',
  umidFill: '--umid-fill',
  ok: '--ok',
  warn: '--warn',
  crit: '--crit',
}

const FALLBACK: ThemeTokens = {
  ink: '#0f212a',
  inkMuted: '#48626e',
  inkFaint: '#5f7a87',
  line: '#dbe3e8',
  panel: '#ffffff',
  accent: '#0b68c4',
  temp: '#d9541f',
  umid: '#0b68c4',
  tempFill: 'rgba(217, 84, 31, 0.12)',
  umidFill: 'rgba(11, 104, 196, 0.1)',
  ok: '#0a8375',
  warn: '#a8660a',
  crit: '#bf311d',
}

function readTokens(): ThemeTokens {
  const styles = window.getComputedStyle(document.documentElement)
  const entries = Object.entries(TOKEN_MAP) as [keyof ThemeTokens, string][]

  return entries.reduce<ThemeTokens>(
    (tokens, [key, cssVar]) => {
      const value = styles.getPropertyValue(cssVar).trim()
      if (value) tokens[key] = value
      return tokens
    },
    { ...FALLBACK },
  )
}

/**
 * Lê as cores do tema atual para alimentar o Chart.js (que desenha em canvas
 * e não enxerga variáveis CSS) e reage à troca de claro/escuro.
 */
export function useThemeTokens(): Ref<ThemeTokens> {
  const tokens = ref<ThemeTokens>(FALLBACK)

  const sync = (): void => {
    tokens.value = readTokens()
  }

  onMounted(sync)
  watch(theme, () => void nextTick(sync))

  return tokens
}
