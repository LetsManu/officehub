<script setup lang="ts">
/**
 * Plan a meeting or change one: title, time (also as a series), who is invited – with their free and busy
 * times like the scheduling assistant in Outlook – optional space and guests from outside.
 */
import { computed, reactive, ref, watch } from 'vue'
import AppIcon from './AppIcon.vue'
import BaseModal from './BaseModal.vue'
import FormField from './FormField.vue'
import UserAvatar from './UserAvatar.vue'
import { ApiError, api } from '@/lib/api'
import { errorText, t } from '@/lib/i18n'
import { currentUser } from '@/lib/session'
import { showToast } from '@/lib/toast'
import type { DirectoryEntry, MeetingDetail, Recurrence, Space } from '@/lib/types'

const props = defineProps<{ open: boolean; meeting?: MeetingDetail | null; spaceId?: number | null; start?: Date | null; end?: Date | null }>()
const emit = defineEmits<{ close: []; saved: [meeting: MeetingDetail] }>()

const people = ref<DirectoryEntry[]>([])
const spaces = ref<Space[]>([])
const search = ref('')
const busy = ref(false)
const form = reactive({ title: '', description: '', day: '', from: '', to: '', invitees: [] as number[], space_id: null as number | null, allow_guests: false, recurrence: '' as Recurrence, until: '' })
const RECURRENCES: Recurrence[] = ['', 'daily', 'weekdays', 'weekly', 'biweekly', 'monthly']
const errors = reactive<Record<string, string>>({})

const editing = computed(() => !!props.meeting)
const chosen = computed(() => form.invitees.map((id) => people.value.find((p) => p.id === id)).filter((p): p is DirectoryEntry => !!p))
const matches = computed(() => {
  const term = search.value.trim().toLowerCase()
  if (!term) return []
  return people.value
    .filter((p) => p.id !== currentUser.value?.id && !form.invitees.includes(p.id) && `${p.full_name} ${p.department}`.toLowerCase().includes(term))
    .slice(0, 6)
})

function pad(n: number) {
  return String(n).padStart(2, '0')
}

function localParts(date: Date) {
  return { day: `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}`, time: `${pad(date.getHours())}:${pad(date.getMinutes())}` }
}

function reset() {
  for (const key of Object.keys(errors)) delete errors[key]
  search.value = ''
  const m = props.meeting
  if (m?.starts_at && m.ends_at) {
    const s = localParts(new Date(m.starts_at))
    Object.assign(form, { title: m.title, description: m.description, day: s.day, from: s.time, to: localParts(new Date(m.ends_at)).time, invitees: m.invitees.map((i) => i.person.id), space_id: m.space_id, allow_guests: !!m.guest_link, recurrence: m.recurrence ?? '', until: m.recurrence_until ?? '' })
  } else {
    // The time chosen in the calendar, otherwise the next full half hour, for one hour
    const start = props.start ? new Date(props.start) : new Date()
    if (!props.start) start.setMinutes(start.getMinutes() < 30 ? 30 : 60, 0, 0)
    const end = props.end ?? new Date(start.getTime() + 3600_000)
    const s = localParts(start)
    Object.assign(form, { title: '', description: '', day: s.day, from: s.time, to: localParts(end).time, invitees: [], space_id: props.spaceId ?? null, allow_guests: false, recurrence: '', until: '' })
  }
}

async function loadLists() {
  if (people.value.length) return
  ;[people.value, spaces.value] = await Promise.all([
    api.get<DirectoryEntry[]>('/api/directory').catch(() => []),
    api.get<Space[]>('/api/spaces').catch(() => []),
  ])
}

function add(p: DirectoryEntry) {
  form.invitees.push(p.id)
  search.value = ''
}

/** Everyone in the chosen space at once. */
async function inviteSpace() {
  if (!form.space_id) return
  const space = await api.get<{ members: { person: { id: number } }[] }>(`/api/spaces/${form.space_id}`)
  for (const m of space.members) if (m.person.id !== currentUser.value?.id && !form.invitees.includes(m.person.id)) form.invitees.push(m.person.id)
}

