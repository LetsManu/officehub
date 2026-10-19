<script setup lang="ts">
/**
 * Planning board: one row per person, one column per day, projects as bars.
 * Planners drag bars to move them, drag the edges to change the dates and drag on an empty row to plan someone.
 * Every bar is also a button that opens the same form, so all of it works with the keyboard.
 */
import { computed, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import AppIcon from '@/components/AppIcon.vue'
import BaseModal from '@/components/BaseModal.vue'
import EmptyState from '@/components/EmptyState.vue'
import FormField from '@/components/FormField.vue'
import LoadState from '@/components/LoadState.vue'
import PageHeader from '@/components/PageHeader.vue'
import UserAvatar from '@/components/UserAvatar.vue'
import { api, query } from '@/lib/api'
import { errorText, formatDate, locale, t } from '@/lib/i18n'
import { assignLanes, dailyLoad, dayDiff, percent, workload } from '@/lib/planning'
import { isApprover } from '@/lib/session'
import { addDays, hours, mondayOf } from '@/lib/time'
import { showToast } from '@/lib/toast'
import type { Allocation, PlanningBoard, PlanningRow, Project } from '@/lib/types'

const ZOOMS = [2, 4, 8, 12] as const
const CELL: Record<number, number> = { 2: 46, 4: 32, 8: 20, 12: 14 }
const LANE = 30

const route = useRoute()
const router = useRouter()
const today = new Date().toISOString().slice(0, 10)

const start = ref(typeof route.query.start === 'string' && /^\d{4}-\d{2}-\d{2}$/.test(route.query.start) ? mondayOf(route.query.start) : mondayOf(today))
const weeks = ref<number>(ZOOMS.includes(Number(route.query.weeks) as (typeof ZOOMS)[number]) ? Number(route.query.weeks) : 4)
const department = ref('')
const board = ref<PlanningBoard | null>(null)
const departments = ref<string[]>([])
const loading = ref(true)
const error = ref<string | null>(null)

const cell = computed(() => CELL[weeks.value])
const dayList = computed(() => board.value?.days.map((d) => d.date) ?? [])
const trackWidth = computed(() => dayList.value.length * cell.value)
const projectsById = computed(() => new Map((board.value?.projects ?? []).map((p) => [p.id, p])))
const activeProjects = computed(() => (board.value?.projects ?? []).filter((p) => p.active))
const editableRows = computed(() => board.value?.rows.filter((r) => r.editable) ?? [])

const weekGroups = computed(() => {
  const groups: { start: string; label: string; days: number }[] = []
  for (const day of dayList.value) {
    const monday = mondayOf(day)
    const last = groups[groups.length - 1]
    if (last && last.start === monday) last.days += 1
    else groups.push({ start: monday, label: t('planning.week', { n: isoWeek(monday) }), days: 1 })
  }
  return groups
})

const rangeLabel = computed(() => (board.value ? `${formatDate(board.value.start)} – ${formatDate(board.value.end)}` : ''))

function isoWeek(iso: string): number {
  const date = new Date(`${iso}T00:00:00Z`)
  date.setUTCDate(date.getUTCDate() + 3 - ((date.getUTCDay() + 6) % 7))
  const firstThursday = new Date(Date.UTC(date.getUTCFullYear(), 0, 4))
  return 1 + Math.round(((date.getTime() - firstThursday.getTime()) / 86_400_000 - 3 + ((firstThursday.getUTCDay() + 6) % 7)) / 7)
}

function weekday(iso: string): string {
  return new Date(`${iso}T00:00:00Z`).toLocaleDateString(locale.value, { weekday: 'short', timeZone: 'UTC' }).slice(0, 2)
}

function dayNumber(iso: string): string {
  return String(Number(iso.slice(8, 10)))
}

async function load() {
  loading.value = board.value === null
  error.value = null
  try {
    board.value = await api.get<PlanningBoard>(
      `/api/planning/board${query({ start: start.value, days: weeks.value * 7, department: department.value })}`,
    )
    if (!department.value) {
      departments.value = [...new Set(board.value.rows.map((r) => r.person.department).filter(Boolean))].sort()
    }
  } catch (e) {
    error.value = errorText(e)
  } finally {
    loading.value = false
  }
}

watch([start, weeks], () => {
  router.replace({ query: { ...route.query, start: start.value, weeks: String(weeks.value) } })
  load()
})
watch(department, load)

function move(direction: number) {
  start.value = addDays(start.value, direction * 7 * Math.max(1, Math.floor(weeks.value / 2)))
}

// ---------- rows, bars and day cells ----------

function rowAllocations(row: PlanningRow): Allocation[] {
  return (board.value?.allocations ?? []).filter((a) => a.user_id === row.person.id).map((a) => preview(a))
}

function lanesFor(row: PlanningRow) {
  return assignLanes(rowAllocations(row))
}

function rowHeight(row: PlanningRow): number {
  const lanes = lanesFor(row)
  const count = Math.max(1, ...[...lanes.values()].map((l) => l + 1))
  return count * LANE + 12
}

function barStyle(a: Allocation, lane: number) {
  const first = dayList.value[0]
  const from = Math.max(0, dayDiff(first, a.start_date))
  const to = Math.min(dayList.value.length - 1, dayDiff(first, a.end_date))
  return { left: `${from * cell.value + 2}px`, width: `${Math.max(1, to - from + 1) * cell.value - 4}px`, top: `${lane * LANE + 6}px` }
}

function visible(a: Allocation): boolean {
  const days = dayList.value
  return days.length > 0 && a.end_date >= days[0] && a.start_date <= days[days.length - 1]
}

function dailyCapacity(row: PlanningRow): number {
  // weekly working time is not sent per person; capacity / working days is the same number
  const workDays = dayList.value.filter((d) => isWorkDay(row, d)).length
  return workDays ? row.capacity / workDays : 0
}

function isWorkDay(row: PlanningRow, day: string): boolean {
  const info = board.value?.days.find((d) => d.date === day)
  return !info?.off && !row.away.includes(day)
}

function dayClass(row: PlanningRow, index: number, loads: number[], perDay: number) {
  const info = board.value!.days[index]
  const day = info.date
  return {
    weekend: info.off === 'weekend',
    holiday: info.off === 'holiday',
    away: row.away.includes(day),
    today: day === today,
    monday: index > 0 && new Date(`${day}T00:00:00Z`).getUTCDay() === 1,
    over: isWorkDay(row, day) && perDay > 0 && loads[index] > perDay + 0.5,
  }
}

function rowLoads(row: PlanningRow): number[] {
  return dailyLoad(rowAllocations(row), dayList.value)
}

function barLabel(a: Allocation): string {
  const project = projectsById.value.get(a.project_id)
  return t('planning.barLabel', {
    project: project?.name ?? '',
    from: formatDate(a.start_date),
    to: formatDate(a.end_date),
    hours: hours(a.minutes_per_day),
  })
}

function loadText(row: PlanningRow): string {
  return t('planning.loadText', { planned: hours(row.planned), capacity: hours(row.capacity) })
}

// ---------- dragging ----------

interface Drag {
  id: number
  mode: 'move' | 'start' | 'end'
  x: number
  shift: number
  moved: boolean
}

const drag = ref<Drag | null>(null)
const creating = ref<{ personId: number; from: string; to: string; anchor: string } | null>(null)

function preview(a: Allocation): Allocation {
  const d = drag.value
  if (!d || d.id !== a.id || !d.shift) return a
  if (d.mode === 'move') return { ...a, start_date: addDays(a.start_date, d.shift), end_date: addDays(a.end_date, d.shift) }
  if (d.mode === 'start') {
    const next = addDays(a.start_date, d.shift)
    return { ...a, start_date: next > a.end_date ? a.end_date : next }
  }
  const next = addDays(a.end_date, d.shift)
  return { ...a, end_date: next < a.start_date ? a.start_date : next }
}

function onBarDown(event: PointerEvent, a: Allocation, row: PlanningRow, mode: Drag['mode']) {
  if (!row.editable || event.button !== 0) return
  event.stopPropagation()
  ;(event.currentTarget as HTMLElement).setPointerCapture(event.pointerId)
  drag.value = { id: a.id, mode, x: event.clientX, shift: 0, moved: false }
}

function onBarMove(event: PointerEvent) {
  if (!drag.value) return
  const dx = event.clientX - drag.value.x
  if (Math.abs(dx) > 4) drag.value.moved = true
  drag.value.shift = Math.round(dx / cell.value)
}

async function onBarUp(a: Allocation) {
  const d = drag.value
  drag.value = null
  if (!d) return
  if (!d.moved) {
    openEditor(a)
    return
  }
  if (!d.shift) return
  const original = board.value!.allocations.find((x) => x.id === a.id)!
  const updated = { ...original }
  if (d.mode === 'move') {
    updated.start_date = addDays(original.start_date, d.shift)
    updated.end_date = addDays(original.end_date, d.shift)
  } else if (d.mode === 'start') {
    updated.start_date = minDate(addDays(original.start_date, d.shift), original.end_date)
  } else {
    updated.end_date = maxDate(addDays(original.end_date, d.shift), original.start_date)
  }
  Object.assign(original, updated)
  try {
    await api.put(`/api/planning/allocations/${a.id}`, payload(updated))
    showToast(t('planning.moved'))
  } catch (e) {
    showToast(errorText(e), 'error')
  }
  await load()
}

function minDate(a: string, b: string) {
  return a < b ? a : b
}

function maxDate(a: string, b: string) {
  return a > b ? a : b
}

function dayAt(event: PointerEvent): string {
  const track = (event.currentTarget as HTMLElement).getBoundingClientRect()
  const index = Math.min(dayList.value.length - 1, Math.max(0, Math.floor((event.clientX - track.left) / cell.value)))
  return dayList.value[index]
}

function onTrackDown(event: PointerEvent, row: PlanningRow) {
  if (!row.editable || event.button !== 0 || !activeProjects.value.length) return
  ;(event.currentTarget as HTMLElement).setPointerCapture(event.pointerId)
  const day = dayAt(event)
  creating.value = { personId: row.person.id, from: day, to: day, anchor: day }
}

function onTrackMove(event: PointerEvent) {
  if (!creating.value) return
  const day = dayAt(event)
  const anchor = creating.value.anchor
  creating.value.from = minDate(anchor, day)
  creating.value.to = maxDate(anchor, day)
}

function onTrackUp() {
  const c = creating.value
  creating.value = null
  if (c) openEditor(null, { user_id: c.personId, start_date: c.from, end_date: c.to })
}

function ghostStyle() {
  const c = creating.value!
  const from = dayDiff(dayList.value[0], c.from)
  const width = dayDiff(c.from, c.to) + 1
  return { left: `${from * cell.value + 2}px`, width: `${width * cell.value - 4}px`, top: '6px' }
}

// ---------- form ----------

const editorOpen = ref(false)
const editing = ref<Allocation | null>(null)
const form = reactive({ user_id: 0, project_id: 0, start_date: '', end_date: '', hours: 4, note: '' })
const errors = reactive<Record<string, string>>({})
const busy = ref(false)

function openEditor(a: Allocation | null, prefill: Partial<Allocation> = {}) {
  if (a && !board.value?.rows.find((r) => r.person.id === a.user_id)?.editable) {
    detail.value = a
    return
  }
  editing.value = a
  const base = a ?? {
    user_id: prefill.user_id ?? editableRows.value[0]?.person.id ?? 0,
    project_id: activeProjects.value[0]?.id ?? 0,
    start_date: prefill.start_date ?? (today > start.value ? today : start.value),
    end_date: prefill.end_date ?? addDays(today > start.value ? today : start.value, 4),
    minutes_per_day: 240,
    note: '',
  }
  Object.assign(form, {
    user_id: base.user_id, project_id: base.project_id, start_date: base.start_date, end_date: base.end_date,
    hours: base.minutes_per_day / 60, note: base.note,
  })
  for (const key of Object.keys(errors)) delete errors[key]
  editorOpen.value = true
}

function payload(a: Pick<Allocation, 'user_id' | 'project_id' | 'start_date' | 'end_date' | 'minutes_per_day' | 'note'>) {
  return { user_id: a.user_id, project_id: a.project_id, start_date: a.start_date, end_date: a.end_date, minutes_per_day: a.minutes_per_day, note: a.note }
}

async function save() {
  for (const key of Object.keys(errors)) delete errors[key]
  if (!form.project_id) errors.project_id = t('validation.project_required')
  if (!form.start_date) errors.start_date = t('validation.start_required')
  if (!form.end_date) errors.end_date = t('validation.end_required')
  else if (form.start_date && form.end_date < form.start_date) errors.end_date = t('validation.end_before_start')
  const minutes = Math.round(Number(form.hours) * 4) * 15
  if (!(minutes >= 15 && minutes <= 720)) errors.hours = t('planning.hoursInvalid')
  if (Object.keys(errors).length) return
  busy.value = true
  try {
    const body = payload({ ...form, minutes_per_day: minutes, note: form.note.trim() })
    if (editing.value) await api.put(`/api/planning/allocations/${editing.value.id}`, body)
    else await api.post('/api/planning/allocations', body)
    editorOpen.value = false
    showToast(t('planning.saved'))
    await load()
  } catch (e) {
    const field = (e as { field?: string }).field
    errors[field && field in form ? field : 'form'] = errorText(e)
  } finally {
    busy.value = false
  }
}

async function remove() {
  if (!editing.value) return
  busy.value = true
  try {
    await api.delete(`/api/planning/allocations/${editing.value.id}`)
    editorOpen.value = false
    showToast(t('planning.removed'))
    await load()
  } catch (e) {
    errors.form = errorText(e)
  } finally {
    busy.value = false
  }
}

const detail = ref<Allocation | null>(null)
const detailProject = computed<Project | undefined>(() => (detail.value ? projectsById.value.get(detail.value.project_id) : undefined))

function onKey(event: KeyboardEvent) {
  if (event.key === 'Escape') {
    drag.value = null
    creating.value = null
  }
}

onMounted(() => {
  load()
  window.addEventListener('keydown', onKey)
})
onBeforeUnmount(() => window.removeEventListener('keydown', onKey))
</script>

<template>
  <div class="page planning-page">
    <PageHeader :title="t('planning.title')" :subtitle="board?.can_plan ? t('planning.subtitle') : t('planning.subtitleMine')">
      <template #actions>
        <RouterLink v-if="isApprover" to="/planning/projects" class="btn btn-secondary"><AppIcon name="briefcase" />{{ t('planning.projects') }}</RouterLink>
        <button v-if="board?.can_plan" type="button" class="btn btn-primary" :disabled="!activeProjects.length" @click="openEditor(null)">
          <AppIcon name="plus" />{{ t('planning.new') }}
        </button>
      </template>
    </PageHeader>

    <div class="toolbar">
      <div class="row nav-group">
        <button type="button" class="btn btn-ghost btn-icon" :aria-label="t('planning.earlier')" @click="move(-1)"><AppIcon name="chevronLeft" /></button>
        <button type="button" class="btn btn-secondary" @click="start = mondayOf(today)">{{ t('planning.today') }}</button>
        <button type="button" class="btn btn-ghost btn-icon" :aria-label="t('planning.later')" @click="move(1)"><AppIcon name="chevronRight" /></button>
        <span class="range" aria-live="polite">{{ rangeLabel }}</span>
      </div>
      <div class="row">
        <div class="segmented" role="group" :aria-label="t('planning.zoom')">
          <button v-for="z in ZOOMS" :key="z" type="button" :aria-pressed="weeks === z" @click="weeks = z">{{ t('planning.weeks', { n: z }) }}</button>
        </div>
        <template v-if="departments.length > 1">
          <label for="pl-dept" class="visually-hidden">{{ t('planning.department') }}</label>
          <select id="pl-dept" v-model="department" class="select dept-select">
            <option value="">{{ t('planning.allDepartments') }}</option>
            <option v-for="d in departments" :key="d" :value="d">{{ d }}</option>
          </select>
        </template>
      </div>
    </div>

    <p v-if="board?.can_plan && !activeProjects.length" class="notice notice-info small">
      {{ t('planning.noProjects') }} <RouterLink v-if="isApprover" to="/planning/projects">{{ t('planning.createProject') }}</RouterLink>
    </p>

    <LoadState :loading="loading" :error="error" @retry="load">
      <section v-if="board && board.rows.length" class="card card-flush board-card">
        <div class="board" :class="`zoom-${weeks}`">
          <div class="board-inner">
            <!-- header -->
            <div class="b-row b-head">
              <div class="b-person b-corner">{{ t('planning.person') }}</div>
              <div class="b-track-head" :style="{ width: `${trackWidth}px` }">
                <div class="weeks">
                  <span v-for="w in weekGroups" :key="w.start" class="week" :style="{ width: `${w.days * cell}px` }">{{ w.label }}</span>
                </div>
                <div class="days">
                  <span
                    v-for="d in board.days"
                    :key="d.date"
                    class="day-head"
                    :class="{ off: d.off, today: d.date === today }"
                    :style="{ width: `${cell}px` }"
                    :title="formatDate(d.date)"
                  >
                    <template v-if="cell >= 30"><span class="wd">{{ weekday(d.date) }}</span></template>
                    <template v-if="cell >= 20 || d.date.endsWith('-01') || new Date(`${d.date}T00:00:00Z`).getUTCDay() === 1">{{ dayNumber(d.date) }}</template>
                  </span>
                </div>
              </div>
            </div>

            <!-- people -->
            <div v-for="row in board.rows" :key="row.person.id" class="b-row">
              <div class="b-person">
                <UserAvatar :id="row.person.id" :name="row.person.full_name" :photo-version="row.person.photo_version" :size="30" />
                <div class="who">
                  <span class="name">{{ row.person.full_name }}</span>
                  <span class="load" :class="`w-${workload(row.planned, row.capacity)}`">
                    <span class="meter" aria-hidden="true"><span :style="{ width: `${Math.min(100, percent(row.planned, row.capacity))}%` }" /></span>
                    <span class="pct">{{ percent(row.planned, row.capacity) }} %</span>
                    <span class="visually-hidden">{{ t(`planning.workload.${workload(row.planned, row.capacity)}`) }}, {{ loadText(row) }}</span>
                  </span>
                  <span class="muted tiny" aria-hidden="true">{{ loadText(row) }}<template v-if="row.booked"> · {{ t('planning.booked', { h: hours(row.booked) }) }}</template></span>
                </div>
              </div>
              <div
                class="b-track"
                :class="{ editable: row.editable && activeProjects.length }"
                :style="{ width: `${trackWidth}px`, height: `${rowHeight(row)}px` }"
                @pointerdown="onTrackDown($event, row)"
                @pointermove="onTrackMove"
                @pointerup="onTrackUp"
                @pointercancel="creating = null"
              >
                <div class="cells" aria-hidden="true">
                  <span
                    v-for="(d, i) in board.days"
                    :key="d.date"
                    class="cell"
                    :class="dayClass(row, i, rowLoads(row), dailyCapacity(row))"
                    :style="{ width: `${cell}px` }"
                  />
                </div>
                <template v-for="a in rowAllocations(row)" :key="a.id">
                  <button
                    v-if="visible(a)"
                    type="button"
                    class="bar"
                    :class="[`pc-${projectsById.get(a.project_id)?.color ?? 'blue'}`, { dragging: drag?.id === a.id, locked: !row.editable }]"
                    :style="barStyle(a, lanesFor(row).get(a.id) ?? 0)"
                    :aria-label="barLabel(a)"
                    :title="barLabel(a)"
                    @pointerdown="onBarDown($event, a, row, 'move')"
                    @pointermove="onBarMove"
                    @pointerup="onBarUp(a)"
                    @pointercancel="drag = null"
                    @click.prevent="drag === null && !row.editable && openEditor(a)"
                    @keydown.enter.prevent="openEditor(a)"
                    @keydown.space.prevent="openEditor(a)"
                  >
                    <span v-if="row.editable" class="grip grip-start" @pointerdown="onBarDown($event, a, row, 'start')" />
                    <span class="bar-text">{{ projectsById.get(a.project_id)?.name }}</span>
                    <span class="bar-hours">{{ hours(a.minutes_per_day) }}</span>
                    <span v-if="row.editable" class="grip grip-end" @pointerdown="onBarDown($event, a, row, 'end')" />
                  </button>
                </template>
                <span v-if="creating?.personId === row.person.id" class="ghost" :style="ghostStyle()" aria-hidden="true" />
              </div>
            </div>
          </div>
        </div>
        <div class="legend small muted">
          <span><span class="lg lg-away" aria-hidden="true" />{{ t('planning.legendAway') }}</span>
          <span><span class="lg lg-off" aria-hidden="true" />{{ t('planning.legendOff') }}</span>
          <span><span class="lg lg-over" aria-hidden="true" />{{ t('planning.legendOver') }}</span>
          <span v-if="board.can_plan">{{ t('planning.hint') }}</span>
        </div>
      </section>
      <section v-else class="card"><EmptyState icon="planning" :message="t('planning.empty')" /></section>
    </LoadState>

    <BaseModal
      :open="editorOpen"
      :title="editing ? t('planning.edit') : t('planning.new')"
      :confirm-label="t('app.save')"
      :busy="busy"
      @close="editorOpen = false"
      @confirm="save"
    >
      <form class="stack" novalidate @submit.prevent="save">
        <div v-if="errors.form" class="notice notice-danger small" role="alert">{{ errors.form }}</div>
        <FormField id="pl-person" :label="t('planning.person')" :error="errors.user_id">
          <template #default="{ attrs }">
            <select v-bind="attrs" v-model.number="form.user_id" class="select">
              <option v-for="r in editableRows" :key="r.person.id" :value="r.person.id">{{ r.person.full_name }}<template v-if="r.person.department"> · {{ r.person.department }}</template></option>
            </select>
          </template>
        </FormField>
        <FormField id="pl-project" :label="t('planning.project')" :error="errors.project_id">
          <template #default="{ attrs }">
            <select v-bind="attrs" v-model.number="form.project_id" class="select">
              <option v-for="p in board?.projects ?? []" :key="p.id" :value="p.id" :disabled="!p.active && p.id !== editing?.project_id">
                {{ p.name }}<template v-if="p.client"> · {{ p.client }}</template>
              </option>
            </select>
          </template>
        </FormField>
        <div class="grid-2">
          <FormField id="pl-start" :label="t('planning.from')" :error="errors.start_date">
            <template #default="{ attrs }"><input v-bind="attrs" v-model="form.start_date" type="date" class="input" /></template>
          </FormField>
          <FormField id="pl-end" :label="t('planning.to')" :error="errors.end_date">
            <template #default="{ attrs }"><input v-bind="attrs" v-model="form.end_date" type="date" class="input" :min="form.start_date" /></template>
          </FormField>
        </div>
        <FormField id="pl-hours" :label="t('planning.hoursPerDay')" :hint="t('planning.hoursHint')" :error="errors.hours">
          <template #default="{ attrs }"><input v-bind="attrs" v-model.number="form.hours" type="number" min="0.25" max="12" step="0.25" class="input hours-input" inputmode="decimal" /></template>
        </FormField>
        <FormField id="pl-note" :label="t('planning.note')" optional>
          <template #default="{ attrs }"><input v-bind="attrs" v-model="form.note" class="input" maxlength="200" /></template>
        </FormField>
        <div v-if="editing">
          <button type="button" class="btn btn-ghost danger-text" :disabled="busy" @click="remove"><AppIcon name="trash" />{{ t('planning.remove') }}</button>
        </div>
      </form>
    </BaseModal>

    <BaseModal :open="detail !== null" :title="detailProject?.name ?? ''" :description="detailProject?.client ?? ''" hide-actions @close="detail = null">
      <dl v-if="detail" class="facts">
        <div><dt>{{ t('planning.period') }}</dt><dd>{{ formatDate(detail.start_date) }} – {{ formatDate(detail.end_date) }}</dd></div>
        <div><dt>{{ t('planning.hoursPerDay') }}</dt><dd>{{ hours(detail.minutes_per_day) }} h</dd></div>
        <div v-if="detail.note"><dt>{{ t('planning.note') }}</dt><dd>{{ detail.note }}</dd></div>
      </dl>
    </BaseModal>
  </div>
</template>

<style scoped>
.planning-page {
  max-width: none;
}

.toolbar {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-3);
}

