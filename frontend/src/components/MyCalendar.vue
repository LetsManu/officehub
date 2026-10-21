<script setup lang="ts">
/**
 * My calendar like in Outlook: day, work week, week or month with my meetings, room bookings, time off,
 * public holidays and company events. Click (or drag) into free time to plan a meeting there.
 */
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import AppIcon from './AppIcon.vue'
import { api, query } from '@/lib/api'
import { errorText, locale, t } from '@/lib/i18n'
import type { CalendarEntry } from '@/lib/types'

type View = 'day' | 'workweek' | 'week' | 'month'

const emit = defineEmits<{ plan: [start: Date, end: Date] }>()
defineExpose({ reload: () => load() })

const HOUR = 48 // pixels per hour in the time grid
const VIEWS: View[] = ['day', 'workweek', 'week', 'month']
const router = useRouter()
const narrow = window.matchMedia('(max-width: 720px)').matches

function stored(): View {
  try {
    const v = localStorage.getItem('officehub-calendar-view') as View | null
    if (v && VIEWS.includes(v)) return v
  } catch {
    /* private window */
  }
  return narrow ? 'day' : 'workweek'
}

const view = ref<View>(stored())
const anchor = ref(startOfDay(new Date()))
const entries = ref<CalendarEntry[]>([])
const loading = ref(false)
const error = ref<string | null>(null)
const scroller = ref<HTMLElement | null>(null)
const now = ref(new Date())
let ticker: number | undefined

// ---------- dates ----------

function startOfDay(d: Date) {
  const x = new Date(d)
  x.setHours(0, 0, 0, 0)
  return x
}

function addDays(d: Date, n: number) {
  const x = new Date(d)
  x.setDate(x.getDate() + n)
  return x
}

function iso(d: Date) {
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
}

function monday(d: Date) {
  return addDays(startOfDay(d), -((d.getDay() + 6) % 7))
}

const days = computed<Date[]>(() => {
  if (view.value === 'day') return [anchor.value]
  if (view.value === 'month') {
    const first = new Date(anchor.value.getFullYear(), anchor.value.getMonth(), 1)
    const start = monday(first)
    const last = new Date(anchor.value.getFullYear(), anchor.value.getMonth() + 1, 0)
    const count = Math.ceil(((last.getTime() - start.getTime()) / 86_400_000 + 1) / 7) * 7
    return Array.from({ length: count }, (_, i) => addDays(start, i))
  }
  const start = monday(anchor.value)
  return Array.from({ length: view.value === 'workweek' ? 5 : 7 }, (_, i) => addDays(start, i))
})

const title = computed(() => {
  const loc = locale.value
  if (view.value === 'month') return anchor.value.toLocaleDateString(loc, { month: 'long', year: 'numeric' })
  if (view.value === 'day') return anchor.value.toLocaleDateString(loc, { weekday: 'long', day: 'numeric', month: 'long', year: 'numeric' })
  const first = days.value[0]
  const last = days.value.at(-1)!
  const week = isoWeek(first)
  const range = `${first.toLocaleDateString(loc, { day: 'numeric', month: first.getMonth() === last.getMonth() ? undefined : 'short' })} – ${last.toLocaleDateString(loc, { day: 'numeric', month: 'short', year: 'numeric' })}`
  return `${range} · ${t('calendarPage.week', { n: week })}`
})

function isoWeek(d: Date) {
  const x = new Date(Date.UTC(d.getFullYear(), d.getMonth(), d.getDate()))
  x.setUTCDate(x.getUTCDate() + 4 - (x.getUTCDay() || 7))
  return Math.ceil(((x.getTime() - Date.UTC(x.getUTCFullYear(), 0, 1)) / 86_400_000 + 1) / 7)
}

function move(step: number) {
  const a = new Date(anchor.value)
  if (view.value === 'month') a.setMonth(a.getMonth() + step, 1)
  else a.setDate(a.getDate() + step * (view.value === 'day' ? 1 : 7))
  anchor.value = startOfDay(a)
}