async function save() {
  for (const key of Object.keys(errors)) delete errors[key]
  if (!form.title.trim()) errors.title = t('validation.title_required')
  if (!form.day || !form.from) errors.starts_at = t('validation.start_required')
  if (!form.to) errors.ends_at = t('validation.end_required')
  if (Object.keys(errors).length) return
  const start = new Date(`${form.day}T${form.from}`)
  const end = new Date(`${form.day}T${form.to}`)
  if (end <= start) end.setDate(end.getDate() + 1) // goes past midnight
  busy.value = true
  try {
    const body = { title: form.title.trim(), description: form.description.trim(), starts_at: start.toISOString(), ends_at: end.toISOString(), invitee_ids: form.invitees, space_id: form.space_id, allow_guests: form.allow_guests, recurrence: form.recurrence, recurrence_until: form.recurrence && form.until ? form.until : null }
    const saved = editing.value ? await api.put<MeetingDetail>(`/api/meetings/${props.meeting!.id}`, body) : await api.post<MeetingDetail>('/api/meetings', body)
    emit('saved', saved)
  } catch (e) {
    const field = e instanceof ApiError ? e.field : undefined
    errors[field && ['title', 'starts_at', 'ends_at', 'recurrence_until'].includes(field) ? field : 'form'] = errorText(e)
  } finally {
    busy.value = false
  }
}

// ---------- free and busy times of everyone invited (like the scheduling assistant in Outlook) ----------

interface Busy {
  start: string
  end: string
  kind: string
}

const DAY_FROM = 7
const DAY_TO = 19
const busyTimes = ref<Record<string, Busy[]>>({})
const busyFor = ref('')
let busyTimer: number | undefined

const rows = computed(() => {
  const me = currentUser.value
  const list = [...(me ? [{ id: me.id, full_name: me.full_name, photo_version: me.photo_version ?? null }] : []), ...chosen.value]
  return list.map((p) => ({ person: p, blocks: blocksOn(busyTimes.value[String(p.id)] ?? [], form.day) }))
})

function minutesOf(d: Date) {
  return d.getHours() * 60 + d.getMinutes()
}

/** Busy blocks on one day as percentages of the shown hours. */
function blocksOn(list: Busy[], day: string) {
  if (!day) return []
  const from = new Date(`${day}T00:00`)
  const to = new Date(from.getTime() + 86_400_000)
  const span = (DAY_TO - DAY_FROM) * 60
  return list
    .map((b) => ({ s: new Date(b.start), e: new Date(b.end), kind: b.kind }))
    .filter((b) => b.s < to && b.e > from)
    .map((b) => {
      const s = Math.max(DAY_FROM * 60, b.s < from ? 0 : minutesOf(b.s))
      const e = Math.min(DAY_TO * 60, b.e >= to ? 24 * 60 : minutesOf(b.e))
      return { left: ((s - DAY_FROM * 60) / span) * 100, width: (Math.max(0, e - s) / span) * 100, kind: b.kind }
    })
    .filter((b) => b.width > 0)
}

const slot = computed(() => {
  if (!form.from || !form.to) return null
  const [fh, fm] = form.from.split(':').map(Number)
  const [th, tm] = form.to.split(':').map(Number)
  const span = (DAY_TO - DAY_FROM) * 60
  const s = Math.max(0, fh * 60 + fm - DAY_FROM * 60)
  const e = Math.min(span, th * 60 + tm - DAY_FROM * 60)
  return e > s ? { left: (s / span) * 100, width: ((e - s) / span) * 100 } : null
})

const conflict = computed(() => !!slot.value && rows.value.some((r) => r.blocks.some((b) => b.left < slot.value!.left + slot.value!.width && b.left + b.width > slot.value!.left)))

async function loadBusy() {
  const me = currentUser.value?.id
  if (!form.day || !me) return
  const ids = [me, ...form.invitees]
  const key = `${ids.join(',')}@${form.day}`
  if (key === busyFor.value) return
  const end = new Date(`${form.day}T00:00`)
  end.setDate(end.getDate() + 14)
  const endIso = `${end.getFullYear()}-${String(end.getMonth() + 1).padStart(2, '0')}-${String(end.getDate()).padStart(2, '0')}`
  try {
    busyTimes.value = await api.get<Record<string, Busy[]>>(`/api/calendar/busy?ids=${ids.join(',')}&start=${form.day}&end=${endIso}`)
    busyFor.value = key
  } catch {
    /* planning works without it */
  }
}

