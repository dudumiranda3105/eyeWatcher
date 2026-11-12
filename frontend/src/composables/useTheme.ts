import { ref } from 'vue'

export type Theme = 'light' | 'dark'

const STORAGE_KEY = 'eyewatcher.theme'

function initial(): Theme {
  // O index.html já aplicou o tema antes da primeira pintura.
  return document.documentElement.dataset.theme === 'dark' ? 'dark' : 'light'
}

/** Tema atual, compartilhado pela aplicação inteira. */
export const theme = ref<Theme>(initial())

export function toggleTheme(): void {
  theme.value = theme.value === 'dark' ? 'light' : 'dark'
  document.documentElement.dataset.theme = theme.value
  try {
    localStorage.setItem(STORAGE_KEY, theme.value)
  } catch {
    /* Sem storage a escolha só vale até recarregar a página. */
  }
}
