import { ref } from 'vue'

export type Theme = 'light' | 'dark'

const KEY = 'officehub.theme'

/** The saved choice, otherwise the device setting (public/theme-init.js does the same before the first paint). */
function stored(): Theme {
  try {
    const value = localStorage.getItem(KEY)
    if (value === 'dark' || value === 'light') return value
  } catch {
    /* storage unavailable */
  }
  return window.matchMedia?.('(prefers-color-scheme: dark)').matches ? 'dark' : 'light'
}

export const theme = ref<Theme>(stored())

export function applyTheme(value: Theme, remember = true): void {
  theme.value = value
  document.documentElement.dataset.theme = value
  if (!remember) return
  try {
    localStorage.setItem(KEY, value)
  } catch {
    /* storage unavailable: the choice simply is not remembered */
  }
}
