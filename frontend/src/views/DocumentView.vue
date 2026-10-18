<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import AppIcon from '@/components/AppIcon.vue'
import LoadState from '@/components/LoadState.vue'
import PageHeader from '@/components/PageHeader.vue'
import { api } from '@/lib/api'
import { renderMarkdown } from '@/lib/markdown'
import { errorText, formatDate, formatFileSize, t } from '@/lib/i18n'
import type { OfficeDocument } from '@/lib/types'

const props = defineProps<{ id: string }>()

const doc = ref<OfficeDocument | null>(null)
const content = ref<{ format: 'md' | 'txt'; text: string } | null>(null)
const loading = ref(true)
const error = ref<string | null>(null)

// renderMarkdown escapes all HTML in the document before adding its own tags.
const html = computed(() => (content.value?.format === 'md' ? renderMarkdown(content.value.text) : ''))

async function load() {
  loading.value = true
  error.value = null
  try {
    doc.value = await api.get<OfficeDocument>(`/api/documents/${props.id}`)
    content.value = doc.value.file_type === 'md' || doc.value.file_type === 'txt' ? await api.get(`/api/documents/${props.id}/content`) : null
  } catch (e) {
    error.value = errorText(e)
  } finally {
    loading.value = false
  }
}

onMounted(load)
</script>

<template>
  <div class="page doc-page">
    <LoadState :loading="loading" :error="error" @retry="load">
      <template v-if="doc">
        <PageHeader :title="doc.title" :subtitle="doc.description" back-to="/documents">
          <template #actions>
            <a v-if="doc.file_type === 'pdf'" :href="`/api/documents/${doc.id}/download?inline=true`" target="_blank" rel="noopener" class="btn btn-primary">
              <AppIcon name="file" />{{ t('documents.openPdf') }}
            </a>
            <a :href="`/api/documents/${doc.id}/download`" class="btn btn-secondary"><AppIcon name="download" />{{ t('documents.download') }}</a>
          </template>
        </PageHeader>

        <p class="muted small">
          {{ t(`documents.categories.${doc.category}`) }} ·
          {{ t('documents.fileInfo', { type: doc.file_type.toUpperCase(), size: formatFileSize(doc.file_size) }) }} ·
          {{ t('documents.updated', { date: formatDate(doc.updated_at) }) }}
        </p>

        <article v-if="content?.format === 'md'" class="card prose" v-html="html" />
        <article v-else-if="content?.format === 'txt'" class="card prose prewrap">{{ content.text }}</article>
        <div v-else class="notice notice-info">
          <AppIcon name="info" />
          <p>{{ t('documents.downloadOnly') }}</p>
        </div>
      </template>
    </LoadState>
  </div>
</template>

<style scoped>
.doc-page {
  max-width: 860px;
}

.prose {
  padding: var(--space-6);
  line-height: 1.7;
  overflow-wrap: anywhere;
}

.prose :deep(h2),
.prose :deep(h3),
.prose :deep(h4) {
  margin: var(--space-5) 0 var(--space-2);
}

.prose :deep(h2:first-child) {
  margin-top: 0;
}

.prose :deep(p),
.prose :deep(ul),
.prose :deep(ol) {
  margin: 0 0 var(--space-3);
}

.prose :deep(code) {
  padding: 1px 6px;
  border-radius: 4px;
  background: var(--color-neutral-soft);
  font-size: 0.92em;
}

@media (max-width: 640px) {
  .prose {
    padding: var(--space-4);
  }
}
</style>
