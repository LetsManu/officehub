<script setup lang="ts">
import { onMounted, reactive, ref, watch } from 'vue'
import AppIcon from '@/components/AppIcon.vue'
import BaseModal from '@/components/BaseModal.vue'
import EmptyState from '@/components/EmptyState.vue'
import FormField from '@/components/FormField.vue'
import LoadState from '@/components/LoadState.vue'
import PageHeader from '@/components/PageHeader.vue'
import UserAvatar from '@/components/UserAvatar.vue'
import { api, query } from '@/lib/api'
import { errorText, formatDate, t } from '@/lib/i18n'
import { isAdmin } from '@/lib/session'
import { showToast } from '@/lib/toast'
import type { Idea, IdeaStatus } from '@/lib/types'

const STATUSES: IdeaStatus[] = ['new', 'review', 'planned', 'done', 'declined']

const ideas = ref<Idea[]>([])
const status = ref<IdeaStatus | ''>('')
const sort = ref<'votes' | 'new'>('votes')
const loading = ref(true)
const error = ref<string | null>(null)

const newOpen = ref(false)
const form = reactive({ title: '', body: '' })
const errors = reactive({ title: '', body: '' })
const saving = ref(false)
const answerFor = ref<Idea | null>(null)
const answer = reactive({ status: 'review' as IdeaStatus, response: '' })
const deleteTarget = ref<Idea | null>(null)

async function load() {
  loading.value = ideas.value.length === 0
  error.value = null
  try {
    ideas.value = await api.get<Idea[]>(`/api/ideas${query({ status: status.value, sort: sort.value })}`)
  } catch (e) {
    error.value = errorText(e)
  } finally {
    loading.value = false
  }
}

function replace(updated: Idea) {
  ideas.value = ideas.value.map((i) => (i.id === updated.id ? updated : i))
}

async function vote(idea: Idea) {
  try {
    replace(await api.post<Idea>(`/api/ideas/${idea.id}/vote`))
  } catch (e) {
    showToast(errorText(e), 'error')
  }
}

function openNew() {
  form.title = form.body = ''
  errors.title = errors.body = ''
  newOpen.value = true
}

async function submit() {
  errors.title = form.title.trim() ? '' : t('validation.title_required')
  errors.body = form.body.trim() ? '' : t('validation.description_required')
  if (errors.title || errors.body) return
  saving.value = true
  try {
    await api.post('/api/ideas', { title: form.title.trim(), body: form.body.trim() })
    newOpen.value = false
    showToast(t('ideas.thanks'))
    await load()
  } catch (e) {
    errors.body = errorText(e)
  } finally {
    saving.value = false
  }
}

function openAnswer(idea: Idea) {
  answerFor.value = idea
  answer.status = idea.status === 'new' ? 'review' : idea.status
  answer.response = idea.response
}

async function saveAnswer() {
  if (!answerFor.value) return
  saving.value = true
  try {
    replace(await api.put<Idea>(`/api/ideas/${answerFor.value.id}/status`, { status: answer.status, response: answer.response.trim() }))
    answerFor.value = null
    showToast(t('ideas.answered'))
  } catch (e) {
    showToast(errorText(e), 'error')
  } finally {
    saving.value = false
  }
}

async function remove() {
  if (!deleteTarget.value) return
  try {
    await api.delete(`/api/ideas/${deleteTarget.value.id}`)
    deleteTarget.value = null
    await load()
  } catch (e) {
    showToast(errorText(e), 'error')
  }
}

watch([status, sort], load)
onMounted(load)
</script>