/** The next time (from the chosen start, working days 8–18) when everyone is free for the same length. */
function findNext() {
  const [fh, fm] = form.from.split(':').map(Number)
  const [th, tm] = form.to.split(':').map(Number)
  const length = Math.max(15, th * 60 + tm - (fh * 60 + fm))
  const all = Object.values(busyTimes.value).flat().map((b) => [new Date(b.start).getTime(), new Date(b.end).getTime()])
  const start = new Date(`${form.day}T${form.from}`)
  start.setMinutes(start.getMinutes() + 30 - (start.getMinutes() % 30))
  for (let tries = 0; tries < 14 * 48; tries++, start.setMinutes(start.getMinutes() + 30)) {
    const day = start.getDay()
    const minute = start.getHours() * 60 + start.getMinutes()
    if (day === 0 || day === 6 || minute < 8 * 60 || minute + length > 18 * 60) continue
    const s = start.getTime()
    const e = s + length * 60_000
    if (all.some(([bs, be]) => bs < e && be > s)) continue
    const pad = (n: number) => String(n).padStart(2, '0')
    form.day = `${start.getFullYear()}-${pad(start.getMonth() + 1)}-${pad(start.getDate())}`
    form.from = `${pad(start.getHours())}:${pad(start.getMinutes())}`
    const end = new Date(e)
    form.to = `${pad(end.getHours())}:${pad(end.getMinutes())}`
    return
  }
  showToast(t('meetings.noFreeTime'), 'info')
}

watch(() => [props.open, form.day, form.invitees.length] as const, ([open]) => {
  if (!open) return
  window.clearTimeout(busyTimer)
  busyTimer = window.setTimeout(loadBusy, 250)
})

const hourMarks = Array.from({ length: DAY_TO - DAY_FROM + 1 }, (_, i) => DAY_FROM + i)

watch(() => props.open, (open) => {
  if (!open) return
  busyFor.value = ''
  reset()
  loadLists()
}, { immediate: true })
</script>

