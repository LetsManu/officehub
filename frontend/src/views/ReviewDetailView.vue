<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import AppIcon from '@/components/AppIcon.vue'
import FormField from '@/components/FormField.vue'
import LoadState from '@/components/LoadState.vue'
import PageHeader from '@/components/PageHeader.vue'
import { api } from '@/lib/api'
import { errorText, formatDate, t } from '@/lib/i18n'
import { showToast } from '@/lib/toast'
import type { Review } from '@/lib/types'

const props = defineProps<{ id: string }>()

const EMPLOYEE_QUESTIONS = ['achievements', 'challenges', 'support', 'wishes']
const REVIEWER_QUESTIONS = ['strengths', 'development', 'feedback']

const review = ref<Review | null>(null)
const loading = ref(true)
const error = ref<string | null>(null)
const busy = ref(false)

const answers = reactive<Record<string, string>>({})
const goals = ref('')
const meetingDate = ref('')

const side = computed(() => review.value?.my_side)
const completed = computed(() => review.value?.status === 'completed')
const myQuestions = computed(() => (side.value === 'reviewer' ? REVIEWER_QUESTIONS : EMPLOYEE_QUESTIONS))
const myPrepDone = computed(() => (side.value === 'reviewer' ? review.value?.reviewer_prep_done : review.value?.employee_prep_done) ?? false)
const otherName = computed(() => (side.value === 'reviewer' ? review.value?.employee.full_name : review.value?.reviewer.full_name) ?? '')
const otherPrep = computed(() => (side.value === 'reviewer' ? review.value?.employee_prep : review.value?.reviewer_prep) ?? null)
const otherQuestions = computed(() => (side.value === 'reviewer' ? EMPLOYEE_QUESTIONS : REVIEWER_QUESTIONS))
const canEditGoals = computed(() => !completed.value && (side.value === 'reviewer' || side.value === 'hr'))
const myConfirmedAt = computed(() => (side.value === 'reviewer' ? review.value?.reviewer_confirmed_at : review.value?.employee_confirmed_at) ?? null)

const heading = computed(() => {
  const r = review.value
  if (!r) return ''
  return r.my_side === 'employee' ? t('reviews.yourReview', { year: r.year }) : t('reviews.withPerson', { year: r.year, name: r.employee.full_name })
})

const steps = computed(() => {
  const r = review.value
  if (!r) return []
  return [
    { label: t('reviews.stepPrepare'), done: r.employee_prep_done && r.reviewer_prep_done },
    { label: t('reviews.stepMeet'), done: Boolean(r.goals.trim()) },
    { label: t('reviews.stepGoals'), done: r.status === 'completed' },
  ]
})

function apply(data: Review) {
  review.value = data
  const mine = (data.my_side === 'reviewer' ? data.reviewer_prep : data.employee_prep) ?? {}
  for (const key of [...EMPLOYEE_QUESTIONS, ...REVIEWER_QUESTIONS]) answers[key] = mine[key] ?? ''
  goals.value = data.goals
  meetingDate.value = data.meeting_date ?? ''
}

async function load() {
  loading.value = true
  error.value = null
  try {
    apply(await api.get<Review>(`/api/reviews/${props.id}`))
  } catch (e) {
    error.value = errorText(e)
  } finally {
    loading.value = false
  }
}

async function run(action: () => Promise<Review>, message: string) {
  busy.value = true
  try {
    apply(await action())
    showToast(message)
  } catch (e) {
    showToast(errorText(e), 'error')
  } finally {
    busy.value = false
  }
}

function savePrep(done: boolean) {
  const payload = Object.fromEntries(myQuestions.value.map((key) => [key, answers[key] ?? '']))
  run(() => api.put(`/api/reviews/${props.id}/prep`, { answers: payload, done }), t('reviews.prepSaved'))
}

function saveGoals() {
  run(() => api.patch(`/api/reviews/${props.id}`, { goals: goals.value, meeting_date: meetingDate.value || null }), t('reviews.goalsSaved'))
}

