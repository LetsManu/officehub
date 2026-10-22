<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import AppIcon from '@/components/AppIcon.vue'
import BaseModal from '@/components/BaseModal.vue'
import EmptyState from '@/components/EmptyState.vue'
import FormField from '@/components/FormField.vue'
import LoadState from '@/components/LoadState.vue'
import PageHeader from '@/components/PageHeader.vue'
import { api } from '@/lib/api'
import { isHr } from '@/lib/session'
import { errorText, formatDate, t } from '@/lib/i18n'
import { showToast } from '@/lib/toast'
import type { DirectoryEntry, Review } from '@/lib/types'

const router = useRouter()
const reviews = ref<Review[]>([])
const people = ref<DirectoryEntry[]>([])
const loading = ref(true)
const error = ref<string | null>(null)

const createOpen = ref(false)
const form = reactive({ employee_id: 0, reviewer_id: 0, year: new Date().getFullYear(), meeting_date: '' })
const formError = ref('')
const saving = ref(false)

function title(review: Review): string {
  return review.my_side === 'employee'
    ? t('reviews.yourReview', { year: review.year })
    : t('reviews.withPerson', { year: review.year, name: review.employee.full_name })
}

async function load() {
  loading.value = true
  error.value = null
  try {
    reviews.value = await api.get<Review[]>('/api/reviews')
  } catch (e) {
    error.value = errorText(e)
  } finally {
    loading.value = false
  }
}

async function openCreate() {
  formError.value = ''
  if (!people.value.length) people.value = await api.get<DirectoryEntry[]>('/api/directory').catch(() => [])
  const first = people.value[0]
  Object.assign(form, { employee_id: first?.id ?? 0, reviewer_id: first?.manager_id ?? 0, year: new Date().getFullYear(), meeting_date: '' })
  createOpen.value = true
}

function onEmployeeChange() {
  const person = people.value.find((p) => p.id === form.employee_id)
  if (person?.manager_id) form.reviewer_id = person.manager_id
}

async function create() {
  saving.value = true
  formError.value = ''
  try {
    const review = await api.post<Review>('/api/reviews', { ...form, meeting_date: form.meeting_date || null })
    createOpen.value = false
    showToast(t('reviews.created'))
    router.push(`/reviews/${review.id}`)
  } catch (e) {
    formError.value = errorText(e)
  } finally {
    saving.value = false
  }
}

onMounted(load)
</script>

<template>
  <div class="page">
    <PageHeader :title="t('reviews.title')" :subtitle="t('reviews.subtitle')">
      <template v-if="isHr" #actions>
        <button type="button" class="btn btn-primary" @click="openCreate"><AppIcon name="plus" />{{ t('reviews.create') }}</button>
      </template>
    </PageHeader>

    <LoadState :loading="loading" :error="error" @retry="load">
      <section class="card card-flush">
        <ul v-if="reviews.length" class="list">
          <li v-for="review in reviews" :key="review.id">
            <RouterLink :to="`/reviews/${review.id}`" class="list-link">
              <span class="icon-box"><AppIcon name="message" /></span>
              <span class="main">
                <span class="title">{{ title(review) }}</span>
                <span class="muted small">
                  {{ t('reviews.reviewer') }}: {{ review.reviewer.full_name }}
                  <template v-if="review.meeting_date"> · {{ t('reviews.meetingDate') }}: {{ formatDate(review.meeting_date) }}</template>
                </span>
              </span>
              <span class="badge" :class="review.status === 'completed' ? 'badge-done' : 'badge-open'">
                {{ review.status === 'completed' ? t('reviews.statusCompleted') : t('reviews.statusPreparation') }}
              </span>
            </RouterLink>
          </li>
        </ul>
        <EmptyState v-else icon="message" :message="t('reviews.empty')" :action-label="isHr ? t('reviews.create') : undefined" @action="openCreate" />
      </section>
    </LoadState>

    <BaseModal :open="createOpen" :title="t('reviews.createTitle')" :confirm-label="t('reviews.create')" :busy="saving" wide @close="createOpen = false" @confirm="create">
      <form class="stack" novalidate @submit.prevent="create">
        <div v-if="formError" class="notice notice-danger small" role="alert">{{ formError }}</div>
        <div class="grid-2">
          <FormField id="r-employee" :label="t('reviews.employee')">
            <template #default="{ attrs }">
              <select v-bind="attrs" v-model.number="form.employee_id" class="select" @change="onEmployeeChange">
                <option v-for="p in people" :key="p.id" :value="p.id">{{ p.full_name }}</option>
              </select>
            </template>
          </FormField>
          <FormField id="r-reviewer" :label="t('reviews.reviewer')">
            <template #default="{ attrs }">
              <select v-bind="attrs" v-model.number="form.reviewer_id" class="select">
                <option v-for="p in people.filter((p) => p.id !== form.employee_id)" :key="p.id" :value="p.id">{{ p.full_name }}</option>
              </select>
            </template>
          </FormField>
          <FormField id="r-year" :label="t('reviews.year')">
            <template #default="{ attrs }"><input v-bind="attrs" v-model.number="form.year" class="input" type="number" min="2000" max="2100" /></template>
          </FormField>
          <FormField id="r-date" :label="t('reviews.meetingDate')" optional>
            <template #default="{ attrs }"><input v-bind="attrs" v-model="form.meeting_date" class="input" type="date" /></template>
          </FormField>
        </div>
      </form>
    </BaseModal>
  </div>
</template>

<style scoped>
.icon-box {
  display: grid;
  place-items: center;
  width: 40px;
  height: 40px;
  border-radius: var(--radius-md);
  background: var(--color-primary-soft);
  color: var(--color-primary-text);
  flex-shrink: 0;
}

.main {
  display: grid;
  gap: 2px;
  flex: 1;
}

.title {
  font-weight: 600;
}

.badge {
  padding: 2px 10px;
  border-radius: 999px;
  font-size: var(--text-xs);
  font-weight: 600;
  white-space: nowrap;
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
