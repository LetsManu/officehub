<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'
import AppIcon from '@/components/AppIcon.vue'
import BaseModal from '@/components/BaseModal.vue'
import EmptyState from '@/components/EmptyState.vue'
import FormField from '@/components/FormField.vue'
import LoadState from '@/components/LoadState.vue'
import PageHeader from '@/components/PageHeader.vue'
import { api } from '@/lib/api'
import { downloadCsv } from '@/lib/csv'
import { ANNOUNCEMENT_CATEGORIES } from '@/lib/requestTypes'
import { errorText, formatDate, formatDateTime, t } from '@/lib/i18n'
import { showToast } from '@/lib/toast'
import { todayIso } from '@/lib/workdays'
import type { Announcement, Confirmations } from '@/lib/types'

const items = ref<Announcement[]>([])
const loading = ref(true)
const error = ref<string | null>(null)

const editorOpen = ref(false)
const editing = ref<Announcement | null>(null)
const EMPTY_FORM = {
  title: '', body: '', category: 'general', publish_date: todayIso(), expiry_date: '', event_date: '', pinned: false,
  must_read: false, poll_question: '', poll_options: ['', ''] as string[],
}
const form = reactive({ ...EMPTY_FORM, poll_options: [...EMPTY_FORM.poll_options] })
const errors = reactive({ title: '', body: '', expiry_date: '', poll_options: '' })

const readsFor = ref<Announcement | null>(null)
const reads = ref<Confirmations | null>(null)
const reminding = ref(false)

async function openReads(item: Announcement) {
  readsFor.value = item
  reads.value = null
  try {
    reads.value = await api.get<Confirmations>(`/api/announcements/${item.id}/confirmations`)
  } catch (e) {
    showToast(errorText(e), 'error')
    readsFor.value = null
  }
}

async function remind() {
  if (!readsFor.value) return
  reminding.value = true
  try {
    const result = await api.post<{ reminded: number }>(`/api/announcements/${readsFor.value.id}/remind`)
    showToast(t('manageNews.remindedToast', { count: result.reminded }))
  } catch (e) {
    showToast(errorText(e), 'error')
  } finally {
    reminding.value = false
  }
}

function exportReads() {
  if (!readsFor.value || !reads.value) return
  const rows = [
    ...reads.value.confirmed.map((r) => [r.full_name, r.department, t('manageNews.readYes'), formatDateTime(r.read_at)]),
    ...reads.value.missing.map((r) => [r.full_name, r.department, t('manageNews.readNo'), '']),
  ]
  downloadCsv(`confirmations-${readsFor.value.id}.csv`, [t('manageNews.csvName'), t('manageNews.csvDepartment'), t('manageNews.csvRead'), t('manageNews.csvWhen')], rows)
}
const formError = ref('')
const saving = ref(false)
const archiveTarget = ref<Announcement | null>(null)

function state(item: Announcement): { label: string; tone: string } {
  const today = todayIso()
  if (item.archived) return { label: t('manageNews.stateArchived'), tone: 'neutral' }
  if (item.publish_date > today) return { label: t('manageNews.stateScheduled'), tone: 'info' }
  if (item.expiry_date && item.expiry_date < today) return { label: t('manageNews.stateExpired'), tone: 'neutral' }
  return { label: t('manageNews.stateLive'), tone: 'success' }
}

async function load() {
  loading.value = true
  error.value = null
  try {
    items.value = await api.get<Announcement[]>('/api/announcements?include=all&limit=200')
  } catch (e) {
    error.value = errorText(e)
  } finally {
    loading.value = false
  }
}

function openEditor(item: Announcement | null) {
  editing.value = item
  Object.assign(
    form,
    item
      ? {
          title: item.title, body: item.body, category: item.category, publish_date: item.publish_date, expiry_date: item.expiry_date ?? '',
          event_date: item.event_date ?? '', pinned: item.pinned, must_read: item.must_read,
          poll_question: item.poll?.question ?? '', poll_options: item.poll ? [...item.poll.options] : ['', ''],
        }
      : { ...EMPTY_FORM, publish_date: todayIso(), poll_options: ['', ''] },
  )
  errors.title = errors.body = errors.expiry_date = errors.poll_options = formError.value = ''
  editorOpen.value = true
}

