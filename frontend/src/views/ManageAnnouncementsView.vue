<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'
import AppIcon from '@/components/AppIcon.vue'
import BaseModal from '@/components/BaseModal.vue'
import EmptyState from '@/components/EmptyState.vue'
import FormField from '@/components/FormField.vue'
import LoadState from '@/components/LoadState.vue'
import PageHeader from '@/components/PageHeader.vue'
import { api } from '@/lib/api'
import { ANNOUNCEMENT_CATEGORIES } from '@/lib/requestTypes'
import { errorText, formatDate, t } from '@/lib/i18n'
import { showToast } from '@/lib/toast'
import { todayIso } from '@/lib/workdays'
import type { Announcement } from '@/lib/types'

const items = ref<Announcement[]>([])
const loading = ref(true)
const error = ref<string | null>(null)

const editorOpen = ref(false)
const editing = ref<Announcement | null>(null)
const form = reactive({ title: '', body: '', category: 'general', publish_date: todayIso(), expiry_date: '', event_date: '', pinned: false })
const errors = reactive({ title: '', body: '', expiry_date: '' })
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
      ? { title: item.title, body: item.body, category: item.category, publish_date: item.publish_date, expiry_date: item.expiry_date ?? '', event_date: item.event_date ?? '', pinned: item.pinned }
      : { title: '', body: '', category: 'general', publish_date: todayIso(), expiry_date: '', event_date: '', pinned: false },
  )
  errors.title = errors.body = errors.expiry_date = formError.value = ''
  editorOpen.value = true
}

async function save() {
  errors.title = form.title.trim() ? '' : t('validation.title_required')
  errors.body = form.body.trim() ? '' : t('validation.body_required')
  errors.expiry_date = form.expiry_date && form.expiry_date < form.publish_date ? t('validation.expiry_before_publish') : ''
  if (errors.title || errors.body || errors.expiry_date) return
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
              </p>
              <p class="muted small">
                <span class="state" :class="`state-${state(item).tone}`">{{ state(item).label }}</span>
                · {{ t(`announcements.categories.${item.category}`) }} · {{ formatDate(item.publish_date) }}
                <template v-if="item.expiry_date"> – {{ formatDate(item.expiry_date) }}</template>
              </p>
            </div>
            <div class="row actions">
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
</style>
