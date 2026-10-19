<script setup lang="ts">
import { computed, onMounted, reactive, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import AppIcon from '@/components/AppIcon.vue'
import BaseModal from '@/components/BaseModal.vue'
import EmptyState from '@/components/EmptyState.vue'
import FormField from '@/components/FormField.vue'
import LoadState from '@/components/LoadState.vue'
import PageHeader from '@/components/PageHeader.vue'
import SortHeader from '@/components/SortHeader.vue'
import UserAvatar from '@/components/UserAvatar.vue'
import { api } from '@/lib/api'
import { errorText, formatDate, t } from '@/lib/i18n'
import { isAdmin } from '@/lib/session'
import { useSort } from '@/lib/sort'
import { refreshSummary } from '@/lib/summary'
import { showToast } from '@/lib/toast'
import type { Training, TrainingStatus } from '@/lib/types'
import { todayIso } from '@/lib/workdays'

const route = useRoute()
const router = useRouter()
const tab = ref<'mine' | 'manage'>(route.query.tab === 'manage' && isAdmin.value ? 'manage' : 'mine')

const mine = ref<TrainingStatus[]>([])
const trainings = ref<Training[]>([])
const selected = ref<Training | null>(null)
const people = ref<TrainingStatus[]>([])
const departments = ref<string[]>([])
const loading = ref(true)
const error = ref<string | null>(null)
const busy = ref(false)

const STATUS_ORDER = { overdue: 0, due_soon: 1, open: 2, expiring: 3, valid: 4 }
const peopleSort = useSort(people, {
  name: (s) => s.person.full_name,
  status: (s) => STATUS_ORDER[s.status],
  due: (s) => s.due_on ?? '',
}, 'status')
const doneCount = computed(() => people.value.filter((p) => p.status === 'valid' || p.status === 'expiring').length)

// Complete (self) or record (HR)
const recordFor = ref<TrainingStatus | null>(null)
const recordForm = reactive({ completed_on: todayIso(), file: null as File | null })
const recordError = ref('')

// Create / edit training
const editorOpen = ref(false)
const editing = ref<Training | null>(null)
const form = reactive({ title: '', description: '', interval_months: '' as number | '', due_within_days: 30, department: '', link: '', active: true })
const formError = ref('')

async function loadMine() {
  mine.value = await api.get<TrainingStatus[]>('/api/trainings/mine')
}

async function loadManage() {
  trainings.value = await api.get<Training[]>('/api/trainings')
  if (selected.value) selected.value = trainings.value.find((t) => t.id === selected.value?.id) ?? null
  if (!selected.value && trainings.value.length) selected.value = trainings.value[0]
  people.value = selected.value ? await api.get<TrainingStatus[]>(`/api/trainings/${selected.value.id}/people`) : []
}

async function load() {
  loading.value = true
  error.value = null
  try {
    if (tab.value === 'manage') await loadManage()
    else await loadMine()
  } catch (e) {
    error.value = errorText(e)
  } finally {
    loading.value = false
  }
}

async function selectTraining(training: Training) {
  selected.value = training
  people.value = await api.get<TrainingStatus[]>(`/api/trainings/${training.id}/people`)
}

function openRecord(status: TrainingStatus) {
  recordFor.value = status
  recordForm.completed_on = todayIso()
  recordForm.file = null
  recordError.value = ''
}

async function saveRecord() {
  const status = recordFor.value
  if (!status) return
  recordError.value = recordForm.completed_on ? '' : t('validation.date_required')
  if (recordError.value) return
  busy.value = true
  try {
    const data = new FormData()
    data.append('completed_on', recordForm.completed_on)
    if (recordForm.file) data.append('file', recordForm.file)
    if (tab.value === 'manage') {
      await api.post(`/api/trainings/${status.training.id}/people/${status.person.id}`, data)
      if (selected.value) await selectTraining(selected.value)
    } else {
      await api.post(`/api/trainings/${status.training.id}/complete`, data)
      await loadMine()
      refreshSummary(true)
    }
    recordFor.value = null
    showToast(t('trainings.recorded'))
  } catch (e) {
    recordError.value = errorText(e)
  } finally {
    busy.value = false
  }
}

function openEditor(training: Training | null) {
  editing.value = training
  Object.assign(form, training
    ? { ...training, interval_months: training.interval_months ?? '' }
    : { title: '', description: '', interval_months: 12, due_within_days: 30, department: '', link: '', active: true })
  formError.value = ''
  editorOpen.value = true
}

async function saveTraining() {
  formError.value = form.title.trim() ? '' : t('validation.title_required')
  if (formError.value) return
  busy.value = true
  try {
    const body = { ...form, title: form.title.trim(), interval_months: form.interval_months === '' ? null : Number(form.interval_months), link: form.link.trim() }
    const saved = editing.value
      ? await api.put<Training>(`/api/trainings/${editing.value.id}`, body)
      : await api.post<Training>('/api/trainings', body)
    editorOpen.value = false
    selected.value = saved
    showToast(t('trainings.saved'))
    await loadManage()
  } catch (e) {
    formError.value = errorText(e)
  } finally {
    busy.value = false
  }
}

async function remind() {
  if (!selected.value) return
  try {
    const result = await api.post<{ reminded: number }>(`/api/trainings/${selected.value.id}/remind`)
    showToast(t('manageNews.remindedToast', { count: result.reminded }))
  } catch (e) {
    showToast(errorText(e), 'error')
  }
}

function dueText(s: TrainingStatus): string {
  if (s.status === 'valid' || s.status === 'expiring') return s.valid_until ? t('trainings.validUntil', { date: formatDate(s.valid_until) }) : t('trainings.doneOnce')
  return s.due_on ? t('trainings.dueOn', { date: formatDate(s.due_on) }) : ''
}

watch(tab, (value) => {
  router.replace({ query: value === 'manage' ? { tab: 'manage' } : {} })
  load()
})

onMounted(async () => {
  load()
  if (isAdmin.value) departments.value = await api.get<string[]>('/api/directory/departments').catch(() => [])
})
</script>

<template>
  <div class="page">
    <PageHeader :title="t('trainings.title')" :subtitle="t('trainings.subtitle')">
      <template v-if="isAdmin && tab === 'manage'" #actions>
        <button type="button" class="btn btn-primary" @click="openEditor(null)"><AppIcon name="plus" />{{ t('trainings.new') }}</button>
      </template>
    </PageHeader>

    <div v-if="isAdmin" class="segmented" role="group" :aria-label="t('trainings.title')">
      <button type="button" :aria-pressed="tab === 'mine'" @click="tab = 'mine'">{{ t('trainings.tabMine') }}</button>
      <button type="button" :aria-pressed="tab === 'manage'" @click="tab = 'manage'">{{ t('trainings.tabManage') }}</button>
    </div>

    <LoadState :loading="loading" :error="error" @retry="load">
      <!-- Mine -->
      <template v-if="tab === 'mine'">
        <ul v-if="mine.length" class="cards">
          <li v-for="s in mine" :key="s.training.id" class="card training" :class="`st-${s.status}`">
            <div class="training-head">
              <span class="t-icon"><AppIcon name="graduation" :size="20" /></span>
              <div class="grow">
                <h2>{{ s.training.title }}</h2>
                <p class="muted small">
                  {{ s.training.interval_months ? t('trainings.every', { count: s.training.interval_months }) : t('trainings.once') }}
                </p>
              </div>
              <span class="badge" :class="`b-${s.status}`">{{ t(`trainings.status.${s.status}`) }}</span>
            </div>
            <p v-if="s.training.description" class="prewrap small">{{ s.training.description }}</p>
            <div class="row foot">
              <span class="small due">{{ dueText(s) }}</span>
              <span class="row">
                <a v-if="s.training.link" :href="s.training.link" target="_blank" rel="noopener noreferrer" class="btn btn-ghost">
                  {{ t('trainings.open') }}<AppIcon name="external" :size="16" :label="t('nav.opensNewTab')" />
                </a>
                <a v-if="s.has_certificate && s.record_id" :href="`/api/trainings/records/${s.record_id}/certificate`" class="btn btn-ghost">
                  <AppIcon name="download" :size="16" />{{ t('trainings.certificate') }}
                </a>
                <button v-if="s.status !== 'valid'" type="button" class="btn btn-primary" @click="openRecord(s)">{{ t('trainings.markDone') }}</button>
              </span>
            </div>
          </li>
        </ul>
        <section v-else class="card"><EmptyState icon="graduation" :message="t('trainings.emptyMine')" /></section>
      </template>

      <!-- Manage -->
      <div v-else class="manage">
        <aside class="card card-flush training-list" :aria-label="t('trainings.title')">
          <ul v-if="trainings.length" class="list">
            <li v-for="tr in trainings" :key="tr.id">
              <button type="button" class="pick" :class="{ active: selected?.id === tr.id }" :aria-current="selected?.id === tr.id ? 'true' : undefined" @click="selectTraining(tr)">
                <span class="pick-title">{{ tr.title }}</span>
                <span class="muted small">{{ tr.department || t('trainings.everyone') }}<template v-if="!tr.active"> · {{ t('trainings.inactive') }}</template></span>
              </button>
            </li>
          </ul>
          <EmptyState v-else icon="graduation" :message="t('trainings.emptyManage')" :action-label="t('trainings.new')" @action="openEditor(null)" />
        </aside>

        <section v-if="selected" class="card card-flush" :aria-label="selected.title">
          <div class="detail-head">
            <div>
              <h2>{{ selected.title }}</h2>
              <p class="muted small">{{ t('trainings.progress', { done: doneCount, total: people.length }) }}</p>
            </div>
            <div class="row">
              <button type="button" class="btn btn-ghost" @click="openEditor(selected)">{{ t('app.edit') }}</button>
              <a class="btn btn-ghost" :href="`/api/trainings/${selected.id}/export.csv`" download><AppIcon name="download" :size="16" />CSV</a>
              <button type="button" class="btn btn-secondary" @click="remind"><AppIcon name="bell" :size="16" />{{ t('trainings.remind') }}</button>
            </div>
          </div>
          <div class="table-wrap table-scroll">
            <table class="table table-sticky">
              <thead>
                <tr>
                  <th scope="col" :aria-sort="peopleSort.ariaSort('name')"><SortHeader :label="t('time.person')" :active="peopleSort.key.value === 'name'" :dir="peopleSort.dir.value" @sort="peopleSort.toggle('name')" /></th>
                  <th scope="col" :aria-sort="peopleSort.ariaSort('status')"><SortHeader :label="t('trainings.statusLabel')" :active="peopleSort.key.value === 'status'" :dir="peopleSort.dir.value" @sort="peopleSort.toggle('status')" /></th>
                  <th scope="col" :aria-sort="peopleSort.ariaSort('due')"><SortHeader :label="t('trainings.date')" :active="peopleSort.key.value === 'due'" :dir="peopleSort.dir.value" @sort="peopleSort.toggle('due')" /></th>
                  <th scope="col"><span class="visually-hidden">{{ t('trainings.record') }}</span></th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="s in peopleSort.sorted.value" :key="s.person.id">
                  <td>
                    <span class="person">
                      <UserAvatar :id="s.person.id" :name="s.person.full_name" :photo-version="s.person.photo_version" :size="28" />
                      {{ s.person.full_name }}
                    </span>
                  </td>
                  <td><span class="badge" :class="`b-${s.status}`">{{ t(`trainings.status.${s.status}`) }}</span></td>
                  <td class="small">{{ dueText(s) }}</td>
                  <td><button type="button" class="btn btn-ghost" @click="openRecord(s)">{{ t('trainings.record') }}</button></td>
                </tr>
              </tbody>
            </table>
          </div>
        </section>
      </div>
    </LoadState>

    <BaseModal
      :open="recordFor !== null"
      :title="tab === 'manage' ? t('trainings.recordFor', { name: recordFor?.person.full_name ?? '' }) : t('trainings.markDone')"
      :description="recordFor?.training.title ?? ''"
      :confirm-label="t('app.save')"
      :busy="busy"
      @close="recordFor = null"
      @confirm="saveRecord"
    >
      <form class="stack" novalidate @submit.prevent="saveRecord">
        <FormField id="tr-date" :label="t('trainings.completedOn')" :error="recordError">
          <template #default="{ attrs }"><input v-bind="attrs" v-model="recordForm.completed_on" type="date" class="input" :max="todayIso()" /></template>
        </FormField>
        <FormField id="tr-file" :label="t('trainings.certificate')" :hint="t('trainings.certificateHint')" optional>
          <template #default="{ attrs }">
            <input v-bind="attrs" type="file" accept=".pdf,.png,.jpg,.jpeg" @change="recordForm.file = ($event.target as HTMLInputElement).files?.[0] ?? null" />
          </template>
        </FormField>
      </form>
    </BaseModal>

    <BaseModal :open="editorOpen" :title="editing ? t('trainings.edit') : t('trainings.new')" :confirm-label="t('app.save')" :busy="busy" wide @close="editorOpen = false" @confirm="saveTraining">
      <form class="stack" novalidate @submit.prevent="saveTraining">
        <div v-if="formError" class="notice notice-danger small" role="alert">{{ formError }}</div>
        <FormField id="tr-title" :label="t('trainings.titleLabel')">
          <template #default="{ attrs }"><input v-bind="attrs" v-model="form.title" class="input" maxlength="150" /></template>
        </FormField>
        <FormField id="tr-desc" :label="t('trainings.description')" optional>
          <template #default="{ attrs }"><textarea v-bind="attrs" v-model="form.description" class="textarea" rows="3" maxlength="4000" /></template>
        </FormField>
        <div class="grid-2">
          <FormField id="tr-interval" :label="t('trainings.interval')" :hint="t('trainings.intervalHint')" optional>
            <template #default="{ attrs }"><input v-bind="attrs" v-model.number="form.interval_months" type="number" min="1" max="120" class="input" /></template>
          </FormField>
          <FormField id="tr-due" :label="t('trainings.dueWithin')">
            <template #default="{ attrs }"><input v-bind="attrs" v-model.number="form.due_within_days" type="number" min="1" max="365" class="input" /></template>
          </FormField>
          <FormField id="tr-dept" :label="t('trainings.audience')">
            <template #default="{ attrs }">
              <select v-bind="attrs" v-model="form.department" class="select">
                <option value="">{{ t('trainings.everyone') }}</option>
                <option v-for="d in departments" :key="d" :value="d">{{ d }}</option>
              </select>
            </template>
          </FormField>
          <FormField id="tr-link" :label="t('trainings.link')" optional>
            <template #default="{ attrs }"><input v-bind="attrs" v-model="form.link" type="url" class="input" maxlength="500" placeholder="https://" /></template>
          </FormField>
        </div>
        <label class="checkbox"><input v-model="form.active" type="checkbox" /><span>{{ t('trainings.activeLabel') }}</span></label>
      </form>
    </BaseModal>
  </div>
</template>

<style scoped>
.cards {
  list-style: none;
  margin: 0;
  padding: 0;
  display: grid;
  gap: var(--space-3);
  grid-template-columns: repeat(auto-fill, minmax(min(100%, 340px), 1fr));
}

.training {
  display: grid;
  gap: var(--space-3);
  align-content: start;
}

.training.st-overdue {
  border-color: color-mix(in srgb, var(--color-danger) 45%, var(--color-border));
}

.training-head {
  display: flex;
  align-items: flex-start;
  gap: var(--space-3);
}

.training-head h2 {
  font-size: var(--text-md);
}

.t-icon {
  display: grid;
  place-items: center;
  width: 40px;
  height: 40px;
  border-radius: var(--radius-md);
  background: var(--color-primary-soft);
  color: var(--color-primary-text);
  flex-shrink: 0;
}

.grow {
  flex: 1;
  min-width: 0;
}

.badge {
  padding: 2px 10px;
  border-radius: var(--radius-full);
  font-size: var(--text-xs);
  font-weight: 700;
  white-space: nowrap;
  background: var(--color-neutral-soft);
  color: var(--color-text-muted);
}

.b-valid {
  background: var(--color-success-soft);
  color: var(--color-success);
}

.b-expiring,
.b-due_soon {
  background: var(--color-warning-soft);
  color: var(--color-warning);
}

.b-overdue {
  background: var(--color-danger-soft);
  color: var(--color-danger);
}

.foot {
  justify-content: space-between;
}

.due {
  color: var(--color-text-muted);
}

.manage {
  display: grid;
  grid-template-columns: minmax(220px, 280px) minmax(0, 1fr);
  gap: var(--space-4);
  align-items: start;
}

.pick {
  display: grid;
  gap: 2px;
  width: 100%;
  padding: var(--space-3) var(--space-4);
  border: 0;
  border-left: 3px solid transparent;
  background: transparent;
  color: inherit;
  font: inherit;
  text-align: left;
  cursor: pointer;
}

.pick:hover {
  background: var(--color-surface-muted);
}

.pick.active {
  border-left-color: var(--color-primary);
  background: var(--color-primary-soft);
}

.pick-title {
  font-weight: 600;
}

.detail-head {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-3);
  padding: var(--space-3) var(--space-4) var(--space-3) var(--space-5);
  border-bottom: 1px solid var(--color-border);
}

.detail-head h2 {
  font-size: var(--text-lg);
}

.person {
  display: inline-flex;
  align-items: center;
  gap: var(--space-2);
}

@media (max-width: 900px) {
  .manage {
    grid-template-columns: 1fr;
  }
}
</style>
