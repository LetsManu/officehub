<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import AppIcon from '@/components/AppIcon.vue'
import EmptyState from '@/components/EmptyState.vue'
import LoadState from '@/components/LoadState.vue'
import PageHeader from '@/components/PageHeader.vue'
import SectionContact from '@/components/SectionContact.vue'
import RequestRow from '@/components/RequestRow.vue'
import { api } from '@/lib/api'
import { DONE_STATUSES, OPEN_STATUSES } from '@/lib/requestTypes'
import { errorText, t } from '@/lib/i18n'
import type { OfficeRequest, RequestList } from '@/lib/types'

type Filter = 'all' | 'open' | 'done' | 'draft'
const FILTERS: Filter[] = ['all', 'open', 'draft', 'done']

const route = useRoute()
const router = useRouter()
const requests = ref<OfficeRequest[]>([])
const loading = ref(true)
const error = ref<string | null>(null)
const filter = ref<Filter>(FILTERS.includes(route.query.show as Filter) ? (route.query.show as Filter) : 'all')

const filterLabels = computed<Record<Filter, string>>(() => ({
  all: t('app.all'),
  open: t('requests.filterOpen'),
  draft: t('requests.filterDrafts'),
  done: t('requests.filterDone'),
}))

const visible = computed(() => {
  switch (filter.value) {
    case 'open':
      return requests.value.filter((r) => OPEN_STATUSES.includes(r.status))
    case 'done':
      return requests.value.filter((r) => DONE_STATUSES.includes(r.status))
    case 'draft':
      return requests.value.filter((r) => r.status === 'draft')
    default:
      return requests.value
  }
})

async function load() {
  loading.value = true
  error.value = null
  try {
    requests.value = (await api.get<RequestList>('/api/requests?limit=500')).items
  } catch (e) {
    error.value = errorText(e)
  } finally {
    loading.value = false
  }
}

watch(filter, (value) => router.replace({ query: value === 'all' ? {} : { show: value } }))
onMounted(load)
</script>

<template>
  <div class="page">
    <PageHeader :title="t('requests.title')" :subtitle="t('requests.subtitle')">
      <template #actions>
        <RouterLink to="/requests/new" class="btn btn-primary"><AppIcon name="plus" />{{ t('requests.new') }}</RouterLink>
      </template>
    </PageHeader>

    <LoadState :loading="loading" :error="error" @retry="load">
      <template v-if="requests.length">
        <div class="segmented" role="group" :aria-label="t('requests.filterLabel')">
          <button v-for="f in FILTERS" :key="f" type="button" :aria-pressed="filter === f" @click="filter = f">{{ filterLabels[f] }}</button>
        </div>
        <section class="card card-flush">
          <ul v-if="visible.length" class="list">
            <li v-for="request in visible" :key="request.id"><RequestRow :request="request" /></li>
          </ul>
          <EmptyState v-else :message="t('requests.emptyFiltered')" :action-label="t('approvals.reset')" @action="filter = 'all'" />
        </section>
      </template>
      <section v-else class="card">
        <EmptyState icon="inbox" :message="t('requests.empty')" :action-label="t('requests.createFirst')" action-to="/requests/new" />
      </section>
    </LoadState>

    <SectionContact section="requests" />
  </div>
</template>
