/**
 * The Windows and Android apps (apps/windows, apps/android) show this portal in their own window, like Teams does.
 * Here the page hands them what only an app can do: notifications from Windows or Android itself, the number on
 * the app icon, a ringing call while the window is hidden, and (Android) the wording for notifications the app
 * shows in the background. In a normal browser none of this exists and everything stays as before.
 *
 * The apps answer by sending an "officehub-app" event to the page: { navigate: '/chat/3' } or
 * { call: 12, action: 'accept' | 'decline' }.
 */

import { language, t } from './i18n'
import de from '@/locales/de'

type Invoke = (cmd: string, args?: Record<string, unknown>) => Promise<unknown>

interface AndroidBridge {
  post(message: string): void
}

const win = (typeof window !== 'undefined' ? window : {}) as unknown as {
  OfficeHubAndroid?: AndroidBridge
  __TAURI_INTERNALS__?: { invoke?: Invoke }
}

/** Which app hosts the portal, if any. */
export function appKind(): 'windows' | 'android' | null {
  if (win.OfficeHubAndroid) return 'android'
  if (win.__TAURI_INTERNALS__?.invoke) return 'windows'
  return null
}

export const inApp = () => appKind() !== null

function send(message: Record<string, unknown>) {
  try {
    if (win.OfficeHubAndroid) win.OfficeHubAndroid.post(JSON.stringify(message))
    else void win.__TAURI_INTERNALS__?.invoke?.('app_message', { message }).catch(() => undefined)
  } catch {
    /* the app went away */
  }
}

/** A notification from Windows. Android shows its own from the background connection (no doubles). */
export function appNotify(n: { title: string; body: string; link?: string; tag: string; sticky?: boolean }) {
  if (appKind() === 'windows') send({ type: 'notify', ...n })
}

export function appBadge(count: number) {
  send({ type: 'badge', count })
}

/** A call rings (or stops ringing: null). The app shows its own ringing window when the portal is hidden. */
export function appRing(call: { meeting_id: number; name: string; text: string } | null) {
  send(call ? { type: 'ring', ...call, accept: t('call.accept'), decline: t('call.decline') } : { type: 'ring-stop' })
}

/** Android writes notifications itself while the app is closed: it gets the wording in the person's language. */
export function appTexts() {
  if (appKind() !== 'android') return
  const kinds: Record<string, string> = {}
  for (const kind of Object.keys(de.notifications.kinds)) kinds[kind] = t(`notifications.kinds.${kind}`)
  const requestTypes: Record<string, string> = {}
  for (const type of Object.keys(de.requestTypes)) requestTypes[type] = t(`requestTypes.${type}`)
  send({
    type: 'texts',
    language: language.value,
    kinds,
    requestTypes,
    callIncoming: t('call.incoming'),
    callAccept: t('call.accept'),
    callDecline: t('call.decline'),
    callPreview: t('chat.callPreview'),
    reminderNow: t('reminder.now'),
    reminderIn: t('reminder.inMinutes', { n: '{n}' }),
    channelName: t('app.name'),
  })
}

/** Signed in (or out): the Android app starts or stops its background connection. */
export function appSignedIn(signedIn: boolean) {
  send({ type: 'session', signedIn })
}

export interface AppEvent {
  navigate?: string
  call?: number
  action?: 'accept' | 'decline'
}

export function onAppEvent(handler: (event: AppEvent) => void): () => void {
  const listener = (e: Event) => handler((e as CustomEvent<AppEvent>).detail ?? {})
  window.addEventListener('officehub-app', listener)
  return () => window.removeEventListener('officehub-app', listener)
}
