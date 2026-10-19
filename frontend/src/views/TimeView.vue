<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import AppIcon from '@/components/AppIcon.vue'
import BaseModal from '@/components/BaseModal.vue'
import FormField from '@/components/FormField.vue'
import LoadState from '@/components/LoadState.vue'
import PageHeader from '@/components/PageHeader.vue'
import SectionContact from '@/components/SectionContact.vue'
import SortHeader from '@/components/SortHeader.vue'
import TimeMonth from '@/components/TimeMonth.vue'
import UserAvatar from '@/components/UserAvatar.vue'
import { api, query } from '@/lib/api'
import { errorText, formatDate, locale, t } from '@/lib/i18n'
import { currentUser, isApprover } from '@/lib/session'
import { summary } from '@/lib/summary'
import { useSort } from '@/lib/sort'
import { addDays, balance, clock, hours, mondayOf } from '@/lib/time'
import { showToast } from '@/lib/toast'
import type { MyAllocation, PendingMonth, Project, TimeDay, TimeEntry, TimeStatus, TimeTeamRow, TimeWeek } from '@/lib/types'
import { todayIso } from '@/lib/workdays'

const route = useRoute()
const router = useRouter()

const tab = ref<'mine' | 'month' | 'team'>(route.query.tab === 'team' ? 'team' : route.query.tab === 'month' ? 'month' : 'mine')
const month = ref(typeof route.query.month === 'string' && /^\d{4}-\d{2}$/.test(route.query.month) ? route.query.month : todayIso().slice(0, 7))
const personId = ref<number | null>(Number(route.query.person) || null)
const weekStart = ref(mondayOf(typeof route.query.week === 'string' ? route.query.week : todayIso()))
const status = ref<TimeStatus | null>(null)
const week = ref<TimeWeek | null>(null)
const team = ref<TimeTeamRow[]>([])
const pendingMonths = ref<PendingMonth[]>([])
const projects = ref<Project[]>([])
const plannedToday = ref<MyAllocation[]>([])
const clockProject = ref<number | null>(null)
const loading = ref(true)
const error = ref<string | null>(null)
const busy = ref(false)
const now = ref(Date.now())
let ticker: number | undefined

const canSeeTeam = computed(() => isApprover.value || summary.value.acting_deputy)
const viewingOther = computed(() => personId.value !== null && personId.value !== currentUser.value?.id)
const isCurrentWeek = computed(() => weekStart.value === mondayOf(todayIso()))
const exportMonth = computed(() => weekStart.value.slice(0, 7))

const runningMinutes = computed(() => {
  const running = status.value?.running
  return running ? Math.max(0, Math.floor((now.value - new Date(running.start_at).getTime()) / 60000)) : 0
})
const todayTotal = computed(() => (status.value ? status.value.today_worked + (status.value.running ? runningMinutes.value - status.value.running.minutes : 0) : 0))
const todayProgress = computed(() => (status.value?.today_target ? Math.min(100, (todayTotal.value / status.value.today_target) * 100) : 0))

const teamSort = useSort(team, {
  name: (r) => r.person.full_name,
  worked: (r) => r.worked,
  diff: (r) => r.worked - r.target,
}, 'name')

const editor = reactive({ open: false, entry: null as TimeEntry | null, day: todayIso(), start: '08:00', end: '12:00', note: '', project_id: null as number | null })
const editorErrors = reactive<Record<string, string>>({})
const deleteTarget = ref<TimeEntry | null>(null)

function dayLabel(day: TimeDay): string {
  return new Date(`${day.date}T00:00`).toLocaleDateString(locale.value, { weekday: 'short', day: 'numeric', month: 'short' })
}

function offLabel(off: string | null): string {
  if (!off) return ''
  return off.startsWith('holiday:') ? off.slice(8) : t('time.vacation')
}

async function loadStatus() {
  status.value = await api.get<TimeStatus>('/api/time/status')
}

async function loadWeek() {
  week.value = await api.get<TimeWeek>(`/api/time/week${query({ start: weekStart.value, person_id: personId.value ?? undefined })}`)
}

async function loadTeam() {
  ;[team.value, pendingMonths.value] = await Promise.all([
    api.get<TimeTeamRow[]>(`/api/time/team${query({ start: weekStart.value })}`),
    api.get<PendingMonth[]>('/api/time/months/pending'),
  ])
}

