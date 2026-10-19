<script setup lang="ts">
/**
 * Month overview of working time: one row per calendar week, a cell per day with worked vs. target,
 * days off, open requests and hints. The person hands the month in; the manager approves it or sends it back.
 */
import { computed, onMounted, ref, watch } from 'vue'
import AppIcon from './AppIcon.vue'
import BaseModal from './BaseModal.vue'
import FormField from './FormField.vue'
import LoadState from './LoadState.vue'
import UserAvatar from './UserAvatar.vue'
import { api, query } from '@/lib/api'
import { errorText, formatDate, formatDateTime, locale, t } from '@/lib/i18n'
import { currentUser } from '@/lib/session'
import { refreshSummary } from '@/lib/summary'
import { balance, hours, mondayOf, addDays } from '@/lib/time'
import { showToast } from '@/lib/toast'
import type { TimeDay, TimeMonth } from '@/lib/types'
import { todayIso } from '@/lib/workdays'

const props = defineProps<{ month: string; personId: number | null }>()
const emit = defineEmits<{ 'update:month': [value: string]; openDay: [date: string]; back: [] }>()

const WEEKEND_KEY = 'officehub.time.weekends'
const data = ref<TimeMonth | null>(null)
const loading = ref(true)
const error = ref<string | null>(null)
const busy = ref(false)
const showWeekends = ref(readWeekends())
const returnOpen = ref(false)
const returnComment = ref('')
const returnError = ref('')
const today = todayIso()

function readWeekends(): boolean {
  try {
    return localStorage.getItem(WEEKEND_KEY) !== 'false'
  } catch {
    return true
  }
}

watch(showWeekends, (value) => {
  try {
    localStorage.setItem(WEEKEND_KEY, String(value))
  } catch {
    /* private window: just don't remember */
  }
})

const monthTitle = computed(() =>
  new Date(`${props.month}-01T00:00:00Z`).toLocaleDateString(locale.value, { month: 'long', year: 'numeric', timeZone: 'UTC' }),
)
const isCurrentMonth = computed(() => props.month === today.slice(0, 7))
const viewingOther = computed(() => props.personId !== null && props.personId !== currentUser.value?.id)

const weekdays = computed(() => {
  const names = Array.from({ length: 7 }, (_, i) =>
    new Date(Date.UTC(2024, 0, 1 + i)).toLocaleDateString(locale.value, { weekday: 'short', timeZone: 'UTC' }).replace('.', ''),
  )
  return showWeekends.value ? names : names.slice(0, 5)
})

/** Calendar weeks as rows of 7 (or 5) cells; days outside the month are null. */
const weeks = computed(() => {
  if (!data.value) return []
  const byDate = new Map(data.value.days.map((d) => [d.date, d]))
  const first = data.value.days[0].date
  const last = data.value.days[data.value.days.length - 1].date
  const rows: { kw: number; days: { date: string; day: TimeDay | null }[] }[] = []
  for (let monday = mondayOf(first); monday <= last; monday = addDays(monday, 7)) {
    const days = Array.from({ length: 7 }, (_, i) => addDays(monday, i)).map((date) => ({ date, day: byDate.get(date) ?? null }))
    rows.push({ kw: isoWeek(monday), days: showWeekends.value ? days : days.slice(0, 5) })
  }
  return rows
})

function isoWeek(iso: string): number {
  const date = new Date(`${iso}T00:00:00Z`)
  date.setUTCDate(date.getUTCDate() + 3 - ((date.getUTCDay() + 6) % 7))
  const jan4 = new Date(Date.UTC(date.getUTCFullYear(), 0, 4))
  return 1 + Math.round(((date.getTime() - jan4.getTime()) / 86_400_000 - 3 + ((jan4.getUTCDay() + 6) % 7)) / 7)
}

function shiftMonth(delta: number) {
  const date = new Date(`${props.month}-01T00:00:00Z`)
  date.setUTCMonth(date.getUTCMonth() + delta)
  emit('update:month', date.toISOString().slice(0, 7))
}

