<script setup lang="ts">
import { t } from '@/lib/i18n'
import type { RequestStatus } from '@/lib/types'

defineProps<{ status: RequestStatus }>()
</script>

<template>
  <span class="badge" :class="`badge-${status}`">
    <span class="dot" aria-hidden="true" />
    {{ t(`statuses.${status}`) }}
  </span>
</template>

<style scoped>
.badge {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 2px 10px;
  border-radius: 999px;
  font-size: var(--text-xs);
  font-weight: 600;
  white-space: nowrap;
  border: 1px solid transparent;
}

.dot {
  width: 7px;
  height: 7px;
  border-radius: 50%;
  background: currentColor;
}

.badge-draft,
.badge-cancelled {
  background: var(--color-neutral-soft);
  color: var(--color-text-muted);
}

.badge-submitted {
  background: var(--color-primary-soft);
  color: var(--color-primary-text);
}

.badge-in_review {
  background: var(--color-warning-soft);
  color: var(--color-warning);
}

.badge-approved {
  background: var(--color-success-soft);
  color: var(--color-success);
}

.badge-rejected {
  background: var(--color-danger-soft);
  color: var(--color-danger);
}
</style>