async function loadProjects() {
  const today = todayIso()
  ;[projects.value, plannedToday.value] = await Promise.all([
    api.get<Project[]>('/api/planning/projects').catch(() => []),
    api.get<MyAllocation[]>(`/api/planning/mine${query({ start: today, end: today })}`).catch(() => []),
  ])
  if (clockProject.value === null && plannedToday.value.length) clockProject.value = plannedToday.value[0].project.id
}

const projectColor = (id: number | null) => projects.value.find((p) => p.id === id)?.color ?? 'slate'

function monthLabel(value: string): string {
  return new Date(`${value}-01T00:00:00Z`).toLocaleDateString(locale.value, { month: 'long', year: 'numeric', timeZone: 'UTC' })
}

function reviewMonth(item: PendingMonth) {
  month.value = item.month
  personId.value = item.person.id
  tab.value = 'month'
}

function openDay(date: string) {
  weekStart.value = mondayOf(date)
  tab.value = 'mine'
}

async function load() {
  loading.value = week.value === null && team.value.length === 0
  error.value = null
  try {
    if (tab.value === 'team') await loadTeam()
    else if (tab.value === 'month') await (viewingOther.value ? Promise.resolve() : loadStatus())
    else await Promise.all([loadWeek(), viewingOther.value ? Promise.resolve() : loadStatus()])
  } catch (e) {
    error.value = errorText(e)
  } finally {
    loading.value = false
  }
}

async function clockAction() {
  busy.value = true
  try {
    status.value = await api.post<TimeStatus>(
      status.value?.running ? '/api/time/clock-out' : '/api/time/clock-in',
      status.value?.running ? {} : { project_id: clockProject.value },
    )
    showToast(status.value.running ? t('time.clockedIn') : t('time.clockedOut'))
    if (tab.value === 'mine') await loadWeek()
  } catch (e) {
    showToast(errorText(e), 'error')
  } finally {
    busy.value = false
  }
}

function toLocalClock(iso: string | null): string {
  return iso ? clock(iso) : ''
}

function openEditor(entry: TimeEntry | null, day?: string) {
  for (const key of Object.keys(editorErrors)) delete editorErrors[key]
  Object.assign(editor, entry
    ? { open: true, entry, day: entry.day, start: toLocalClock(entry.start_at), end: toLocalClock(entry.end_at) || toLocalClock(new Date().toISOString()), note: entry.note, project_id: entry.project_id }
    : { open: true, entry: null, day: day ?? todayIso(), start: '08:00', end: '12:00', note: '', project_id: plannedToday.value[0]?.project.id ?? null })
}

async function saveEntry() {
  for (const key of Object.keys(editorErrors)) delete editorErrors[key]
  if (!editor.day) editorErrors.day = t('validation.date_required')
  if (editor.end <= editor.start) editorErrors.end = t('validation.end_before_start_time')
  if (Object.keys(editorErrors).length) return
  busy.value = true
  try {
    const body = { start: editor.start, end: editor.end, note: editor.note.trim(), project_id: editor.project_id }
    if (editor.entry) await api.put(`/api/time/entries/${editor.entry.id}`, body)
    else await api.post('/api/time/entries', { ...body, day: editor.day })
    editor.open = false
    showToast(t('time.saved'))
    await Promise.all([loadWeek(), loadStatus()])
  } catch (e) {
    const field = (e as { field?: string }).field
    editorErrors[field && ['day', 'start', 'end', 'project_id'].includes(field) ? field : 'start'] = errorText(e)
  } finally {
    busy.value = false
  }
}

async function removeEntry() {
  if (!deleteTarget.value) return
  busy.value = true
  try {
    await api.delete(`/api/time/entries/${deleteTarget.value.id}`)
    deleteTarget.value = null
    showToast(t('time.deleted'))
    await Promise.all([loadWeek(), loadStatus()])
  } catch (e) {
    showToast(errorText(e), 'error')
  } finally {
    busy.value = false
  }
}

function showPerson(id: number) {
  personId.value = id
  tab.value = 'mine'
}

