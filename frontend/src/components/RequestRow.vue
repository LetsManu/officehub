<script setup lang="ts">
import { computed } from 'vue'
import AppIcon from './AppIcon.vue'
import StatusBadge from './StatusBadge.vue'
import { TYPE_ICONS } from '@/lib/requestTypes'
import { formatDate, formatDateTime, formatMoney, formatPeriod, t } from '@/lib/i18n'
import type { OfficeRequest } from '@/lib/types'

const props = defineProps<{ request: OfficeRequest; showRequester?: boolean }>()

/** The one most useful detail for each type, shown under the title. */
const summary = computed(() => {
  const r = props.request
  const parts: string[] = [t(`requestTypes.${r.type}`)]
  if (r.type === 'expense' && r.amount) parts.push(formatMoney(r.amount, r.currency))
  if ((r.type === 'vacation' || r.type === 'home_office') && r.start_date) {
    parts.push(formatPeriod(r.start_date, r.end_date))
    if (r.working_days) parts.push(r.working_days === 1 ? t('requests.day') : t('requests.days', { count: r.working_days }))
  }
  if ((r.type === 'equipment' || r.type === 'it_access') && r.item) parts.push(r.item)
  if (r.type === 'appointment' && r.confirmed_time) parts.push(formatDateTime(r.confirmed_time))
  return parts.join(' · ')
})
</script>

<template>
  <RouterLink :to="`/requests/${request.id}`" class="list-link request-row">
    <span class="type-icon"><AppIcon :name="TYPE_ICONS[request.type]" /></span>
    <span class="main">
      <span class="title">{{ request.title }}</span>
      <span class="meta">{{ summary }}</span>
      <span v-if="showRequester" class="meta">{{ request.requester.full_name }} · {{ request.requester.department }}</span>
    </span>
    <span class="side">
      <StatusBadge :status="request.status" />
      <span class="meta date">{{ t('requests.updated', { date: formatDate(request.updated_at) }) }}</span>
    </span>
  </RouterLink>
</template>

<style scoped>
.type-icon {
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
  min-width: 0;
}

.title {
  font-weight: 600;
  overflow-wrap: anywhere;
}

.meta {
  font-size: var(--text-sm);
  color: var(--color-text-muted);
}

.side {
  display: grid;
  justify-items: end;
  gap: 4px;
  text-align: right;
}

@media (max-width: 560px) {
  .request-row {
    flex-wrap: wrap;
  }

  .side {
    width: 100%;
    display: flex;
    justify-content: space-between;
    padding-left: 56px;
  }
}
</style>
