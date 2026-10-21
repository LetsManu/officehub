/** Turns a stored notification (kind + params) into a sentence in the reader's language. */

import { formatDate, t } from './i18n'
import type { AppNotification } from './types'

export const NOTIFICATION_ICONS: Record<string, string> = {
  request_submitted: 'inbox',
  request_in_review: 'clock',
  request_approved: 'checkCircle',
  request_rejected: 'alert',
  request_comment: 'message',
  visitor_arrived: 'badge',
  review_created: 'users',
  booking_cancelled: 'door',
  must_read_new: 'megaphone',
  must_read_reminder: 'megaphone',
  personal_document: 'file',
  welcome: 'star',
  meeting_invite: 'video',
  meeting_cancelled: 'calendar',
  call_missed: 'phone',
  meeting_reminder: 'calendar',
}

export function notificationText(item: AppNotification): string {
  const params: Record<string, string | number> = { ...item.params }
  if (typeof params.type === 'string') params.type = t(`requestTypes.${params.type}`)
  if (typeof params.day === 'string') params.day = formatDate(params.day)
  const key = `notifications.kinds.${item.kind}`
  const text = t(key, params)
  return text === key ? t('notifications.kinds.other') : text
}

/** "5 minutes ago", "yesterday" … using the browser's built-in wording. */
export function timeAgo(iso: string, locale: string, now = Date.now()): string {
  const seconds = Math.round((new Date(iso).getTime() - now) / 1000)
  const format = new Intl.RelativeTimeFormat(locale, { numeric: 'auto' })
  const steps: [Intl.RelativeTimeFormatUnit, number][] = [
    ['day', 86_400],
    ['hour', 3_600],
    ['minute', 60],
  ]
  for (const [unit, size] of steps) {
    if (Math.abs(seconds) >= size) return format.format(Math.round(seconds / size), unit)
  }
  return format.format(0, 'minute')
}
