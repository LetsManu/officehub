<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { useRoute } from 'vue-router'
import AppIcon from '@/components/AppIcon.vue'
import FormField from '@/components/FormField.vue'
import LoadState from '@/components/LoadState.vue'
import PageHeader from '@/components/PageHeader.vue'
import { api } from '@/lib/api'
import { currentUser, isApprover, isHr } from '@/lib/session'
import { errorText, formatDate, t } from '@/lib/i18n'
import { showToast } from '@/lib/toast'
import type { Checklist, OnboardingTask } from '@/lib/types'

const props = defineProps<{ id: string }>()
const OWNERS = ['hr', 'it', 'manager'] as const

const checklist = ref<Checklist | null>(null)
const loading = ref(true)
const error = ref<string | null>(null)
const busy = ref(false)
const newTask = reactive({ title: '', owner: 'hr' as (typeof OWNERS)[number] })
const newTaskError = ref('')

const route = useRoute()
const kind = computed(() => (route.query.kind === 'offboarding' ? 'offboarding' : 'onboarding'))
const isSelf = computed(() => checklist.value?.person.id === currentUser.value?.id)
const groups = computed(() =>
  OWNERS.map((owner) => ({ owner, tasks: checklist.value?.tasks.filter((task) => task.owner === owner) ?? [] })).filter((g) => g.tasks.length),
)

function taskTitle(task: OnboardingTask): string {
  if (task.key === 'asset_return') return t('onboarding.returnItem', { item: task.title })
  if (task.key && kind.value === 'offboarding') return t(`onboarding.offTasks.${task.key}`)
  return task.key ? t(`onboarding.tasks.${task.key}`) : task.title
}

async function load() {
  loading.value = true
  error.value = null
  try {
    checklist.value = await api.get<Checklist>(`/api/onboarding/${props.id}?kind=${kind.value}`)
  } catch (e) {
    error.value = errorText(e)
  } finally {
    loading.value = false
  }
}

async function toggle(task: OnboardingTask) {
  busy.value = true
  try {
    checklist.value = await api.patch<Checklist>(`/api/onboarding/tasks/${task.id}`, { done: !task.done })
  } catch (e) {
    showToast(errorText(e), 'error')
  } finally {
    busy.value = false
  }
}

async function addTask() {
  newTaskError.value = newTask.title.trim() ? '' : t('validation.title_required')
  if (newTaskError.value) return
  busy.value = true
  try {
    checklist.value = await api.post<Checklist>(`/api/onboarding/${props.id}/tasks`, { title: newTask.title.trim(), owner: newTask.owner, kind: kind.value })
    newTask.title = ''
    showToast(t('onboarding.taskAdded'))
  } catch (e) {
    newTaskError.value = errorText(e)
  } finally {
    busy.value = false
  }
}

onMounted(load)
</script>

<template>
  <div class="page checklist-page">
    <LoadState :loading="loading" :error="error" @retry="load">
      <template v-if="checklist">
        <PageHeader
          :title="
            kind === 'offboarding'
              ? t('onboarding.offChecklistFor', { name: checklist.person.full_name })
              : isSelf
                ? t('dashboard.onboardingTitle')
                : t('onboarding.checklistFor', { name: checklist.person.full_name })
          "
          :back-to="isApprover ? (kind === 'offboarding' ? '/onboarding?kind=offboarding' : '/onboarding') : '/'"
        />

        <section class="card stack">
          <div class="row-between">
            <p class="progress-text" :class="{ ok: checklist.done === checklist.total }">
              {{ checklist.done === checklist.total ? t('onboarding.complete') : t('onboarding.progress', { done: checklist.done, total: checklist.total }) }}
            </p>
            <p v-if="kind === 'offboarding' && checklist.last_day" class="muted small">{{ t('onboarding.lastDay', { date: formatDate(checklist.last_day) }) }}</p>
            <p v-if="checklist.manager_name" class="muted small">{{ t('onboarding.managerIs', { name: checklist.manager_name }) }}</p>
          </div>
          <progress :value="checklist.done" :max="checklist.total" :aria-label="t('onboarding.progress', { done: checklist.done, total: checklist.total })" />
          <p v-if="isSelf" class="muted small">{{ t('onboarding.readOnly') }}</p>
        </section>

        <section v-for="group in groups" :key="group.owner" class="card card-flush" :aria-labelledby="`owner-${group.owner}`">
          <h2 :id="`owner-${group.owner}`" class="group-title">{{ t(`onboarding.owners.${group.owner}`) }}</h2>
          <ul class="list">
            <li v-for="task in group.tasks" :key="task.id" class="task">
              <label v-if="task.can_toggle" class="checkbox task-check">
                <input type="checkbox" :checked="task.done" :disabled="busy" @change="toggle(task)" />
                <span :class="{ done: task.done }">{{ taskTitle(task) }}</span>
              </label>
              <span v-else class="task-static">
                <AppIcon :name="task.done ? 'checkCircle' : 'clock'" :class="task.done ? 'ok' : 'muted'" :label="task.done ? t('onboarding.complete') : undefined" />
                <span :class="{ done: task.done }">{{ taskTitle(task) }}</span>
              </span>
              <span v-if="task.done && task.done_by && task.done_at" class="muted small">
                {{ t('onboarding.doneBy', { name: task.done_by, date: formatDate(task.done_at) }) }}
              </span>
            </li>
          </ul>
        </section>

        <details v-if="isHr" class="disclosure">
          <summary>{{ t('onboarding.addTask') }}</summary>
          <form class="disclosure-body stack" novalidate @submit.prevent="addTask">
            <div class="grid-2">
              <FormField id="task-title" :label="t('onboarding.taskTitle')" :error="newTaskError">
                <template #default="{ attrs }"><input v-bind="attrs" v-model="newTask.title" class="input" maxlength="150" /></template>
              </FormField>
              <FormField id="task-owner" :label="t('onboarding.taskOwner')">
                <template #default="{ attrs }">
                  <select v-bind="attrs" v-model="newTask.owner" class="select">
                    <option v-for="owner in OWNERS" :key="owner" :value="owner">{{ t(`onboarding.owners.${owner}`) }}</option>
                  </select>
                </template>
              </FormField>
            </div>
            <div><button type="submit" class="btn btn-secondary" :disabled="busy"><AppIcon name="plus" />{{ t('onboarding.addTask') }}</button></div>
          </form>
        </details>
      </template>
    </LoadState>
  </div>
</template>

<style scoped>
.checklist-page {
  max-width: 760px;
}

progress {
  width: 100%;
  height: 10px;
  accent-color: var(--color-success);
}

.progress-text {
  font-weight: 650;
}

.group-title {
  padding: var(--space-3) var(--space-5);
  border-bottom: 1px solid var(--color-border);
  font-size: var(--text-md);
}

.task {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-1) var(--space-3);
  padding: var(--space-2) var(--space-5);
}

.task-check {
  align-items: center;
}

.task-static {
  display: flex;
  align-items: center;
  gap: var(--space-3);
  min-height: var(--touch);
}

.done {
  color: var(--color-text-muted);
  text-decoration: line-through;
}

.ok {
  color: var(--color-success);
}
</style>
