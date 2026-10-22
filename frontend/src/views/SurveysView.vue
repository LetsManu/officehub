<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import AppIcon from '@/components/AppIcon.vue'
import BaseModal from '@/components/BaseModal.vue'
import EmptyState from '@/components/EmptyState.vue'
import FormField from '@/components/FormField.vue'
import LoadState from '@/components/LoadState.vue'
import PageHeader from '@/components/PageHeader.vue'
import { api } from '@/lib/api'
import { errorText, formatDate, t } from '@/lib/i18n'
import { isHr } from '@/lib/session'
import { refreshSummary } from '@/lib/summary'
import { showToast } from '@/lib/toast'
import type { Survey, SurveyQuestion } from '@/lib/types'

const surveys = ref<Survey[]>([])
const loading = ref(true)
const error = ref<string | null>(null)

const builderOpen = ref(false)
const saving = ref(false)
const form = reactive({ title: '', intro: '', closes_on: '', results_public: false, questions: [] as SurveyQuestion[] })
const formError = ref('')

const open = computed(() => surveys.value.filter((s) => s.status === 'open'))
const others = computed(() => surveys.value.filter((s) => s.status !== 'open'))

async function load() {
  loading.value = surveys.value.length === 0
  error.value = null
  try {
    surveys.value = await api.get<Survey[]>('/api/surveys')
  } catch (e) {
    error.value = errorText(e)
  } finally {
    loading.value = false
  }
}

function openBuilder() {
  Object.assign(form, {
    title: '', intro: '', closes_on: '', results_public: false,
    questions: [{ text: '', kind: 'scale', options: [] }, { text: '', kind: 'text', options: [] }],
  })
  formError.value = ''
  builderOpen.value = true
}

function addQuestion(kind: SurveyQuestion['kind']) {
  form.questions.push({ text: '', kind, options: kind === 'choice' ? ['', ''] : [] })
}

async function create() {
  const questions = form.questions
    .map((q) => ({ ...q, text: q.text.trim(), options: q.options.map((o) => o.trim()).filter(Boolean) }))
    .filter((q) => q.text)
  formError.value = !form.title.trim()
    ? t('validation.title_required')
    : !questions.length
      ? t('surveys.needQuestion')
      : questions.some((q) => q.kind === 'choice' && q.options.length < 2)
        ? t('validation.poll_options_required')
        : ''
  if (formError.value) return
  saving.value = true
  try {
    await api.post('/api/surveys', { title: form.title.trim(), intro: form.intro.trim(), questions, closes_on: form.closes_on || null, results_public: form.results_public })
    builderOpen.value = false
    showToast(t('surveys.created'))
    await load()
  } catch (e) {
    formError.value = errorText(e)
  } finally {
    saving.value = false
  }
}

async function setStatus(survey: Survey, status: 'open' | 'closed') {
  try {
    await api.patch(`/api/surveys/${survey.id}`, { status })
    showToast(status === 'open' ? t('surveys.opened') : t('surveys.closedToast'))
    await load()
    refreshSummary(true)
  } catch (e) {
    showToast(errorText(e), 'error')
  }
}

onMounted(load)
</script>