function today() {
  anchor.value = startOfDay(new Date())
}

// ---------- data ----------

async function load() {
  loading.value = true
  error.value = null
  try {
    entries.value = await api.get<CalendarEntry[]>(`/api/calendar${query({ start: iso(days.value[0]), end: iso(days.value.at(-1)!) })}`)
  } catch (e) {
    error.value = errorText(e)
  } finally {
    loading.value = false
  }
}

function label(e: CalendarEntry) {
  if (e.kind === 'vacation' || e.kind === 'home_office') {
    return `${t(`calendar.kinds.${e.kind}`)}${e.status === 'pending' ? ` (${t('calendarPage.requested')})` : ''}`
  }
  return e.title
}

const ICONS: Record<string, string> = { meeting: 'video', booking: 'door', vacation: 'sun', home_office: 'home', holiday: 'flag', event: 'megaphone' }

function clock(d: Date) {
  return d.toLocaleTimeString(locale.value, { hour: '2-digit', minute: '2-digit' })
}

/** All-day entries (time off, holidays, events) per shown day. */
const allDay = computed(() => {
  const map = new Map<string, CalendarEntry[]>()
  for (const e of entries.value) {
    if (!e.day) continue
    for (let d = new Date(`${e.day}T00:00`); iso(d) <= (e.last_day ?? e.day); d = addDays(d, 1)) {
      map.set(iso(d), [...(map.get(iso(d)) ?? []), e])
    }
  }
  return map
})

interface Placed {
  entry: CalendarEntry
  start: Date
  end: Date
  top: number
  height: number
  column: number
  columns: number
}

/** Timed entries per day, side by side where they overlap (like Outlook). */
const timed = computed(() => {
  const map = new Map<string, Placed[]>()
  for (const day of days.value) {
    const from = day.getTime()
    const to = addDays(day, 1).getTime()
    const list = entries.value
      .filter((e) => e.start && e.end && new Date(e.start).getTime() < to && new Date(e.end).getTime() > from)
      .map((e) => ({ entry: e, start: new Date(Math.max(new Date(e.start!).getTime(), from)), end: new Date(Math.min(new Date(e.end!).getTime(), to)) }))
      .sort((a, b) => a.start.getTime() - b.start.getTime() || b.end.getTime() - a.end.getTime())
    const placed: Placed[] = []
    let cluster: Placed[] = []
    let clusterEnd = 0
    const finish = () => {
      const columns = Math.max(1, ...cluster.map((p) => p.column + 1))
      for (const p of cluster) p.columns = columns
      cluster = []
    }
    for (const item of list) {
      if (cluster.length && item.start.getTime() >= clusterEnd) finish()
      const used = new Set(cluster.filter((p) => p.end.getTime() > item.start.getTime()).map((p) => p.column))
      let column = 0
      while (used.has(column)) column++
      const minutes = (item.start.getTime() - from) / 60_000
      const length = Math.max(20, (item.end.getTime() - item.start.getTime()) / 60_000)
      const p: Placed = { ...item, top: (minutes / 60) * HOUR, height: (length / 60) * HOUR - 2, column, columns: 1 }
      cluster.push(p)
      placed.push(p)
      clusterEnd = Math.max(clusterEnd, item.end.getTime())
    }
    finish()
    map.set(iso(day), placed)
  }
  return map
})

const monthEntries = computed(() => {
  const map = new Map<string, CalendarEntry[]>()
  for (const day of days.value) {
    const key = iso(day)
    const list = [...(allDay.value.get(key) ?? []), ...(timed.value.get(key) ?? []).map((p) => p.entry)]
    map.set(key, list)
  }
  return map
})

function isToday(d: Date) {
  return iso(d) === iso(now.value)
}

const nowTop = computed(() => ((now.value.getHours() * 60 + now.value.getMinutes()) / 60) * HOUR)

function open(e: CalendarEntry) {
  if (e.link) router.push(e.link)
}