function confirmGoals() {
  run(() => api.post(`/api/reviews/${props.id}/confirm`), t('reviews.confirmedToast'))
}

onMounted(load)
</script>

<template>
  <div class="page review-page">
    <LoadState :loading="loading" :error="error" @retry="load">
      <template v-if="review">
        <PageHeader :title="heading" back-to="/reviews">
          <template #actions>
            <span class="badge" :class="completed ? 'badge-done' : 'badge-open'">
              {{ completed ? t('reviews.statusCompleted') : t('reviews.statusPreparation') }}
            </span>
          </template>
        </PageHeader>

        <section class="card">
          <h2 class="visually-hidden">{{ t('reviews.steps') }}</h2>
          <ol class="steps">
            <li v-for="(step, index) in steps" :key="step.label" :class="{ done: step.done }">
              <span class="step-number" aria-hidden="true"><AppIcon v-if="step.done" name="check" :size="16" /><template v-else>{{ index + 1 }}</template></span>
              <span>{{ step.label }}</span>
            </li>
          </ol>
          <dl class="facts meta">
            <div><dt>{{ t('reviews.employee') }}</dt><dd>{{ review.employee.full_name }}</dd></div>
            <div><dt>{{ t('reviews.reviewer') }}</dt><dd>{{ review.reviewer.full_name }}</dd></div>
            <div><dt>{{ t('reviews.meetingDate') }}</dt><dd>{{ review.meeting_date ? formatDate(review.meeting_date) : '–' }}</dd></div>
          </dl>
          <p v-if="side === 'hr'" class="muted small">{{ t('reviews.hrView') }}</p>
        </section>

        <div v-if="completed" class="notice notice-success"><AppIcon name="checkCircle" /><p>{{ t('reviews.completedText') }}</p></div>

        <!-- My preparation -->
        <section v-if="side !== 'hr'" class="card stack" aria-labelledby="my-prep">
          <div class="row-between">
            <h2 id="my-prep">{{ t('reviews.myPrep') }}</h2>
            <span class="small" :class="myPrepDone ? 'ok' : 'muted'">{{ myPrepDone ? t('reviews.prepDone') : t('reviews.prepOpen') }}</span>
          </div>
          <FormField v-for="key in myQuestions" :id="`q-${key}`" :key="key" :label="t(`reviews.questions.${key}`)" optional>
            <template #default="{ attrs }">
              <textarea v-bind="attrs" v-model="answers[key]" class="textarea" rows="3" maxlength="3000" :readonly="myPrepDone || completed" />
            </template>
          </FormField>
          <div v-if="!completed" class="form-actions">
            <template v-if="!myPrepDone">
              <button type="button" class="btn btn-secondary" :disabled="busy" @click="savePrep(false)">{{ t('reviews.saveDraft') }}</button>
              <button type="button" class="btn btn-primary" :disabled="busy" @click="savePrep(true)">{{ t('reviews.finishPrep') }}</button>
            </template>
            <button v-else type="button" class="btn btn-ghost" :disabled="busy" @click="savePrep(false)">{{ t('reviews.reopenPrep') }}</button>
          </div>
        </section>

        <!-- The other side's preparation (HR sees both) -->
        <template v-if="side === 'hr'">
          <section v-for="who in (['employee', 'reviewer'] as const)" :key="who" class="card stack">
            <h2>{{ t('reviews.otherPrep', { name: review[who].full_name }) }}</h2>
            <dl class="answers">
              <div v-for="key in who === 'employee' ? EMPLOYEE_QUESTIONS : REVIEWER_QUESTIONS" :key="key">
                <dt>{{ t(`reviews.questions.${key}`) }}</dt>
                <dd class="prewrap">{{ review[`${who}_prep`]?.[key] || '–' }}</dd>
              </div>
            </dl>
          </section>
        </template>
        <section v-else class="card stack">
          <h2>{{ t('reviews.otherPrep', { name: otherName }) }}</h2>
          <dl v-if="otherPrep" class="answers">
            <div v-for="key in otherQuestions" :key="key">
              <dt>{{ t(`reviews.questions.${key}`) }}</dt>
              <dd class="prewrap">{{ otherPrep[key] || '–' }}</dd>
            </div>
          </dl>
          <p v-else class="muted">{{ t('reviews.otherPrepHidden', { name: otherName }) }}</p>
        </section>

        <!-- Goals -->
        <section class="card stack" aria-labelledby="goals-title">
          <h2 id="goals-title">{{ t('reviews.goals') }}</h2>
          <p class="muted small">{{ t('reviews.goalsHint') }}</p>
          <template v-if="canEditGoals">
            <FormField id="meeting-date" :label="t('reviews.meetingDate')" optional>
              <template #default="{ attrs }"><input v-bind="attrs" v-model="meetingDate" class="input date-input" type="date" /></template>
            </FormField>
            <FormField id="goals" :label="t('reviews.goals')">
              <template #default="{ attrs }"><textarea v-bind="attrs" v-model="goals" class="textarea" rows="5" maxlength="5000" /></template>
            </FormField>
            <div class="form-actions"><button type="button" class="btn btn-secondary" :disabled="busy" @click="saveGoals">{{ t('reviews.saveGoals') }}</button></div>
          </template>
          <p v-else class="prewrap goals-text">{{ review.goals || t('reviews.goalsEmpty') }}</p>

          <dl class="facts">
            <div>
              <dt>{{ review.employee.full_name }}</dt>
              <dd>{{ review.employee_confirmed_at ? t('reviews.confirmed', { date: formatDate(review.employee_confirmed_at) }) : t('reviews.notConfirmed') }}</dd>
            </div>
            <div>
              <dt>{{ review.reviewer.full_name }}</dt>
              <dd>{{ review.reviewer_confirmed_at ? t('reviews.confirmed', { date: formatDate(review.reviewer_confirmed_at) }) : t('reviews.notConfirmed') }}</dd>
            </div>
          </dl>
          <div v-if="side !== 'hr' && !completed && !myConfirmedAt && review.goals.trim()" class="form-actions">
            <button type="button" class="btn btn-primary" :disabled="busy" @click="confirmGoals"><AppIcon name="check" />{{ t('reviews.confirm') }}</button>
          </div>
        </section>
      </template>
    </LoadState>
  </div>
