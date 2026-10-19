<script setup lang="ts">
import { computed, onMounted, reactive, ref, watch } from 'vue'
import AppIcon from '@/components/AppIcon.vue'
import BaseModal from '@/components/BaseModal.vue'
import EmptyState from '@/components/EmptyState.vue'
import FormField from '@/components/FormField.vue'
import LoadState from '@/components/LoadState.vue'
import PageHeader from '@/components/PageHeader.vue'
import SectionContact from '@/components/SectionContact.vue'
import { api, query } from '@/lib/api'
import { errorText, t } from '@/lib/i18n'
import { renderMarkdown } from '@/lib/markdown'
import { isAdmin } from '@/lib/session'
import { showToast } from '@/lib/toast'
import type { HelpArticle } from '@/lib/types'

const SECTIONS = ['general', 'requests', 'documents', 'announcements', 'directory', 'rooms', 'visitors', 'dashboard'] as const
const VOTED_KEY = 'officehub.helpVotes'

const articles = ref<HelpArticle[]>([])
const search = ref('')
const section = ref('')
const loading = ref(true)
const error = ref<string | null>(null)
const voted = ref<number[]>(readVoted())

const editorOpen = ref(false)
const editing = ref<HelpArticle | null>(null)
const form = reactive({ section: 'general', question: '', answer: '', sort_order: 0, active: true })
const errors = reactive({ question: '', answer: '' })
const formError = ref('')
const saving = ref(false)
const deleteTarget = ref<HelpArticle | null>(null)

let timer: number | undefined

function readVoted(): number[] {
  try {
    const value = JSON.parse(localStorage.getItem(VOTED_KEY) ?? '[]')
    return Array.isArray(value) ? value.filter((v) => typeof v === 'number') : []
  } catch {
    return []
  }
}

/** Sections that have articles, in a fixed order. */
const grouped = computed(() =>
  SECTIONS.map((key) => ({ key, items: articles.value.filter((a) => a.section === key) })).filter((group) => group.items.length),
)

async function load() {
  loading.value = articles.value.length === 0
  error.value = null
  try {
    articles.value = await api.get<HelpArticle[]>(
      `/api/help${query({ q: search.value.trim(), section: section.value, include_inactive: isAdmin.value ? 'true' : '' })}`,
    )
  } catch (e) {
    error.value = errorText(e)
  } finally {
    loading.value = false
  }
}

async function feedback(article: HelpArticle, helpful: boolean) {
  try {
    const updated = await api.post<HelpArticle>(`/api/help/${article.id}/feedback`, { helpful })
    articles.value = articles.value.map((a) => (a.id === updated.id ? updated : a))
    voted.value = [...voted.value, article.id]
    try {
      localStorage.setItem(VOTED_KEY, JSON.stringify(voted.value.slice(-200)))
    } catch {
      /* not remembered */
    }
    showToast(t('help.thanks'))
  } catch (e) {
    showToast(errorText(e), 'error')
  }
}

function openEditor(article: HelpArticle | null) {
  editing.value = article
  Object.assign(form, article
    ? { section: article.section, question: article.question, answer: article.answer, sort_order: article.sort_order, active: article.active }
    : { section: section.value || 'general', question: '', answer: '', sort_order: 0, active: true })
  errors.question = errors.answer = formError.value = ''
  editorOpen.value = true
}

async function save() {
  errors.question = form.question.trim() ? '' : t('validation.question_required')
  errors.answer = form.answer.trim() ? '' : t('validation.answer_required')
  if (errors.question || errors.answer) return
  saving.value = true
  formError.value = ''
  try {
    const body = { ...form, question: form.question.trim(), answer: form.answer.trim() }
    if (editing.value) await api.put(`/api/help/${editing.value.id}`, body)
    else await api.post('/api/help', body)
    editorOpen.value = false
    showToast(t('help.saved'))
    await load()
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
    await api.delete(`/api/help/${deleteTarget.value.id}`)
    deleteTarget.value = null
    showToast(t('help.deleted'))
    await load()
  } catch (e) {
    showToast(errorText(e), 'error')
  } finally {
    saving.value = false
  }
}

watch([search, section], () => {
  window.clearTimeout(timer)
  timer = window.setTimeout(load, 250)
})

onMounted(load)
</script>