watch([tab, personId, weekStart, month], () => {
  router.replace({
    query: {
      ...(tab.value !== 'mine' ? { tab: tab.value } : {}),
      ...(personId.value && tab.value !== 'team' ? { person: String(personId.value) } : {}),
      ...(!isCurrentWeek.value && tab.value === 'mine' ? { week: weekStart.value } : {}),
      ...(tab.value === 'month' && month.value !== todayIso().slice(0, 7) ? { month: month.value } : {}),
    },
  })
  load()
})

onMounted(() => {
  load()
  loadProjects()
  ticker = window.setInterval(() => (now.value = Date.now()), 30_000)
})
onBeforeUnmount(() => window.clearInterval(ticker))
</script>

<template>
  <div class="page">
    <PageHeader :title="t('time.title')" :subtitle="t('time.subtitle')" />

    <div class="segmented" role="group" :aria-label="t('time.title')">
      <button type="button" :aria-pressed="tab === 'mine'" @click="tab = 'mine'">{{ t('time.tabWeek') }}</button>
      <button type="button" :aria-pressed="tab === 'month'" @click="tab = 'month'">{{ t('time.tabMonth') }}</button>
      <button v-if="canSeeTeam" type="button" :aria-pressed="tab === 'team'" @click="tab = 'team'; personId = null">
        {{ t('time.tabTeam') }}<span v-if="summary.time_months_pending" class="seg-count">{{ summary.time_months_pending }}</span>
      </button>
    </div>

    <!-- Clock card -->
    <section v-if="tab !== 'team' && !viewingOther && status" class="clock-card" :class="{ running: status.running }" aria-labelledby="clock-title">
      <div class="clock-main">
        <p id="clock-title" class="clock-state">
          <span class="dot" aria-hidden="true" />
          {{ status.running ? t('time.runningSince', { time: clock(status.running.start_at) }) : t('time.notRunning') }}
          <span v-if="status.running?.project_name" class="proj-chip" :class="`pc-${projectColor(status.running.project_id)}`">
            <span class="project-dot" aria-hidden="true" />{{ status.running.project_name }}
          </span>
        </p>
        <p class="clock-total" aria-live="polite">{{ hours(todayTotal) }}<span class="of"> / {{ hours(status.today_target) }} h</span></p>
        <div class="progress" aria-hidden="true"><span :style="{ width: `${todayProgress}%` }" /></div>
        <p class="muted small">{{ t('time.todayHint') }}</p>
      </div>
      <div class="clock-side">
      <div v-if="!status.running && projects.length" class="clock-project">
        <label for="clock-project" class="small muted">{{ t('time.project') }}</label>
        <select id="clock-project" v-model="clockProject" class="select">
          <option :value="null">{{ t('time.noProject') }}</option>
          <optgroup v-if="plannedToday.length" :label="t('time.plannedToday')">
            <option v-for="a in plannedToday" :key="`p${a.id}`" :value="a.project.id">{{ a.project.name }} · {{ hours(a.minutes_per_day) }} h</option>
          </optgroup>
          <optgroup :label="t('time.allProjects')">
            <option v-for="p in projects" :key="p.id" :value="p.id">{{ p.name }}</option>
          </optgroup>
        </select>
      </div>
      <button type="button" class="btn clock-btn" :class="status.running ? 'btn-danger' : 'btn-primary'" :disabled="busy" @click="clockAction">
        <AppIcon :name="status.running ? 'stop' : 'play'" :size="22" />
        {{ status.running ? t('time.clockOut') : t('time.clockIn') }}
      </button>
      </div>
      <dl class="clock-stats">
        <div><dt>{{ t('time.thisWeek') }}</dt><dd>{{ hours(status.week_worked) }} / {{ hours(status.week_target) }} h</dd></div>
        <div>
          <dt>{{ t('time.balance') }}</dt>
          <dd :class="status.balance_year >= 0 ? 'plus' : 'minus'">{{ balance(status.balance_year) }} h</dd>
        </div>
      </dl>
    </section>

    <TimeMonth
      v-if="tab === 'month'"
      v-model:month="month"
      :person-id="personId"
      @open-day="openDay"
      @back="tab = 'team'; personId = null"
    />

    <!-- Week navigation -->
    <div v-if="tab !== 'month'" class="week-bar">
      <div class="row">
        <button type="button" class="btn btn-secondary btn-icon" :aria-label="t('time.prevWeek')" @click="weekStart = addDays(weekStart, -7)"><AppIcon name="chevronLeft" /></button>
        <h2 class="week-title">{{ t('time.weekOf', { from: formatDate(weekStart), to: formatDate(addDays(weekStart, 6)) }) }}</h2>
        <button type="button" class="btn btn-secondary btn-icon" :aria-label="t('time.nextWeek')" :disabled="isCurrentWeek" @click="weekStart = addDays(weekStart, 7)"><AppIcon name="chevronRight" /></button>
        <button v-if="!isCurrentWeek" type="button" class="btn btn-ghost" @click="weekStart = mondayOf(todayIso())">{{ t('time.thisWeekButton') }}</button>
      </div>
      <div v-if="tab === 'mine'" class="row">
        <a class="btn btn-ghost" :href="`/api/time/export.csv${query({ month: exportMonth, person_id: personId ?? undefined })}`" download>
          <AppIcon name="download" :size="18" />{{ t('time.export') }}
        </a>
        <button v-if="!viewingOther" type="button" class="btn btn-secondary" @click="openEditor(null)"><AppIcon name="plus" :size="18" />{{ t('time.addEntry') }}</button>
      </div>
    </div>

    <LoadState v-if="tab !== 'month'" :loading="loading" :error="error" @retry="load">
      <!-- Months waiting for approval -->
      <section v-if="tab === 'team' && pendingMonths.length" class="card card-flush pending-card" aria-labelledby="pending-title">
        <h2 id="pending-title" class="h3 pending-title"><AppIcon name="checkCircle" :size="20" />{{ t('time.month.toApprove') }}</h2>
        <ul class="list">
          <li v-for="item in pendingMonths" :key="`${item.person.id}-${item.month}`" class="pending-row">
            <span class="person">
              <UserAvatar :id="item.person.id" :name="item.person.full_name" :photo-version="item.person.photo_version" :size="32" />
              <span>
                <strong>{{ item.person.full_name }}</strong>
                <span class="muted small block">{{ monthLabel(item.month) }} · {{ hours(item.worked) }} / {{ hours(item.target) }} h</span>
              </span>
            </span>
            <button type="button" class="btn btn-secondary" @click="reviewMonth(item)">{{ t('time.month.review') }}</button>
          </li>
        </ul>
      </section>

      <!-- Team -->
      <section v-if="tab === 'team'" class="card card-flush">
        <div class="table-wrap">
          <table class="table">
            <thead>
              <tr>
                <th scope="col" :aria-sort="teamSort.ariaSort('name')"><SortHeader :label="t('time.person')" :active="teamSort.key.value === 'name'" :dir="teamSort.dir.value" @sort="teamSort.toggle('name')" /></th>
                <th scope="col" class="num" :aria-sort="teamSort.ariaSort('worked')"><SortHeader :label="t('time.worked')" :active="teamSort.key.value === 'worked'" :dir="teamSort.dir.value" @sort="teamSort.toggle('worked')" /></th>
                <th scope="col" class="num">{{ t('time.target') }}</th>
                <th scope="col" class="num" :aria-sort="teamSort.ariaSort('diff')"><SortHeader :label="t('time.difference')" :active="teamSort.key.value === 'diff'" :dir="teamSort.dir.value" @sort="teamSort.toggle('diff')" /></th>
                <th scope="col"><span class="visually-hidden">{{ t('time.details') }}</span></th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="row in teamSort.sorted.value" :key="row.person.id">
                <td>
                  <span class="person">
                    <UserAvatar :id="row.person.id" :name="row.person.full_name" :photo-version="row.person.photo_version" :size="32" />
                    <span>
                      {{ row.person.full_name }}
                      <span v-if="row.clocked_in" class="live small"><span class="dot" aria-hidden="true" />{{ t('time.present') }}</span>
                    </span>
                  </span>
                </td>
                <td class="num">{{ hours(row.worked) }}</td>
                <td class="num">{{ hours(row.target) }}</td>
                <td class="num" :class="row.worked - row.target >= 0 ? 'plus' : 'minus'">{{ balance(row.worked - row.target) }}</td>
                <td><button type="button" class="btn btn-ghost" @click="showPerson(row.person.id)">{{ t('time.details') }}</button></td>
              </tr>
            </tbody>
          </table>
        </div>
      </section>

      <!-- Week -->
      <section v-else-if="week" class="card card-flush" :aria-label="week.person.full_name">
        <div v-if="viewingOther" class="other-head">
          <UserAvatar :id="week.person.id" :name="week.person.full_name" :photo-version="week.person.photo_version" :size="36" />
          <strong>{{ week.person.full_name }}</strong>
          <button type="button" class="btn btn-ghost" @click="tab = 'team'; personId = null">{{ t('time.backToTeam') }}</button>
        </div>
        <ul class="list days">
          <li v-for="day in week.days" :key="day.date" class="day" :class="{ today: day.date === todayIso(), weekend: !day.target && !day.off && !day.entries.length }">
            <div class="day-head">
              <span class="day-name">{{ dayLabel(day) }}</span>
              <span v-if="day.off" class="off-chip">{{ offLabel(day.off) }}</span>
              <span v-else-if="day.pending" class="off-chip pending-chip">{{ t('time.month.pendingShort') }}</span>
              <span v-else-if="day.home_office" class="off-chip">{{ t('time.month.homeOffice') }}</span>
            </div>
            <ul v-if="day.entries.length" class="entries">
              <li v-for="entry in day.entries" :key="entry.id" class="entry">
                <span class="range">{{ clock(entry.start_at) }} – {{ entry.end_at ? clock(entry.end_at) : t('time.now') }}</span>
                <span class="muted small">{{ hours(entry.minutes) }} h</span>
                <span v-if="entry.project_name" class="proj-chip small" :class="`pc-${projectColor(entry.project_id)}`"><span class="project-dot" aria-hidden="true" />{{ entry.project_name }}</span>
                <span v-if="entry.note" class="note small">{{ entry.note }}</span>
                <span v-if="entry.edited" class="edited small" :title="t('time.editedHint')">{{ t('time.edited') }}</span>
                <span v-if="!viewingOther && entry.end_at" class="entry-actions">
                  <button type="button" class="btn btn-ghost btn-icon" :aria-label="t('time.editEntry')" @click="openEditor(entry)"><AppIcon name="edit" :size="16" /></button>
                  <button type="button" class="btn btn-ghost btn-icon" :aria-label="t('time.deleteEntry')" @click="deleteTarget = entry"><AppIcon name="trash" :size="16" /></button>
                </span>
              </li>
            </ul>
            <p v-for="w in day.warnings" :key="w" class="warning small"><AppIcon name="alert" :size="14" />{{ t(`time.warnings.${w}`) }}</p>
            <div class="day-sum">
              <span class="worked">{{ hours(day.worked) }}</span>
              <span class="muted small">/ {{ hours(day.target) }}</span>
              <button v-if="!viewingOther && day.date <= todayIso() && !day.entries.length && day.target" type="button" class="btn btn-ghost add-day" @click="openEditor(null, day.date)">
                <AppIcon name="plus" :size="16" />{{ t('time.add') }}
              </button>
            </div>
          </li>
        </ul>
        <div class="week-foot">
          <span>{{ t('time.weekTotal') }}: <strong>{{ hours(week.worked) }}</strong> / {{ hours(week.target) }} h</span>
          <span>{{ t('time.balance') }}: <strong :class="week.balance_year >= 0 ? 'plus' : 'minus'">{{ balance(week.balance_year) }} h</strong></span>
        </div>
      </section>
    </LoadState>

    <SectionContact section="time" />

    <BaseModal :open="editor.open" :title="editor.entry ? t('time.editEntry') : t('time.addEntry')" :confirm-label="t('app.save')" :busy="busy" @close="editor.open = false" @confirm="saveEntry">
      <form class="stack" novalidate @submit.prevent="saveEntry">
        <FormField id="te-day" :label="t('time.day')" :error="editorErrors.day">
          <template #default="{ attrs }"><input v-bind="attrs" v-model="editor.day" type="date" class="input" :max="todayIso()" :disabled="!!editor.entry" /></template>
        </FormField>
        <div class="grid-2">
          <FormField id="te-start" :label="t('time.from')" :error="editorErrors.start">
            <template #default="{ attrs }"><input v-bind="attrs" v-model="editor.start" type="time" class="input" step="60" /></template>
          </FormField>
          <FormField id="te-end" :label="t('time.to')" :error="editorErrors.end">
            <template #default="{ attrs }"><input v-bind="attrs" v-model="editor.end" type="time" class="input" step="60" /></template>
          </FormField>
        </div>
        <FormField v-if="projects.length || editor.project_id" id="te-project" :label="t('time.project')" :error="editorErrors.project_id" optional>
          <template #default="{ attrs }">
            <select v-bind="attrs" v-model="editor.project_id" class="select">
              <option :value="null">{{ t('time.noProject') }}</option>
              <option v-if="editor.entry?.project_id && !projects.some((p) => p.id === editor.entry?.project_id)" :value="editor.entry.project_id">{{ editor.entry.project_name }}</option>
              <option v-for="p in projects" :key="p.id" :value="p.id">{{ p.name }}</option>
            </select>
          </template>
        </FormField>
        <FormField id="te-note" :label="t('time.note')" optional>
          <template #default="{ attrs }"><input v-bind="attrs" v-model="editor.note" class="input" maxlength="200" :placeholder="t('time.notePlaceholder')" /></template>
        </FormField>
        <p class="muted small">{{ t('time.editHint') }}</p>
      </form>
    </BaseModal>

    <BaseModal
      :open="deleteTarget !== null"
      :title="t('time.deleteTitle')"
      :description="deleteTarget ? `${clock(deleteTarget.start_at)} – ${clock(deleteTarget.end_at)}` : ''"
      :confirm-label="t('time.deleteEntry')"
      tone="danger"
      :busy="busy"
      @close="deleteTarget = null"
      @confirm="removeEntry"
    />
  </div>
