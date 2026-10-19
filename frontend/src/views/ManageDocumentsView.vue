<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import AppIcon from '@/components/AppIcon.vue'
import PersonalDocumentsPanel from '@/components/admin/PersonalDocumentsPanel.vue'
import BaseModal from '@/components/BaseModal.vue'
import EmptyState from '@/components/EmptyState.vue'
import FormField from '@/components/FormField.vue'
import LoadState from '@/components/LoadState.vue'
import PageHeader from '@/components/PageHeader.vue'
import { api } from '@/lib/api'
import { DOCUMENT_CATEGORIES } from '@/lib/requestTypes'
import { loadConfig, publicConfig } from '@/lib/session'
import { errorText, formatDate, formatFileSize, t } from '@/lib/i18n'
import { showToast } from '@/lib/toast'
import type { OfficeDocument } from '@/lib/types'

const documents = ref<OfficeDocument[]>([])
const loading = ref(true)
const error = ref<string | null>(null)
const showArchived = ref(false)

const editorOpen = ref(false)
const editing = ref<OfficeDocument | null>(null)
const form = reactive({ title: '', category: 'policy', description: '' })
const file = ref<File | null>(null)
const errors = reactive({ title: '', file: '' })
const formError = ref('')
const saving = ref(false)

const archiveTarget = ref<OfficeDocument | null>(null)

const maxUploadMb = computed(() => publicConfig.value?.max_upload_mb ?? 15)
const visible = computed(() => documents.value.filter((d) => showArchived.value || !d.archived))

async function load() {
  loading.value = true
  error.value = null
  try {
    documents.value = await api.get<OfficeDocument[]>('/api/documents?include_archived=true')
  } catch (e) {
    error.value = errorText(e)
  } finally {
    loading.value = false
  }
}

function openEditor(doc: OfficeDocument | null) {
  editing.value = doc
  Object.assign(form, doc ? { title: doc.title, category: doc.category, description: doc.description } : { title: '', category: 'policy', description: '' })
  file.value = null
  errors.title = errors.file = formError.value = ''
  editorOpen.value = true
}

function onFile(event: Event) {
  file.value = (event.target as HTMLInputElement).files?.[0] ?? null
  errors.file = ''
  // Suggest a title from the file name for new uploads.
  if (file.value && !form.title && !editing.value) form.title = file.value.name.replace(/\.[^.]+$/, '').replace(/[-_]+/g, ' ')
}

async function save() {
  errors.title = form.title.trim() ? '' : t('validation.title_required')
  errors.file = !editing.value && !file.value ? t('validation.file_required') : file.value && file.value.size > maxUploadMb.value * 1024 * 1024 ? t('validation.file_too_large') : ''
  if (errors.title || errors.file) return
  saving.value = true
  formError.value = ''
  try {
    if (editing.value) {
      await api.patch(`/api/documents/${editing.value.id}`, { title: form.title.trim(), category: form.category, description: form.description.trim() })
      if (file.value) {
        const data = new FormData()
        data.append('file', file.value)
        await api.post(`/api/documents/${editing.value.id}/file`, data)
      }
      showToast(t('manageDocs.saved'))
    } else {
      const data = new FormData()
      data.append('file', file.value!)
      data.append('title', form.title.trim())
      data.append('category', form.category)
      data.append('description', form.description.trim())
      await api.post('/api/documents', data)
      showToast(t('manageDocs.uploaded'))
    }
    editorOpen.value = false
    await load()
  } catch (e) {
    formError.value = errorText(e)
  } finally {
    saving.value = false
  }
}

async function setArchived(doc: OfficeDocument, archived: boolean) {
  saving.value = true
  try {
    await api.patch(`/api/documents/${doc.id}`, { archived })
    showToast(archived ? t('manageDocs.archivedToast') : t('manageDocs.restoredToast'))
    archiveTarget.value = null
    await load()
  } catch (e) {
    showToast(errorText(e), 'error')
  } finally {
    saving.value = false
  }
}

onMounted(() => {
  loadConfig()
  load()
})
</script>