/** A meeting that runs right now (or starts within 10 minutes) gets a join button. */
function joinable(e: CalendarEntry) {
  if (e.kind !== 'meeting' || !e.start || !e.end) return false
  const t0 = new Date(e.start).getTime() - 10 * 60_000
  return t0 <= now.value.getTime() && new Date(e.end).getTime() >= now.value.getTime()
}

function join(e: CalendarEntry) {
  router.push(`${e.link}/room`)
}

// ---------- click or drag into free time to plan a meeting ----------

const selecting = ref<{ day: string; from: number; to: number } | null>(null)
let dragDay: Date | null = null

function minuteAt(event: PointerEvent, column: HTMLElement) {
  const y = event.clientY - column.getBoundingClientRect().top
  return Math.max(0, Math.min(24 * 60, Math.floor(((y / HOUR) * 60) / 30) * 30))
}

function down(event: PointerEvent, day: Date) {
  if ((event.target as HTMLElement).closest('.event') || event.button !== 0) return
  const column = event.currentTarget as HTMLElement
  column.setPointerCapture(event.pointerId)
  dragDay = day
  const m = minuteAt(event, column)
  selecting.value = { day: iso(day), from: m, to: m + 30 }
}

function drag(event: PointerEvent) {
  if (!selecting.value) return
  const m = minuteAt(event, event.currentTarget as HTMLElement)
  selecting.value.to = Math.max(selecting.value.from + 30, m + 30)
}

function up() {
  const s = selecting.value
  selecting.value = null
  if (!s || !dragDay) return
  const start = new Date(dragDay)
  start.setMinutes(s.from)
  const end = new Date(dragDay)
  end.setMinutes(Math.min(s.to, 24 * 60))
  if (end <= start) end.setTime(start.getTime() + 30 * 60_000)
  emit('plan', start, end)
}

function planDay(day: Date) {
  const start = new Date(day)
  start.setHours(9, 0, 0, 0)
  emit('plan', start, new Date(start.getTime() + 3600_000))
}

const hours = Array.from({ length: 24 }, (_, h) => h)
const hourLabel = (h: number) => new Date(2024, 0, 1, h).toLocaleTimeString(locale.value, { hour: '2-digit', minute: '2-digit' })

watch(view, async (v) => {
  try {
    localStorage.setItem('officehub-calendar-view', v)
  } catch {
    /* private window */
  }
  if (v !== 'month') {
    await nextTick()
    scrollToMorning()
  }
})
watch(days, load)

function scrollToMorning() {
  if (scroller.value) scroller.value.scrollTop = 7 * HOUR
}

onMounted(async () => {
  await load()
  await nextTick()
  scrollToMorning()
  ticker = window.setInterval(() => (now.value = new Date()), 60_000)
})
onBeforeUnmount(() => window.clearInterval(ticker))
</script>