<template>
  <div class="page">
    <PageHeader :title="t('surveys.title')" :subtitle="t('surveys.subtitle')">
      <template v-if="isHr" #actions>
        <button type="button" class="btn btn-primary" @click="openBuilder"><AppIcon name="plus" />{{ t('surveys.new') }}</button>
      </template>
    </PageHeader>

    <p class="notice notice-info small"><AppIcon name="shield" :size="18" />{{ t('surveys.anonymous') }}</p>

    <LoadState :loading="loading" :error="error" @retry="load">
      <section v-if="open.length" class="stack" aria-labelledby="open-title">
        <h2 id="open-title" class="section-title">{{ t('surveys.openTitle') }}</h2>
        <article v-for="s in open" :key="s.id" class="card survey">
          <div class="survey-main">
            <h3>{{ s.title }}</h3>
            <p class="muted small">
              {{ t('surveys.questions', { count: s.questions.length }) }}
              <template v-if="s.closes_on"> · {{ t('surveys.until', { date: formatDate(s.closes_on) }) }}</template>
              <template v-if="isHr"> · {{ t('surveys.responses', { count: s.responses }) }}</template>
            </p>
          </div>
          <div class="row">
            <span v-if="s.answered" class="done-chip"><AppIcon name="check" :size="16" />{{ t('surveys.answered') }}</span>
            <RouterLink v-else :to="`/surveys/${s.id}`" class="btn btn-primary">{{ t('surveys.take') }}</RouterLink>
            <RouterLink v-if="s.can_see_results" :to="`/surveys/${s.id}?results=1`" class="btn btn-ghost">{{ t('surveys.results') }}</RouterLink>
            <button v-if="isHr" type="button" class="btn btn-ghost" @click="setStatus(s, 'closed')">{{ t('surveys.close') }}</button>
          </div>
        </article>
      </section>

      <section v-if="others.length" class="stack" aria-labelledby="other-title">
        <h2 id="other-title" class="section-title">{{ t('surveys.otherTitle') }}</h2>
        <ul class="card card-flush list">
          <li v-for="s in others" :key="s.id" class="row-item">
            <span class="grow">
              <strong>{{ s.title }}</strong>
              <span class="muted small"> · {{ t(`surveys.status.${s.status}`) }}<template v-if="isHr"> · {{ t('surveys.responses', { count: s.responses }) }}</template></span>
            </span>
            <button v-if="isHr && s.status === 'draft'" type="button" class="btn btn-secondary" @click="setStatus(s, 'open')">{{ t('surveys.start') }}</button>
            <RouterLink v-if="s.can_see_results" :to="`/surveys/${s.id}?results=1`" class="btn btn-ghost">{{ t('surveys.results') }}</RouterLink>
          </li>
        </ul>
      </section>

      <section v-if="!surveys.length" class="card"><EmptyState icon="chart" :message="t('surveys.empty')" /></section>
    </LoadState>

    <BaseModal :open="builderOpen" :title="t('surveys.new')" :confirm-label="t('surveys.saveDraft')" :busy="saving" wide @close="builderOpen = false" @confirm="create">
      <form class="stack" novalidate @submit.prevent="create">
        <div v-if="formError" class="notice notice-danger small" role="alert">{{ formError }}</div>
        <FormField id="sv-title" :label="t('surveys.titleLabel')">
          <template #default="{ attrs }"><input v-bind="attrs" v-model="form.title" class="input" maxlength="150" /></template>
        </FormField>
        <FormField id="sv-intro" :label="t('surveys.intro')" optional>
          <template #default="{ attrs }"><textarea v-bind="attrs" v-model="form.intro" class="textarea" rows="2" maxlength="2000" /></template>
        </FormField>
        <fieldset class="questions">
          <legend class="label-strong">{{ t('surveys.questionsTitle') }}</legend>
          <div v-for="(q, i) in form.questions" :key="i" class="question">
            <div class="row q-head">
              <span class="q-number">{{ i + 1 }}</span>
              <label :for="`sv-q-${i}`" class="visually-hidden">{{ t('surveys.questionText') }}</label>
              <input :id="`sv-q-${i}`" v-model="q.text" class="input grow" maxlength="200" :placeholder="t('surveys.questionText')" />
              <label :for="`sv-k-${i}`" class="visually-hidden">{{ t('surveys.kind') }}</label>
              <select :id="`sv-k-${i}`" v-model="q.kind" class="select kind" @change="q.options = q.kind === 'choice' && q.options.length < 2 ? ['', ''] : q.options">
                <option value="scale">{{ t('surveys.kinds.scale') }}</option>
                <option value="choice">{{ t('surveys.kinds.choice') }}</option>
                <option value="text">{{ t('surveys.kinds.text') }}</option>
              </select>
              <button v-if="form.questions.length > 1" type="button" class="btn btn-ghost btn-icon" :aria-label="t('surveys.removeQuestion', { number: i + 1 })" @click="form.questions.splice(i, 1)">
                <AppIcon name="trash" :size="18" />
              </button>
            </div>
            <div v-if="q.kind === 'choice'" class="options">
              <input v-for="(_, j) in q.options" :key="j" v-model="q.options[j]" class="input" maxlength="80" :placeholder="t('manageNews.pollOption', { number: j + 1 })" :aria-label="t('manageNews.pollOption', { number: j + 1 })" />
              <button v-if="q.options.length < 8" type="button" class="btn btn-ghost" @click="q.options.push('')"><AppIcon name="plus" :size="16" />{{ t('manageNews.pollAdd') }}</button>
            </div>
          </div>
          <div class="row">
            <button v-if="form.questions.length < 10" type="button" class="btn btn-secondary" @click="addQuestion('scale')"><AppIcon name="plus" :size="16" />{{ t('surveys.addQuestion') }}</button>
          </div>
        </fieldset>
        <div class="grid-2">
          <FormField id="sv-close" :label="t('surveys.closesOn')" optional>
            <template #default="{ attrs }"><input v-bind="attrs" v-model="form.closes_on" type="date" class="input" /></template>
          </FormField>
        </div>
        <label class="checkbox"><input v-model="form.results_public" type="checkbox" /><span>{{ t('surveys.publicResults') }}</span></label>
        <p class="muted small">{{ t('surveys.draftHint') }}</p>
      </form>
    </BaseModal>
  </div>
</template>

<style scoped>
.section-title {
  font-size: var(--text-md);
}

.survey {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-3);
}

.survey-main {
  display: grid;
  gap: 2px;
}

.done-chip {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 4px 12px;
  border-radius: var(--radius-full);
  background: var(--color-success-soft);
  color: var(--color-success);
  font-weight: 600;
  font-size: var(--text-sm);
}

.row-item {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: var(--space-2);
  padding: var(--space-3) var(--space-3) var(--space-3) var(--space-5);
}

.grow {
  flex: 1;
  min-width: 0;
}

.questions {
  display: grid;
  gap: var(--space-3);
  margin: 0;
  padding: 0;
  border: 0;
}

.label-strong {
  font-weight: 600;
  margin-bottom: var(--space-2);
}

.question {
  display: grid;
  gap: var(--space-2);
  padding: var(--space-3);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-md);
  background: var(--color-surface-muted);
}

.q-head {
  flex-wrap: nowrap;
  gap: var(--space-2);
}

.q-number {
  display: grid;
  place-items: center;
  width: 28px;
  height: 28px;
  border-radius: 50%;
  background: var(--color-primary-soft);
  color: var(--color-primary-text);
  font-weight: 700;
  font-size: var(--text-sm);
  flex-shrink: 0;
}

.kind {
  width: auto;
  min-width: 140px;
}

.options {
  display: grid;
  gap: var(--space-2);
  padding-left: 36px;
}

.options .btn {
  justify-self: start;
}

@media (max-width: 560px) {
  .q-head {
    flex-wrap: wrap;
  }
}
</style>