<template>
  <div class="page">
    <PageHeader :title="t('manageDocs.title')" :subtitle="t('manageDocs.subtitle')">
      <template #actions>
        <button type="button" class="btn btn-primary" @click="openEditor(null)"><AppIcon name="upload" />{{ t('manageDocs.upload') }}</button>
      </template>
    </PageHeader>

    <label class="checkbox">
      <input v-model="showArchived" type="checkbox" />
      <span>{{ t('manageDocs.showArchived') }}</span>
    </label>

    <LoadState :loading="loading" :error="error" @retry="load">
      <section class="card card-flush">
        <div v-if="visible.length" class="table-wrap">
          <table class="table">
            <thead>
              <tr>
                <th scope="col">{{ t('manageDocs.titleLabel') }}</th>
                <th scope="col">{{ t('documents.category') }}</th>
                <th scope="col">{{ t('manageDocs.file') }}</th>
                <th scope="col">{{ t('detail.updated') }}</th>
                <th scope="col"><span class="visually-hidden">{{ t('app.edit') }}</span></th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="doc in visible" :key="doc.id" :class="{ archived: doc.archived }">
                <td>
                  <RouterLink :to="`/documents/${doc.id}`" class="doc-title">{{ doc.title }}</RouterLink>
                  <span v-if="doc.archived" class="archived-tag">{{ t('manageDocs.archived') }}</span>
                </td>
                <td>{{ t(`documents.categories.${doc.category}`) }}</td>
                <td class="muted">{{ doc.file_type.toUpperCase() }} · {{ formatFileSize(doc.file_size) }}</td>
                <td class="muted">{{ formatDate(doc.updated_at) }}</td>
                <td class="actions">
                  <button type="button" class="btn btn-ghost" @click="openEditor(doc)">{{ t('app.edit') }}</button>
                  <button v-if="!doc.archived" type="button" class="btn btn-ghost" @click="archiveTarget = doc">{{ t('manageDocs.archive') }}</button>
                  <button v-else type="button" class="btn btn-ghost" :disabled="saving" @click="setArchived(doc, false)">{{ t('manageDocs.restore') }}</button>
                </td>
              </tr>
            </tbody>
          </table>
        </div>
        <EmptyState v-else icon="folder" :message="t('manageDocs.empty')" :action-label="t('manageDocs.upload')" @action="openEditor(null)" />
      </section>
    </LoadState>

    <BaseModal
      :open="editorOpen"
      :title="editing ? t('manageDocs.editTitle') : t('manageDocs.uploadTitle')"
      :confirm-label="editing ? t('app.save') : t('manageDocs.upload')"
      :busy="saving"
      wide
      @close="editorOpen = false"
      @confirm="save"
    >
      <form class="stack" novalidate @submit.prevent="save">
        <div v-if="formError" class="notice notice-danger small" role="alert">{{ formError }}</div>
        <FormField
          id="doc-file"
          :label="editing ? t('manageDocs.replaceFile') : t('manageDocs.file')"
          :hint="editing ? t('manageDocs.replaceHint') : t('manageDocs.fileHint', { size: maxUploadMb })"
          :error="errors.file"
        >
          <template #default="{ attrs }">
            <input v-bind="attrs" type="file" class="file-input" accept=".pdf,.md,.txt,.docx" @change="onFile" />
          </template>
        </FormField>
        <FormField id="doc-title" :label="t('manageDocs.titleLabel')" :error="errors.title">
          <template #default="{ attrs }"><input v-bind="attrs" v-model="form.title" class="input" maxlength="150" /></template>
        </FormField>
        <FormField id="doc-category" :label="t('documents.category')">
          <template #default="{ attrs }">
            <select v-bind="attrs" v-model="form.category" class="select">
              <option v-for="c in DOCUMENT_CATEGORIES" :key="c" :value="c">{{ t(`documents.categories.${c}`) }}</option>
            </select>
          </template>
        </FormField>
        <FormField id="doc-description" :label="t('manageDocs.description')" optional>
          <template #default="{ attrs }"><textarea v-bind="attrs" v-model="form.description" class="textarea" rows="2" maxlength="1000" /></template>
        </FormField>
      </form>
    </BaseModal>

    <BaseModal
      :open="archiveTarget !== null"
      :title="t('manageDocs.archiveTitle')"
      :description="t('manageDocs.archiveText', { title: archiveTarget?.title ?? '' })"
      :confirm-label="t('manageDocs.archive')"
      tone="danger"
      :busy="saving"
      @close="archiveTarget = null"
      @confirm="archiveTarget && setArchived(archiveTarget, true)"
    />

    <PersonalDocumentsPanel />
  </div>
</template>

<style scoped>
.doc-title {
  font-weight: 600;
}

.archived td {
  color: var(--color-text-muted);
}

.archived-tag {
  margin-left: var(--space-2);
  padding: 1px 8px;
  border-radius: 999px;
  background: var(--color-neutral-soft);
  font-size: var(--text-xs);
  font-weight: 600;
}

.actions {
  text-align: right;
  white-space: nowrap;
}

.file-input {
  min-height: var(--touch);
  font: inherit;
  font-size: var(--text-sm);
  max-width: 100%;
}
</style>
