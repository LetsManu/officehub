<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import AppIcon from '@/components/AppIcon.vue'
import EmptyState from '@/components/EmptyState.vue'
import LoadState from '@/components/LoadState.vue'
import PageHeader from '@/components/PageHeader.vue'
import { api, query } from '@/lib/api'
import { DOCUMENT_CATEGORIES } from '@/lib/requestTypes'
import { errorText, formatDate, formatFileSize, t } from '@/lib/i18n'
import type { OfficeDocument } from '@/lib/types'

const route = useRoute()
const router = useRouter()

const search = ref(typeof route.query.q === 'string' ? route.query.q : '')
const category = ref(typeof route.query.category === 'string' ? route.query.category : '')
const documents = ref<OfficeDocument[]>([])
const loading = ref(true)
const error = ref<string | null>(null)
const hasAny = ref(true)

let timer: number | undefined
let requestNumber = 0

const resultLabel = computed(() => (documents.value.length === 1 ? t('documents.resultsOne') : t('documents.results', { count: documents.value.length })))
/** Splits a snippet into plain and matching parts so the search term can be highlighted safely. */
function highlight(text: string): { text: string; match: boolean }[] {
  const term = search.value.trim()
  if (!term) return [{ text, match: false }]
  const escaped = term.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
  return text
    .split(new RegExp(`(${escaped})`, 'gi'))
    .filter(Boolean)
    .map((part) => ({ text: part, match: part.toLowerCase() === term.toLowerCase() }))
}

const filtered = computed(() => Boolean(search.value.trim() || category.value))

async function load() {
  const current = ++requestNumber
  loading.value = documents.value.length === 0
  error.value = null
  try {
    const result = await api.get<OfficeDocument[]>(`/api/documents${query({ q: search.value.trim(), category: category.value })}`)
    if (current !== requestNumber) return // a newer search is already running
    documents.value = result
    if (!filtered.value) hasAny.value = result.length > 0
  } catch (e) {
    error.value = errorText(e)
  } finally {
    if (current === requestNumber) loading.value = false
  }
}

function clearFilters() {
  search.value = ''
  category.value = ''
}

watch([search, category], () => {
  router.replace({ query: { ...(search.value ? { q: search.value } : {}), ...(category.value ? { category: category.value } : {}) } })
  window.clearTimeout(timer)
  timer = window.setTimeout(load, 250)
})

onMounted(load)
</script>

<template>
  <div class="page">
    <PageHeader :title="t('documents.title')" :subtitle="t('documents.subtitle')" />

    <div class="filters" role="search">
      <div class="search-box">
        <label for="doc-search" class="visually-hidden">{{ t('documents.search') }}</label>
        <AppIcon name="search" class="search-icon" />
        <input id="doc-search" v-model="search" class="input" type="search" :placeholder="t('documents.searchPlaceholder')" autocomplete="off" />
      </div>
      <div>
        <label for="doc-category" class="visually-hidden">{{ t('documents.category') }}</label>
        <select id="doc-category" v-model="category" class="select">
          <option value="">{{ t('documents.allCategories') }}</option>
          <option v-for="c in DOCUMENT_CATEGORIES" :key="c" :value="c">{{ t(`documents.categories.${c}`) }}</option>
        </select>
      </div>
    </div>

    <LoadState :loading="loading" :error="error" @retry="load">
      <section v-if="documents.length" class="card card-flush">
        <p class="result-count muted small" aria-live="polite">{{ resultLabel }}</p>
        <ul class="list">
          <li v-for="doc in documents" :key="doc.id" class="doc">
            <RouterLink :to="`/documents/${doc.id}`" class="list-link doc-link">
              <span class="doc-icon"><AppIcon name="file" /></span>
              <span class="doc-main">
                <span class="doc-title">{{ doc.title }}</span>
                <span v-if="doc.snippet" class="snippet">
                  <template v-for="(part, i) in highlight(doc.snippet)" :key="i"><mark v-if="part.match">{{ part.text }}</mark><template v-else>{{ part.text }}</template></template>
                </span>
                <span v-else-if="doc.description" class="muted small">{{ doc.description }}</span>
                <span class="muted small">
                  {{ t(`documents.categories.${doc.category}`) }} · {{ doc.file_type.toUpperCase() }} · {{ t('documents.updated', { date: formatDate(doc.updated_at) }) }}
                </span>
              </span>
            </RouterLink>
            <a class="btn btn-ghost btn-icon download" :href="`/api/documents/${doc.id}/download`" :aria-label="`${t('documents.download')}: ${doc.title} (${formatFileSize(doc.file_size)})`">
              <AppIcon name="download" />
            </a>
          </li>
        </ul>
      </section>
      <section v-else class="card">
        <EmptyState
          v-if="filtered || hasAny"
          icon="search"
          :message="t('documents.noResults', { query: search || t(`documents.categories.${category}`) })"
          :action-label="t('documents.clearSearch')"
          @action="clearFilters"
        />
        <EmptyState v-else icon="file" :message="t('documents.empty')" />
      </section>
    </LoadState>
  </div>
</template>

<style scoped>
.filters {
  display: grid;
  gap: var(--space-3);
  grid-template-columns: minmax(0, 1fr) minmax(180px, 240px);
}

.search-box {
  position: relative;
}

.search-box .input {
  padding-left: 42px;
}

.search-icon {
  position: absolute;
  left: 13px;
  top: 50%;
  transform: translateY(-50%);
  color: var(--color-text-muted);
  pointer-events: none;
}

.result-count {
  padding: var(--space-3) var(--space-5);
  border-bottom: 1px solid var(--color-border);
}

.doc {
  display: flex;
  align-items: center;
  padding-right: var(--space-3);
}

.doc-link {
  flex: 1;
  min-width: 0;
}

.doc-icon {
  display: grid;
  place-items: center;
  width: 40px;
  height: 40px;
  border-radius: var(--radius-md);
  background: var(--color-neutral-soft);
  color: var(--color-text-muted);
  flex-shrink: 0;
}

.doc-main {
  display: grid;
  gap: 2px;
  min-width: 0;
}

.doc-title {
  font-weight: 600;
}

.snippet {
  font-size: var(--text-sm);
  color: var(--color-text);
  font-style: italic;
}

.snippet mark {
  padding: 0 2px;
  border-radius: 3px;
  background: var(--color-warning-soft);
  color: inherit;
  font-weight: 600;
  font-style: normal;
}

.download {
  color: var(--color-text-muted);
}

@media (max-width: 640px) {
  .filters {
    grid-template-columns: 1fr;
  }
}
</style>
