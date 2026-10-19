<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRoute } from 'vue-router'
import AppIcon from '@/components/AppIcon.vue'
import LoadState from '@/components/LoadState.vue'
import PageHeader from '@/components/PageHeader.vue'
import { api } from '@/lib/api'
import { errorText, t } from '@/lib/i18n'
import { refreshSummary } from '@/lib/summary'
import { showToast } from '@/lib/toast'
import type { Survey, SurveyResults } from '@/lib/types'

const props = defineProps<{ id: string }>()
const route = useRoute()

const survey = ref<Survey | null>(null)
const results = ref<SurveyResults | null>(null)
const answers = ref<(number | string | null)[]>([])
const loading = ref(true)
const error = ref<string | null>(null)
const sending = ref(false)
const missing = ref<number[]>([])

const showResults = computed(() => route.query.results === '1' || Boolean(survey.value?.answered && survey.value.can_see_results))
const SCALE = [1, 2, 3, 4, 5]

async function load() {
  loading.value = true
  error.value = null
  try {
    const list = await api.get<Survey[]>('/api/surveys')
    survey.value = list.find((s) => String(s.id) === props.id) ?? null
    if (!survey.value) throw new Error(t('surveys.notFound'))
    answers.value = survey.value.questions.map(() => null)
    if (showResults.value && survey.value.can_see_results) results.value = await api.get<SurveyResults>(`/api/surveys/${props.id}/results`)
  } catch (e) {
    error.value = errorText(e)
  } finally {
    loading.value = false
  }
}

async function send() {
  if (!survey.value) return
  missing.value = survey.value.questions.map((q, i) => (q.kind !== 'text' && answers.value[i] === null ? i : -1)).filter((i) => i >= 0)
  if (missing.value.length) {
    document.getElementById(`q-${missing.value[0]}`)?.focus()
    return
  }
  sending.value = true
  try {
    survey.value = await api.post<Survey>(`/api/surveys/${props.id}/respond`, { answers: answers.value })
    showToast(t('surveys.thanks'))
    refreshSummary(true)
  } catch (e) {
    showToast(errorText(e), 'error')
  } finally {
    sending.value = false
  }
}

function percent(count: number, counts: number[]): number {
  const total = counts.reduce((a, b) => a + b, 0)
  return total ? Math.round((count / total) * 100) : 0
}

onMounted(load)
</script>

<template>
  <div class="page survey-page">
    <PageHeader :title="survey?.title ?? t('surveys.title')" :crumbs="[{ label: t('surveys.title'), to: '/surveys' }]" />
    <LoadState :loading="loading" :error="error" @retry="load">
      <template v-if="survey">
        <p v-if="survey.intro" class="prewrap">{{ survey.intro }}</p>

        <!-- Results -->
        <template v-if="results">
          <p class="muted">{{ t('surveys.responses', { count: results.responses }) }}</p>
          <div v-if="!results.enough" class="notice notice-info"><AppIcon name="shield" /><p>{{ t('surveys.notEnough', { count: 5 }) }}</p></div>
          <section v-for="(q, i) in results.questions" v-else :key="i" class="card stack-sm">
            <h2 class="q-title">{{ i + 1 }}. {{ q.text }}</h2>
            <p v-if="q.average !== null" class="average">{{ t('surveys.average', { value: q.average.toLocaleString() }) }}</p>
            <ul v-if="q.kind !== 'text'" class="bars">
              <li v-for="(count, j) in q.counts" :key="j">
                <span class="bar-label">{{ q.kind === 'scale' ? t(`surveys.scale.${j + 1}`) : q.options[j] }}</span>
                <span class="bar"><span :style="{ width: `${percent(count, q.counts)}%` }" /></span>
                <span class="bar-value">{{ percent(count, q.counts) }} %</span>
              </li>
            </ul>
            <ul v-else-if="q.texts.length" class="texts">
              <li v-for="(text, j) in q.texts" :key="j">“{{ text }}”</li>
            </ul>
            <p v-else class="muted small">{{ t('surveys.noTexts') }}</p>
          </section>
        </template>

        <!-- Done -->
        <div v-else-if="survey.answered" class="card thanks">
          <AppIcon name="checkCircle" :size="40" />
          <h2>{{ t('surveys.thanks') }}</h2>
          <p class="muted">{{ t('surveys.thanksText') }}</p>
          <RouterLink to="/surveys" class="btn btn-secondary">{{ t('surveys.back') }}</RouterLink>
        </div>

        <!-- Answer -->
        <form v-else class="stack" novalidate @submit.prevent="send">
          <p class="notice notice-info small"><AppIcon name="shield" :size="18" />{{ t('surveys.anonymous') }}</p>
          <fieldset v-for="(q, i) in survey.questions" :key="i" class="card question" :class="{ missing: missing.includes(i) }">
            <legend class="q-title">{{ i + 1 }}. {{ q.text }}</legend>
            <div v-if="q.kind === 'scale'" class="scale" role="radiogroup" :aria-label="q.text">
              <label v-for="value in SCALE" :key="value" class="scale-option" :class="{ chosen: answers[i] === value }">
                <input :id="value === 1 ? `q-${i}` : undefined" v-model="answers[i]" type="radio" :name="`q-${i}`" :value="value" class="visually-hidden" />
                <span class="scale-number">{{ value }}</span>
                <span class="scale-text small">{{ t(`surveys.scale.${value}`) }}</span>
              </label>
            </div>
            <div v-else-if="q.kind === 'choice'" class="choices">
              <label v-for="(option, j) in q.options" :key="j" class="checkbox">
                <input :id="j === 0 ? `q-${i}` : undefined" v-model="answers[i]" type="radio" :name="`q-${i}`" :value="j" />
                <span>{{ option }}</span>
              </label>
            </div>
            <textarea v-else :id="`q-${i}`" v-model="answers[i]" class="textarea" rows="3" maxlength="1000" :aria-label="q.text" :placeholder="t('surveys.textPlaceholder')" />
            <p v-if="missing.includes(i)" class="error small" role="alert">{{ t('surveys.pleaseAnswer') }}</p>
          </fieldset>
          <div class="form-actions">
            <button type="submit" class="btn btn-primary" :disabled="sending">{{ t('surveys.send') }}</button>
          </div>
        </form>
      </template>
    </LoadState>
  </div>