</template>

<style scoped>
.review-page {
  max-width: 860px;
}

.steps {
  list-style: none;
  margin: 0 0 var(--space-4);
  padding: 0;
  display: flex;
  flex-wrap: wrap;
  gap: var(--space-3) var(--space-5);
}

.steps li {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  color: var(--color-text-muted);
}

.steps li.done {
  color: var(--color-text);
}

.step-number {
  display: grid;
  place-items: center;
  width: 28px;
  height: 28px;
  border-radius: 50%;
  border: 2px solid var(--color-border-strong);
  font-size: var(--text-sm);
  font-weight: 700;
}

.done .step-number {
  border-color: var(--color-success);
  background: var(--color-success);
  color: #fff;
}

.answers {
  display: grid;
  gap: var(--space-4);
  margin: 0;
}

.answers dt {
  font-size: var(--text-sm);
  font-weight: 600;
  color: var(--color-text-muted);
}

.answers dd {
  margin: 4px 0 0;
}

.ok {
  color: var(--color-success);
  font-weight: 600;
}

.date-input {
  max-width: 220px;
}

.goals-text {
  padding: var(--space-3) var(--space-4);
  border-radius: var(--radius-md);
  background: var(--color-surface-muted);
}

.badge {
  padding: 2px 10px;
  border-radius: 999px;
  font-size: var(--text-xs);
  font-weight: 600;
}

.badge-open {
  background: var(--color-warning-soft);
  color: var(--color-warning);
}

.badge-done {
  background: var(--color-success-soft);
  color: var(--color-success);
}
</style>
