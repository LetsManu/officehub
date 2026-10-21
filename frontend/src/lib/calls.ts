/** Start a video call: with a person (it rings on their side) or in a conversation. */

import type { Router } from 'vue-router'
import { api } from './api'
import { errorText } from './i18n'
import { showToast } from './toast'

export async function startCall(router: Router, target: { user_id: number } | { channel_id: number }, rings = true): Promise<void> {
  try {
    const call = await api.post<{ meeting_id: number }>('/api/calls', target)
    await router.push({ path: `/meetings/${call.meeting_id}/room`, query: { call: rings ? '1' : undefined, from: router.currentRoute.value.fullPath } })
  } catch (e) {
    showToast(errorText(e), 'error')
  }
}

/** Open the direct conversation with a person. */
export async function messagePerson(router: Router, userId: number): Promise<void> {
  try {
    const conversation = await api.post<{ id: number }>('/api/chat/direct', { user_id: userId })
    await router.push(`/chat/${conversation.id}`)
  } catch (e) {
    showToast(errorText(e), 'error')
  }
}