<template>
  <div class="page ideas-page">
    <PageHeader :title="t('ideas.title')" :subtitle="t('ideas.subtitle')">
      <template #actions>
        <button type="button" class="btn btn-primary" @click="openNew"><AppIcon name="lightbulb" />{{ t('ideas.new') }}</button>
      </template>
    </PageHeader>

    <div class="row filters">
      <div class="segmented" role="group" :aria-label="t('ideas.sort')">
        <button type="button" :aria-pressed="sort === 'votes'" @click="sort = 'votes'">{{ t('ideas.sortVotes') }}</button>
        <button type="button" :aria-pressed="sort === 'new'" @click="sort = 'new'">{{ t('ideas.sortNew') }}</button>
      </div>
      <label for="idea-status" class="visually-hidden">{{ t('ideas.statusLabel') }}</label>
      <select id="idea-status" v-model="status" class="select status-select">
        <option value="">{{ t('ideas.allStatuses') }}</option>
        <option v-for="s in STATUSES" :key="s" :value="s">{{ t(`ideas.status.${s}`) }}</option>
      </select>
    </div>

    <LoadState :loading="loading" :error="error" @retry="load">
      <ul v-if="ideas.length" class="idea-list">
        <li v-for="idea in ideas" :key="idea.id" class="card idea">
          <button
            type="button"
            class="vote"
            :class="{ voted: idea.voted }"
            :aria-pressed="idea.voted"
            :aria-label="t('ideas.voteLabel', { title: idea.title, count: idea.votes })"
            :disabled="idea.status === 'done' || idea.status === 'declined'"
            @click="vote(idea)"
          >
            <AppIcon name="arrowUp" :size="18" />
            <span class="vote-count">{{ idea.votes }}</span>
          </button>
          <div class="idea-main">
            <div class="row idea-head">
              <h2>{{ idea.title }}</h2>
              <span class="status" :class="`s-${idea.status}`">{{ t(`ideas.status.${idea.status}`) }}</span>
            </div>
            <p class="prewrap">{{ idea.body }}</p>
            <p class="meta muted small">
              <UserAvatar :id="idea.author.id" :name="idea.author.full_name" :photo-version="idea.author.photo_version" :size="22" />
              {{ idea.author.full_name }} · {{ formatDate(idea.created_at) }}
            </p>
            <div v-if="idea.response" class="response">
              <p class="small"><strong>{{ t('ideas.response') }}</strong></p>
              <p class="prewrap">{{ idea.response }}</p>
            </div>
            <div v-if="isAdmin || idea.can_delete" class="row actions">
              <button v-if="isAdmin" type="button" class="btn btn-secondary" @click="openAnswer(idea)">{{ t('ideas.answer') }}</button>
              <button v-if="idea.can_delete" type="button" class="btn btn-ghost danger-text" @click="deleteTarget = idea">{{ t('ideas.delete') }}</button>
            </div>
          </div>
        </li>
      </ul>
      <section v-else class="card">
        <EmptyState icon="lightbulb" :message="t('ideas.empty')" :action-label="t('ideas.new')" @action="openNew" />
      </section>
    </LoadState>

    <BaseModal :open="newOpen" :title="t('ideas.new')" :description="t('ideas.newHint')" :confirm-label="t('ideas.submit')" :busy="saving" @close="newOpen = false" @confirm="submit">
      <form class="stack" novalidate @submit.prevent="submit">
        <FormField id="idea-title" :label="t('ideas.titleLabel')" :error="errors.title">
          <template #default="{ attrs }"><input v-bind="attrs" v-model="form.title" class="input" maxlength="150" /></template>
        </FormField>
        <FormField id="idea-body" :label="t('ideas.body')" :error="errors.body">
          <template #default="{ attrs }"><textarea v-bind="attrs" v-model="form.body" class="textarea" rows="5" maxlength="4000" /></template>
        </FormField>
      </form>
    </BaseModal>

    <BaseModal :open="answerFor !== null" :title="t('ideas.answer')" :description="answerFor?.title ?? ''" :confirm-label="t('app.save')" :busy="saving" @close="answerFor = null" @confirm="saveAnswer">
      <form class="stack" novalidate @submit.prevent="saveAnswer">
        <FormField id="idea-status-set" :label="t('ideas.statusLabel')">
          <template #default="{ attrs }">
            <select v-bind="attrs" v-model="answer.status" class="select">
              <option v-for="s in STATUSES" :key="s" :value="s">{{ t(`ideas.status.${s}`) }}</option>
            </select>
          </template>
        </FormField>
        <FormField id="idea-response" :label="t('ideas.response')" :hint="t('ideas.responseHint')" optional>
          <template #default="{ attrs }"><textarea v-bind="attrs" v-model="answer.response" class="textarea" rows="4" maxlength="2000" /></template>
        </FormField>
      </form>
    </BaseModal>

    <BaseModal
      :open="deleteTarget !== null"
      :title="t('ideas.deleteTitle')"
      :description="deleteTarget?.title ?? ''"
      :confirm-label="t('ideas.delete')"
      tone="danger"
      @close="deleteTarget = null"
      @confirm="remove"
    />
  </div>
</template>

<style scoped>
.ideas-page {
  max-width: 900px;
}

.filters {
  justify-content: space-between;
}

.status-select {
  width: auto;
  min-width: 200px;
}

.idea-list {
  list-style: none;
  margin: 0;
  padding: 0;
  display: grid;
  gap: var(--space-3);
}

.idea {
  display: flex;
  gap: var(--space-4);
  align-items: flex-start;
}

.vote {
  display: grid;
  justify-items: center;
  gap: 2px;
  min-width: 56px;
  padding: var(--space-2);
  border: 1px solid var(--color-border-strong);
  border-radius: var(--radius-md);
  background: var(--color-surface);
  color: var(--color-text-muted);
  font: inherit;
  cursor: pointer;
  transition: border-color var(--t-fast) ease, background-color var(--t-fast) ease;
}

.vote:hover:not(:disabled) {
  border-color: var(--color-primary);
}

.vote.voted {
  border-color: var(--color-primary);
  background: var(--color-primary-soft);
  color: var(--color-primary-text);
}

.vote:disabled {
  cursor: default;
  opacity: 0.7;
}

.vote-count {
  font-weight: 700;
  font-variant-numeric: tabular-nums;
}

.idea-main {
  display: grid;
  gap: var(--space-2);
  flex: 1;
  min-width: 0;
}

.idea-head {
  justify-content: space-between;
}

.idea-head h2 {
  font-size: var(--text-lg);
}

.status {
  padding: 2px 10px;
  border-radius: var(--radius-full);
  font-size: var(--text-xs);
  font-weight: 700;
  background: var(--color-neutral-soft);
  color: var(--color-text-muted);
}

.s-review,
.s-planned {
  background: var(--color-primary-soft);
  color: var(--color-primary-text);
}

.s-done {
  background: var(--color-success-soft);
  color: var(--color-success);
}

.s-declined {
  background: var(--color-danger-soft);
  color: var(--color-danger);
}

.meta {
  display: inline-flex;
  align-items: center;
  gap: var(--space-2);
}

.response {
  padding: var(--space-3) var(--space-4);
  border-left: 3px solid var(--color-primary);
  border-radius: 0 var(--radius-sm) var(--radius-sm) 0;
  background: var(--color-surface-muted);
}

.actions {
  gap: var(--space-2);
}

.danger-text {
  color: var(--color-danger);
}
</style>
