/** Badge counts for the navigation and the bell. Refreshed on navigation and every minute. */

import { ref } from 'vue'
import { api } from './api'
import type { Summary } from './types'

const EMPTY: Summary = { unread: 0, approvals_pending: 0, reviews_todo: 0, visitors_today: 0, must_read_open: 0, personal_documents_new: 0, acting_deputy: false, trainings_due: 0, surveys_open: 0 }
const INTERVAL_MS = 60_000

export const summary = ref<Summary>({ ...EMPTY })

let timer: number | undefined
let lastLoad = 0

export async function refreshSummary(force = false): Promise<void> {
  // Navigating quickly between pages should not send a request each time.
  if (!force && Date.now() - lastLoad < 5_000) return
  lastLoad = Date.now()
  try {
    summary.value = await api.get<Summary>('/api/me/summary')
  } catch {
    /* counts are a convenience; keep the last known values */
  }
}

export function startSummary(): void {
  stopSummary()
  refreshSummary(true)
  timer = window.setInterval(() => {
    if (document.visibilityState === 'visible') refreshSummary(true)
  }, INTERVAL_MS)
}

export function stopSummary(): void {
  window.clearInterval(timer)
  summary.value = { ...EMPTY }
  lastLoad = 0
}