</template>

<style scoped>
.clock-side {
  display: grid;
  gap: var(--space-2);
  justify-items: stretch;
}

.clock-project {
  display: grid;
  gap: 4px;
}

.proj-chip {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 2px 8px;
  border-radius: 99px;
  background: var(--color-neutral-soft);
  color: var(--color-text);
  font-weight: 600;
}

.pending-chip {
  border: 1px dashed var(--color-primary);
}

.seg-count {
  display: inline-grid;
  place-items: center;
  min-width: 20px;
  height: 20px;
  margin-left: 6px;
  padding: 0 6px;
  border-radius: 99px;
  background: var(--color-badge);
  color: var(--color-on-badge);
  font-size: 0.75rem;
  font-weight: 700;
}

.pending-card {
  margin-bottom: var(--space-4);
}

.pending-title {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  padding: var(--space-4) var(--space-5) var(--space-2);
}

.pending-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-3);
  padding: var(--space-3) var(--space-5);
}

.block {
  display: block;
}

.clock-card {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto;
  gap: var(--space-4) var(--space-6);
  align-items: center;
  padding: var(--space-5) var(--space-6);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-lg);
  background: var(--color-surface);
  box-shadow: var(--shadow-card);
}

.clock-card.running {
  border-color: color-mix(in srgb, var(--color-success) 45%, var(--color-border));
}

