<script setup lang="ts">
/** Who is away, holidays, company events and birthdays for the whole team, month by month. */
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import AppIcon from './AppIcon.vue'
import EmptyState from './EmptyState.vue'
import LoadState from './LoadState.vue'
import { api, query } from '@/lib/api'
import { errorText, formatDateLong, locale, t } from '@/lib/i18n'
import type { TeamCalendar } from '@/lib/types'
import { holidayName, holidaysFor, holidaysVersion } from '@/lib/holidays'
import { todayIso } from '@/lib/workdays'

interface Entry {
  key: string
  kind: 'vacation' | 'home_office' | 'event' | 'birthday' | 'holiday'
  label: string
  link?: string
}

const route = useRoute()
const router = useRouter()
const month = ref(/^\d{4}-\d{2}$/.test(String(route.query.month)) ? String(route.query.month) : todayIso().slice(0, 7))
const department = ref(typeof route.query.department === 'string' ? route.query.department : '')
const departments = ref<string[]>([])
const data = ref<TeamCalendar | null>(null)
const loading = ref(true)
const error = ref<string | null>(null)

// Small screens get a list instead of the month grid.
const media = window.matchMedia('(max-width: 720px)')
const narrow = ref(media.matches)
const onMedia = (event: MediaQueryListEvent) => (narrow.value = event.matches)

const title = computed(() => new Date(`${month.value}-01T00:00`).toLocaleDateString(locale.value, { month: 'long', year: 'numeric' }))
const weekdays = computed(() =>
  Array.from({ length: 7 }, (_, i) => new Date(2024, 0, 1 + i).toLocaleDateString(locale.value, { weekday: 'short' })),
)
const icsUrl = computed(() => `/api/team/calendar.ics${query({ month: month.value, department: department.value })}`)

function iso(date: Date): string {
  return new Date(date.getTime() - date.getTimezoneOffset() * 60000).toISOString().slice(0, 10)
}

function shift(delta: number) {
  const date = new Date(`${month.value}-01T00:00`)
  date.setMonth(date.getMonth() + delta)
  month.value = iso(date).slice(0, 7)
}

/** All entries per day of the shown month. */
const byDay = computed(() => {
  const map = new Map<string, Entry[]>()
  void holidaysVersion.value
  const add = (day: string, entry: Entry) => map.set(day, [...(map.get(day) ?? []), entry])
  const d = data.value
  if (!d) return map
  for (const h of holidaysFor(Number(month.value.slice(0, 4)))) {
    if (h.date.startsWith(month.value)) add(h.date, { key: `h-${h.date}`, kind: 'holiday', label: holidayName(h) })
  }
  for (const e of d.events) add(e.date, { key: `e-${e.link}`, kind: 'event', label: e.title, link: e.link })
  for (const b of d.birthdays) add(b.date, { key: `b-${b.person.id}`, kind: 'birthday', label: b.person.full_name })
  for (const a of d.absences) {
    const cursor = new Date(`${a.start_date}T00:00`)
    const end = new Date(`${a.end_date}T00:00`)
    while (cursor <= end) {
      const weekday = cursor.getDay()
      if (weekday !== 0 && weekday !== 6) add(iso(cursor), { key: `a-${a.person.id}-${a.start_date}`, kind: a.type, label: a.person.full_name })
      cursor.setDate(cursor.getDate() + 1)
    }
  }
  return map
})

/** Weeks (Monday first) covering the month; days outside the month are null. */
const weeks = computed(() => {
  const first = new Date(`${month.value}-01T00:00`)
  const offset = (first.getDay() + 6) % 7
  const days: (string | null)[] = Array(offset).fill(null)
  const cursor = new Date(first)
  while (cursor.getMonth() === first.getMonth()) {
    days.push(iso(cursor))
    cursor.setDate(cursor.getDate() + 1)
  }
  while (days.length % 7) days.push(null)
  return Array.from({ length: days.length / 7 }, (_, i) => days.slice(i * 7, i * 7 + 7))
})

const agenda = computed(() => [...byDay.value.entries()].filter(([day]) => day.startsWith(month.value)).sort(([a], [b]) => (a < b ? -1 : 1)))

const ICONS: Record<Entry['kind'], string> = { holiday: 'flag', vacation: 'sun', home_office: 'home', event: 'calendar', birthday: 'star' }