<template>
  <div class="my-calendar">
    <div class="toolbar">
      <div class="nav-group" role="group" :aria-label="t('calendarPage.navigate')">
        <button type="button" class="btn btn-secondary" @click="today">{{ t('calendarPage.today') }}</button>
        <button type="button" class="btn btn-ghost btn-icon" :aria-label="t('calendarPage.previous')" @click="move(-1)"><AppIcon name="chevronLeft" /></button>
        <button type="button" class="btn btn-ghost btn-icon" :aria-label="t('calendarPage.next')" @click="move(1)"><AppIcon name="chevronRight" /></button>
        <h2 class="range" aria-live="polite">{{ title }}</h2>
      </div>
      <div class="segmented" role="group" :aria-label="t('calendarPage.viewLabel')">
        <button v-for="v in VIEWS" :key="v" type="button" :aria-pressed="view === v" @click="view = v">{{ t(`calendarPage.views.${v}`) }}</button>
      </div>
    </div>

    <p v-if="error" class="notice notice-danger small" role="alert">{{ error }}</p>

    <!-- Month -->
    <div v-if="view === 'month'" class="card card-flush month" :aria-busy="loading">
      <div class="month-head">
        <span v-for="d in days.slice(0, 7)" :key="d.getDay()">{{ d.toLocaleDateString(locale, { weekday: 'short' }) }}</span>
      </div>
      <div class="month-grid">
        <div v-for="d in days" :key="iso(d)" class="month-day" :class="{ other: d.getMonth() !== anchor.getMonth(), today: isToday(d), weekend: d.getDay() % 6 === 0 }">
          <button type="button" class="day-num" :aria-label="t('calendarPage.planOn', { date: d.toLocaleDateString(locale, { weekday: 'long', day: 'numeric', month: 'long' }) })" @click="planDay(d)">{{ d.getDate() }}</button>
          <ul class="chips">
            <li v-for="e in monthEntries.get(iso(d))!.slice(0, 4)" :key="e.id">
              <button type="button" class="chip" :class="[`k-${e.kind}`, { pending: e.status === 'pending' }]" :title="label(e)" @click="open(e)">
                <template v-if="e.start">{{ clock(new Date(e.start)) }} </template>{{ label(e) }}
              </button>
            </li>
            <li v-if="monthEntries.get(iso(d))!.length > 4" class="muted tiny">{{ t('calendar.more', { count: monthEntries.get(iso(d))!.length - 4 }) }}</li>
          </ul>
        </div>
      </div>
    </div>

    <!-- Day / week: time grid -->
    <div v-else class="card card-flush week" :class="`cols-${days.length}`" :aria-busy="loading">
      <div class="week-head">
        <span class="gutter" />
        <div v-for="d in days" :key="iso(d)" class="col-head" :class="{ today: isToday(d) }">
          <span class="wd">{{ d.toLocaleDateString(locale, { weekday: 'short' }) }}</span>
          <span class="dn">{{ d.getDate() }}</span>
        </div>
      </div>
      <div class="allday">
        <span class="gutter tiny muted">{{ t('calendarPage.allDay') }}</span>
        <div v-for="d in days" :key="iso(d)" class="allday-col">
          <button v-for="e in allDay.get(iso(d)) ?? []" :key="e.id" type="button" class="chip" :class="[`k-${e.kind}`, { pending: e.status === 'pending' }]" :title="label(e)" @click="open(e)">
            <AppIcon :name="ICONS[e.kind] ?? 'calendar'" :size="13" />{{ label(e) }}
          </button>
        </div>
      </div>
      <div ref="scroller" class="scroller">
        <div class="grid">
          <div class="gutter hours" aria-hidden="true">
            <span v-for="h in hours" :key="h" class="hour">{{ h ? hourLabel(h) : '' }}</span>
          </div>
          <div
            v-for="d in days"
            :key="iso(d)"
            class="day-col"
            :class="{ today: isToday(d), weekend: d.getDay() % 6 === 0 }"
            @pointerdown="down($event, d)"
            @pointermove="drag"
            @pointerup="up"
            @pointercancel="selecting = null"
          >
            <div
              v-if="selecting && selecting.day === iso(d)"
              class="selection"
              :style="{ top: `${(selecting.from / 60) * HOUR}px`, height: `${((selecting.to - selecting.from) / 60) * HOUR}px` }"
            />
            <div
              v-for="p in timed.get(iso(d)) ?? []"
              :key="p.entry.id"
              class="event"
              :class="[`k-${p.entry.kind}`, { pending: p.entry.status === 'pending', short: p.height < 40 }]"
              :style="{ top: `${p.top}px`, height: `${p.height}px`, left: `calc(${(p.column / p.columns) * 100}% + 2px)`, width: `calc(${100 / p.columns}% - 4px)` }"
            >
              <button type="button" class="event-main" @click="open(p.entry)">
                <span class="ev-title">{{ p.entry.title }}</span>
                <span class="ev-meta">{{ clock(p.start) }} – {{ clock(p.end) }}<template v-if="p.entry.detail"> · {{ p.entry.detail }}</template></span>
              </button>
              <button v-if="joinable(p.entry)" type="button" class="ev-join" :aria-label="t('meetings.join')" @click="join(p.entry)"><AppIcon name="video" :size="14" />{{ t('meetings.join') }}</button>
            </div>
            <div v-if="isToday(d)" class="now" :style="{ top: `${nowTop}px` }" aria-hidden="true" />
          </div>
        </div>
      </div>
    </div>
    <p class="muted small hint">{{ t('calendarPage.hint') }}</p>
  </div>