async function save() {
  errors.title = form.title.trim() ? '' : t('validation.title_required')
  errors.body = form.body.trim() ? '' : t('validation.body_required')
  errors.expiry_date = form.expiry_date && form.expiry_date < form.publish_date ? t('validation.expiry_before_publish') : ''
  const options = form.poll_options.map((o) => o.trim()).filter(Boolean)
  errors.poll_options = form.poll_question.trim() && options.length < 2 ? t('validation.poll_options_required') : ''
  if (errors.title || errors.body || errors.expiry_date || errors.poll_options) return
  saving.value = true
  formError.value = ''
  const body = {
    title: form.title.trim(),
    body: form.body.trim(),
    category: form.category,
    publish_date: form.publish_date || todayIso(),
    expiry_date: form.expiry_date || null,
    event_date: form.category === 'event' && form.event_date ? form.event_date : null,
    pinned: form.pinned,
    must_read: form.must_read,
    poll_question: form.poll_question.trim() || null,
    poll_options: form.poll_question.trim() ? options : null,
  }
  try {
    if (editing.value) {
      await api.patch(`/api/announcements/${editing.value.id}`, body)
      showToast(t('manageNews.saved'))
    } else {
      await api.post('/api/announcements', body)
      showToast(t('manageNews.published'))
    }
    editorOpen.value = false
    await load()
  } catch (e) {
    formError.value = errorText(e)
  } finally {
    saving.value = false
  }
}

async function setArchived(item: Announcement, archived: boolean) {
  saving.value = true
  try {
    await api.patch(`/api/announcements/${item.id}`, { archived })
    showToast(archived ? t('manageNews.archivedToast') : t('manageNews.restoredToast'))
    archiveTarget.value = null
    await load()
  } catch (e) {
    showToast(errorText(e), 'error')
  } finally {
    saving.value = false
  }
}

onMounted(load)
</script>