function entryText(entry: Entry): string {
  if (entry.kind === 'vacation' || entry.kind === 'home_office') return `${entry.label} · ${t(`calendar.kinds.${entry.kind}`)}`
  if (entry.kind === 'birthday') return t('calendar.birthdayOf', { name: entry.label })
  if (entry.kind === 'holiday') return `${entry.label} · ${t('calendar.kinds.holiday')}`
  return entry.label
}

async function load() {
  loading.value = data.value === null
  error.value = null
  try {
    data.value = await api.get<TeamCalendar>(`/api/team/calendar${query({ month: month.value, department: department.value })}`)
  } catch (e) {
    error.value = errorText(e)
  } finally {
    loading.value = false
  }
}

watch([month, department], () => {
  router.replace({ query: { view: 'team', ...(month.value !== todayIso().slice(0, 7) ? { month: month.value } : {}), ...(department.value ? { department: department.value } : {}) } })
  load()
})

onMounted(async () => {
  media.addEventListener('change', onMedia)
  load()
  departments.value = await api.get<string[]>('/api/directory/departments').catch(() => [])
})
onBeforeUnmount(() => media.removeEventListener('change', onMedia))
</script>

<template>
  <div class="team-calendar">

    <div class="toolbar">
      <div class="row month-nav" role="group" :aria-label="t('calendar.month')">
        <button type="button" class="btn btn-secondary btn-icon" :aria-label="t('calendar.previous')" @click="shift(-1)"><AppIcon name="chevronLeft" /></button>
        <h2 class="month-title" aria-live="polite">{{ title }}</h2>
        <button type="button" class="btn btn-secondary btn-icon" :aria-label="t('calendar.next')" @click="shift(1)"><AppIcon name="chevronRight" /></button>
        <button v-if="month !== todayIso().slice(0, 7)" type="button" class="btn btn-ghost" @click="month = todayIso().slice(0, 7)">{{ t('calendar.thisMonth') }}</button>
      </div>
      <div class="row">
        <a :href="icsUrl" class="btn btn-secondary" download><AppIcon name="download" />{{ t('calendar.export') }}</a>
        <label for="cal-dept" class="visually-hidden">{{ t('calendar.department') }}</label>
        <select id="cal-dept" v-model="department" class="select">
          <option value="">{{ t('calendar.allDepartments') }}</option>
          <option v-for="d in departments" :key="d" :value="d">{{ d }}</option>
        </select>
      </div>
    </div>

    <ul class="legend" :aria-label="t('calendar.legend')">
      <li v-for="kind in (['holiday', 'vacation', 'home_office', 'event', 'birthday'] as const)" :key="kind" :class="`kind-${kind}`">
        <AppIcon :name="ICONS[kind]" :size="16" />{{ t(`calendar.kinds.${kind}`) }}
      </li>
    </ul>

    <LoadState :loading="loading" :error="error" @retry="load">
      <template v-if="narrow">
        <section v-if="agenda.length" class="card card-flush">
          <ul class="list">
            <li v-for="[day, entries] in agenda" :key="day" class="agenda-day" :class="{ today: day === todayIso() }">
              <p class="agenda-date">{{ formatDateLong(day) }}</p>
              <ul class="entries">
                <li v-for="entry in entries" :key="entry.key" class="entry" :class="`kind-${entry.kind}`">
                  <AppIcon :name="ICONS[entry.kind]" :size="16" />
                  <RouterLink v-if="entry.link" :to="entry.link">{{ entryText(entry) }}</RouterLink>
                  <span v-else>{{ entryText(entry) }}</span>
                </li>
              </ul>
            </li>
          </ul>
        </section>
        <section v-else class="card"><EmptyState icon="calendar" :message="t('calendar.empty')" /></section>
      </template>

      <div v-else class="card card-flush grid-wrap">
        <table class="month">
          <caption class="visually-hidden">{{ title }}</caption>
          <thead>
            <tr><th v-for="(day, i) in weekdays" :key="day" scope="col" :class="{ weekend: i >= 5 }">{{ day }}</th></tr>
          </thead>
          <tbody>
            <tr v-for="(week, w) in weeks" :key="w">
              <td v-for="(day, i) in week" :key="i" :class="{ empty: !day, weekend: i >= 5, today: day === todayIso() }">
                <template v-if="day">
                  <span class="day-number" :aria-label="formatDateLong(day)">{{ Number(day.slice(8)) }}</span>
                  <ul v-if="byDay.get(day)?.length" class="entries">
                    <li v-for="entry in byDay.get(day)!.slice(0, 4)" :key="entry.key" class="entry" :class="`kind-${entry.kind}`" :title="entryText(entry)">
                      <AppIcon :name="ICONS[entry.kind]" :size="14" />
                      <RouterLink v-if="entry.link" :to="entry.link" class="entry-text">{{ entry.label }}</RouterLink>
                      <span v-else class="entry-text">{{ entry.label }}<span class="visually-hidden"> · {{ t(`calendar.kinds.${entry.kind}`) }}</span></span>
                    </li>
                    <li v-if="byDay.get(day)!.length > 4" class="more small muted">{{ t('calendar.more', { count: byDay.get(day)!.length - 4 }) }}</li>
                  </ul>
                </template>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </LoadState>
    <p class="muted small">{{ t('calendar.privacy') }}</p>
  </div>