<template>
  <div class="page help-page">
    <PageHeader :title="t('help.title')" :subtitle="t('help.subtitle')">
      <template v-if="isAdmin" #actions>
        <button type="button" class="btn btn-primary" @click="openEditor(null)"><AppIcon name="plus" />{{ t('help.new') }}</button>
      </template>
    </PageHeader>

    <div class="filters" role="search">
      <div class="search-box">
        <label for="help-search" class="visually-hidden">{{ t('help.search') }}</label>
        <AppIcon name="search" class="search-icon" />
        <input id="help-search" v-model="search" class="input" type="search" :placeholder="t('help.searchPlaceholder')" autocomplete="off" />
      </div>
      <div>
        <label for="help-section" class="visually-hidden">{{ t('help.section') }}</label>
        <select id="help-section" v-model="section" class="select">
          <option value="">{{ t('help.allSections') }}</option>
          <option v-for="s in SECTIONS" :key="s" :value="s">{{ t(`help.sections.${s}`) }}</option>
        </select>
      </div>
    </div>

    <LoadState :loading="loading" :error="error" @retry="load">
      <template v-if="grouped.length">
        <section v-for="group in grouped" :key="group.key" class="stack-sm" :aria-labelledby="`help-${group.key}`">
          <h2 :id="`help-${group.key}`" class="group-title">{{ t(`help.sections.${group.key}`) }}</h2>
          <details v-for="article in group.items" :key="article.id" class="disclosure article" :class="{ inactive: !article.active }">
            <summary>
              <span>
                {{ article.question }}
                <span v-if="!article.active" class="muted small"> · {{ t('help.hidden') }}</span>
              </span>
            </summary>
            <div class="disclosure-body stack">
              <!-- renderMarkdown escapes all HTML before adding its own tags -->
              <div class="prose" v-html="renderMarkdown(article.answer)" />
              <div class="row-between feedback">
                <p v-if="voted.includes(article.id)" class="muted small"><AppIcon name="check" :size="16" />{{ t('help.thanks') }}</p>
                <div v-else class="row" role="group" :aria-label="t('help.helpful')">
                  <span class="small">{{ t('help.helpful') }}</span>
                  <button type="button" class="btn btn-secondary" @click="feedback(article, true)">{{ t('app.yes') }}</button>
                  <button type="button" class="btn btn-secondary" @click="feedback(article, false)">{{ t('app.no') }}</button>
                </div>
                <div v-if="isAdmin" class="row admin-row">
                  <span class="muted small">{{ t('help.counts', { yes: article.helpful_yes, no: article.helpful_no }) }}</span>
                  <button type="button" class="btn btn-ghost" @click="openEditor(article)">{{ t('app.edit') }}</button>
                  <button type="button" class="btn btn-ghost danger-text" @click="deleteTarget = article">{{ t('help.delete') }}</button>
                </div>
              </div>
            </div>
          </details>
        </section>
      </template>
      <section v-else class="card">
        <EmptyState icon="lifebuoy" :message="search || section ? t('help.noResults') : t('help.empty')" />
      </section>
    </LoadState>

    <section class="card ask">
      <AppIcon name="message" />
      <div class="stack-sm">
        <h2>{{ t('help.notFoundTitle') }}</h2>
        <p class="muted">{{ t('help.notFoundText') }}</p>
      </div>
    </section>
    <SectionContact :section="section && section !== 'general' ? section : 'dashboard'" />

    <BaseModal
      :open="editorOpen"
      :title="editing ? t('help.editTitle') : t('help.newTitle')"
      :confirm-label="t('app.save')"
      :busy="saving"
      wide
      @close="editorOpen = false"
      @confirm="save"
    >
      <form class="stack" novalidate @submit.prevent="save">
        <div v-if="formError" class="notice notice-danger small" role="alert">{{ formError }}</div>
        <FormField id="h-section" :label="t('help.section')">
          <template #default="{ attrs }">
            <select v-bind="attrs" v-model="form.section" class="select">
              <option v-for="s in SECTIONS" :key="s" :value="s">{{ t(`help.sections.${s}`) }}</option>
            </select>
          </template>
        </FormField>
        <FormField id="h-question" :label="t('help.question')" :error="errors.question">
          <template #default="{ attrs }"><input v-bind="attrs" v-model="form.question" class="input" maxlength="200" /></template>
        </FormField>
        <FormField id="h-answer" :label="t('help.answer')" :hint="t('help.answerHint')" :error="errors.answer">
          <template #default="{ attrs }"><textarea v-bind="attrs" v-model="form.answer" class="textarea" rows="6" maxlength="10000" /></template>
        </FormField>
        <label class="checkbox"><input v-model="form.active" type="checkbox" /><span>{{ t('help.visible') }}</span></label>
      </form>
    </BaseModal>

    <BaseModal
      :open="deleteTarget !== null"
      :title="t('help.deleteTitle')"
      :description="deleteTarget?.question ?? ''"
      :confirm-label="t('help.delete')"
      tone="danger"
      :busy="saving"
      @close="deleteTarget = null"
      @confirm="remove"
    />
  </div>
</template>

<style scoped>
.help-page {
  max-width: 860px;
}

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

.group-title {
  margin-top: var(--space-2);
  font-size: var(--text-md);
}

.article.inactive {
  opacity: 0.7;
}

.prose :deep(p),
.prose :deep(ul),
.prose :deep(ol) {
  margin: 0 0 var(--space-3);
}

.prose :deep(p:last-child) {
  margin-bottom: 0;
}

.feedback {
  padding-top: var(--space-3);
  border-top: 1px solid var(--color-border);
}

.feedback p {
  display: inline-flex;
  align-items: center;
  gap: var(--space-1);
}

.feedback .btn {
  min-height: 36px;
}

.admin-row {
  gap: var(--space-1);
}

.danger-text {
  color: var(--color-danger);
}

.ask {
  display: flex;
  gap: var(--space-4);
  align-items: flex-start;
}

.ask > .icon {
  color: var(--color-primary-text);
  flex-shrink: 0;
}

@media (max-width: 640px) {
  .filters {
    grid-template-columns: 1fr;
  }
}
</style>
