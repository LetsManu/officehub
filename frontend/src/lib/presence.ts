/**
 * Who is reachable right now (the coloured dot like in Teams). Avatars that show a dot register their
 * person here; one request every 30 seconds asks for all of them at once.
 */

import { reactive, ref } from 'vue'
import { api } from './api'
import { t } from './i18n'
import type { ManualPresence, Presence } from './types'

export type { ManualPresence, Presence, PresenceState } from './types'

const POLL_MS = 30_000
export const presence = reactive(new Map<number, Presence>())
/** What I am doing in OfficeHub right now ("file:12" while editing, "meeting:4" while in a meeting). */
export const myActivity = ref('')
/** My own presence, from the regular summary request. */
export const myPresence = ref<Presence>({ state: 'available', text: '', manual: 'auto' })
const watched = new Map<number, number>()
let timer: number | undefined
let pending: number | undefined

async function load() {
  const ids = [...watched.keys()]
  if (!ids.length || document.visibilityState !== 'visible') return
  try {
    const result = await api.get<Record<string, Presence>>(`/api/presence?ids=${ids.join(',')}`)
    for (const [id, value] of Object.entries(result)) presence.set(Number(id), value)
  } catch {
    /* the dots simply stay as they were */
  }
}

/** Show the presence of this person; call the returned function when it is no longer shown. */
export function watchPresence(id: number): () => void {
  const fresh = !watched.has(id)
  watched.set(id, (watched.get(id) ?? 0) + 1)
  if (fresh) {
    // Many avatars appear at once: ask for them together a moment later
    window.clearTimeout(pending)
    pending = window.setTimeout(load, 150)
  }
  timer ??= window.setInterval(load, POLL_MS)
  return () => {
    const left = (watched.get(id) ?? 1) - 1
    if (left > 0) watched.set(id, left)
    else watched.delete(id)
    if (!watched.size) {
      window.clearInterval(timer)
      timer = undefined
    }
  }
}

export function setMyPresence(value: Presence, myId: number | undefined) {
  myPresence.value = value
  if (myId) presence.set(myId, value)
}

export async function changeMyPresence(manual: ManualPresence, text: string, myId: number | undefined) {
  setMyPresence(await api.put<Presence>('/api/me/presence', { presence: manual, status_text: text }), myId)
}

/** "Editing Budget.xlsx", "In a meeting: Weekly" – what someone is doing right now, when they share it. */
export function activityText(value: Presence | undefined): string {
  const a = value?.activity
  if (!a) return ''
  if (a.kind === 'editing') return a.label ? t('presence.activity.editingFile', { name: a.label }) : t('presence.activity.editing')
  return a.label ? t('presence.activity.meetingNamed', { name: a.label }) : t('presence.activity.meeting')
}