</template>

<style scoped>
.my-calendar {
  display: grid;
  gap: var(--space-3);
}

.toolbar {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-3);
}

.nav-group {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: var(--space-1);
}

.range {
  margin: 0 0 0 var(--space-2);
  font-size: var(--text-lg);
}

/* ---------- colours per kind ---------- */
.k-meeting {
  --ev: var(--color-primary);
  --ev-soft: var(--color-primary-soft);
}

.k-booking {
  --ev: #0f766e;
  --ev-soft: color-mix(in srgb, #0f766e 14%, var(--color-surface));
}

.k-vacation {
  --ev: #b45309;
  --ev-soft: color-mix(in srgb, #f59e0b 18%, var(--color-surface));
}

.k-home_office {
  --ev: #6d28d9;
  --ev-soft: color-mix(in srgb, #8b5cf6 16%, var(--color-surface));
}

.k-holiday {
  --ev: #b91c1c;
  --ev-soft: color-mix(in srgb, #ef4444 14%, var(--color-surface));
}

.k-event {
  --ev: #1d4ed8;
  --ev-soft: color-mix(in srgb, #3b82f6 12%, var(--color-surface));
}

.chip {
  display: flex;
  align-items: center;
  gap: 4px;
  width: 100%;
  min-width: 0;
  padding: 2px 6px;
  overflow: hidden;
  border: 0;
  border-left: 3px solid var(--ev);
  border-radius: 4px;
  background: var(--ev-soft);
  color: var(--color-text);
  font: inherit;
  font-size: 0.78rem;
  text-align: left;
  text-overflow: ellipsis;
  white-space: nowrap;
  cursor: pointer;
}

.chip.pending,
.event.pending {
  background: repeating-linear-gradient(135deg, var(--ev-soft) 0 6px, var(--color-surface) 6px 12px);
}

/* ---------- week ---------- */
.week {
  --gutter: 56px;
  overflow: hidden;
}

.week-head,
.allday,
.grid {
  display: grid;
  grid-template-columns: var(--gutter) repeat(var(--cols), minmax(0, 1fr));
}

.cols-1 {
  --cols: 1;
}

.cols-5 {
  --cols: 5;
}

.cols-7 {
  --cols: 7;
}

.week-head {
  border-bottom: 1px solid var(--color-border);
}

.col-head {
  display: flex;
  align-items: baseline;
  gap: 6px;
  padding: var(--space-2) var(--space-3);
  border-left: 1px solid var(--color-border);
}

.col-head .wd {
  color: var(--color-text-muted);
  font-size: var(--text-sm);
}

.col-head .dn {
  font-size: var(--text-lg);
  font-weight: 600;
}

.col-head.today .dn {
  display: inline-grid;
  min-width: 30px;
  height: 30px;
  place-items: center;
  border-radius: 50%;
  background: var(--color-primary);
  color: var(--color-on-primary);
}

.allday {
  min-height: 34px;
  border-bottom: 1px solid var(--color-border);
}

.gutter {
  padding: 6px 6px 0 0;
  text-align: right;
}

.allday .gutter {
  padding: 8px 6px 0 2px;
  font-size: 0.66rem;
  line-height: 1.2;
  hyphens: auto;
  overflow-wrap: anywhere;
}

.allday-col {
  display: grid;
  align-content: start;
  gap: 2px;
  padding: 3px;
  border-left: 1px solid var(--color-border);
}

.scroller {
  height: min(68vh, 720px);
  overflow-y: auto;
}

.grid {
  position: relative;
  height: calc(24 * 48px);
}

.hours {
  position: relative;
  display: grid;
  grid-template-rows: repeat(24, 48px);
  padding: 0;
}

.hour {
  position: relative;
  top: -0.6em;
  padding-right: 8px;
  color: var(--color-text-subtle);
  font-size: 0.72rem;
  text-align: right;
}

.day-col {
  position: relative;
  border-left: 1px solid var(--color-border);
  background-image: repeating-linear-gradient(to bottom, var(--color-border) 0 1px, transparent 1px 24px, color-mix(in srgb, var(--color-border) 45%, transparent) 24px 25px, transparent 25px 48px);
  cursor: cell;
  touch-action: pan-y;
  user-select: none;
}

.day-col.weekend {
  background-color: var(--color-surface-muted);
}

.selection {
  position: absolute;
  right: 2px;
  left: 2px;
  border: 2px dashed var(--color-primary);
  border-radius: 6px;
  background: color-mix(in srgb, var(--color-primary) 12%, transparent);
  pointer-events: none;
}

.event {
  position: absolute;
  display: grid;
  align-content: start;
  overflow: hidden;
  border-left: 3px solid var(--ev);
  border-radius: 6px;
  background: var(--ev-soft);
  box-shadow: 0 1px 2px rgb(0 0 0 / 8%);
}

.event-main {
  display: grid;
  min-width: 0;
  padding: 3px 6px;
  border: 0;
  background: none;
  color: var(--color-text);
  font: inherit;
  text-align: left;
  cursor: pointer;
}

.ev-title {
  overflow: hidden;
  font-size: 0.8rem;
  font-weight: 600;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.ev-meta {
  overflow: hidden;
  color: var(--color-text-muted);
  font-size: 0.72rem;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.event.short .ev-meta {
  display: none;
}

.ev-join {
  display: inline-flex;
  align-items: center;
  justify-self: start;
  gap: 4px;
  margin: 0 6px 4px;
  padding: 2px 8px;
  border: 0;
  border-radius: 99px;
  background: var(--color-primary);
  color: var(--color-on-primary);
  font: inherit;
  font-size: 0.72rem;
  font-weight: 600;
  cursor: pointer;
}

.now {
  position: absolute;
  right: 0;
  left: 0;
  height: 2px;
  background: #dc2626;
  pointer-events: none;
}

.now::before {
  content: '';
  position: absolute;
  top: -4px;
  left: -5px;
  width: 10px;
  height: 10px;
  border-radius: 50%;
  background: #dc2626;
}

/* ---------- month ---------- */
.month-head,
.month-grid {
  display: grid;
  grid-template-columns: repeat(7, minmax(0, 1fr));
}

.month-head span {
  padding: var(--space-2) var(--space-3);
  color: var(--color-text-muted);
  font-size: var(--text-sm);
  font-weight: 600;
}

.month-day {
  display: grid;
  align-content: start;
  gap: 4px;
  min-height: 110px;
  padding: 4px;
  border-top: 1px solid var(--color-border);
  border-left: 1px solid var(--color-border);
}

.month-day.weekend {
  background: var(--color-surface-muted);
}

.month-day.other {
  opacity: 0.55;
}

.day-num {
  justify-self: start;
  min-width: 28px;
  height: 28px;
  border: 0;
  border-radius: 50%;
  background: none;
  color: inherit;
  font: inherit;
  font-weight: 600;
  cursor: pointer;
}

.day-num:hover {
  background: var(--color-primary-soft);
}

.month-day.today .day-num {
  background: var(--color-primary);
  color: var(--color-on-primary);
}

.chips {
  display: grid;
  gap: 2px;
  margin: 0;
  padding: 0;
  list-style: none;
}

.hint {
  margin: 0;
}

@media (max-width: 720px) {
  .week {
    --gutter: 44px;
  }

  .month-day {
    min-height: 64px;
  }

  .chip {
    font-size: 0.7rem;
  }
}

@media (prefers-reduced-motion: reduce) {
  .event {
    box-shadow: none;
  }
}
</style>
