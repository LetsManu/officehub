<script setup lang="ts">
import { onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import AppIcon from '@/components/AppIcon.vue'
import EmptyState from '@/components/EmptyState.vue'
import LoadState from '@/components/LoadState.vue'
import PageHeader from '@/components/PageHeader.vue'
import { api } from '@/lib/api'
import { isAdmin } from '@/lib/session'
import { errorText, formatDate, t } from '@/lib/i18n'
import { showToast } from '@/lib/toast'
import type { ChecklistSummary, DirectoryEntry } from '@/lib/types'

const route = useRoute()
const router = useRouter()
const kind = ref<'onboarding' | 'offboarding'>(route.query.kind === 'offboarding' ? 'offboarding' : 'onboarding')
const lastDay = ref('')
const items = ref<ChecklistSummary[]>([])
const people = ref<DirectoryEntry[]>([])
const startPerson = ref<number | ''>('')
const loading = ref(true)
const error = ref<string | null>(null)

async function load() {
  loading.value = true
  error.value = null
  try {
    items.value = await api.get<ChecklistSummary[]>(`/api/onboarding?kind=${kind.value}`)
    if (isAdmin.value && !people.value.length) people.value = await api.get<DirectoryEntry[]>('/api/directory')
  } catch (e) {
    error.value = errorText(e)
  } finally {
    loading.value = false
  }
}

async function start() {
  if (!startPerson.value || (kind.value === 'offboarding' && !lastDay.value)) return
  try {
    if (kind.value === 'offboarding') {
      await api.post(`/api/onboarding/${startPerson.value}/offboarding`, { last_day: lastDay.value })
      showToast(t('onboarding.offStarted'))
      router.push(`/onboarding/${startPerson.value}?kind=offboarding`)
    } else {
      await api.post(`/api/onboarding/${startPerson.value}/start`)
      showToast(t('onboarding.started'))
      router.push(`/onboarding/${startPerson.value}`)
    }
  } catch (e) {
    showToast(errorText(e), 'error')
  }
}

watch(kind, (value) => {
  router.replace({ query: value === 'offboarding' ? { kind: value } : {} })
  load()
})

onMounted(load)
</script>

<template>
  <div class="page">
    <PageHeader :title="t('onboarding.title')" :subtitle="t('onboarding.subtitle')" />

    <div class="segmented" role="group" :aria-label="t('onboarding.title')">
      <button type="button" :aria-pressed="kind === 'onboarding'" @click="kind = 'onboarding'">{{ t('onboarding.tabOn') }}</button>
      <button type="button" :aria-pressed="kind === 'offboarding'" @click="kind = 'offboarding'">{{ t('onboarding.tabOff') }}</button>
    </div>

    <LoadState :loading="loading" :error="error" @retry="load">
      <section class="card card-flush">
        <ul v-if="items.length" class="list">
          <li v-for="item in items" :key="item.person.id">
            <RouterLink :to="kind === 'offboarding' ? `/onboarding/${item.person.id}?kind=offboarding` : `/onboarding/${item.person.id}`" class="list-link">
              <span class="icon-box"><AppIcon :name="kind === 'offboarding' ? 'logout' : 'clipboard'" /></span>
              <span class="main">
                <span class="name">{{ item.person.full_name }}</span>
                <span class="muted small">
                  {{ item.person.department }}<template v-if="kind === 'offboarding' && item.last_day"> · {{ t('onboarding.lastDay', { date: formatDate(item.last_day) }) }}</template>
                </span>
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
        <EmptyState v-else icon="clipboard" :message="kind === 'offboarding' ? t('onboarding.offEmpty') : t('onboarding.empty')" />
      </section>

      <details v-if="isAdmin" class="disclosure">
        <summary>{{ kind === 'offboarding' ? t('onboarding.offStart') : t('onboarding.start') }}</summary>
        <form class="disclosure-body row" @submit.prevent="start">
          <label for="start-person" class="visually-hidden">{{ t('onboarding.person') }}</label>
          <select id="start-person" v-model.number="startPerson" class="select person-select">
            <option value="" disabled>{{ t('onboarding.person') }}</option>
            <option v-for="p in people" :key="p.id" :value="p.id">{{ p.full_name }} · {{ p.department }}</option>
          </select>
          <template v-if="kind === 'offboarding'">
            <label for="last-day" class="visually-hidden">{{ t('onboarding.lastDayLabel') }}</label>
            <input id="last-day" v-model="lastDay" type="date" class="input day-input" :aria-label="t('onboarding.lastDayLabel')" />
          </template>
          <button type="submit" class="btn btn-primary" :disabled="!startPerson || (kind === 'offboarding' && !lastDay)">
            {{ kind === 'offboarding' ? t('onboarding.offStartButton') : t('admin.startOnboarding') }}
          </button>
          <p v-if="kind === 'offboarding'" class="muted small hint">{{ t('onboarding.offHint') }}</p>
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

.day-input {
  width: auto;
}

.hint {
  flex-basis: 100%;
}
</style>
