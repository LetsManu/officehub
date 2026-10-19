/** "Install as app" button: shown when the browser offers to install the portal. */

import { ref } from 'vue'

interface InstallPrompt extends Event {
  prompt: () => Promise<void>
  userChoice: Promise<{ outcome: 'accepted' | 'dismissed' }>
}

let deferred: InstallPrompt | null = null
export const canInstall = ref(false)

window.addEventListener('beforeinstallprompt', (event) => {
  event.preventDefault()
  deferred = event as InstallPrompt
  canInstall.value = true
})

window.addEventListener('appinstalled', () => {
  deferred = null
  canInstall.value = false
})

export async function installApp(): Promise<void> {
  if (!deferred) return
  await deferred.prompt()
  await deferred.userChoice
  deferred = null
  canInstall.value = false
}
