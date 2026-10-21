/**
 * Badge counts for the navigation and the bell, my presence and meeting reminders. Asked every 30 seconds
 * (also in a background tab), which tells OfficeHub that I am online and whether I stepped away. New messages
 * and notifications found this way pop up on the computer and play a soft sound.
 */

import { ref } from 'vue'
import { api } from './api'
import { chime, notifyDesktop } from './desktop'
import { t } from './i18n'
import { notificationText } from './notifications'
import { setMyPresence } from './presence'
import { currentUser } from './session'
import type { AppNotification, Conversation, NotificationList, Summary } from './types'

const EMPTY: Summary = { unread: 0, approvals_pending: 0, reviews_todo: 0, visitors_today: 0, must_read_open: 0, personal_documents_new: 0, acting_deputy: false, trainings_due: 0, surveys_open: 0, time_months_pending: 0, chat_unread: 0, cards_due: 0, reminders: [] }
const INTERVAL_MS = 30_000
const IDLE_MS = 5 * 60_000

export const summary = ref<Summary>({ ...EMPTY })

let timer: number | undefined
let lastLoad = 0
let lastInput = Date.now()
let primed = false
let seenNotification = 0
let seenChat = ''
const remindedKeys = new Set<string>()

function onInput() {
  lastInput = Date.now()
}

export async function refreshSummary(force = false): Promise<void> {
  // Navigating quickly between pages should not send a request each time.
  if (!force && Date.now() - lastLoad < 5_000) return
  lastLoad = Date.now()
  const idle = Date.now() - lastInput > IDLE_MS
  try {
    const before = summary.value
    const next = await api.get<Summary>(`/api/me/summary${idle ? '?idle=true' : ''}`)
    summary.value = next
    if (next.presence) setMyPresence(next.presence, currentUser.value?.id)
    if (primed) {
      if (next.unread > before.unread) announceNotifications()
      if (next.chat_unread > before.chat_unread) announceMessages()
    } else {
      await remember()
      primed = true
    }
    announceReminders(next)
  } catch {
    /* counts are a convenience; keep the last known values */
  }
}

/** What is already known at the start does not pop up. */
async function remember() {
  try {
    const list = await api.get<NotificationList>('/api/notifications?limit=1')
    seenNotification = list.items[0]?.id ?? 0
  } catch {
    /* next time */
  }
  seenChat = new Date().toISOString()
}

async function announceNotifications() {
  const list = await api.get<NotificationList>('/api/notifications?limit=5').catch(() => null)
  if (!list) return
  const fresh = list.items.filter((n: AppNotification) => n.id > seenNotification && !n.read).reverse()
  seenNotification = Math.max(seenNotification, ...list.items.map((n) => n.id))
  for (const n of fresh) {
    // Reminders come with their own banner and sound
    if (n.kind === 'meeting_reminder') continue
    notifyDesktop({ title: 'OfficeHub', body: notificationText(n), link: n.link || '/activity', tag: `n${n.id}` })
  }
  if (fresh.some((n) => n.kind !== 'meeting_reminder')) chime('message')
}

async function announceMessages() {
  const conversations = await api.get<Conversation[]>('/api/chat').catch(() => null)
  if (!conversations) return
  const fresh = conversations.filter((c) => c.unread && c.last && Date.parse(c.last.at) > Date.parse(seenChat))
  seenChat = new Date().toISOString()
  const here = (id: number) => document.visibilityState === 'visible' && window.location.pathname.endsWith(`/chat/${id}`)
  for (const c of fresh.filter((c) => !here(c.id))) {
    const body = c.last!.call ? t('chat.callPreview') : c.last!.body
    notifyDesktop({ title: c.name, body: c.last!.author && c.kind === 'channel' ? `${c.last!.author}: ${body}` : body, link: `/chat/${c.id}`, tag: `c${c.id}` })
  }
  if (fresh.some((c) => !here(c.id))) chime('message')
}

function announceReminders(s: Summary) {
  for (const r of s.reminders ?? []) {
    const key = `${r.meeting_id}-${r.starts_at}`
    if (remindedKeys.has(key)) continue
    remindedKeys.add(key)
    const minutes = Math.max(0, Math.round((new Date(r.starts_at).getTime() - Date.now()) / 60_000))
    notifyDesktop({ title: r.title, body: minutes ? t('reminder.inMinutes', { n: minutes }) : t('reminder.now'), link: `/meetings/${r.meeting_id}/room`, tag: `r${key}`, sticky: true })
    chime('reminder')
  }
}

export function startSummary(): void {
  stopSummary()
  for (const name of ['pointermove', 'keydown', 'pointerdown', 'scroll']) window.addEventListener(name, onInput, { passive: true })
  refreshSummary(true)
  timer = window.setInterval(() => refreshSummary(true), INTERVAL_MS)
}

export function stopSummary(): void {
  window.clearInterval(timer)
  for (const name of ['pointermove', 'keydown', 'pointerdown', 'scroll']) window.removeEventListener(name, onInput)
  summary.value = { ...EMPTY }
  lastLoad = 0
  primed = false
}