/** What a day looks like: off, vacation, pending request, missing time or a hint. */
function kind(day: TimeDay): string {
  if (day.off?.startsWith('holiday:')) return 'holiday'
  if (day.off === 'vacation') return 'vacation'
  if (!day.target && !day.worked) return 'weekend'
  if (day.pending) return 'pending'
  return 'work'
}

function missing(day: TimeDay): boolean {
  return day.target > 0 && day.worked === 0 && day.date < today && !day.entries.length
}

function hints(day: TimeDay): string[] {
  const list = day.warnings.map((w) => t(`time.warnings.${w}`))
  if (missing(day)) list.push(t('time.month.missing'))
  return list
}

function dayAria(day: TimeDay): string {
  const parts = [formatDate(day.date)]
  if (day.off) parts.push(day.off.startsWith('holiday:') ? day.off.slice(8) : t('time.vacation'))
  if (day.pending) parts.push(t('time.month.pending', { type: t(`requestTypes.${day.pending}`) }))
  if (day.home_office) parts.push(t('time.month.homeOffice'))
  if (day.target || day.worked) parts.push(t('time.month.workedOf', { worked: hours(day.worked), target: hours(day.target) }))
  parts.push(...hints(day))
  return parts.join(', ')
}

async function load() {
  loading.value = data.value === null
  error.value = null
  try {
    data.value = await api.get<TimeMonth>(`/api/time/month${query({ month: props.month, person_id: props.personId ?? undefined })}`)
  } catch (e) {
    error.value = errorText(e)
  } finally {
    loading.value = false
  }
}

async function submit() {
  busy.value = true
  try {
    data.value = await api.post<TimeMonth>(`/api/time/months/${props.month}/submit`, {})
    showToast(t('time.month.submitted'))
  } catch (e) {
    showToast(errorText(e), 'error')
  } finally {
    busy.value = false
  }
}

async function decide(action: 'approve' | 'return') {
  if (!data.value) return
  if (action === 'return' && !returnComment.value.trim()) {
    returnError.value = t('time.month.commentRequired')
    return
  }
  busy.value = true
  try {
    data.value = await api.post<TimeMonth>(`/api/time/months/${props.month}/${action}`, {
      person_id: data.value.person.id,
      comment: action === 'return' ? returnComment.value.trim() : '',
    })
    returnOpen.value = false
    showToast(action === 'approve' ? t('time.month.approved') : t('time.month.returned'))
    refreshSummary(true)
  } catch (e) {
    if (action === 'return') returnError.value = errorText(e)
    else showToast(errorText(e), 'error')
  } finally {
    busy.value = false
  }
}

function openReturn() {
  returnComment.value = ''
  returnError.value = ''
  returnOpen.value = true
}

watch(() => [props.month, props.personId], load)
onMounted(load)
</script>

