/** Formatting for working time. */

import { locale } from './i18n'

/** 450 → "7:30" */
export function hours(minutes: number): string {
  const sign = minutes < 0 ? '−' : ''
  const abs = Math.abs(Math.round(minutes))
  return `${sign}${Math.floor(abs / 60)}:${String(abs % 60).padStart(2, '0')}`
}

/** Signed balance, e.g. "+3:15" or "−0:45". */
export function balance(minutes: number): string {
  return minutes > 0 ? `+${hours(minutes)}` : hours(minutes)
}

/** Local clock time "08:05" of an ISO timestamp. */
export function clock(iso: string | null): string {
  if (!iso) return ''
  return new Date(iso).toLocaleTimeString(locale.value, { hour: '2-digit', minute: '2-digit' })
}

/** Monday of the week that contains the ISO date. */
export function mondayOf(isoDate: string): string {
  const date = new Date(`${isoDate}T00:00:00Z`)
  const weekday = (date.getUTCDay() + 6) % 7
  date.setUTCDate(date.getUTCDate() - weekday)
  return date.toISOString().slice(0, 10)
}

export function addDays(isoDate: string, days: number): string {
  const date = new Date(`${isoDate}T00:00:00Z`)
  date.setUTCDate(date.getUTCDate() + days)
  return date.toISOString().slice(0, 10)
}
