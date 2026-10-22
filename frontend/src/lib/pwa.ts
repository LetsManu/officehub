/**
 * The portal as an installed app: whether it runs as one, which device it is on (for the install steps),
 * whether the network is there, the number on the app icon, and whether a newer version is running on the
 * server (then it offers to reload).
 */

import { ref } from 'vue'
import { appBadge } from './native'

export type Platform = 'ios' | 'android' | 'desktop'

/** Opened from the installed app (not in a browser tab). */
export function isStandalone(): boolean {
  const nav = navigator as Navigator & { standalone?: boolean }
  return window.matchMedia?.('(display-mode: standalone)').matches || nav.standalone === true
}

export function platform(): Platform {
  const ua = navigator.userAgent
  // iPads report themselves as a Mac but have a touch screen.
  if (/iPhone|iPad|iPod/.test(ua) || (/Macintosh/.test(ua) && navigator.maxTouchPoints > 1)) return 'ios'
  if (/Android/.test(ua)) return 'android'
  return 'desktop'
}

export const online = ref(navigator.onLine)
window.addEventListener('online', () => (online.value = true))
window.addEventListener('offline', () => (online.value = false))

/** Unread messages and notifications on the app icon (where the system supports it). */
export function setBadge(count: number): void {
  appBadge(count)
  const nav = navigator as Navigator & { setAppBadge?: (n?: number) => Promise<void>; clearAppBadge?: () => Promise<void> }
  if (count > 0) nav.setAppBadge?.(count).catch(() => undefined)
  else nav.clearAppBadge?.().catch(() => undefined)
}

let knownVersion = ''
export const updateReady = ref(false)

/** The version the server runs; a different one than at the start means OfficeHub was updated. */
export function noteVersion(version: string | undefined): void {
  if (!version) return
  if (!knownVersion) knownVersion = version
  else if (version !== knownVersion) updateReady.value = true
}

export function reload(): void {
  window.location.reload()
}