<template>
  <LoadState :loading="loading" :error="error" @retry="load">
    <div v-if="data" class="month stack">
      <div v-if="viewingOther" class="other-head">
        <UserAvatar :id="data.person.id" :name="data.person.full_name" :photo-version="data.person.photo_version" :size="36" />
        <strong>{{ data.person.full_name }}</strong>
        <button type="button" class="btn btn-ghost" @click="emit('back')">{{ t('time.backToTeam') }}</button>
      </div>

      <!-- Month bar -->
      <div class="month-bar">
        <div class="row">
          <button type="button" class="btn btn-secondary btn-icon" :aria-label="t('time.month.prev')" @click="shiftMonth(-1)"><AppIcon name="chevronLeft" /></button>
          <h2 class="month-title">{{ monthTitle }}</h2>
          <button type="button" class="btn btn-secondary btn-icon" :aria-label="t('time.month.next')" :disabled="isCurrentMonth" @click="shiftMonth(1)"><AppIcon name="chevronRight" /></button>
          <span class="status" :class="`st-${data.status}`">
            <AppIcon :name="data.status === 'approved' ? 'checkCircle' : data.status === 'returned' ? 'alert' : data.status === 'submitted' ? 'clock' : 'edit'" :size="16" />
            {{ t(`time.month.status.${data.status}`) }}
          </span>
        </div>
        <div class="row">
          <label class="checkbox small">
            <input v-model="showWeekends" type="checkbox" />
            <span>{{ t('time.month.showWeekends') }}</span>
          </label>
          <a class="btn btn-ghost" :href="`/api/time/export.csv${query({ month, person_id: personId ?? undefined })}`" download>
            <AppIcon name="download" :size="18" />{{ t('time.month.timesheet') }}
          </a>
          <button v-if="data.can_submit" type="button" class="btn btn-primary" :disabled="busy" @click="submit">
            <AppIcon name="check" :size="18" />{{ t('time.month.submit') }}
          </button>
          <template v-if="data.can_decide">
            <button type="button" class="btn btn-secondary" :disabled="busy" @click="openReturn">{{ t('time.month.sendBack') }}</button>
            <button type="button" class="btn btn-primary" :disabled="busy" @click="decide('approve')"><AppIcon name="check" :size="18" />{{ t('time.month.approve') }}</button>
          </template>
        </div>
      </div>

      <p v-if="data.status === 'returned' && data.comment" class="notice notice-warning small" role="status">
        <strong>{{ t('time.month.returnedBy', { name: data.decided_by ?? '' }) }}</strong> {{ data.comment }}
      </p>
      <p v-else-if="data.status === 'submitted'" class="notice notice-info small">
        {{ t('time.month.submittedHint', { date: formatDateTime(data.submitted_at) }) }}
      </p>
      <p v-else-if="data.status === 'approved'" class="notice notice-success small">
        {{ t('time.month.approvedHint', { name: data.decided_by ?? '', date: formatDateTime(data.decided_at) }) }}
      </p>

      <!-- Tiles -->
      <dl class="tiles">
        <div class="tile">
          <dt>{{ t('time.balance') }}</dt>
          <dd :class="data.balance_year >= 0 ? 'plus' : 'minus'">{{ balance(data.balance_year) }} h</dd>
        </div>
        <div class="tile">
          <dt>{{ t('time.month.target') }}</dt>
          <dd>{{ hours(data.target) }} h</dd>
        </div>
        <div class="tile">
          <dt>{{ t('time.month.worked') }}</dt>
          <dd>{{ hours(data.worked) }} h <span class="sub" :class="data.worked - data.target >= 0 ? 'plus' : 'minus'">{{ balance(data.worked - data.target) }}</span></dd>
        </div>
        <div class="tile">
          <dt>{{ t('time.month.vacationLeft') }}</dt>
          <dd>{{ data.vacation.remaining }} <span class="sub muted">{{ t('time.month.vacationOf', { n: data.vacation.entitlement, planned: data.vacation.planned }) }}</span></dd>
        </div>
      </dl>

      <!-- Calendar -->
      <section class="card card-flush cal-card">
        <table class="cal" :class="{ 'no-weekend': !showWeekends }">
          <caption class="visually-hidden">{{ monthTitle }}</caption>
          <thead>
            <tr>
              <th scope="col" class="kw-head">{{ t('time.month.kw') }}</th>
              <th v-for="name in weekdays" :key="name" scope="col">{{ name }}</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="row in weeks" :key="row.kw">
              <th scope="row" class="kw">{{ row.kw }}</th>
              <td v-for="cell in row.days" :key="cell.date" :class="cell.day ? [`k-${kind(cell.day)}`, { today: cell.date === today, done: data.status === 'approved' }] : 'outside'">
                <button
                  v-if="cell.day"
                  type="button"
                  class="cell"
                  :aria-label="dayAria(cell.day)"
                  @click="emit('openDay', cell.date)"
                >
                  <span class="c-top">
                    <span class="c-num">{{ Number(cell.date.slice(8)) }}</span>
                    <span v-if="hints(cell.day).length" class="c-hint" :title="hints(cell.day).join(' · ')">
                      <AppIcon name="info" :size="16" />
                    </span>
                  </span>
                  <span v-if="cell.day.off" class="c-label">{{ cell.day.off.startsWith('holiday:') ? cell.day.off.slice(8) : t('time.vacation') }}</span>
                  <span v-else-if="cell.day.pending" class="c-label">{{ t('time.month.pendingShort') }}</span>
                  <span v-else-if="cell.day.home_office" class="c-label">{{ t('time.month.homeOffice') }}</span>
                  <span v-if="cell.date > today && cell.day.target && !cell.day.worked" class="c-time c-future">{{ t('time.month.targetShort', { h: hours(cell.day.target) }) }}</span>
                  <span v-else-if="cell.day.target || cell.day.worked" class="c-time">
                    <span class="c-worked">{{ hours(cell.day.worked) }}</span>
                    <span class="c-target">/ {{ hours(cell.day.target) }}</span>
                  </span>
                  <span v-if="cell.day.target && cell.date <= today" class="c-bar" aria-hidden="true">
                    <span :style="{ width: `${Math.min(100, (cell.day.worked / cell.day.target) * 100)}%` }" />
                  </span>
                  <span v-if="hints(cell.day).length" class="c-hint-text">{{ hints(cell.day)[0] }}</span>
                </button>
                <span v-else class="c-num muted" aria-hidden="true">{{ Number(cell.date.slice(8)) }}</span>
              </td>
            </tr>
          </tbody>
        </table>
        <div class="legend small muted">
          <span><span class="lg lg-vacation" aria-hidden="true" />{{ t('time.vacation') }}</span>
          <span><span class="lg lg-pending" aria-hidden="true" />{{ t('time.month.pendingShort') }}</span>
          <span><span class="lg lg-off" aria-hidden="true" />{{ t('time.month.legendOff') }}</span>
          <span><AppIcon name="info" :size="14" class="lg-hint" />{{ t('time.month.legendHint') }}</span>
          <span>{{ t('time.month.clickHint') }}</span>
        </div>
      </section>
    </div>

    <BaseModal :open="returnOpen" :title="t('time.month.sendBackTitle')" :description="t('time.month.sendBackText')" :confirm-label="t('time.month.sendBack')" :busy="busy" @close="returnOpen = false" @confirm="decide('return')">
      <FormField id="tm-comment" :label="t('time.month.comment')" :error="returnError">
        <template #default="{ attrs }"><textarea v-bind="attrs" v-model="returnComment" class="textarea" rows="3" maxlength="300" /></template>
      </FormField>
    </BaseModal>
  </LoadState>
