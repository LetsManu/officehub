import { createApp } from 'vue'
import App from './App.vue'
import { router } from './router'
import { setUnauthorizedHandler } from './lib/api'
import { clearSession } from './lib/session'
import { applyTheme, theme } from './lib/theme'
import { loadBranding } from './lib/branding'
import { language, setLanguage } from './lib/i18n'
import './styles.css'

applyTheme(theme.value, false)
setLanguage(language.value)
loadBranding()

setUnauthorizedHandler(() => {
  clearSession()
  const current = router.currentRoute.value
  if (!current.meta.public) router.push({ path: '/login', query: { redirect: current.fullPath } })
})

createApp(App).use(router).mount('#app')

// Installable app: register the service worker in production builds only.
if (import.meta.env.PROD && 'serviceWorker' in navigator) {
  window.addEventListener('load', () => navigator.serviceWorker.register('/sw.js').catch(() => undefined))
}