<template>
  <BaseModal :open="open" wide :title="editing ? t('meetings.edit') : t('meetings.new')" :description="editing ? '' : t('meetings.newHint')" :confirm-label="editing ? t('app.save') : t('meetings.send')" :busy="busy" @close="emit('close')" @confirm="save">
    <form class="stack" novalidate @submit.prevent="save">
      <div v-if="errors.form" class="notice notice-danger small" role="alert">{{ errors.form }}</div>
      <FormField id="mf-title" :label="t('meetings.fields.title')" :error="errors.title">
        <template #default="{ attrs }"><input v-bind="attrs" v-model="form.title" class="input" maxlength="160" :placeholder="t('meetings.fields.titlePlaceholder')" /></template>
      </FormField>
      <div class="times">
        <FormField id="mf-day" :label="t('meetings.fields.day')" :error="errors.starts_at">
          <template #default="{ attrs }"><input v-bind="attrs" v-model="form.day" class="input" type="date" /></template>
        </FormField>
        <FormField id="mf-from" :label="t('meetings.fields.from')">
          <template #default="{ attrs }"><input v-bind="attrs" v-model="form.from" class="input" type="time" step="300" /></template>
        </FormField>
        <FormField id="mf-to" :label="t('meetings.fields.to')" :error="errors.ends_at">
          <template #default="{ attrs }"><input v-bind="attrs" v-model="form.to" class="input" type="time" step="300" /></template>
        </FormField>
      </div>

      <div class="field">
        <label for="mf-people" class="label">{{ t('meetings.fields.invitees') }}</label>
        <ul v-if="chosen.length" class="chips">
          <li v-for="p in chosen" :key="p.id" class="chip">
            <UserAvatar :id="p.id" :name="p.full_name" :photo-version="p.photo_version" :size="22" />{{ p.full_name }}
            <button type="button" class="chip-x" :aria-label="t('meetings.removeInvitee', { name: p.full_name })" @click="form.invitees = form.invitees.filter((x) => x !== p.id)"><AppIcon name="close" :size="14" /></button>
          </li>
        </ul>
        <div class="picker">
          <input id="mf-people" v-model="search" class="input" type="search" autocomplete="off" :placeholder="t('meetings.fields.searchPeople')" @keydown.enter.prevent="matches[0] && add(matches[0])" />
          <ul v-if="matches.length" class="matches" role="listbox" :aria-label="t('meetings.fields.invitees')">
            <li v-for="p in matches" :key="p.id" role="option" :aria-selected="false">
              <button type="button" @click="add(p)"><UserAvatar :id="p.id" :name="p.full_name" :photo-version="p.photo_version" :size="24" />{{ p.full_name }}<span class="muted small">{{ p.department }}</span></button>
            </li>
          </ul>
        </div>
      </div>

      <div class="times series">
        <FormField id="mf-repeat" :label="t('meetings.fields.repeat')">
          <template #default="{ attrs }">
            <select v-bind="attrs" v-model="form.recurrence" class="select">
              <option v-for="r in RECURRENCES" :key="r" :value="r">{{ t(`meetings.repeat.${r || 'none'}`) }}</option>
            </select>
          </template>
        </FormField>
        <FormField v-if="form.recurrence" id="mf-until" :label="t('meetings.fields.until')" :error="errors.recurrence_until" optional>
          <template #default="{ attrs }"><input v-bind="attrs" v-model="form.until" class="input" type="date" :min="form.day" /></template>
        </FormField>
      </div>

      <section v-if="form.day" class="assistant" :aria-label="t('meetings.availability')">
        <div class="assistant-head">
          <p class="label">{{ t('meetings.availability') }}</p>
          <button type="button" class="btn btn-ghost" @click="findNext"><AppIcon name="search" :size="16" />{{ t('meetings.findTime') }}</button>
        </div>
        <div class="scale" aria-hidden="true">
          <span class="who-col" />
          <span class="track"><span v-for="h in hourMarks" :key="h" class="mark" :style="{ left: `${((h - DAY_FROM) / (DAY_TO - DAY_FROM)) * 100}%` }">{{ h }}</span></span>
        </div>
        <ul class="people-rows">
          <li v-for="r in rows" :key="r.person.id" class="prow">
            <span class="who-col"><UserAvatar :id="r.person.id" :name="r.person.full_name" :photo-version="r.person.photo_version" :size="22" status /><span class="pname">{{ r.person.full_name }}</span></span>
            <span class="track">
              <span v-if="slot" class="chosen" :class="{ clash: conflict }" :style="{ left: `${slot.left}%`, width: `${slot.width}%` }" />
              <span v-for="(b, i) in r.blocks" :key="i" class="busy-block" :class="`b-${b.kind}`" :style="{ left: `${b.left}%`, width: `${b.width}%` }" />
              <span class="visually-hidden">{{ r.blocks.length ? t('meetings.busyCount', { n: r.blocks.length }) : t('meetings.allFree') }}</span>
            </span>
          </li>
        </ul>
        <p class="small" :class="conflict ? 'warn' : 'muted'" role="status">{{ conflict ? t('meetings.clash') : t('meetings.everyoneFree') }}</p>
      </section>

      <div v-if="spaces.length && !editing" class="space-row">
        <FormField id="mf-space" :label="t('meetings.fields.space')" :hint="t('meetings.fields.spaceHint')" optional>
          <template #default="{ attrs }">
            <select v-bind="attrs" v-model="form.space_id" class="select">
              <option :value="null">{{ t('meetings.fields.noSpace') }}</option>
              <option v-for="s in spaces" :key="s.id" :value="s.id">{{ s.name }}</option>
            </select>
          </template>
        </FormField>
        <button v-if="form.space_id" type="button" class="btn btn-ghost" @click="inviteSpace"><AppIcon name="users" :size="18" />{{ t('meetings.inviteSpace') }}</button>
      </div>

      <FormField id="mf-desc" :label="t('meetings.fields.agenda')" optional>
        <template #default="{ attrs }"><textarea v-bind="attrs" v-model="form.description" class="textarea" rows="3" maxlength="4000" :placeholder="t('meetings.fields.agendaPlaceholder')" /></template>
      </FormField>

      <label class="checkbox">
        <input v-model="form.allow_guests" type="checkbox" />
        <span>{{ t('meetings.fields.guests') }}<span class="muted small block">{{ t('meetings.fields.guestsHint') }}</span></span>
      </label>
    </form>
  </BaseModal>
