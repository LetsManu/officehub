/** Counts Monday–Friday between two ISO dates (inclusive), minus holidays. Mirrors the backend rule. */
export function countWorkingDays(start: string, end: string, holidays: ReadonlySet<string> = new Set()): number {
  const from = parseIsoDate(start)
  const to = parseIsoDate(end)
  if (!from || !to || to < from) return 0
  let days = 0
  const cursor = new Date(from)
  while (cursor <= to) {
    const weekday = cursor.getUTCDay()
    if (weekday !== 0 && weekday !== 6 && !holidays.has(cursor.toISOString().slice(0, 10))) days++
    cursor.setUTCDate(cursor.getUTCDate() + 1)
  }
  return days
}

export function parseIsoDate(value: string): Date | null {
  if (!/^\d{4}-\d{2}-\d{2}$/.test(value)) return null
  const date = new Date(`${value}T00:00:00Z`)
  return Number.isNaN(date.getTime()) ? null : date
}

export function todayIso(): string {
  const now = new Date()
  const local = new Date(now.getTime() - now.getTimezoneOffset() * 60000)
  return local.toISOString().slice(0, 10)
}