</template>

<style scoped>
.other-head {
  display: flex;
  align-items: center;
  gap: var(--space-3);
}

.month-bar {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-3);
}

.month-title {
  min-width: 10ch;
  font-size: var(--text-lg);
  text-align: center;
}

.status {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 4px 10px;
  border-radius: 99px;
  background: var(--color-neutral-soft);
  font-size: var(--text-sm);
  font-weight: 600;
}

.st-submitted {
  background: var(--color-primary-soft);
  color: var(--color-primary-text);
}

.st-approved {
  background: var(--color-success-soft);
  color: var(--color-success);
}

.st-returned {
  background: var(--color-warning-soft);
  color: var(--color-warning);
}

.tiles {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(160px, 1fr));
  gap: var(--space-3);
  margin: 0;
}

.tile {
  padding: var(--space-3) var(--space-4);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-lg);
  background: var(--color-surface);
}

.tile dt {
  font-size: var(--text-sm);
  color: var(--color-text-muted);
}

.tile dd {
  margin: 0;
  font-family: var(--font-heading);
  font-size: var(--text-xl);
  font-weight: 600;
  font-variant-numeric: tabular-nums;
}

.sub {
  font-family: var(--font-body);
  font-size: var(--text-sm);
  font-weight: 600;
}

.plus {
  color: var(--color-success);
}

.minus {
  color: var(--color-warning);
}

.cal-card {
  overflow-x: auto;
}

.cal {
  width: 100%;
  min-width: 640px;
  border-collapse: separate;
  border-spacing: 4px;
  table-layout: fixed;
}

.cal.no-weekend {
  min-width: 480px;
}

