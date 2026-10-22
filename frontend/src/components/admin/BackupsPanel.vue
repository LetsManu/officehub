<script setup lang="ts">
/**
 * Backups: every night the database and all files go into one archive in the backup folder. Shows whether the last
 * one worked, lets administrators back up now, download an archive or go back to it.
 */
import { onMounted, ref } from 'vue'
import AppIcon from '@/components/AppIcon.vue'
import BaseModal from '@/components/BaseModal.vue'
import FormField from '@/components/FormField.vue'
import { api } from '@/lib/api'
import { errorText, formatDateTime, formatFileSize, t } from '@/lib/i18n'
import { showToast } from '@/lib/toast'

interface BackupItem {
  name: string
  size: number
  created_at: string
}

interface Overview {
  available: boolean
  folder: string
  options: { enabled: boolean; hour: number; keep: number }
  last: { at: string | null; ok: boolean | null; name: string | null; size: number | null; error: string | null }
  items: BackupItem[]
}

const data = ref<Overview | null>(null)
const options = ref({ enabled: true, hour: 2, keep: 14 })
const busy = ref(false)
const saving = ref(false)
const restoring = ref<BackupItem | null>(null)
const restoreBusy = ref(false)
const HOURS = Array.from({ length: 24 }, (_, h) => h)

async function load() {
  data.value = await api.get<Overview>('/api/admin/backups')
  options.value = { ...data.value.options }
}

async function save() {
  saving.value = true
  try {
    data.value = await api.put<Overview>('/api/admin/backups/settings', options.value)
    showToast(t('backups.saved'))
  } catch (e) {
    showToast(errorText(e), 'error')
  } finally {
    saving.value = false
  }
}

async function backUpNow() {
  busy.value = true
  try {
    await api.post('/api/admin/backups')
    showToast(t('backups.done'))
  } catch (e) {
    showToast(errorText(e), 'error')
  } finally {
    busy.value = false
    await load().catch(() => undefined)
  }
}

async function restore() {
  if (!restoring.value) return
  restoreBusy.value = true
  try {
    await api.post(`/api/admin/backups/${encodeURIComponent(restoring.value.name)}/restore`)
    showToast(t('backups.restored'))
    // Everything changed underneath the page (and maybe the sign-in): start fresh
    window.setTimeout(() => window.location.reload(), 1200)
  } catch (e) {
    showToast(errorText(e), 'error')
    restoreBusy.value = false
    restoring.value = null
  }
}

const label = (b: BackupItem) => formatDateTime(b.created_at)
const kind = (b: BackupItem) => (b.name.endsWith('-manual.tar.gz') ? 'manual' : b.name.endsWith('-restore.tar.gz') ? 'restore' : 'auto')

onMounted(() => load().catch((e) => showToast(errorText(e), 'error')))
</script>

<template>
  <div v-if="data" class="stack">
    <p class="muted">{{ t('backups.intro') }}</p>
    <p v-if="!data.available" class="notice notice-info small">{{ t('backups.unavailable') }}</p>
    <template v-else>
      <div v-if="data.last.ok === false" class="notice notice-danger small" role="alert">
        <AppIcon name="alert" :size="18" />
        <span><strong>{{ t('backups.failed', { when: formatDateTime(data.last.at) }) }}</strong><span class="block">{{ data.last.error }}</span></span>
      </div>
      <div v-else-if="data.last.ok" class="notice notice-success small">
        <AppIcon name="check" :size="18" />{{ t('backups.lastOk', { when: formatDateTime(data.last.at), size: formatFileSize(data.last.size ?? 0) }) }}
      </div>
      <p v-else class="notice notice-info small">{{ t('backups.none') }}</p>

      <form class="options" novalidate @submit.prevent="save">
        <label class="checkbox wide">
          <input v-model="options.enabled" type="checkbox" />
          <span>{{ t('backups.enabled') }}</span>
        </label>
        <FormField id="backup-hour" :label="t('backups.hour')">
          <template #default="{ attrs }">
            <select v-bind="attrs" v-model.number="options.hour" class="select" :disabled="!options.enabled">
              <option v-for="h in HOURS" :key="h" :value="h">{{ t('backups.at', { hour: String(h).padStart(2, '0') }) }}</option>
            </select>
          </template>
        </FormField>
        <FormField id="backup-keep" :label="t('backups.keep')" :hint="t('backups.keepHint')">
          <template #default="{ attrs }"><input v-bind="attrs" v-model.number="options.keep" type="number" min="1" max="365" class="input" /></template>
        </FormField>
        <div class="actions">
          <button type="submit" class="btn btn-primary" :disabled="saving">{{ t('app.save') }}</button>
          <button type="button" class="btn btn-secondary" :disabled="busy" @click="backUpNow"><AppIcon name="download" :size="18" />{{ busy ? t('backups.working') : t('backups.now') }}</button>
        </div>
      </form>
      <p class="muted small">{{ t('backups.folder', { folder: data.folder }) }}</p>

      <ul v-if="data.items.length" class="list" :aria-label="t('backups.list')">
        <li v-for="b in data.items" :key="b.name" class="row">
          <AppIcon name="archive" :size="18" />
          <span class="grow"><strong>{{ label(b) }}</strong><span class="muted small block">{{ t(`backups.kinds.${kind(b)}`) }} · {{ formatFileSize(b.size) }}</span></span>
          <a class="btn btn-ghost" :href="`/api/admin/backups/${encodeURIComponent(b.name)}/download`" download :aria-label="t('backups.downloadOne', { when: label(b) })"><AppIcon name="download" :size="16" />{{ t('files.download') }}</a>
          <button type="button" class="btn btn-ghost" @click="restoring = b">{{ t('backups.restore') }}</button>
        </li>
      </ul>
    </template>

    <BaseModal :open="restoring !== null" :title="t('backups.restoreTitle', { when: restoring ? label(restoring) : '' })" :description="t('backups.restoreText')" :confirm-label="t('backups.restore')" :busy="restoreBusy" tone="danger" @close="restoring = null" @confirm="restore" />
  </div>
</template>

<style scoped>
.options {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
  align-items: start;
  gap: var(--space-3) var(--space-4);
}

.wide,
.actions {
  grid-column: 1 / -1;
}

.actions {
  display: flex;
  flex-wrap: wrap;
  gap: var(--space-2);
}

.notice {
  align-items: center;
}

.list {
  display: grid;
  margin: 0;
  padding: 0;
  list-style: none;
}

.row {
  display: flex;
  align-items: center;
  gap: var(--space-3);
  padding: var(--space-2) 0;
  border-top: 1px solid var(--color-border);
}

.grow {
  flex: 1;
  min-width: 0;
}

.block {
  display: block;
}

@media (max-width: 560px) {
  .row {
    flex-wrap: wrap;
  }
}
</style>