</template>

<style scoped>
.toolbar {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-3);
}

.month-nav {
  gap: var(--space-2);
}

.month-title {
  min-width: 180px;
  text-align: center;
  text-transform: capitalize;
}

.legend {
  list-style: none;
  margin: 0;
  padding: 0;
  display: flex;
  flex-wrap: wrap;
  gap: var(--space-2) var(--space-4);
  font-size: var(--text-sm);
}

.legend li {
  display: inline-flex;
  align-items: center;
  gap: 6px;
}

.grid-wrap {
  overflow-x: auto;
}

.month {
  width: 100%;
  min-width: 700px;
  border-collapse: collapse;
  table-layout: fixed;
}

.month th {
  padding: var(--space-2);
  border-bottom: 1px solid var(--color-border);
  background: var(--color-surface-muted);
  color: var(--color-text-muted);
  font-size: var(--text-xs);
  font-weight: 600;
  text-transform: uppercase;
}

.month td {
  height: 112px;
  padding: 6px;
  vertical-align: top;
  border-right: 1px solid var(--color-border);
  border-bottom: 1px solid var(--color-border);
}

.month td:last-child {
  border-right: 0;
}

.month tr:last-child td {
  border-bottom: 0;
}

.month td.weekend,
.month th.weekend {
  background: var(--color-surface-muted);
}

.month td.empty {
  background: var(--color-bg);
}

.day-number {
  display: inline-grid;
  place-items: center;
  min-width: 26px;
  height: 26px;
  border-radius: var(--radius-full);
  font-size: var(--text-sm);
  font-weight: 600;
}

.today .day-number {
  background: var(--color-primary);
  color: var(--color-on-primary);
}

.entries {
  list-style: none;
  margin: 4px 0 0;
  padding: 0;
  display: grid;
  gap: 3px;
}

.entry {
  display: flex;
  align-items: center;
  gap: 4px;
  min-width: 0;
  padding: 2px 6px;
  border-radius: var(--radius-sm);
  font-size: var(--text-xs);
  font-weight: 600;
}

.entry-text {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  color: inherit;
}

.kind-holiday {
  color: var(--color-text);
}

.entry.kind-holiday {
  background: var(--color-border);
}

.kind-vacation {
  color: var(--color-warning);
}

.kind-home_office {
  color: var(--color-primary-text);
}

.kind-event {
  color: var(--color-success);
}

.kind-birthday {
  color: var(--color-text-muted);
}

.entry.kind-vacation {
  background: var(--color-warning-soft);
}

.entry.kind-home_office {
  background: var(--color-primary-soft);
}

.entry.kind-event {
  background: var(--color-success-soft);
}

.entry.kind-birthday {
  background: var(--color-neutral-soft);
}

.more {
  padding-left: 6px;
}

.agenda-day {
  display: grid;
  gap: var(--space-2);
  padding: var(--space-3) var(--space-4);
}

.agenda-day.today {
  background: var(--color-primary-soft);
}

.agenda-date {
  font-weight: 600;
}

.agenda-day .entry {
  font-size: var(--text-sm);
  padding: var(--space-1) var(--space-2);
}
</style>
