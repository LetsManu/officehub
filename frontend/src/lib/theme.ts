import { ref } from 'vue'

export type Theme = 'light' | 'dark'

const KEY = 'officehub.theme'

function stored(): Theme {
  try {
    return localStorage.getItem(KEY) === 'dark' ? 'dark' : 'light'
  } catch {
    return 'light'
  }
}

export const theme = ref<Theme>(stored())

export function applyTheme(value: Theme): void {
  theme.value = value
  document.documentElement.dataset.theme = value
  try {
    localStorage.setItem(KEY, value)
  } catch {
    /* storage unavailable: the choice simply is not remembered */
  }
}
