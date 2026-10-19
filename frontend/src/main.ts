import { createApp } from 'vue'
import App from './App.vue'
import { router } from './router'
import { setUnauthorizedHandler } from './lib/api'
import { clearSession } from './lib/session'
import { applyTheme, theme } from './lib/theme'
import { language, setLanguage } from './lib/i18n'
import './styles.css'

applyTheme(theme.value, false)
setLanguage(language.value)

setUnauthorizedHandler(() => {
  clearSession()
  const current = router.currentRoute.value
  if (!current.meta.public) router.push({ path: '/login', query: { redirect: current.fullPath } })
})

createApp(App).use(router).mount('#app')
