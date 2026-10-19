<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import AppIcon from '@/components/AppIcon.vue'
import EmptyState from '@/components/EmptyState.vue'
import LoadState from '@/components/LoadState.vue'
import PageHeader from '@/components/PageHeader.vue'
import SectionContact from '@/components/SectionContact.vue'
import { api, query } from '@/lib/api'
import { DOCUMENT_CATEGORIES } from '@/lib/requestTypes'
import { errorText, formatDate, formatFileSize, t } from '@/lib/i18n'
import { refreshSummary, summary } from '@/lib/summary'
import type { OfficeDocument, PersonalDocument } from '@/lib/types'

const route = useRoute()
const router = useRouter()

const tab = ref<'all' | 'mine'>(route.query.tab === 'mine' ? 'mine' : 'all')
const personal = ref<PersonalDocument[]>([])
const personalLoading = ref(false)

async function loadPersonal() {
  personalLoading.value = true
  try {
    personal.value = await api.get<PersonalDocument[]>('/api/personal-documents')
  } catch (e) {
    error.value = errorText(e)
  } finally {
    personalLoading.value = false
  }
}

function opened(doc: PersonalDocument) {
  // The download marks it as opened on the server; update the list and badges shortly after.
  window.setTimeout(() => {
    loadPersonal()
    refreshSummary(true)
  }, 800)
  if (!doc.opened_at) doc.opened_at = new Date().toISOString()
}

watch(tab, (value) => {
  router.replace({ query: value === 'mine' ? { tab: 'mine' } : {} })
  if (value === 'mine') loadPersonal()
})

const search = ref(typeof route.query.q === 'string' ? route.query.q : '')
const category = ref(typeof route.query.category === 'string' ? route.query.category : '')
const sort = ref(route.query.sort === 'updated' ? 'updated' : 'title')
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
    const result = await api.get<OfficeDocument[]>(`/api/documents${query({ q: search.value.trim(), category: category.value, sort: sort.value })}`)
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

watch([search, category, sort], () => {
  if (tab.value === 'mine') return
  router.replace({
    query: {
      ...(search.value ? { q: search.value } : {}),
      ...(category.value ? { category: category.value } : {}),
      ...(sort.value !== 'title' ? { sort: sort.value } : {}),
    },
  })
  window.clearTimeout(timer)
  timer = window.setTimeout(load, 250)
})

onMounted(() => {
  load()
  if (tab.value === 'mine') loadPersonal()
})
</script>

<template>
  <div class="page">
    <PageHeader :title="t('documents.title')" :subtitle="t('documents.subtitle')" />

    <div class="segmented" role="group" :aria-label="t('documents.title')">
      <button type="button" :aria-pressed="tab === 'all'" @click="tab = 'all'">{{ t('documents.tabAll') }}</button>
      <button type="button" :aria-pressed="tab === 'mine'" @click="tab = 'mine'">
        {{ t('documents.tabMine') }}
        <span v-if="summary.personal_documents_new" class="count-badge">{{ summary.personal_documents_new }}<span class="visually-hidden"> {{ t('personalDocs.new') }}</span></span>
      </button>
    </div>

    <template v-if="tab === 'mine'">
      <p class="notice notice-info small"><AppIcon name="shield" :size="18" />{{ t('personalDocs.privacy') }}</p>
      <LoadState :loading="personalLoading && !personal.length" :error="null">
        <section v-if="personal.length" class="card card-flush">
          <ul class="list">
            <li v-for="doc in personal" :key="doc.id" class="doc">
              <a :href="`/api/personal-documents/${doc.id}/download`" class="list-link doc-link" @click="opened(doc)">
                <span class="doc-icon"><AppIcon name="file" /></span>
                <span class="doc-main">
                  <span class="doc-title">
                    {{ doc.title }}
                    <span v-if="!doc.opened_at" class="new-tag">{{ t('personalDocs.new') }}</span>
                  </span>
                  <span class="muted small">{{ formatDate(doc.created_at) }} · {{ doc.file_type.toUpperCase() }} · {{ formatFileSize(doc.file_size) }} · {{ t('personalDocs.from', { name: doc.uploaded_by.full_name }) }}</span>
                </span>
                <AppIcon name="download" class="download" />
              </a>
            </li>
          </ul>
        </section>
        <section v-else class="card"><EmptyState icon="file" :message="t('personalDocs.empty')" /></section>
      </LoadState>
    </template>

    <div v-else class="filters" role="search">
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
      <div>
        <label for="doc-sort" class="visually-hidden">{{ t('documents.sort') }}</label>
        <select id="doc-sort" v-model="sort" class="select">
          <option value="title">{{ t('documents.sortTitle') }}</option>
          <option value="updated">{{ t('documents.sortUpdated') }}</option>
        </select>
      </div>
    </div>

    <LoadState v-if="tab === 'all'" :loading="loading" :error="error" @retry="load">
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

    <SectionContact section="documents" />
  </div>
</template>

<style scoped>
.filters {
  display: grid;
  gap: var(--space-3);
  grid-template-columns: minmax(0, 1fr) minmax(180px, 240px) minmax(160px, 200px);
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

.segmented button {
  display: inline-flex;
  align-items: center;
  gap: var(--space-2);
}

.notice .icon {
  flex-shrink: 0;
}

.new-tag {
  margin-left: var(--space-2);
  padding: 1px 8px;
  border-radius: var(--radius-full);
  background: var(--color-primary-soft);
  color: var(--color-primary-text);
  font-size: var(--text-xs);
  font-weight: 700;
}

@media (max-width: 640px) {
  .filters {
    grid-template-columns: 1fr;
  }
}
</style>
