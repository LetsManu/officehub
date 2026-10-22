/**
 * The Windows and Android apps (apps/windows, apps/android) show this portal in their own window, like Teams does.
 * Here the page hands them what only an app can do: notifications from Windows or Android itself, the number on
 * the app icon, a ringing call while the window is hidden, and (Android) the wording for notifications the app
 * shows in the background. In a normal browser none of this exists and everything stays as before.
 *
 * The apps answer by sending an "officehub-app" event to the page: { navigate: '/chat/3' },
 * { call: 12, action: 'accept' | 'decline' }, { menu: true } (Android's "More" tab) or { status: 'busy' } (Windows tray).
 * What another Android app shared waits in the app: /share?from=app reads it from /__app/share/* (only the app's
 * WebView answers these addresses).
 */

import { language, t } from './i18n'
import de from '@/locales/de'

type Invoke = (cmd: string, args?: Record<string, unknown>) => Promise<unknown>

/** Android: a WebMessageListener only the company's address can reach (apps/android MainActivity). */
interface AndroidBridge {
  postMessage(message: string): void
}

type Host = { OfficeHubAndroid?: AndroidBridge; __TAURI_INTERNALS__?: { invoke?: Invoke } }

const host = () => (typeof window !== 'undefined' ? window : {}) as unknown as Host

/** Which app hosts the portal, if any. */
export function appKind(): 'windows' | 'android' | null {
  const win = host()
  if (win.OfficeHubAndroid) return 'android'
  if (win.__TAURI_INTERNALS__?.invoke) return 'windows'
  return null
}

export const inApp = () => appKind() !== null

function send(message: Record<string, unknown>) {
  const win = host()
  try {
    if (win.OfficeHubAndroid) win.OfficeHubAndroid.postMessage(JSON.stringify(message))
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
    navActivity: t('nav.activity'),
    navChat: t('nav.chat'),
    navSpaces: t('nav.spaces'),
    navCalendar: t('nav.calendar'),
    navMore: t('nav.more'),
  })
}

/** Android's bottom bar shows the numbers on Activity and Chat, like Teams. */
export function appCounts(activity: number, chat: number) {
  if (appKind() === 'android') send({ type: 'counts', activity, chat })
}

/** Android's pull to refresh only starts when the page is scrolled to the very top. */
export function appScrolled(atTop: boolean) {
  if (appKind() === 'android') send({ type: 'scroll', atTop })
}

/** Signed in (or out): the Android app starts or stops its background connection. */
export function appSignedIn(signedIn: boolean) {
  send({ type: 'session', signedIn })
}

/** The page that is open (the address bar stays plain): Android skips notifications for the chat already on screen. */
export function appPlace(path: string) {
  if (appKind() === 'android') send({ type: 'place', path })
}

export interface AppEvent {
  navigate?: string
  call?: number
  action?: 'accept' | 'decline'
  /** Android's "More" tab: open the menu */
  menu?: boolean
  /** Windows tray menu: set my status */
  status?: 'auto' | 'available' | 'busy' | 'dnd' | 'away' | 'offline'
}

export function onAppEvent(handler: (event: AppEvent) => void): () => void {
  const listener = (e: Event) => handler((e as CustomEvent<AppEvent>).detail ?? {})
  window.addEventListener('officehub-app', listener)
  return () => window.removeEventListener('officehub-app', listener)
}
