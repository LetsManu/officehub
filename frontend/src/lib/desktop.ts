/**
 * Notifications on the computer (outside the browser tab) and a soft sound, like Teams does for new
 * messages, mentions, calls and meeting reminders. Nothing is sent through outside push services: this
 * works while OfficeHub is open, also as a background tab or as the installed app.
 */

import { reactive } from 'vue'
import { router } from '../router'
import { myPresence } from './presence'

const KEY = 'officehub-desktop'

function load(): { desktop: boolean; sound: boolean } {
  try {
    return { desktop: false, sound: true, ...JSON.parse(localStorage.getItem(KEY) ?? '{}') }
  } catch {
    return { desktop: false, sound: true }
  }
}

export const desktopPrefs = reactive(load())

export function saveDesktopPrefs() {
  try {
    localStorage.setItem(KEY, JSON.stringify(desktopPrefs))
  } catch {
    /* private window */
  }
}

export const desktopSupported = typeof window !== 'undefined' && 'Notification' in window

export function desktopAllowed() {
  return desktopSupported && Notification.permission === 'granted' && desktopPrefs.desktop
}

/** Ask the browser once (must follow a click). */
export async function enableDesktop(): Promise<boolean> {
  if (!desktopSupported) return false
  const answer = Notification.permission === 'granted' ? 'granted' : await Notification.requestPermission()
  desktopPrefs.desktop = answer === 'granted'
  saveDesktopPrefs()
  return desktopPrefs.desktop
}

/** "Do not disturb": no sounds and no pop-ups. */
export function quiet() {
  return myPresence.value.state === 'dnd'
}

let audio: AudioContext | null = null

export function chime(kind: 'message' | 'reminder' = 'message') {
  if (!desktopPrefs.sound || quiet()) return
  try {
    audio ??= new AudioContext()
    const now = audio.currentTime
    const notes = kind === 'message' ? [[0, 740], [0.12, 988]] : [[0, 659], [0.18, 880], [0.36, 659]]
    for (const [start, freq] of notes) {
      const osc = audio.createOscillator()
      const gain = audio.createGain()
      osc.frequency.value = freq
      gain.gain.setValueAtTime(0, now + start)
      gain.gain.linearRampToValueAtTime(0.08, now + start + 0.02)
      gain.gain.linearRampToValueAtTime(0, now + start + 0.18)
      osc.connect(gain).connect(audio.destination)
      osc.start(now + start)
      osc.stop(now + start + 0.2)
    }
  } catch {
    /* the browser allows sound only after the page was clicked once */
  }
}

/** Is the person looking at the portal right now? Then the page itself shows it, no pop-up needed. */
export function looking() {
  return document.visibilityState === 'visible' && document.hasFocus()
}

export async function notifyDesktop(n: { title: string; body: string; link?: string; tag: string; sticky?: boolean }) {
  if (!desktopAllowed() || quiet() || looking()) return
  const options: NotificationOptions = { body: n.body, tag: n.tag, icon: '/icon-192.png', badge: '/icon-192.png', data: { url: n.link ?? '/' }, requireInteraction: !!n.sticky }
  try {
    const registration = await navigator.serviceWorker?.getRegistration?.()
    if (registration) {
      await registration.showNotification(n.title, options)
      return
    }
    const shown = new Notification(n.title, options)
    shown.onclick = () => {
      window.focus()
      if (n.link) router.push(n.link)
      shown.close()
    }
  } catch {
    /* blocked or not supported here */
  }
}

/** A click on a notification shown by the service worker opens the page here. */
export function listenForNotificationClicks() {
  navigator.serviceWorker?.addEventListener?.('message', (event) => {
    const url = (event.data as { navigate?: string } | null)?.navigate
    if (url && url.startsWith('/')) router.push(url)
  })
}