<template>
  <div class="page">
    <PageHeader :title="t('manageNews.title')" :subtitle="t('manageNews.subtitle')">
      <template #actions>
        <button type="button" class="btn btn-primary" @click="openEditor(null)"><AppIcon name="plus" />{{ t('manageNews.new') }}</button>
      </template>
    </PageHeader>

    <LoadState :loading="loading" :error="error" @retry="load">
      <section class="card card-flush">
        <ul v-if="items.length" class="list">
          <li v-for="item in items" :key="item.id" class="item">
            <div class="item-main">
              <p class="item-title">
                <AppIcon v-if="item.pinned" name="pin" :size="16" :label="t('announcements.pinned')" />
                {{ item.title }}
                <span v-if="item.must_read" class="mini-tag">{{ t('announcements.mustRead') }}</span>
                <span v-if="item.poll" class="mini-tag">{{ t('manageNews.hasPoll') }}</span>
              </p>
              <p class="muted small">
                <span class="state" :class="`state-${state(item).tone}`">{{ state(item).label }}</span>
                · {{ t(`announcements.categories.${item.category}`) }} · {{ formatDate(item.publish_date) }}
                <template v-if="item.expiry_date"> – {{ formatDate(item.expiry_date) }}</template>
              </p>
            </div>
            <div class="row actions">
              <button v-if="item.must_read" type="button" class="btn btn-ghost" @click="openReads(item)">{{ t('manageNews.reads') }}</button>
              <button type="button" class="btn btn-ghost" @click="openEditor(item)">{{ t('app.edit') }}</button>
              <button v-if="!item.archived" type="button" class="btn btn-ghost" @click="archiveTarget = item">{{ t('manageNews.archive') }}</button>
              <button v-else type="button" class="btn btn-ghost" :disabled="saving" @click="setArchived(item, false)">{{ t('manageNews.restore') }}</button>
            </div>
          </li>
        </ul>
        <EmptyState v-else icon="megaphone" :message="t('manageNews.empty')" :action-label="t('manageNews.new')" @action="openEditor(null)" />
      </section>
    </LoadState>

    <BaseModal
      :open="editorOpen"
      :title="editing ? t('manageNews.editTitle') : t('manageNews.newTitle')"
      :confirm-label="editing ? t('app.save') : t('manageNews.publish')"
      :busy="saving"
      wide
      @close="editorOpen = false"
      @confirm="save"
    >
      <form class="stack" novalidate @submit.prevent="save">
        <div v-if="formError" class="notice notice-danger small" role="alert">{{ formError }}</div>
        <FormField id="ann-title" :label="t('manageNews.titleLabel')" :error="errors.title">
          <template #default="{ attrs }"><input v-bind="attrs" v-model="form.title" class="input" maxlength="150" /></template>
        </FormField>
        <FormField id="ann-body" :label="t('manageNews.body')" :error="errors.body">
          <template #default="{ attrs }"><textarea v-bind="attrs" v-model="form.body" class="textarea" rows="6" maxlength="10000" /></template>
        </FormField>
        <div class="grid-2">
          <FormField id="ann-category" :label="t('manageNews.category')">
            <template #default="{ attrs }">
              <select v-bind="attrs" v-model="form.category" class="select">
                <option v-for="c in ANNOUNCEMENT_CATEGORIES" :key="c" :value="c">{{ t(`announcements.categories.${c}`) }}</option>
              </select>
            </template>
          </FormField>
          <FormField v-if="form.category === 'event'" id="ann-event" :label="t('manageNews.eventDate')" optional>
            <template #default="{ attrs }"><input v-bind="attrs" v-model="form.event_date" class="input" type="date" /></template>
          </FormField>
        </div>
        <label class="checkbox">
          <input v-model="form.pinned" type="checkbox" aria-describedby="pinned-hint" />
          <span>
            <span class="label-text">{{ t('manageNews.pinned') }}</span><br />
            <span id="pinned-hint" class="muted small">{{ t('manageNews.pinnedHint') }}</span>
          </span>
        </label>
        <label class="checkbox">
          <input v-model="form.must_read" type="checkbox" aria-describedby="must-read-hint" />
          <span>
            <span class="label-text">{{ t('manageNews.mustRead') }}</span><br />
            <span id="must-read-hint" class="muted small">{{ t('manageNews.mustReadHint') }}</span>
          </span>
        </label>
        <details class="disclosure" :open="Boolean(form.poll_question) || undefined">
          <summary>{{ t('manageNews.poll') }}</summary>
          <div class="disclosure-body stack">
            <FormField id="ann-poll-q" :label="t('manageNews.pollQuestion')" :hint="t('manageNews.pollHint')" optional>
              <template #default="{ attrs }"><input v-bind="attrs" v-model="form.poll_question" class="input" maxlength="200" /></template>
            </FormField>
            <fieldset v-if="form.poll_question.trim()" class="poll-options">
              <legend class="label-text">{{ t('manageNews.pollOptions') }}</legend>
              <div v-for="(_, i) in form.poll_options" :key="i" class="row poll-row">
                <label :for="`ann-opt-${i}`" class="visually-hidden">{{ t('manageNews.pollOption', { number: i + 1 }) }}</label>
                <input :id="`ann-opt-${i}`" v-model="form.poll_options[i]" class="input" maxlength="100" :placeholder="t('manageNews.pollOption', { number: i + 1 })" />
                <button v-if="form.poll_options.length > 2" type="button" class="btn btn-ghost btn-icon" :aria-label="t('manageNews.pollRemove', { number: i + 1 })" @click="form.poll_options.splice(i, 1)">
                  <AppIcon name="trash" :size="18" />
                </button>
              </div>
              <p v-if="errors.poll_options" class="field-error small" role="alert">{{ errors.poll_options }}</p>
              <button v-if="form.poll_options.length < 6" type="button" class="btn btn-ghost add-option" @click="form.poll_options.push('')">
                <AppIcon name="plus" :size="18" />{{ t('manageNews.pollAdd') }}
              </button>
              <p v-if="editing?.poll" class="muted small">{{ t('manageNews.pollResetHint') }}</p>
            </fieldset>
          </div>
        </details>
        <details class="disclosure" :open="Boolean(form.expiry_date) || form.publish_date !== todayIso() || undefined">
          <summary>{{ t('manageNews.more') }}</summary>
          <div class="disclosure-body grid-2">
            <FormField id="ann-publish" :label="t('manageNews.publishDate')">
              <template #default="{ attrs }"><input v-bind="attrs" v-model="form.publish_date" class="input" type="date" /></template>
            </FormField>
            <FormField id="ann-expiry" :label="t('manageNews.expiryDate')" :hint="t('manageNews.expiryHint')" :error="errors.expiry_date" optional>
              <template #default="{ attrs }"><input v-bind="attrs" v-model="form.expiry_date" class="input" type="date" :min="form.publish_date" /></template>
            </FormField>
          </div>
        </details>
      </form>
    </BaseModal>

    <BaseModal
      :open="readsFor !== null"
      :title="t('manageNews.readsTitle')"
      :description="readsFor?.title ?? ''"
      hide-actions
      wide
      @close="readsFor = null"
    >
      <p v-if="!reads" class="muted">{{ t('app.loading') }}</p>
      <div v-else class="stack">
        <p class="reads-summary">
          {{ t('manageNews.readsCount', { done: reads.confirmed.length, total: reads.confirmed.length + reads.missing.length }) }}
        </p>
        <progress :value="reads.confirmed.length" :max="reads.confirmed.length + reads.missing.length" :aria-label="t('manageNews.readsTitle')" />
        <div class="grid-2 reads">
          <section>
            <h3>{{ t('manageNews.readsMissing') }}</h3>
            <ul class="people">
              <li v-for="r in reads.missing" :key="r.id">{{ r.full_name }} <span class="muted small">{{ r.department }}</span></li>
              <li v-if="!reads.missing.length" class="muted">{{ t('manageNews.readsAllDone') }}</li>
            </ul>
          </section>
          <section>
            <h3>{{ t('manageNews.readsConfirmed') }}</h3>
            <ul class="people">
              <li v-for="r in reads.confirmed" :key="r.id">{{ r.full_name }} <span class="muted small">{{ formatDateTime(r.read_at) }}</span></li>
            </ul>
          </section>
        </div>
        <div class="form-actions">
          <button type="button" class="btn btn-secondary" @click="exportReads"><AppIcon name="download" />{{ t('manageNews.exportCsv') }}</button>
          <button v-if="reads.missing.length" type="button" class="btn btn-primary" :disabled="reminding" @click="remind"><AppIcon name="bell" />{{ t('manageNews.remind') }}</button>
        </div>
      </div>
    </BaseModal>

    <BaseModal
      :open="archiveTarget !== null"
      :title="t('manageNews.archiveTitle')"
      :description="t('manageNews.archiveText', { title: archiveTarget?.title ?? '' })"
      :confirm-label="t('manageNews.archive')"
      tone="danger"
      :busy="saving"
      @close="archiveTarget = null"
      @confirm="archiveTarget && setArchived(archiveTarget, true)"
    />
  </div>