</template>

<style scoped>
.times {
  display: grid;
  grid-template-columns: 1.4fr 1fr 1fr;
  gap: var(--space-3);
}

@media (max-width: 560px) {
  .times {
    grid-template-columns: 1fr 1fr;
  }

  .times > :first-child {
    grid-column: 1 / -1;
  }
}

.chips {
  display: flex;
  flex-wrap: wrap;
  gap: var(--space-2);
  margin: 0 0 var(--space-2);
  padding: 0;
  list-style: none;
}

.chip {
  display: inline-flex;
  align-items: center;
  gap: var(--space-2);
  padding: 3px 4px 3px 4px;
  border-radius: 99px;
  background: var(--color-neutral-soft);
  font-size: 0.88rem;
}

.chip-x {
  display: grid;
  width: 24px;
  height: 24px;
  place-items: center;
  border: 0;
  border-radius: 50%;
  background: transparent;
  color: var(--color-text-muted);
  cursor: pointer;
}

.chip-x:hover {
  background: var(--color-surface);
  color: var(--color-text);
}

.picker {
  position: relative;
}

.matches {
  position: absolute;
  z-index: 5;
  right: 0;
  left: 0;
  margin: 4px 0 0;
  padding: var(--space-1);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-md, 10px);
  background: var(--color-surface-raised);
  box-shadow: var(--shadow-lg, 0 10px 30px rgb(0 0 0 / 15%));
  list-style: none;
}

.matches button {
  display: flex;
  width: 100%;
  align-items: center;
  gap: var(--space-2);
  padding: var(--space-2);
  border: 0;
  border-radius: 8px;
  background: transparent;
  color: inherit;
  text-align: left;
  cursor: pointer;
}

.matches button:hover,
.matches button:focus-visible {
  background: var(--color-primary-soft);
}

.matches .muted {
  margin-left: auto;
}

.series {
  grid-template-columns: 1fr 1fr;
}

.assistant {
  display: grid;
  gap: 6px;
  padding: var(--space-3);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-md);
  background: var(--color-surface-muted);
}

.assistant-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-2);
}

.assistant-head .label {
  margin: 0;
  font-weight: 600;
}

.scale,
.prow {
  display: grid;
  grid-template-columns: 150px 1fr;
  align-items: center;
  gap: var(--space-2);
}

.people-rows {
  display: grid;
  gap: 4px;
  margin: 0;
  padding: 0;
  list-style: none;
}

.who-col {
  display: flex;
  align-items: center;
  gap: 6px;
  min-width: 0;
  font-size: var(--text-sm);
}

.pname {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.track {
  position: relative;
  height: 22px;
  border-radius: 4px;
  background: repeating-linear-gradient(to right, var(--color-surface) 0 calc(100% / 12 - 1px), var(--color-border) calc(100% / 12 - 1px) calc(100% / 12));
}

.scale .track {
  height: 16px;
  background: none;
}

.mark {
  position: absolute;
  transform: translateX(-50%);
  color: var(--color-text-subtle);
  font-size: 0.68rem;
}

.busy-block {
  position: absolute;
  top: 3px;
  bottom: 3px;
  border-radius: 3px;
  background: #64748b;
}

.b-away {
  background: #9333ea;
}

.b-booking {
  background: #0f766e;
}

.chosen {
  position: absolute;
  top: 0;
  bottom: 0;
  border: 2px solid var(--color-primary);
  border-radius: 4px;
  background: color-mix(in srgb, var(--color-primary) 14%, transparent);
}

.chosen.clash {
  border-color: var(--color-danger);
  background: color-mix(in srgb, var(--color-danger) 14%, transparent);
}

.warn {
  margin: 0;
  color: var(--color-danger);
  font-weight: 600;
}

.assistant .muted {
  margin: 0;
}

@media (max-width: 560px) {
  .scale,
  .prow {
    grid-template-columns: 90px 1fr;
  }
}

.space-row {
  display: flex;
  flex-wrap: wrap;
  align-items: flex-end;
  gap: var(--space-3);
}

.space-row > :first-child {
  flex: 1;
  min-width: 220px;
}

.block {
  display: block;
}
</style>