.clock-main {
  display: grid;
  gap: var(--space-2);
}

.clock-state {
  display: inline-flex;
  align-items: center;
  gap: var(--space-2);
  font-weight: 600;
  color: var(--color-text-muted);
}

.dot {
  display: inline-block;
  width: 10px;
  height: 10px;
  border-radius: 50%;
  background: var(--color-border-strong);
}

.running .dot,
.live .dot {
  background: var(--color-success);
  box-shadow: 0 0 0 4px color-mix(in srgb, var(--color-success) 20%, transparent);
}

.clock-total {
  font-family: var(--font-heading);
  font-size: 2.5rem;
  font-weight: 600;
  line-height: 1.1;
  font-variant-numeric: tabular-nums;
}

.of {
  font-size: var(--text-lg);
  color: var(--color-text-muted);
  font-weight: 500;
}

.progress {
  height: 8px;
  max-width: 420px;
  border-radius: var(--radius-full);
  background: var(--color-neutral-soft);
  overflow: hidden;
}

.progress span {
  display: block;
  height: 100%;
  border-radius: inherit;
  background: var(--color-success);
  transition: width var(--t-med) var(--ease);
}

.clock-btn {
  min-width: 180px;
  min-height: 64px;
  font-size: var(--text-lg);
  border-radius: var(--radius-lg);
}