</template>

<style scoped>
.item {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-3);
  padding: var(--space-3) var(--space-3) var(--space-3) var(--space-5);
}

.item-main {
  display: grid;
  gap: 2px;
  min-width: 0;
}

.item-title {
  display: inline-flex;
  align-items: center;
  gap: var(--space-2);
  font-weight: 600;
}

.state {
  font-weight: 600;
}

.state-success {
  color: var(--color-success);
}

.state-info {
  color: var(--color-primary-text);
}

.label-text {
  font-weight: 600;
}

.actions {
  gap: var(--space-1);
}

.mini-tag {
  padding: 1px 8px;
  border-radius: var(--radius-full);
  background: var(--color-neutral-soft);
  color: var(--color-text-muted);
  font-size: var(--text-xs);
  font-weight: 600;
}

.poll-options {
  display: grid;
  gap: var(--space-2);
  margin: 0;
  padding: 0;
  border: 0;
}

.poll-row {
  flex-wrap: nowrap;
  gap: var(--space-2);
}

.add-option {
  justify-self: start;
}

.field-error {
  color: var(--color-danger);
}

.reads-summary {
  font-weight: 600;
}

.reads progress,
progress {
  width: 100%;
  height: 8px;
  accent-color: var(--color-success);
}

.reads h3 {
  margin-bottom: var(--space-2);
}

.people {
  list-style: none;
  margin: 0;
  padding: 0;
  display: grid;
  gap: var(--space-1);
  max-height: 260px;
  overflow-y: auto;
}
</style>
