<script setup lang="ts">
import { onMounted, ref, watch } from 'vue'
import AppIcon from '@/components/AppIcon.vue'
import EmptyState from '@/components/EmptyState.vue'
import LoadState from '@/components/LoadState.vue'
import PageHeader from '@/components/PageHeader.vue'
import { api, query } from '@/lib/api'
import { errorText, formatDateTime, t } from '@/lib/i18n'
import type { User } from '@/lib/types'

interface AuditItem {
  id: number
  action: string
  target: string
  details: Record<string, string>
  actor_name: string | null
  created_at: string
}

const ACTIONS = [
  'user_created', 'user_updated', 'password_reset', 'two_factor_reset', 'request_approved', 'request_rejected',
  'document_uploaded', 'document_updated', 'document_replaced', 'announcement_created', 'announcement_updated',
  'personal_document_sent', 'personal_document_deleted', 'settings_updated', 'branding_updated', 'holidays_updated',
  'asset_created', 'asset_updated', 'asset_assigned', 'asset_returned', 'training_created', 'training_updated',
  'training_confirmed', 'survey_created', 'survey_closed', 'idea_status', 'offboarding_started',
  'project_created', 'project_updated', 'project_deleted', 'time_month_approved', 'time_month_returned',
]
const PAGE = 50

const items = ref<AuditItem[]>([])
const total = ref(0)
const people = ref<User[]>([])
const filters = ref({ action: '', actor_id: '', date_from: '', date_to: '' })
const offset = ref(0)
const loading = ref(true)
const error = ref<string | null>(null)

function params(extra: Record<string, string | number> = {}) {
  const f = filters.value
  return query({ action: f.action, actor_id: f.actor_id, date_from: f.date_from, date_to: f.date_to, ...extra })
}

async function load(more = false) {
  loading.value = !more
  error.value = null
  try {
    const result = await api.get<{ items: AuditItem[]; total: number }>(`/api/admin/audit${params({ limit: PAGE, offset: more ? offset.value : 0 })}`)
    items.value = more ? [...items.value, ...result.items] : result.items
    total.value = result.total
    offset.value = items.value.length
  } catch (e) {
    error.value = errorText(e)
  } finally {
    loading.value = false
  }
}

function detailText(item: AuditItem): string {
  return Object.entries(item.details)
    .filter(([, value]) => value !== '' && value !== 'None')
    .map(([key, value]) => `${key}: ${value}`)
    .join(' · ')
}

watch(filters, () => load(), { deep: true })
onMounted(async () => {
  load()
  people.value = await api.get<User[]>('/api/admin/users').catch(() => [])
})
</script>

<template>
  <div class="page">
    <PageHeader :title="t('audit.title')" :subtitle="t('audit.subtitle')" :crumbs="[{ label: t('nav.administration'), to: '/admin' }]">
      <template #actions>
        <a class="btn btn-secondary" :href="`/api/admin/audit/export.csv${params()}`" download><AppIcon name="download" :size="18" />{{ t('audit.export') }}</a>
      </template>
    </PageHeader>

    <div class="filters">
      <div class="field">
        <label for="au-action" class="label">{{ t('audit.action') }}</label>
        <select id="au-action" v-model="filters.action" class="select">
          <option value="">{{ t('app.all') }}</option>
          <option v-for="a in ACTIONS" :key="a" :value="a">{{ t(`audit.actions.${a}`) }}</option>
        </select>
      </div>
      <div class="field">
        <label for="au-actor" class="label">{{ t('audit.person') }}</label>
        <select id="au-actor" v-model="filters.actor_id" class="select">
          <option value="">{{ t('app.all') }}</option>
          <option v-for="p in people" :key="p.id" :value="String(p.id)">{{ p.full_name }}</option>
        </select>
      </div>
      <div class="field">
        <label for="au-from" class="label">{{ t('admin.exportFrom') }}</label>
        <input id="au-from" v-model="filters.date_from" type="date" class="input" />
      </div>
      <div class="field">
        <label for="au-to" class="label">{{ t('admin.exportTo') }}</label>
        <input id="au-to" v-model="filters.date_to" type="date" class="input" />
      </div>
    </div>

    <LoadState :loading="loading" :error="error" @retry="load()">
      <section v-if="items.length" class="card card-flush">
        <p class="muted small count">{{ t('audit.count', { count: total }) }}</p>
        <div class="table-wrap table-scroll">
          <table class="table table-sticky">
            <thead>
              <tr>
                <th scope="col">{{ t('audit.when') }}</th>
                <th scope="col">{{ t('audit.person') }}</th>
                <th scope="col">{{ t('audit.action') }}</th>
                <th scope="col">{{ t('audit.target') }}</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="item in items" :key="item.id">
                <td class="nowrap">{{ formatDateTime(item.created_at) }}</td>
                <td>{{ item.actor_name ?? '–' }}</td>
                <td><span class="action">{{ t(`audit.actions.${item.action}`) }}</span></td>
                <td>
                  {{ item.target }}
                  <span v-if="detailText(item)" class="muted small details">{{ detailText(item) }}</span>
                </td>
              </tr>
            </tbody>
          </table>
        </div>
        <div v-if="items.length < total" class="more">
          <button type="button" class="btn btn-secondary" @click="load(true)">{{ t('audit.more') }}</button>
        </div>
      </section>
      <section v-else class="card"><EmptyState icon="history" :message="t('audit.empty')" /></section>
    </LoadState>
  </div>
</template>

<style scoped>
.filters {
  display: grid;
  gap: var(--space-3);
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

.count {
  padding: var(--space-3) var(--space-5);
  border-bottom: 1px solid var(--color-border);
}

.nowrap {
  white-space: nowrap;
}

.action {
  font-weight: 600;
}

.details {
  display: block;
  overflow-wrap: anywhere;
}

.more {
  display: flex;
  justify-content: center;
  padding: var(--space-4);
  border-top: 1px solid var(--color-border);
}
</style>