.cal thead th {
  padding: var(--space-2) 0 0;
  font-size: var(--text-sm);
  font-weight: 600;
  color: var(--color-text-muted);
  text-transform: uppercase;
  letter-spacing: 0.03em;
}

.kw-head,
.kw {
  width: 44px;
}

.kw {
  border-radius: var(--radius-md);
  background: var(--color-neutral-soft);
  color: var(--color-text-muted);
  font-size: var(--text-sm);
  font-weight: 700;
  text-align: center;
}

.cal td {
  height: 96px;
  padding: 0;
  vertical-align: top;
  border-radius: var(--radius-md);
  background: var(--color-surface-muted);
  border: 1px solid var(--color-border);
}

.cal td.outside {
  background: transparent;
  border-style: dashed;
  padding: var(--space-2);
}

.cal td.k-weekend,
.cal td.k-holiday {
  background: var(--color-neutral-soft);
}

.cal td.k-vacation {
  background: var(--color-primary-soft);
  border-color: color-mix(in srgb, var(--color-primary) 30%, var(--color-border));
}

.cal td.k-pending {
  border: 1px dashed var(--color-primary);
}

.cal td.done {
  box-shadow: inset 0 3px 0 var(--color-success);
}

.cal td.today {
  outline: 2px solid var(--color-primary);
  outline-offset: 1px;
}

.cell {
  display: flex;
  flex-direction: column;
  gap: 4px;
  width: 100%;
  height: 100%;
  padding: var(--space-2);
  border: 0;
  border-radius: inherit;
  background: transparent;
  color: var(--color-text);
  font: inherit;
  text-align: left;
  cursor: pointer;
  transition: background-color 150ms ease-out;
}

.cell:hover {
  background: color-mix(in srgb, var(--color-primary) 6%, transparent);
}

.cell:focus-visible {
  outline: 3px solid var(--color-focus);
  outline-offset: 1px;
}

.c-top {
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.c-num {
  font-weight: 700;
  font-variant-numeric: tabular-nums;
  color: var(--color-text-muted);
}

.today .c-num {
  color: var(--color-primary-text);
}

.c-hint {
  display: inline-flex;
  color: var(--color-warning);
}

.c-label {
  font-size: 0.78rem;
  font-weight: 600;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.c-time {
  margin-top: auto;
  font-variant-numeric: tabular-nums;
}

.c-future {
  font-size: 0.78rem;
  color: var(--color-text-subtle);
}

.c-worked {
  font-weight: 700;
}

.c-target {
  font-size: 0.78rem;
  color: var(--color-text-muted);
}

.c-bar {
  position: relative;
  height: 4px;
  border-radius: 2px;
  background: var(--color-border);
  overflow: hidden;
}

.c-bar > span {
  position: absolute;
  inset: 0 auto 0 0;
  border-radius: inherit;
  background: var(--color-success);
}

.c-hint-text {
  font-size: 0.72rem;
  color: var(--color-warning);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
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

.lg-vacation {
  background: var(--color-primary-soft);
}

.lg-pending {
  border: 1px dashed var(--color-primary);
}

.lg-off {
  background: var(--color-neutral-soft);
}

.lg-hint {
  color: var(--color-warning);
}

@media (max-width: 720px) {
  .cal,
  .cal.no-weekend {
    min-width: 0;
    border-spacing: 2px;
  }

  .kw-head,
  .kw {
    width: 26px;
    font-size: 0.7rem;
  }

  .cal thead th {
    font-size: 0.7rem;
    letter-spacing: 0;
  }

  .cal td {
    height: 64px;
  }

  .cell {
    padding: 4px;
    gap: 2px;
  }

  .c-num,
  .c-time {
    font-size: 0.75rem;
  }

  .c-hint {
    display: none;
  }

  .c-target,
  .c-label,
  .c-hint-text {
    display: none;
  }
}

@media (prefers-reduced-motion: reduce) {
  .cell {
    transition: none;
  }
}

@media print {
  .month-bar .row:last-child,
  .legend {
    display: none;
  }
}
</style>
