<script setup lang="ts">
/** HR: share a file with exactly one person (payslip, contract, certificate). */
import { computed, onMounted, reactive, ref, watch } from 'vue'
import AppIcon from '../AppIcon.vue'
import BaseModal from '../BaseModal.vue'
import EmptyState from '../EmptyState.vue'
import FormField from '../FormField.vue'
import { api } from '@/lib/api'
import { errorText, formatDate, formatFileSize, t } from '@/lib/i18n'
import { publicConfig } from '@/lib/session'
import { showToast } from '@/lib/toast'
import type { PersonalDocument, User } from '@/lib/types'

const people = ref<User[]>([])
const personId = ref<number | null>(null)
const docs = ref<PersonalDocument[]>([])
const uploadOpen = ref(false)
const form = reactive({ title: '' })
const file = ref<File | null>(null)
const errors = reactive({ title: '', file: '' })
const formError = ref('')
const saving = ref(false)
const deleteTarget = ref<PersonalDocument | null>(null)

const maxUploadMb = computed(() => publicConfig.value?.max_upload_mb ?? 15)
const person = computed(() => people.value.find((p) => p.id === personId.value))

async function loadDocs() {
  if (!personId.value) return
  docs.value = await api.get<PersonalDocument[]>(`/api/personal-documents?person_id=${personId.value}`)
}

function onFile(event: Event) {
  file.value = (event.target as HTMLInputElement).files?.[0] ?? null
  errors.file = ''
  if (file.value && !form.title) form.title = file.value.name.replace(/\.[^.]+$/, '').replace(/[-_]+/g, ' ')
}

function openUpload() {
  form.title = ''
  file.value = null
  errors.title = errors.file = formError.value = ''
  uploadOpen.value = true
}

async function upload() {
  errors.title = form.title.trim() ? '' : t('validation.title_required')
  errors.file = !file.value ? t('validation.file_required') : file.value.size > maxUploadMb.value * 1024 * 1024 ? t('validation.file_too_large') : ''
  if (errors.title || errors.file || !personId.value) return
  saving.value = true
  formError.value = ''
  try {
    const data = new FormData()
    data.append('file', file.value!)
    data.append('title', form.title.trim())
    data.append('person_id', String(personId.value))
    await api.post('/api/personal-documents', data)
    uploadOpen.value = false
    showToast(t('personalDocs.sent', { name: person.value?.full_name ?? '' }))
    await loadDocs()
  } catch (e) {
    formError.value = errorText(e)
  } finally {
    saving.value = false
  }
}

async function remove() {
  if (!deleteTarget.value) return
  saving.value = true
  try {
    await api.delete(`/api/personal-documents/${deleteTarget.value.id}`)
    deleteTarget.value = null
    showToast(t('personalDocs.deleted'))
    await loadDocs()
  } catch (e) {
    showToast(errorText(e), 'error')
  } finally {
    saving.value = false
  }
}

watch(personId, () => loadDocs().catch((e) => showToast(errorText(e), 'error')))

onMounted(async () => {
  people.value = (await api.get<User[]>('/api/admin/users')).filter((p) => p.is_active)
})
</script>

<template>
  <section class="card stack" aria-labelledby="personal-title">
    <div class="row-between">
      <div class="stack-sm">
        <h2 id="personal-title">{{ t('personalDocs.adminTitle') }}</h2>
        <p class="muted small">{{ t('personalDocs.adminHint') }}</p>
      </div>
      <button type="button" class="btn btn-primary" :disabled="!personId" @click="openUpload"><AppIcon name="upload" />{{ t('personalDocs.send') }}</button>
    </div>
    <div class="person-pick">
      <label for="personal-person" class="label">{{ t('personalDocs.person') }}</label>
      <select id="personal-person" v-model="personId" class="select">
        <option :value="null" disabled>{{ t('personalDocs.choosePerson') }}</option>
        <option v-for="p in people" :key="p.id" :value="p.id">{{ p.full_name }} · {{ p.department }}</option>
      </select>
    </div>
    <template v-if="personId">
      <ul v-if="docs.length" class="list docs">
        <li v-for="doc in docs" :key="doc.id" class="doc">
          <span class="grow">
            <span class="doc-title">{{ doc.title }}</span><br />
            <span class="muted small">
              {{ formatDate(doc.created_at) }} · {{ formatFileSize(doc.file_size) }} ·
              {{ doc.opened_at ? t('personalDocs.openedOn', { date: formatDate(doc.opened_at) }) : t('personalDocs.notOpened') }}
            </span>
          </span>
          <button type="button" class="btn btn-ghost btn-icon" :aria-label="`${t('personalDocs.delete')}: ${doc.title}`" @click="deleteTarget = doc">
            <AppIcon name="trash" />
          </button>
        </li>
      </ul>
      <EmptyState v-else icon="file" :message="t('personalDocs.noneForPerson')" />
    </template>

    <BaseModal
      :open="uploadOpen"
      :title="t('personalDocs.sendTo', { name: person?.full_name ?? '' })"
      :description="t('personalDocs.sendHint')"
      :confirm-label="t('personalDocs.send')"
      :busy="saving"
      @close="uploadOpen = false"
      @confirm="upload"
    >
      <form class="stack" novalidate @submit.prevent="upload">
        <div v-if="formError" class="notice notice-danger small" role="alert">{{ formError }}</div>
        <FormField id="pd-file" :label="t('manageDocs.file')" :hint="t('personalDocs.fileHint', { size: maxUploadMb })" :error="errors.file">
          <template #default="{ attrs }">
            <input v-bind="attrs" type="file" class="file-input" accept=".pdf,.png,.jpg,.jpeg,.docx,.txt" @change="onFile" />
          </template>
        </FormField>
        <FormField id="pd-title" :label="t('manageDocs.titleLabel')" :error="errors.title">
          <template #default="{ attrs }"><input v-bind="attrs" v-model="form.title" class="input" maxlength="150" /></template>
        </FormField>
      </form>
    </BaseModal>

    <BaseModal
      :open="deleteTarget !== null"
      :title="t('personalDocs.deleteTitle')"
      :description="t('personalDocs.deleteText', { title: deleteTarget?.title ?? '' })"
      :confirm-label="t('personalDocs.delete')"
      tone="danger"
      :busy="saving"
      @close="deleteTarget = null"
      @confirm="remove"
    />
  </section>
</template>

<style scoped>
.person-pick {
  display: grid;
  gap: 6px;
  max-width: 420px;
}

.label {
  font-weight: 600;
  font-size: var(--text-sm);
}

.docs {
  border: 1px solid var(--color-border);
  border-radius: var(--radius-md);
}

.doc {
  display: flex;
  align-items: center;
  gap: var(--space-3);
  padding: var(--space-2) var(--space-2) var(--space-2) var(--space-4);
}

.doc-title {
  font-weight: 600;
}

.grow {
  flex: 1;
}

.file-input {
  font: inherit;
}
</style>