.clock-stats {
  grid-column: 1 / -1;
  display: flex;
  flex-wrap: wrap;
  gap: var(--space-6);
  margin: 0;
  padding-top: var(--space-4);
  border-top: 1px solid var(--color-border);
}

.clock-stats dt {
  font-size: var(--text-sm);
  color: var(--color-text-muted);
}

.clock-stats dd {
  margin: 0;
  font-weight: 700;
  font-size: var(--text-lg);
  font-variant-numeric: tabular-nums;
}

.plus {
  color: var(--color-success);
}

.minus {
  color: var(--color-warning);
}

.week-bar {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-3);
}

.week-title {
  font-size: var(--text-md);
  min-width: 220px;
  text-align: center;
}

.other-head {
  display: flex;
  align-items: center;
  gap: var(--space-3);
  padding: var(--space-3) var(--space-5);
  border-bottom: 1px solid var(--color-border);
}

.other-head .btn {
  margin-left: auto;
}

.day {
  display: grid;
  grid-template-columns: 160px minmax(0, 1fr) 150px;
  grid-template-areas: 'head entries sum' 'head warn sum';
  gap: var(--space-1) var(--space-4);
  align-items: center;
  padding: var(--space-3) var(--space-5);
}

.day.today {
  background: color-mix(in srgb, var(--color-primary-soft) 60%, transparent);
}

