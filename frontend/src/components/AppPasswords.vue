<script setup lang="ts">
/**
 * Programs and network drive: an app password per program (WordCraft, DeckCraft, Explorer, Finder …), so files of the
 * spaces open and save directly on the computer. The password is shown once; removing it locks that program out.
 */
import { onMounted, ref } from 'vue'
import AppIcon from './AppIcon.vue'
import BaseModal from './BaseModal.vue'
import FormField from './FormField.vue'
import SyncStatusBadge from './SyncStatusBadge.vue'
import { api } from '@/lib/api'
import { errorText, formatDateTime, locale, t } from '@/lib/i18n'
import { problemText, syncedText } from '@/lib/syncStatus'
import { showToast } from '@/lib/toast'
import type { AppPassword } from '@/lib/types'

interface Created extends AppPassword {
  password: string
  login: string
  drive_url: string
}

const items = ref<AppPassword[]>([])
const name = ref('')
const nameError = ref('')
const busy = ref(false)
const created = ref<Created | null>(null)
const removing = ref<AppPassword | null>(null)

const driveUrl = `${window.location.origin}/dav/`
const windowsDrive = `\\\\${window.location.hostname}${window.location.protocol === 'https:' ? '@SSL' : ''}${window.location.port ? `@${window.location.port}` : ''}\\dav`

async function load() {
  items.value = await api.get<AppPassword[]>('/api/profile/app-passwords').catch(() => [])
}

async function create() {
  nameError.value = name.value.trim() ? '' : t('validation.name_required')
  if (nameError.value) return
  busy.value = true
  try {
    created.value = await api.post<Created>('/api/profile/app-passwords', { name: name.value.trim() })
    name.value = ''
    await load()
  } catch (e) {
    nameError.value = errorText(e)
  } finally {
    busy.value = false
  }
}

async function remove() {
  if (!removing.value) return
  try {
    await api.delete(`/api/profile/app-passwords/${removing.value.id}`)
    showToast(t('programs.removed'))
    removing.value = null
    await load()
  } catch (e) {
    showToast(errorText(e), 'error')
  }
}

async function copy(text: string) {
  try {
    await navigator.clipboard.writeText(text)
    showToast(t('files.copied'))
  } catch {
    window.prompt(t('files.copyThis'), text)
  }
}

onMounted(load)
</script>

<template>
  <section id="programs" class="card stack" aria-labelledby="programs-title">
    <h2 id="programs-title">{{ t('programs.title') }}</h2>
    <p class="muted">{{ t('programs.intro') }}</p>
    <ol class="steps small">
      <li>{{ t('programs.step1') }}</li>
      <li>{{ t('programs.step2') }}</li>
      <li>{{ t('programs.step3') }}</li>
    </ol>
    <dl class="addresses">
      <dt>{{ t('programs.windows') }}</dt>
      <dd><code>{{ windowsDrive }}</code><button type="button" class="btn btn-ghost btn-icon" :aria-label="t('files.copy')" @click="copy(windowsDrive)"><AppIcon name="clipboard" :size="16" /></button></dd>
      <dt>{{ t('programs.other') }}</dt>
      <dd><code>{{ driveUrl }}</code><button type="button" class="btn btn-ghost btn-icon" :aria-label="t('files.copy')" @click="copy(driveUrl)"><AppIcon name="clipboard" :size="16" /></button></dd>
    </dl>

    <form class="new" novalidate @submit.prevent="create">
      <FormField id="ap-name" :label="t('programs.name')" :error="nameError" :hint="t('programs.nameHint')">
        <template #default="{ attrs }"><input v-bind="attrs" v-model="name" class="input" maxlength="80" autocomplete="off" /></template>
      </FormField>
      <button type="submit" class="btn btn-primary" :disabled="busy"><AppIcon name="key" :size="18" />{{ t('programs.create') }}</button>
    </form>

    <ul v-if="items.length" class="list">
      <li v-for="p in items" :key="p.id" class="row">
        <AppIcon name="key" :size="18" />
        <span class="grow">
          <strong>{{ p.name }}</strong>
          <span class="muted small block">{{ p.last_used_at ? t('programs.lastUsed', { when: formatDateTime(p.last_used_at) }) : t('programs.neverUsed') }}</span>
          <span v-if="p.device" class="sync small block">
            <SyncStatusBadge :status="p.device.status" />
            <span>{{ p.device.device_name ? t('syncDevices.folderOn', { device: p.device.device_name }) : t('syncDevices.folder') }}: {{ syncedText(p.device, locale) }}</span>
          </span>
          <span v-if="p.device && problemText(p.device)" class="problem small block">{{ problemText(p.device) }}</span>
        </span>
        <button type="button" class="btn btn-ghost" @click="removing = p">{{ t('programs.remove') }}</button>
      </li>
    </ul>

    <BaseModal :open="created !== null" :title="t('programs.createdTitle')" :description="t('programs.createdText')" hide-actions @close="created = null">
      <dl v-if="created" class="addresses">
        <dt>{{ t('programs.login') }}</dt>
        <dd><code>{{ created.login }}</code><button type="button" class="btn btn-ghost btn-icon" :aria-label="t('files.copy')" @click="copy(created.login)"><AppIcon name="clipboard" :size="16" /></button></dd>
        <dt>{{ t('programs.password') }}</dt>
        <dd><code class="secret">{{ created.password }}</code><button type="button" class="btn btn-ghost btn-icon" :aria-label="t('files.copy')" @click="copy(created.password)"><AppIcon name="clipboard" :size="16" /></button></dd>
        <dt>{{ t('programs.address') }}</dt>
        <dd><code>{{ driveUrl }}</code></dd>
      </dl>
      <button type="button" class="btn btn-primary done" @click="created = null">{{ t('programs.done') }}</button>
    </BaseModal>
    <BaseModal :open="removing !== null" :title="t('programs.removeTitle', { name: removing?.name ?? '' })" :description="t('programs.removeText')" :confirm-label="t('programs.remove')" tone="danger" @close="removing = null" @confirm="remove" />
  </section>
</template>

<style scoped>
.steps {
  display: grid;
  gap: 4px;
  margin: 0;
  padding-left: var(--space-5);
}

.addresses {
  display: grid;
  grid-template-columns: max-content minmax(0, 1fr);
  align-items: center;
  gap: var(--space-2) var(--space-3);
  margin: 0;
}

.addresses dt {
  color: var(--color-text-muted);
  font-size: var(--text-sm);
}

.addresses dd {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  min-width: 0;
  margin: 0;
}

code {
  overflow-wrap: anywhere;
  padding: 4px 8px;
  border-radius: var(--radius-sm);
  background: var(--color-surface-muted);
  font-size: 0.85rem;
}

.secret {
  font-size: 1rem;
  font-weight: 700;
  letter-spacing: 0.04em;
}

.new {
  display: flex;
  flex-wrap: wrap;
  align-items: flex-end;
  gap: var(--space-3);
}

.new > :first-child {
  flex: 1;
  min-width: 220px;
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
}

.block {
  display: block;
}

.sync {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: var(--space-2);
  margin-top: var(--space-1);
}

.problem {
  color: var(--color-warning);
}

.done {
  margin-top: var(--space-4);
}

@media (max-width: 560px) {
  .addresses {
    grid-template-columns: 1fr;
  }
}
</style>