.nav-group {
  gap: var(--space-2);
}

.range {
  font-weight: 600;
  margin-left: var(--space-2);
}

.dept-select {
  width: auto;
}

.board-card {
  overflow: hidden;
}

.board {
  overflow-x: auto;
  overscroll-behavior-x: contain;
}

.board-inner {
  display: grid;
  width: max-content;
  min-width: 100%;
}

.b-row {
  display: flex;
  border-bottom: 1px solid var(--color-border);
}

.b-person {
  position: sticky;
  left: 0;
  z-index: 2;
  display: flex;
  align-items: center;
  gap: var(--space-3);
  width: 240px;
  flex-shrink: 0;
  padding: var(--space-2) var(--space-4);
  background: var(--color-surface);
  border-right: 1px solid var(--color-border);
}

.b-head {
  position: sticky;
  top: 0;
  z-index: 3;
  background: var(--color-surface-muted);
}

.b-corner {
  background: var(--color-surface-muted);
  font-size: var(--text-sm);
  font-weight: 600;
  color: var(--color-text-muted);
}

.who {
  display: grid;
  gap: 2px;
  min-width: 0;
}

.name {
  font-weight: 600;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.tiny {
  font-size: 0.75rem;
}

.load {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  font-size: 0.8rem;
  font-weight: 600;
}

.meter {
  position: relative;
  width: 72px;
  height: 6px;
  border-radius: 99px;
  background: var(--color-neutral-soft);
  overflow: hidden;
}

.meter > span {
  position: absolute;
  inset: 0 auto 0 0;
  border-radius: inherit;
  background: var(--color-text-subtle);
}

.w-good .meter > span,
.w-full .meter > span {
  background: var(--color-success);
}

.w-over .meter > span {
  background: var(--color-warning);
}

.w-over .pct {
  color: var(--color-warning);
}

.b-track-head {
  display: grid;
}

.weeks,
.days {
  display: flex;
}

.week {
  padding: 6px 8px;
  font-size: 0.75rem;
  font-weight: 600;
  color: var(--color-text-muted);
  border-left: 1px solid var(--color-border);
  white-space: nowrap;
  overflow: hidden;
}

.day-head {
  display: grid;
  place-items: center;
  padding: 2px 0 6px;
  font-size: 0.72rem;
  color: var(--color-text-muted);
  font-variant-numeric: tabular-nums;
  line-height: 1.2;
}

.day-head .wd {
  font-size: 0.68rem;
  text-transform: uppercase;
  letter-spacing: 0.02em;
}

.day-head.off {
  color: var(--color-text-subtle);
  background: var(--color-neutral-soft);
}

.day-head.today {
  color: var(--color-primary-text);
  font-weight: 700;
}

.b-track {
  position: relative;
  flex-shrink: 0;
  touch-action: pan-y;
}

.b-track.editable {
  cursor: copy;
}

.cells {
  position: absolute;
  inset: 0;
  display: flex;
}

.cell {
  position: relative;
  height: 100%;
  border-left: 1px solid transparent;
}

.cell.monday {
  border-left-color: var(--color-border);
}

.cell.weekend,
.cell.holiday {
  background: var(--color-neutral-soft);
}

.cell.away {
  background: repeating-linear-gradient(135deg, var(--color-neutral-soft) 0 4px, transparent 4px 8px);
}

.cell.today::before {
  content: '';
  position: absolute;
  inset: 0 auto 0 50%;
  width: 2px;
  background: var(--color-primary);
  opacity: 0.5;
}

.cell.over::after {
  content: '';
  position: absolute;
  inset: auto 1px 2px;
  height: 4px;
  border-radius: 2px;
  background: var(--color-warning);
}

.bar {
  position: absolute;
  display: flex;
  align-items: center;
  gap: 6px;
  height: 24px;
  padding: 0 8px;
  border: 0;
  border-radius: 6px;
  background: var(--pc);
  color: #fff;
  font: inherit;
  font-size: 0.78rem;
  font-weight: 600;
  text-align: left;
  cursor: grab;
  overflow: hidden;
  box-shadow: 0 1px 2px rgb(0 0 0 / 0.15);
  transition: box-shadow 150ms ease-out, transform 150ms ease-out;
  touch-action: none;
  z-index: 1;
}

.bar:hover {
  box-shadow: 0 2px 8px rgb(0 0 0 / 0.25);
}

.bar:focus-visible {
  outline: 3px solid var(--color-focus);
  outline-offset: 2px;
}

.bar.dragging {
  cursor: grabbing;
  transform: translateY(-1px);
  box-shadow: 0 6px 16px rgb(0 0 0 / 0.3);
  z-index: 2;
}

.bar.locked {
  cursor: pointer;
}

.bar-text {
  flex: 0 1 auto;
  min-width: 0;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.bar-hours {
  opacity: 0.9;
  font-variant-numeric: tabular-nums;
}

.zoom-8 .bar-hours,
.zoom-12 .bar-hours {
  display: none;
}

.grip {
  position: absolute;
  top: 0;
  bottom: 0;
  width: 8px;
  cursor: ew-resize;
}

.grip-start {
  left: 0;
}

.grip-end {
  right: 0;
}

.grip::after {
  content: '';
  position: absolute;
  top: 7px;
  bottom: 7px;
  left: 3px;
  width: 2px;
  border-radius: 1px;
  background: rgb(255 255 255 / 0.6);
  opacity: 0;
  transition: opacity 150ms;
}

.bar:hover .grip::after {
  opacity: 1;
}

.ghost {
  position: absolute;
  height: 24px;
  border: 2px dashed var(--color-primary);
  border-radius: 6px;
  background: var(--color-primary-soft);
  pointer-events: none;
}

.legend {
  display: flex;
  flex-wrap: wrap;
  gap: var(--space-2) var(--space-5);
  padding: var(--space-3) var(--space-4);
  border-top: 1px solid var(--color-border);
}

.legend > span {
  display: inline-flex;
  align-items: center;
  gap: 6px;
}

.lg {
  display: inline-block;
  width: 14px;
  height: 14px;
  border-radius: 3px;
  border: 1px solid var(--color-border);
}

.lg-off {
  background: var(--color-neutral-soft);
}

.lg-away {
  background: repeating-linear-gradient(135deg, var(--color-border-strong) 0 3px, transparent 3px 6px);
}

.lg-over {
  height: 5px;
  border: 0;
  background: var(--color-warning);
}

.hours-input {
  max-width: 140px;
}

.danger-text {
  color: var(--color-danger);
}

.facts {
  display: grid;
  gap: var(--space-3);
}

.facts dt {
  font-size: var(--text-sm);
  color: var(--color-text-muted);
}

.facts dd {
  margin: 0;
  font-weight: 600;
}

@media (max-width: 720px) {
  .b-person {
    width: 150px;
    padding: var(--space-2);
  }

  .b-person :deep(.avatar) {
    display: none;
  }

  .meter {
    width: 40px;
  }
}

@media (prefers-reduced-motion: reduce) {
  .bar {
    transition: none;
  }
}
</style>
