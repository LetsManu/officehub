<script setup lang="ts">
/**
 * Backups: every night the database and all files go into one archive in the backup folder. Shows whether the last
 * one worked, lets administrators back up now, download an archive or go back to it. A second copy can go to the
 * company's own NAS (Windows share or SFTP); the password is never sent back, only whether one is set.
 */
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
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

type NasKind = 'off' | 'smb' | 'sftp'

interface NasSettings {
  kind: NasKind
  path: string
  host: string
  port: number
  folder: string
  user: string
  keep: number
}

interface NasStatus {
  at: string | null
  ok: boolean | null
  name: string | null
  code: string | null
  error: string | null
  running: boolean
  count: number | null
}

interface Overview {
  available: boolean
  nas: NasSettings & { has_password: boolean }
  nas_last: NasStatus
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
const NAS_KINDS: NasKind[] = ['off', 'smb', 'sftp']

const nas = ref<NasSettings & { password: string }>({ kind: 'off', path: '', host: '', port: 22, folder: '', user: '', keep: 0, password: '' })
const nasSaving = ref(false)
const nasTesting = ref(false)
const nasTest = ref<{ ok: boolean; text: string } | null>(null)
let poll: number | undefined

function nasForm(stored: Overview['nas']) {
  return { kind: stored.kind, path: stored.path, host: stored.host, port: stored.port, folder: stored.folder, user: stored.user, keep: stored.keep, password: '' }
}

async function load() {
  data.value = await api.get<Overview>('/api/admin/backups')
  options.value = { ...data.value.options }
  nas.value = nasForm(data.value.nas)
  watchCopy()
}

/** While the copy to the NAS runs (after "Back up now"), look again every few seconds. */
function watchCopy() {
  window.clearTimeout(poll)
  if (data.value?.nas_last.running) poll = window.setTimeout(() => refreshStatus().catch(() => undefined), 4000)
}

async function refreshStatus() {
  const fresh = await api.get<Overview>('/api/admin/backups')
  if (data.value) {
    data.value.nas_last = fresh.nas_last
    data.value.items = fresh.items
  }
  watchCopy()
}

/** The reason in the reader's language when the server sent a known code, otherwise the server's own words. */
const nasLastText = computed(() => {
  const last = data.value?.nas_last
  if (!last || last.ok !== false) return ''
  const known = last.code ? errorText({ code: last.code }) : ''
  return known && known !== t('errors.unknown') ? known : (last.error ?? '')
})

async function saveNas() {
  nasSaving.value = true
  try {
    data.value = await api.put<Overview>('/api/admin/backups/nas', nas.value)
    nas.value = nasForm(data.value.nas)
    showToast(t('backups.nas.saved'))
  } catch (e) {
    showToast(errorText(e), 'error')
  } finally {
    nasSaving.value = false
  }
}

async function testNas() {
  nasTesting.value = true
  nasTest.value = null
  try {
    await api.post('/api/admin/backups/nas/test', nas.value)
    nasTest.value = { ok: true, text: t('backups.nas.testOk') }
  } catch (e) {
    nasTest.value = { ok: false, text: errorText(e) }
  } finally {
    nasTesting.value = false
  }
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
onBeforeUnmount(() => window.clearTimeout(poll))
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

      <section class="stack-sm nas" aria-labelledby="nas-title">
        <h3 id="nas-title"><AppIcon name="box" :size="18" />{{ t('backups.nas.title') }}</h3>
        <p class="muted small">{{ t('backups.nas.intro') }}</p>
        <p v-if="data.nas_last.running" class="notice notice-info small" role="status">{{ t('backups.nas.running') }}</p>
        <div v-else-if="data.nas_last.ok === false" class="notice notice-danger small" role="alert">
          <AppIcon name="alert" :size="18" />
          <span><strong>{{ t('backups.nas.failed', { when: formatDateTime(data.nas_last.at) }) }}</strong><span class="block">{{ nasLastText }}</span></span>
        </div>
        <div v-else-if="data.nas_last.ok && data.nas.kind !== 'off'" class="notice notice-success small">
          <AppIcon name="check" :size="18" />{{ t('backups.nas.lastOk', { when: formatDateTime(data.nas_last.at), count: String(data.nas_last.count ?? 1) }) }}
        </div>
        <p v-else-if="data.nas.kind !== 'off'" class="notice notice-info small">{{ t('backups.nas.none') }}</p>

        <form class="options" novalidate @submit.prevent="saveNas">
          <FormField id="nas-kind" :label="t('backups.nas.kind')">
            <template #default="{ attrs }">
              <select v-bind="attrs" v-model="nas.kind" class="select" @change="nasTest = null">
                <option v-for="k in NAS_KINDS" :key="k" :value="k">{{ t(`backups.nas.kinds.${k}`) }}</option>
              </select>
            </template>
          </FormField>
          <FormField v-if="nas.kind === 'smb'" id="nas-path" class="wide" :label="t('backups.nas.path')" :hint="t('backups.nas.pathHint')">
            <template #default="{ attrs }"><input v-bind="attrs" v-model="nas.path" class="input" placeholder="\\nas\backup\officehub" autocomplete="off" spellcheck="false" /></template>
          </FormField>
          <template v-else-if="nas.kind === 'sftp'">
            <FormField id="nas-host" :label="t('backups.nas.host')">
              <template #default="{ attrs }"><input v-bind="attrs" v-model="nas.host" class="input" placeholder="nas.firma.local" autocomplete="off" spellcheck="false" /></template>
            </FormField>
            <FormField id="nas-port" :label="t('backups.nas.port')">
              <template #default="{ attrs }"><input v-bind="attrs" v-model.number="nas.port" type="number" min="1" max="65535" class="input" /></template>
            </FormField>
            <FormField id="nas-folder" class="wide" :label="t('backups.nas.folder')" :hint="t('backups.nas.folderHint')">
              <template #default="{ attrs }"><input v-bind="attrs" v-model="nas.folder" class="input" placeholder="/volume1/backup/officehub" autocomplete="off" spellcheck="false" /></template>
            </FormField>
          </template>
          <template v-if="nas.kind !== 'off'">
            <FormField id="nas-user" :label="t('backups.nas.user')">
              <template #default="{ attrs }"><input v-bind="attrs" v-model="nas.user" class="input" autocomplete="off" spellcheck="false" /></template>
            </FormField>
            <FormField id="nas-password" :label="t('backups.nas.password')" :hint="data.nas.has_password ? t('backups.nas.passwordKept') : ''">
              <template #default="{ attrs }"><input v-bind="attrs" v-model="nas.password" class="input" type="password" autocomplete="new-password" /></template>
            </FormField>
            <FormField id="nas-keep" :label="t('backups.nas.keep')" :hint="t('backups.nas.keepHint')">
              <template #default="{ attrs }"><input v-bind="attrs" v-model.number="nas.keep" type="number" min="0" max="365" class="input" /></template>
            </FormField>
          </template>
          <div v-if="nasTest" class="wide notice small" :class="nasTest.ok ? 'notice-success' : 'notice-danger'" :role="nasTest.ok ? 'status' : 'alert'">
            <AppIcon :name="nasTest.ok ? 'check' : 'alert'" :size="18" />{{ nasTest.text }}
          </div>
          <div class="actions">
            <button v-if="nas.kind !== 'off'" type="button" class="btn btn-secondary" :disabled="nasTesting" @click="testNas">{{ nasTesting ? t('backups.nas.testing') : t('backups.nas.test') }}</button>
            <button type="submit" class="btn btn-primary" :disabled="nasSaving">{{ nasSaving ? t('app.saving') : t('app.save') }}</button>
          </div>
        </form>
      </section>

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

.nas {
  padding-top: var(--space-4);
  border-top: 1px solid var(--color-border);
}

.nas h3 {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  margin: 0;
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