.day.weekend {
  color: var(--color-text-subtle);
}

.day-head {
  grid-area: head;
  display: grid;
  gap: 4px;
  justify-items: start;
}

.day-name {
  font-weight: 600;
}

.off-chip {
  padding: 1px 8px;
  border-radius: var(--radius-full);
  background: var(--color-warning-soft);
  color: var(--color-warning);
  font-size: var(--text-xs);
  font-weight: 700;
}

.entries {
  grid-area: entries;
  list-style: none;
  margin: 0;
  padding: 0;
  display: grid;
  gap: 2px;
}

.entry {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: var(--space-1) var(--space-3);
  min-height: 32px;
}

.range {
  font-weight: 600;
  font-variant-numeric: tabular-nums;
}

.note {
  color: var(--color-text-muted);
  font-style: italic;
}

.edited {
  padding: 0 6px;
  border-radius: var(--radius-sm);
  background: var(--color-neutral-soft);
  color: var(--color-text-muted);
}

.entry-actions {
  display: inline-flex;
}

.entry-actions .btn {
  min-height: 32px;
  width: 32px;
}

.warning {
  grid-area: warn;
  display: inline-flex;
  align-items: center;
  gap: 4px;
  color: var(--color-warning);
}

.day-sum {
  grid-area: sum;
  display: flex;
  align-items: baseline;
  justify-content: flex-end;
  gap: 4px;
  font-variant-numeric: tabular-nums;
}

.worked {
  font-weight: 700;
}

.add-day {
  min-height: 32px;
  padding: 0 var(--space-2);
  margin-left: var(--space-2);
}

.week-foot {
  display: flex;
  flex-wrap: wrap;
  justify-content: space-between;
  gap: var(--space-3);
  padding: var(--space-3) var(--space-5);
  border-top: 1px solid var(--color-border);
  background: var(--color-surface-muted);
  font-variant-numeric: tabular-nums;
}

.person {
  display: inline-flex;
  align-items: center;
  gap: var(--space-3);
}

.live {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  margin-left: var(--space-2);
  color: var(--color-success);
  font-weight: 600;
}

@media (max-width: 720px) {
  .clock-card {
    grid-template-columns: 1fr;
    padding: var(--space-4);
  }

  .clock-btn {
    width: 100%;
  }

  .week-bar > .row:first-child {
    flex-wrap: nowrap;
    width: 100%;
  }

  .week-title {
    min-width: 0;
    flex: 1;
    font-size: var(--text-sm);
  }

  .day {
    grid-template-columns: minmax(0, 1fr) auto;
    grid-template-areas: 'head sum' 'entries entries' 'warn warn';
    padding: var(--space-3) var(--space-4);
  }
}
</style>
