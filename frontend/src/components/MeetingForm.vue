<script setup lang="ts">
/** Plan a meeting or change one: title, time, who is invited, optional space and guests from outside. */
import { computed, reactive, ref, watch } from 'vue'
import AppIcon from './AppIcon.vue'
import BaseModal from './BaseModal.vue'
import FormField from './FormField.vue'
import UserAvatar from './UserAvatar.vue'
import { ApiError, api } from '@/lib/api'
import { errorText, t } from '@/lib/i18n'
import { currentUser } from '@/lib/session'
import type { DirectoryEntry, MeetingDetail, Space } from '@/lib/types'

const props = defineProps<{ open: boolean; meeting?: MeetingDetail | null; spaceId?: number | null }>()
const emit = defineEmits<{ close: []; saved: [meeting: MeetingDetail] }>()

const people = ref<DirectoryEntry[]>([])
const spaces = ref<Space[]>([])
const search = ref('')
const busy = ref(false)
const form = reactive({ title: '', description: '', day: '', from: '', to: '', invitees: [] as number[], space_id: null as number | null, allow_guests: false })
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
    Object.assign(form, { title: m.title, description: m.description, day: s.day, from: s.time, to: localParts(new Date(m.ends_at)).time, invitees: m.invitees.map((i) => i.person.id), space_id: m.space_id, allow_guests: !!m.guest_link })
  } else {
    // Next full half hour, for one hour
    const start = new Date()
    start.setMinutes(start.getMinutes() < 30 ? 30 : 60, 0, 0)
    const s = localParts(start)
    Object.assign(form, { title: '', description: '', day: s.day, from: s.time, to: localParts(new Date(start.getTime() + 3600_000)).time, invitees: [], space_id: props.spaceId ?? null, allow_guests: false })
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
    const body = { title: form.title.trim(), description: form.description.trim(), starts_at: start.toISOString(), ends_at: end.toISOString(), invitee_ids: form.invitees, space_id: form.space_id, allow_guests: form.allow_guests }
    const saved = editing.value ? await api.put<MeetingDetail>(`/api/meetings/${props.meeting!.id}`, body) : await api.post<MeetingDetail>('/api/meetings', body)
    emit('saved', saved)
  } catch (e) {
    const field = e instanceof ApiError ? e.field : undefined
    errors[field && ['title', 'starts_at', 'ends_at'].includes(field) ? field : 'form'] = errorText(e)
  } finally {
    busy.value = false
  }
}

watch(() => props.open, (open) => {
  if (!open) return
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
