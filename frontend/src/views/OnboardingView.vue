<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import AppIcon from '@/components/AppIcon.vue'
import EmptyState from '@/components/EmptyState.vue'
import LoadState from '@/components/LoadState.vue'
import PageHeader from '@/components/PageHeader.vue'
import { api } from '@/lib/api'
import { isAdmin } from '@/lib/session'
import { errorText, t } from '@/lib/i18n'
import { showToast } from '@/lib/toast'
import type { ChecklistSummary, DirectoryEntry } from '@/lib/types'

const router = useRouter()
const items = ref<ChecklistSummary[]>([])
const people = ref<DirectoryEntry[]>([])
const startPerson = ref<number | ''>('')
const loading = ref(true)
const error = ref<string | null>(null)

async function load() {
  loading.value = true
  error.value = null
  try {
    items.value = await api.get<ChecklistSummary[]>('/api/onboarding')
    if (isAdmin.value && !people.value.length) people.value = await api.get<DirectoryEntry[]>('/api/directory')
  } catch (e) {
    error.value = errorText(e)
  } finally {
    loading.value = false
  }
}

async function start() {
  if (!startPerson.value) return
  try {
    await api.post(`/api/onboarding/${startPerson.value}/start`)
    showToast(t('onboarding.started'))
    router.push(`/onboarding/${startPerson.value}`)
  } catch (e) {
    showToast(errorText(e), 'error')
  }
}

onMounted(load)
</script>

<template>
  <div class="page">
    <PageHeader :title="t('onboarding.title')" :subtitle="t('onboarding.subtitle')" />

    <LoadState :loading="loading" :error="error" @retry="load">
      <section class="card card-flush">
        <ul v-if="items.length" class="list">
          <li v-for="item in items" :key="item.person.id">
            <RouterLink :to="`/onboarding/${item.person.id}`" class="list-link">
              <span class="icon-box"><AppIcon name="clipboard" /></span>
              <span class="main">
                <span class="name">{{ item.person.full_name }}</span>
                <span class="muted small">{{ item.person.department }}</span>
              </span>
              <span class="progress-wrap">
                <span class="small" :class="{ ok: item.done === item.total }">
                  {{ item.done === item.total ? t('onboarding.complete') : t('onboarding.progress', { done: item.done, total: item.total }) }}
                </span>
                <progress :value="item.done" :max="item.total" :aria-label="t('onboarding.progress', { done: item.done, total: item.total })" />
              </span>
            </RouterLink>
          </li>
        </ul>
        <EmptyState v-else icon="clipboard" :message="t('onboarding.empty')" />
      </section>

      <details v-if="isAdmin" class="disclosure">
        <summary>{{ t('onboarding.start') }}</summary>
        <form class="disclosure-body row" @submit.prevent="start">
          <label for="start-person" class="visually-hidden">{{ t('onboarding.person') }}</label>
          <select id="start-person" v-model.number="startPerson" class="select person-select">
            <option value="" disabled>{{ t('onboarding.person') }}</option>
            <option v-for="p in people" :key="p.id" :value="p.id">{{ p.full_name }} · {{ p.department }}</option>
          </select>
          <button type="submit" class="btn btn-primary" :disabled="!startPerson">{{ t('admin.startOnboarding') }}</button>
        </form>
      </details>
    </LoadState>
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

.name {
  font-weight: 600;
}

.progress-wrap {
  display: grid;
  justify-items: end;
  gap: 4px;
  min-width: 140px;
}

progress {
  width: 140px;
  height: 8px;
  accent-color: var(--color-success);
}

.ok {
  color: var(--color-success);
  font-weight: 600;
}

.person-select {
  max-width: 360px;
}
</style>
