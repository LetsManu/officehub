/** Public and company holidays per year, cached for the session. */

import { ref } from 'vue'
import { api } from './api'
import { language } from './i18n'

export interface Holiday {
  date: string
  name_de: string
  name_en: string
  company: boolean
  id: number | null
}

const cache = new Map<number, Promise<Holiday[]>>()
/** Bumped when a year finished loading, so computed values that use holidays recalculate. */
export const holidaysVersion = ref(0)
const loaded = new Map<number, Holiday[]>()

export function holidaysFor(year: number): Holiday[] {
  if (!cache.has(year)) {
    cache.set(
      year,
      api
        .get<Holiday[]>(`/api/holidays?year=${year}`)
        .catch(() => [])
        .then((list) => {
          loaded.set(year, list)
          holidaysVersion.value++
          return list
        }),
    )
  }
  return loaded.get(year) ?? []
}

export function holidaySet(start: string, end: string): Set<string> {
  void holidaysVersion.value
  const set = new Set<string>()
  const from = Number(start.slice(0, 4))
  const to = Number(end.slice(0, 4))
  if (!from || !to) return set
  for (let year = from; year <= to && year - from < 3; year++) for (const h of holidaysFor(year)) set.add(h.date)
  return set
}

export function holidayName(h: Holiday): string {
  return language.value === 'de' ? h.name_de : h.name_en
}

export function clearHolidays(): void {
  cache.clear()
  loaded.clear()
  holidaysVersion.value++
}
