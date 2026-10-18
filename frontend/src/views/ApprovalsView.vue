<script setup lang="ts">
import { computed, onMounted, reactive, ref, watch } from 'vue'
import EmptyState from '@/components/EmptyState.vue'
import LoadState from '@/components/LoadState.vue'
import PageHeader from '@/components/PageHeader.vue'
import RequestRow from '@/components/RequestRow.vue'
import { api, query } from '@/lib/api'
import { REQUEST_TYPES, STATUSES } from '@/lib/requestTypes'
import { errorText, t } from '@/lib/i18n'
import type { OfficeRequest, RequestList, User } from '@/lib/types'

type View = 'pending' | 'all'

const view = ref<View>('pending')
const filters = reactive({ type: '', status: '', requester_id: '', date_from: '', date_to: '' })
const requests = ref<OfficeRequest[]>([])
const total = ref(0)
const people = ref<User[]>([])
const loading = ref(true)
const error = ref<string | null>(null)

const hasFilters = computed(() => Object.values(filters).some(Boolean))
const activeFilterCount = computed(() => Object.values(filters).filter(Boolean).length)
// Drafts of other people are private, so they are not offered as a filter.
const statusOptions = STATUSES.filter((s) => s !== 'draft')

async function load() {
  loading.value = true
  error.value = null
  try {
    const status = view.value === 'pending' ? 'submitted,in_review' : filters.status
    const result = await api.get<RequestList>(
      `/api/requests${query({ scope: 'all', status, type: filters.type, requester_id: filters.requester_id, date_from: filters.date_from, date_to: filters.date_to, limit: 200 })}`,
    )
    // In "all" view only show other people's requests and own non-drafts.
    requests.value = result.items.filter((r) => r.status !== 'draft')
    total.value = result.total
  } catch (e) {
    error.value = errorText(e)
  } finally {
    loading.value = false
  }
}

function resetFilters() {
  Object.assign(filters, { type: '', status: '', requester_id: '', date_from: '', date_to: '' })
}

watch(view, load)
watch(filters, load, { deep: true })

onMounted(async () => {
  load()
  try {
    people.value = await api.get<User[]>('/api/admin/users')
  } catch {
    people.value = []
  }
})
</script>

<template>
  <div class="page">
    <PageHeader :title="t('approvals.title')" :subtitle="t('approvals.subtitle')" />

    <div class="row-between">
      <div class="segmented" role="group" :aria-label="t('approvals.title')">
        <button type="button" :aria-pressed="view === 'pending'" @click="view = 'pending'">{{ t('approvals.pending') }}</button>
        <button type="button" :aria-pressed="view === 'all'" @click="view = 'all'">{{ t('approvals.all') }}</button>
      </div>
    </div>

    <details class="disclosure" :open="hasFilters || undefined">
      <summary>{{ t('approvals.filters') }}{{ activeFilterCount ? ` (${activeFilterCount})` : '' }}</summary>
      <div class="disclosure-body stack">
        <div class="filter-grid">
          <div class="field">
            <label for="flt-type" class="label">{{ t('approvals.type') }}</label>
            <select id="flt-type" v-model="filters.type" class="select">
              <option value="">{{ t('app.all') }}</option>
              <option v-for="type in REQUEST_TYPES" :key="type" :value="type">{{ t(`requestTypes.${type}`) }}</option>
            </select>
          </div>
          <div v-if="view === 'all'" class="field">
            <label for="flt-status" class="label">{{ t('approvals.status') }}</label>
            <select id="flt-status" v-model="filters.status" class="select">
              <option value="">{{ t('app.all') }}</option>
              <option v-for="s in statusOptions" :key="s" :value="s">{{ t(`statuses.${s}`) }}</option>
            </select>
          </div>
          <div class="field">
            <label for="flt-person" class="label">{{ t('approvals.employee') }}</label>
            <select id="flt-person" v-model="filters.requester_id" class="select">
              <option value="">{{ t('app.all') }}</option>
              <option v-for="p in people" :key="p.id" :value="String(p.id)">{{ p.full_name }}</option>
            </select>
          </div>
          <div class="field">
            <label for="flt-from" class="label">{{ t('approvals.from') }}</label>
            <input id="flt-from" v-model="filters.date_from" type="date" class="input" />
          </div>
          <div class="field">
            <label for="flt-to" class="label">{{ t('approvals.to') }}</label>
            <input id="flt-to" v-model="filters.date_to" type="date" class="input" :min="filters.date_from || undefined" />
          </div>
        </div>
        <div v-if="hasFilters"><button type="button" class="btn btn-ghost" @click="resetFilters">{{ t('approvals.reset') }}</button></div>
      </div>
    </details>

    <LoadState :loading="loading" :error="error" @retry="load">
      <section class="card card-flush">
        <ul v-if="requests.length" class="list">
          <li v-for="request in requests" :key="request.id"><RequestRow :request="request" show-requester /></li>
        </ul>
        <EmptyState
          v-else
          :icon="hasFilters ? 'search' : 'checkCircle'"
          :message="hasFilters ? t('approvals.emptyFiltered') : view === 'pending' ? t('approvals.empty') : t('approvals.emptyFiltered')"
          :action-label="hasFilters ? t('approvals.reset') : undefined"
          @action="resetFilters"
        />
      </section>
    </LoadState>
  </div>
</template>

<style scoped>
.filter-grid {
  display: grid;
  gap: var(--space-4);
  grid-template-columns: repeat(auto-fit, minmax(min(100%, 180px), 1fr));
}

.field {
  display: grid;
  gap: 6px;
}

.label {
  font-weight: 600;
  font-size: var(--text-sm);
}
</style>