</template>

<style scoped>
.survey-page {
  max-width: 760px;
}

.q-title {
  font-size: var(--text-md);
  font-weight: 600;
  margin-bottom: var(--space-3);
  padding: 0;
}

.question {
  margin: 0;
}

.question.missing {
  border-color: var(--color-danger);
}

.scale {
  display: grid;
  grid-template-columns: repeat(5, minmax(0, 1fr));
  gap: var(--space-2);
}

.scale-option {
  display: grid;
  justify-items: center;
  gap: 4px;
  padding: var(--space-3) var(--space-1);
  border: 1px solid var(--color-border-strong);
  border-radius: var(--radius-md);
  text-align: center;
  cursor: pointer;
  transition: border-color var(--t-fast) ease, background-color var(--t-fast) ease;
}

.scale-option:hover {
  border-color: var(--color-primary);
}

.scale-option.chosen {
  border-color: var(--color-primary);
  background: var(--color-primary-soft);
}

.scale-option:focus-within {
  outline: 3px solid var(--color-focus);
  outline-offset: 2px;
}

.scale-number {
  font-family: var(--font-heading);
  font-size: var(--text-xl);
  font-weight: 600;
}

.scale-text {
  color: var(--color-text-muted);
  line-height: 1.2;
}

.choices {
  display: grid;
  gap: var(--space-1);
}

.error {
  color: var(--color-danger);
  margin-top: var(--space-2);
}

.thanks {
  display: grid;
  justify-items: center;
  gap: var(--space-3);
  padding: var(--space-7) var(--space-5);
  text-align: center;
  color: var(--color-success);
}

.thanks h2,
.thanks p {
  color: var(--color-text);
}

.average {
  font-weight: 700;
  color: var(--color-primary-text);
}

.bars {
  list-style: none;
  margin: 0;
  padding: 0;
  display: grid;
  gap: var(--space-2);
}

.bars li {
  display: grid;
  grid-template-columns: minmax(100px, 160px) minmax(0, 1fr) 48px;
  align-items: center;
  gap: var(--space-3);
}

.bar-label {
  font-size: var(--text-sm);
}

.bar {
  height: 12px;
  border-radius: var(--radius-full);
  background: var(--color-neutral-soft);
  overflow: hidden;
}

.bar span {
  display: block;
  height: 100%;
  border-radius: inherit;
  background: var(--color-primary);
}

.bar-value {
  text-align: right;
  font-weight: 600;
  font-variant-numeric: tabular-nums;
  font-size: var(--text-sm);
}

.texts {
  margin: 0;
  padding-left: var(--space-4);
  display: grid;
  gap: var(--space-2);
  font-style: italic;
}

@media (max-width: 560px) {
  .scale-text {
    display: none;
  }
}
</style>
